"""Synthetic end-to-end feature-table fixtures: causality, window boundaries, eligibility."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from newsvar.data import news
from newsvar.data.calendar import CalendarSnapshot, build_xnys_snapshot
from newsvar.data.datasets import materialize_market_dataset
from newsvar.data.market import MarketSource
from newsvar.features import table as ft
from newsvar.hashing import canonical_json, sha256
from newsvar.nlp.scoring import SCORE_SCHEMA

CORPUS_START = date(2019, 9, 2)


def _source(series: str, values: dict[date, float]) -> MarketSource:
    return MarketSource(
        series_id=series,
        values=values,
        placeholders=(),
        source_rows=len(values),
        raw_sha256=hashlib.sha256(series.encode()).hexdigest(),
        raw_relative_path=f"synthetic/{series}.csv",
        retrieved_at_utc="2026-11-24T00:00:00+00:00",
    )


def _market(tmp_path: Path, calendar: CalendarSnapshot, *, bump_from: date | None = None) -> Path:
    prices, vix = {}, {}
    sessions = [origin.session for origin in calendar.origins] + [calendar.origins[-1].next_session]
    for index, session in enumerate(sessions):
        level = 3000.0 * (1.0 + 0.01 * ((index * 7) % 5 - 2)) + index
        if bump_from is not None and session >= bump_from:
            level *= 1.5
        prices[session], vix[session] = level, 15.0 + index % 9
    path, _ = materialize_market_dataset(
        tmp_path / f"market-{bump_from}",
        calendar,
        _source("SP500", prices),
        _source("VIX", vix),
        study_target_end=calendar.origins[-3].session,
    )
    return path


def _corpus(tmp_path: Path, events: list[tuple[datetime, str]], missing: set[datetime]) -> Path:
    identity = {"schema_version": "news_corpus_v2", "fixture": len(events), "gaps": len(missing)}
    corpus_id = sha256(canonical_json(identity))
    root = tmp_path / "news" / corpus_id
    root.mkdir(parents=True)
    rows, titles = [], []
    for index, (when, title) in enumerate(events):
        digest = news.content_hash(title)
        rows.append(
            {
                "event_id": f"e{index}",
                "batch_time_utc": when,
                "source_common_name": "example.com",
                "content_sha256": digest,
                "sample_key": news.sample_key(digest),
                "status": news.RETAINED,
                "gdelt_tone": 0.0,
            }
        )
        titles.append(
            {"content_sha256": digest, "title_clean": title, "first_batch_time_utc": when}
        )
    batches, moment = [], datetime(2019, 9, 1, tzinfo=UTC)
    while moment < datetime(2020, 3, 1, tzinfo=UTC):
        status = "absent_from_catalog" if moment in missing else "ok"
        batches.append({"stamp": moment.strftime("%Y%m%d%H%M%S"), "status": status})
        moment += timedelta(minutes=15)
    pq.write_table(pa.Table.from_pylist(rows, schema=news.EVENT_SCHEMA), root / "events.parquet")
    pq.write_table(pa.Table.from_pylist(titles, schema=news.TITLE_SCHEMA), root / "titles.parquet")
    pq.write_table(pa.Table.from_pylist(batches), root / "batches.parquet")
    return root


def _scores(titles: list[str], negative: float = 0.5) -> pa.Table:
    return pa.Table.from_pylist(
        [
            {
                "content_sha256": news.content_hash(title),
                "positive": 0.2,
                "negative": negative,
                "neutral": 0.8 - negative,
                "token_count": 5,
                "truncated": False,
            }
            for title in titles
        ],
        schema=SCORE_SCHEMA,
    )


@pytest.fixture(scope="module")
def calendar() -> CalendarSnapshot:
    return build_xnys_snapshot(date(2019, 3, 1), date(2020, 2, 14))


def test_market_features_ignore_same_day_and_future_prices(
    tmp_path: Path, calendar: CalendarSnapshot
) -> None:
    target = next(o for o in calendar.origins if o.session == date(2020, 1, 15))
    corpus = _corpus(tmp_path, [], set())
    kwargs = dict(
        calendar=calendar,
        corpus=corpus,
        corpus_start=CORPUS_START,
        scores=_scores([]),
        config=ft.FeatureConfig(),
    )
    clean = ft.build_rows(market_dataset=_market(tmp_path, calendar), **kwargs)
    bumped = ft.build_rows(
        market_dataset=_market(tmp_path, calendar, bump_from=target.session), **kwargs
    )
    position = calendar.origins.index(target)
    # A price change at the origin session or later cannot alter that origin's inputs.
    assert clean[: position + 1] == bumped[: position + 1]
    assert clean[position + 1] != bumped[position + 1]
    row = clean[position]
    assert row["eligible"] and row["has_news"] == 0.0 and row["sentiment_mean"] is None
    assert row["vix_last"] == pytest.approx((15.0 + (position - 1) % 9) / 100.0)
    assert clean[10]["ineligible_reasons"].startswith("market_history_missing_or_stale")


def test_news_boundaries_gaps_and_lagged_sentiment(
    tmp_path: Path, calendar: CalendarSnapshot
) -> None:
    target = next(o for o in calendar.origins if o.session == date(2020, 1, 15))
    position = calendar.origins.index(target)
    at_cutoff = target.cutoff_utc - timedelta(minutes=15)
    events = [(at_cutoff, "Stocks fall at the cutoff"), (at_cutoff + timedelta(minutes=15), "Late")]
    gap_day = next(o for o in calendar.origins if o.session == date(2020, 1, 22))
    missing = {gap_day.cutoff_utc - timedelta(minutes=15 * step) for step in range(2, 12)}
    corpus = _corpus(tmp_path, events, missing)
    market = _market(tmp_path, calendar)
    scores = _scores([title for _, title in events])

    def build(config: ft.FeatureConfig) -> list[dict[str, object]]:
        return ft.build_rows(
            market_dataset=market,
            calendar=calendar,
            corpus=corpus,
            corpus_start=CORPUS_START,
            scores=scores,
            config=config,
        )

    rows = build(ft.FeatureConfig())
    assert rows[position]["retained_count"] == 1 and rows[position + 1]["retained_count"] == 1
    assert rows[position]["negative_probability_mean"] == pytest.approx(0.5)
    gap = rows[calendar.origins.index(gap_day)]
    assert not gap["eligible"] and gap["ineligible_reasons"] == "feed_incomplete"
    assert gap["news_log_rate"] is None
    # A longer availability buffer moves the boundary headline into the next window.
    delayed = build(ft.FeatureConfig(buffer_minutes=60))
    assert delayed[position]["retained_count"] == 0 and delayed[position + 1]["retained_count"] == 2
    shifted = build(ft.FeatureConfig(session_delay=1))
    assert shifted[position]["retained_count"] == 0 and shifted[position + 1]["retained_count"] == 1
    lagged = build(ft.FeatureConfig(sentiment_lag=5))
    assert lagged[position]["sentiment_mean"] is None
    assert lagged[position + 5]["sentiment_mean"] == rows[position]["sentiment_mean"]
    assert lagged[position + 5]["retained_count"] == rows[position + 5]["retained_count"]
    # Unscored designated headlines fail the coverage gate instead of reading as neutral.
    unscored = ft.build_rows(
        market_dataset=market,
        calendar=calendar,
        corpus=corpus,
        corpus_start=CORPUS_START,
        scores=_scores([]),
        config=ft.FeatureConfig(),
    )
    assert unscored[position]["ineligible_reasons"] == "scoring_coverage_below_gate"

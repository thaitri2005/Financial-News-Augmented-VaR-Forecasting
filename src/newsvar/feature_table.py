"""Materialize the daily M/C/S feature table from market, corpus and score artifacts.

One row per forecast origin. Every value is built from inputs available at that
origin's cutoff: labels and market observations by their recorded availability,
news by batch time plus the declared Class B buffer. No target return of the row
itself is read here; labels are joined later by the experiment runner.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.calendar import CalendarSnapshot, ForecastOrigin
from newsvar.features import FeatureInputError, HeadlineScore, NewsWindow, market_features
from newsvar.features import news_features as build_news_features
from newsvar.news import (
    RETAINED,
    assign_windows,
    ok_batch_times,
    sample_threshold,
    window_coverage,
)
from newsvar.provenance import canonical_json, sha256

MARKET_FEATURES = (
    "return_last",
    "abs_return_last",
    "downside_square_last",
    "vol_5",
    "vol_21",
    "vol_63",
    "ewma_sigma",
    "vix_last",
    "vix_change",
)
CONTROL_FEATURES = ("news_log_rate", "news_rate_z63", "log_window_hours", "has_news")
SENTIMENT_FEATURES = (
    "sentiment_mean",
    "negative_probability_mean",
    "sentiment_dispersion",
    "negative_headline_ratio",
    "sentiment_shock21",
    "negative_log_intensity",
)
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "Q0": MARKET_FEATURES,
    "Q1": MARKET_FEATURES + CONTROL_FEATURES,
    "Q2": MARKET_FEATURES + CONTROL_FEATURES + SENTIMENT_FEATURES,
}
ALL_FEATURES = FEATURE_GROUPS["Q2"]
MIN_SCORING_COVERAGE = 0.98
NEWS_WARMUP_WINDOWS = 63
MARKET_WARMUP_RETURNS = 63

# Frozen on 2026-11-24 without reference to returns: headlines that mainly restate a
# same-day index or share-price move. Used only for the declared recap-exclusion sensitivity.
RECAP_PATTERN = re.compile(
    r"\b(stocks?|shares|dow|nasdaq|s&p|wall street|markets?|futures|index|indexes|indices)\b"
    r".{0,60}\b(clos(e|es|ed|ing)|falls?|fell|ris(e|es|ing)|rose|drops?|dropped|plung(e|es|ed)"
    r"|surg(e|es|ed)|rall(y|ies|ied)|tumbl(e|es|ed)|slump(s|ed)?|gain(s|ed)?|sinks?|sank"
    r"|slid(e|es)?|jump(s|ed)?|soar(s|ed)?|ends?|ended|finish(es|ed)?|opens?|opened)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FeatureConfig:
    """Declared, outcome-blind choices that distinguish one feature table from another."""

    buffer_minutes: int = 15
    session_delay: int = 0
    counts_include_duplicates: bool = False
    sampling_rate: float = 1.0
    sentiment_lag: int = 0
    exclude_source: str | None = None
    exclude_recaps: bool = False

    def __post_init__(self) -> None:
        if self.buffer_minutes < 0 or self.session_delay < 0 or self.sentiment_lag < 0:
            raise FeatureInputError("Feature configuration delays cannot be negative.")


def _market_state(
    market_dataset: Path, origins: Sequence[ForecastOrigin]
) -> list[dict[str, float | None] | None]:
    """Nine market features per origin from labels/VIX available by its cutoff, else None."""
    labels = pq.read_table(
        market_dataset / "labels.parquet",
        columns=["target_end_session", "return_simple", "label_available_at_utc"],
    ).to_pylist()
    labels.sort(key=lambda row: row["target_end_session"])
    available = [row["label_available_at_utc"] for row in labels]
    if any(later < earlier for earlier, later in zip(available, available[1:], strict=False)):
        raise FeatureInputError("Label availability must be nondecreasing in target-end order.")
    returns = [float(row["return_simple"]) for row in labels]
    ends = [row["target_end_session"] for row in labels]
    observations = pq.read_table(
        market_dataset / "market_observations.parquet",
        columns=["series_id", "observation_date", "value", "available_at_utc"],
    ).to_pylist()
    vix = {
        row["observation_date"]: (row["value"], row["available_at_utc"])
        for row in observations
        if row["series_id"] == "VIX" and row["value"] is not None
    }

    def vix_at(session: date, cutoff: datetime) -> float | None:
        value = vix.get(session)
        if value is None or value[1] is None or value[1] > cutoff:
            return None
        return float(value[0])

    by_session = {origin.session: origin for origin in origins}
    result: list[dict[str, float | None] | None] = []
    known = 0
    for origin in origins:
        while known < len(labels) and available[known] <= origin.cutoff_utc:
            known += 1
        if known < MARKET_WARMUP_RETURNS or ends[known - 1] != origin.previous_session:
            result.append(None)
            continue
        earlier = by_session.get(origin.previous_session)
        previous2 = None if earlier is None else earlier.previous_session
        result.append(
            market_features(
                returns[:known],
                [
                    None if previous2 is None else vix_at(previous2, origin.cutoff_utc),
                    vix_at(origin.previous_session, origin.cutoff_utc),
                ],
            )
        )
    return result


def recap_hashes(corpus: Path) -> set[str]:
    table = pq.read_table(corpus / "titles.parquet", columns=["content_sha256", "title_clean"])
    return {
        digest
        for digest, title in zip(
            table.column(0).to_pylist(), table.column(1).to_pylist(), strict=True
        )
        if RECAP_PATTERN.search(title)
    }


def build_news_windows(
    corpus: Path,
    origins: Sequence[ForecastOrigin],
    scores: pa.Table,
    config: FeatureConfig,
) -> list[NewsWindow]:
    """Assign events to origin windows and attach scored probabilities to designated events."""
    import pandas as pd

    events = pq.read_table(
        corpus / "events.parquet",
        columns=["batch_time_utc", "content_sha256", "sample_key", "status", "source_common_name"],
    ).to_pandas(types_mapper=pd.ArrowDtype)
    if config.exclude_source is not None:
        events = events[events["source_common_name"] != config.exclude_source]
    if config.exclude_recaps:
        events = events[~events["content_sha256"].isin(list(recap_hashes(corpus)))]
    unit = str(events["batch_time_utc"].dtype)
    divisor = 1 if "[s" in unit else 1_000 if "[ms" in unit else 1_000_000
    seconds = events["batch_time_utc"].astype("int64").to_numpy() // divisor
    index = assign_windows(seconds, origins, buffer_minutes=config.buffer_minutes)
    retained_mask = (events["status"] == RETAINED).to_numpy(dtype=bool, na_value=False)
    counted = index >= 0
    if not config.counts_include_duplicates:
        counted &= retained_mask
    size = len(origins)
    retained_counts = np.bincount(index[counted], minlength=size)
    designated_mask = (
        (index >= 0)
        & retained_mask
        & (events["sample_key"].to_numpy(dtype=np.int64) < sample_threshold(config.sampling_rate))
    )
    designated_counts = np.bincount(index[designated_mask], minlength=size)
    designated = pd.DataFrame(
        {
            "window": index[designated_mask],
            "content_sha256": events["content_sha256"].to_numpy()[designated_mask],
        }
    )
    score_frame = scores.select(["content_sha256", "positive", "negative", "neutral"]).to_pandas()
    score_frame = score_frame.drop_duplicates("content_sha256")
    joined = designated.merge(score_frame, on="content_sha256", how="inner").sort_values(
        "window", kind="stable"
    )
    windows_scored: dict[int, tuple[HeadlineScore, ...]] = {}
    for window, group in joined.groupby("window", sort=True):
        windows_scored[int(window)] = tuple(
            HeadlineScore(float(p), float(n), float(u))
            for p, n, u in zip(group["positive"], group["negative"], group["neutral"], strict=True)
        )
    coverage = window_coverage(
        ok_batch_times(corpus), origins, buffer_minutes=config.buffer_minutes
    )
    windows = [
        NewsWindow(
            duration_hours=origin.news_window_hours,
            feed_complete=coverage[position].feed_complete,
            retained_count=int(retained_counts[position]),
            scored=windows_scored.get(position, ()),
            designated_count=int(designated_counts[position]),
            sampling_rate=config.sampling_rate,
        )
        for position, origin in enumerate(origins)
    ]
    if config.session_delay:
        empty = NewsWindow(1.0, False, 0, (), 0, config.sampling_rate)
        windows = [empty] * config.session_delay + windows[: -config.session_delay]
    return windows


def first_covered_origin(origins: Sequence[ForecastOrigin], corpus_start: date) -> int:
    """Index of the first origin whose whole news window starts on/after the corpus start."""
    for position, origin in enumerate(origins):
        if origin.previous_cutoff_utc.date() >= corpus_start:
            return position
    return len(origins)


def build_rows(
    *,
    market_dataset: Path,
    calendar: CalendarSnapshot,
    corpus: Path,
    corpus_start: date,
    scores: pa.Table,
    config: FeatureConfig,
) -> list[dict[str, Any]]:
    """Build every origin's feature row plus the quality fields that decide eligibility."""
    origins = calendar.origins
    market = _market_state(market_dataset, origins)
    windows = build_news_windows(corpus, origins, scores, config)
    first_news = first_covered_origin(origins, corpus_start) + config.session_delay
    rows: list[dict[str, Any]] = []
    for position, origin in enumerate(origins):
        values: dict[str, float | None] = dict.fromkeys(ALL_FEATURES)
        reasons: list[str] = []
        state = market[position]
        if state is None:
            reasons.append("market_history_missing_or_stale")
        else:
            values.update(state)
            if any(state[name] is None for name in MARKET_FEATURES):
                reasons.append("market_feature_null")
        window = windows[position]
        warm = position - NEWS_WARMUP_WINDOWS >= first_news
        if not warm:
            reasons.append("news_history_warmup")
        if position >= NEWS_WARMUP_WINDOWS:
            news = build_news_features(window, windows[position - NEWS_WARMUP_WINDOWS : position])
            values.update(news.values)
        if not window.feed_complete:
            reasons.append("feed_incomplete")
        elif window.scoring_coverage < MIN_SCORING_COVERAGE:
            reasons.append("scoring_coverage_below_gate")
        rows.append(
            {
                "origin_session": origin.session,
                "target_end_session": origin.next_session,
                "cutoff_utc": origin.cutoff_utc,
                **values,
                "feed_complete": window.feed_complete,
                "window_hours": window.duration_hours,
                "retained_count": window.retained_count,
                "designated_count": window.designated,
                "scored_count": len(window.scored),
                "scoring_coverage": window.scoring_coverage,
                "eligible": not reasons,
                "ineligible_reasons": ";".join(reasons),
            }
        )
    if config.sentiment_lag:
        lag = config.sentiment_lag
        for position in range(len(rows) - 1, -1, -1):
            source = rows[position - lag] if position >= lag else None
            for name in SENTIMENT_FEATURES:
                rows[position][name] = None if source is None else source[name]
            if source is None or not source["feed_complete"]:
                if rows[position]["eligible"]:
                    rows[position]["eligible"] = False
                    rows[position]["ineligible_reasons"] = "lagged_sentiment_source_unavailable"
    return rows


ROW_SCHEMA = pa.schema(
    [
        pa.field("origin_session", pa.date32(), nullable=False),
        pa.field("target_end_session", pa.date32(), nullable=False),
        pa.field("cutoff_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        *[pa.field(name, pa.float64(), nullable=True) for name in ALL_FEATURES],
        pa.field("feed_complete", pa.bool_(), nullable=False),
        pa.field("window_hours", pa.float64(), nullable=False),
        pa.field("retained_count", pa.int64(), nullable=False),
        pa.field("designated_count", pa.int64(), nullable=False),
        pa.field("scored_count", pa.int64(), nullable=False),
        pa.field("scoring_coverage", pa.float64(), nullable=False),
        pa.field("eligible", pa.bool_(), nullable=False),
        pa.field("ineligible_reasons", pa.string(), nullable=False),
    ]
)


def materialize(
    output_root: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    identity: Mapping[str, object],
) -> tuple[Path, dict[str, object]]:
    """Atomically commit a feature table under the hash of its declared identity."""
    table_id = sha256(canonical_json(dict(identity)))
    destination = output_root / table_id
    if destination.exists():
        return destination, load(destination)
    output_root.mkdir(parents=True, exist_ok=True)
    stage = output_root / f".{table_id}.{uuid.uuid4().hex}.staging"
    stage.mkdir()
    path = stage / "features.parquet"
    pq.write_table(pa.Table.from_pylist([dict(row) for row in rows], schema=ROW_SCHEMA), path)
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())
    manifest = {
        "feature_table_id": table_id,
        "identity": dict(identity),
        "rows": len(rows),
        "eligible_rows": sum(bool(row["eligible"]) for row in rows),
        "sha256": _digest(path),
    }
    with (stage / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stage, destination)
    return destination, load(destination)


def _digest(path: Path) -> str:
    import hashlib

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path: Path) -> dict[str, object]:
    root = path.resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or sha256(canonical_json(manifest["identity"])) != manifest["feature_table_id"]
        or root.name != manifest["feature_table_id"]
        or _digest(root / "features.parquet") != manifest["sha256"]
    ):
        raise FeatureInputError("Feature table manifest or checksum mismatch.")
    return manifest


def config_identity(config: FeatureConfig) -> dict[str, object]:
    return asdict(config)

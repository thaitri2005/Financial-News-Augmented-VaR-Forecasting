"""Outcome-blind news normalization, dedup and window-assignment fixtures."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from newsvar.data import news
from newsvar.data.calendar import build_xnys_snapshot

T0 = datetime(2020, 3, 16, 12, 0, tzinfo=UTC)


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "batch_stamp": "20200316120000",
        "gkg_record_id": "20200316120000-1",
        "source_collection": "1",
        "source_common_name": "example.com",
        "document_identifier": "https://example.com/a",
        "has_us_location": True,
        "is_translated": False,
        "gdelt_tone": -1.0,
        "page_title_raw": "Stocks &amp;amp; bonds <b>fall</b>  as Fed isn&#39;t cutting",
    }
    base.update(overrides)
    return base


def test_normalization_preserves_case_numbers_and_negation() -> None:
    assert news.normalize_title(_record()["page_title_raw"]) == (  # type: ignore[arg-type]
        "Stocks & bonds fall as Fed isn't cutting"
    )
    assert news.normalize_title("   ") is None and news.normalize_title(None) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"source_collection": "2"}, "not_web_collection"),
        ({"is_translated": True}, "translated"),
        ({"has_us_location": False}, "no_us_location"),
        ({"page_title_raw": None}, "no_title"),
        ({"page_title_raw": "12 - 3"}, "title_too_short_or_nonalphabetic"),
    ],
)
def test_relevance_exclusions_are_cause_specific(overrides: dict[str, object], reason: str) -> None:
    record = _record(**overrides)
    title = news.normalize_title(record["page_title_raw"])  # type: ignore[arg-type]
    assert news.exclusion_reason(record, title) == reason


def test_dedup_uses_only_past_records_and_a_72_hour_lookback() -> None:
    dedup = news.Deduplicator()
    assert dedup.observe(T0, "Dow drops 5%", "u1") == news.RETAINED
    assert dedup.observe(T0, "DOW DROPS 5%", "u2") == news.DUPLICATE_TITLE
    assert dedup.observe(T0 + timedelta(hours=1), "Dow drops 6%", "u3") == news.RETAINED
    assert dedup.observe(T0 + timedelta(hours=2), "New headline", "u1") == news.DUPLICATE_URL
    # Each occurrence refreshes the lookback, so an unchanged replay never becomes new news.
    assert dedup.observe(T0 + timedelta(hours=70), "Dow drops 5%", "u4") == news.DUPLICATE_TITLE
    assert dedup.observe(T0 + timedelta(hours=141), "Dow drops 5%", "u5") == news.DUPLICATE_TITLE
    assert dedup.observe(T0 + timedelta(hours=214), "Dow drops 5%", "u6") == news.RETAINED
    with pytest.raises(news.NewsError):
        dedup.observe(T0, "Late record", "u7")


def test_appending_future_records_cannot_change_earlier_statuses() -> None:
    early = [_record(gkg_record_id=f"r{i}", document_identifier=f"u{i}") for i in range(3)]
    late = [
        _record(
            gkg_record_id="r9",
            document_identifier="u9",
            batch_stamp="20200317120000",
            page_title_raw="A different later story",
        )
    ]
    first, _, _ = news.day_events(early, news.Deduplicator())
    both, _, _ = news.day_events(early + late, news.Deduplicator())
    assert both[: len(first)] == first
    assert [event["status"] for event in first] == [
        news.RETAINED,
        news.DUPLICATE_TITLE,
        news.DUPLICATE_TITLE,
    ]


def test_window_assignment_boundaries_and_coverage() -> None:
    snapshot = build_xnys_snapshot(date(2020, 3, 9), date(2020, 3, 20))
    origins = snapshot.origins
    monday = next(o for o in origins if o.session == date(2020, 3, 16))
    position = origins.index(monday)
    cutoff = int(monday.cutoff_utc.timestamp())
    times = np.asarray([cutoff - 900, cutoff - 899, cutoff - 899 - 3 * 86400], dtype=np.int64)
    assigned = news.assign_windows(times, origins, buffer_minutes=15)
    # Available exactly at the cutoff is eligible; one second later belongs to the next window.
    assert assigned[0] == position and assigned[1] == position + 1
    # One second after Friday's cutoff belongs to Monday's window.
    assert assigned[2] == position
    assert news.assign_windows(np.asarray([cutoff + 10**8]), origins, buffer_minutes=15)[0] == -1

    grid = [
        datetime.fromtimestamp(second, UTC)
        for second in range(
            int(monday.previous_cutoff_utc.timestamp()) - 3600,
            int(monday.cutoff_utc.timestamp()) + 3600,
            900,
        )
    ]
    coverage = news.window_coverage(grid, origins, buffer_minutes=15)[position]
    assert coverage.expected_batches == round(monday.news_window_hours * 4)
    assert coverage.ok_batches == coverage.expected_batches and coverage.feed_complete
    thinned = news.window_coverage(grid[::2], origins, buffer_minutes=15)[position]
    assert not thinned.feed_complete and thinned.ok_batches < thinned.expected_batches

"""Adjacent-session, availability, and missing-price temporal fixtures."""

from datetime import UTC, date, datetime, timedelta

import pytest

from newsvar.calendar import CalendarSnapshot, build_xnys_snapshot
from newsvar.ingestion.market import MarketSource
from newsvar.labels import (
    HISTORICAL_AVAILABILITY_BASIS,
    build_labels,
    historical_prior_session_availability,
)


@pytest.fixture(scope="module")
def grid() -> CalendarSnapshot:
    return build_xnys_snapshot(date(2025, 7, 2), date(2025, 7, 9))


def _source(values: dict[date, float], *, series_id: str = "SP500") -> MarketSource:
    return MarketSource(
        series_id=series_id,
        values=values,
        placeholders=(),
        source_rows=len(values),
        raw_sha256="a" * 64,
        raw_relative_path="synthetic.csv",
        retrieved_at_utc="2026-09-15T14:48:20+00:00",
    )


def _prices() -> dict[date, float]:
    return {
        date(2025, 7, 2): 100,
        date(2025, 7, 3): 99,
        date(2025, 7, 7): 101,
        date(2025, 7, 8): 102,
        date(2025, 7, 9): 103,
        date(2025, 7, 10): 104,
    }


def _build(grid: CalendarSnapshot, source: MarketSource):
    return build_labels(
        grid,
        source,
        historical_prior_session_availability(grid, source),
        availability_basis=HISTORICAL_AVAILABILITY_BASIS,
    )


def test_early_close_weekend_target_and_t_minus_two_training(grid: CalendarSnapshot) -> None:
    built = _build(grid, _source(_prices()))
    by_session = {label.origin_session: label for label in built.labels}
    july2 = by_session[date(2025, 7, 2)]
    july3 = by_session[date(2025, 7, 3)]
    july7_cutoff = next(
        origin.cutoff_utc for origin in grid.origins if origin.session == date(2025, 7, 7)
    )
    assert july2.target_end_session == date(2025, 7, 3)
    assert july2.target_end_utc == datetime(2025, 7, 3, 17, tzinfo=UTC)
    assert july2.return_simple == pytest.approx(-0.01)
    assert july2.source_raw_sha256 == "a" * 64
    assert july2.market_manifest_id is None
    assert july2.label_available_at_utc == july7_cutoff
    assert july2.eligible_for_refit(july7_cutoff)
    assert july3.target_end_session == date(2025, 7, 7)
    assert july3.return_simple == pytest.approx(101 / 99 - 1)
    assert not july3.eligible_for_refit(july7_cutoff)
    assert "return_simple" not in built.quality_report()


def test_missing_intermediate_close_does_not_bridge(grid: CalendarSnapshot) -> None:
    prices = _prices()
    del prices[date(2025, 7, 3)]
    built = _build(grid, _source(prices))
    skips = {item.origin_session: item.reason for item in built.skipped}
    sessions = {label.origin_session for label in built.labels}
    assert skips[date(2025, 7, 2)] == "missing_end_close"
    assert skips[date(2025, 7, 3)] == "missing_start_close"
    assert date(2025, 7, 7) in sessions
    assert date(2025, 7, 2) not in sessions


def test_calendar_edge_availability_is_unresolved(grid: CalendarSnapshot) -> None:
    built = _build(grid, _source(_prices()))
    skips = {item.origin_session: item.reason for item in built.skipped}
    assert skips[date(2025, 7, 8)] == "unknown_end_availability"
    assert skips[date(2025, 7, 9)] == "unknown_start_availability"


def test_explicit_availability_must_follow_each_scheduled_close(grid: CalendarSnapshot) -> None:
    source = _source(_prices())
    available = historical_prior_session_availability(grid, source)
    available[date(2025, 7, 3)] = datetime(2025, 7, 3, 16, tzinfo=UTC)
    built = build_labels(grid, source, available, availability_basis=HISTORICAL_AVAILABILITY_BASIS)
    skips = {item.origin_session: item.reason for item in built.skipped}
    assert skips[date(2025, 7, 2)] == "availability_before_scheduled_close"
    assert skips[date(2025, 7, 3)] == "availability_before_scheduled_close"
    available[date(2025, 7, 3)] = datetime(2025, 7, 3, 18)
    with pytest.raises(ValueError, match="UTC-aware"):
        build_labels(grid, source, available, availability_basis="historical")


def test_version_changes_with_availability_policy_or_mapping(grid: CalendarSnapshot) -> None:
    source = _source(_prices())
    available = historical_prior_session_availability(grid, source)
    original = build_labels(grid, source, available, availability_basis="historical")
    revised = build_labels(grid, source, available, availability_basis="prospective")
    assert original.target_vintage_id == revised.target_vintage_id
    assert original.label_version_id != revised.label_version_id
    available[date(2025, 7, 8)] += timedelta(minutes=1)
    delayed = build_labels(grid, source, available, availability_basis="historical")
    assert original.label_version_id != delayed.label_version_id


def test_wrong_series_and_naive_refit_cutoff_reject(grid: CalendarSnapshot) -> None:
    with pytest.raises(ValueError, match="SP500"):
        _build(grid, _source(_prices(), series_id="VIX"))
    label = _build(grid, _source(_prices())).labels[0]
    with pytest.raises(ValueError, match="timezone-aware"):
        label.eligible_for_refit(datetime(2025, 7, 7, 19, 30))

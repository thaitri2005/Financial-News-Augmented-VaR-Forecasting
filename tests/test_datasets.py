"""Small immutable Parquet dataset fixtures with no retained-source return output."""

from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from newsvar.data.calendar import CalendarSnapshot, build_xnys_snapshot
from newsvar.data.datasets import (
    DatasetIntegrityError,
    load_market_dataset,
    materialize_market_dataset,
    verify_calendar_extension,
)
from newsvar.data.market import MarketSource


def _source(
    series_id: str, values: dict[date, float], placeholders: tuple[date, ...] = ()
) -> MarketSource:
    return MarketSource(
        series_id=series_id,
        values=values,
        placeholders=placeholders,
        source_rows=len(values) + len(placeholders),
        raw_sha256=("a" if series_id == "SP500" else "b") * 64,
        raw_relative_path=f"{series_id.lower()}.csv",
        retrieved_at_utc="2026-09-15T14:48:20+00:00",
    )


@pytest.fixture(scope="module")
def calendars() -> tuple[CalendarSnapshot, CalendarSnapshot]:
    original = build_xnys_snapshot(date(2025, 7, 2), date(2025, 7, 8))
    extended = build_xnys_snapshot(date(2025, 7, 2), date(2025, 7, 10))
    return original, extended


@pytest.fixture(scope="module")
def sources() -> tuple[MarketSource, MarketSource]:
    prices = {
        date(2025, 7, 2): 100,
        date(2025, 7, 3): 99,
        date(2025, 7, 7): 101,
        date(2025, 7, 8): 102,
        date(2025, 7, 9): 103,
        date(2025, 7, 10): 104,
    }
    vix = {day: 20 for day in prices}
    vix[date(2025, 7, 4)] = 19
    return _source("SP500", prices, (date(2025, 7, 4),)), _source("VIX", vix)


def test_extension_requires_original_origin_equivalence(
    calendars: tuple[CalendarSnapshot, CalendarSnapshot],
) -> None:
    original, extended = calendars
    verify_calendar_extension(original, extended)
    with pytest.raises(DatasetIntegrityError, match="does not extend"):
        verify_calendar_extension(extended, original)


def test_materializes_versioned_tables_and_recovers_right_edge(
    tmp_path: Path,
    calendars: tuple[CalendarSnapshot, CalendarSnapshot],
    sources: tuple[MarketSource, MarketSource],
) -> None:
    _, extended = calendars
    sp500, vix = sources
    path, manifest = materialize_market_dataset(
        tmp_path, extended, sp500, vix, study_target_end=date(2025, 7, 8)
    )
    assert path.name == manifest["dataset_id"]
    assert manifest["tables"]["labels"]["rows"] == 4
    assert manifest["tables"]["label_exclusions"]["rows"] == 2
    labels = pq.read_table(path / "labels.parquet").to_pylist()
    assert {row["origin_session"] for row in labels} == {
        date(2025, 7, 2),
        date(2025, 7, 3),
        date(2025, 7, 7),
        date(2025, 7, 8),
    }
    july7 = next(row for row in labels if row["origin_session"] == date(2025, 7, 7))
    assert july7["target_end_in_study_horizon"] is True
    assert july7["market_manifest_id"] == manifest["dataset_id"]
    july8 = next(row for row in labels if row["origin_session"] == date(2025, 7, 8))
    assert july8["target_end_in_study_horizon"] is False
    market = pq.read_table(path / "market_observations.parquet").to_pylist()
    placeholder = next(
        row
        for row in market
        if row["series_id"] == "SP500" and row["observation_date"] == date(2025, 7, 4)
    )
    assert placeholder["value"] is None
    assert placeholder["quality_status"] == "source_placeholder_off_xnys_session"
    assert (
        materialize_market_dataset(
            tmp_path, extended, sp500, vix, study_target_end=date(2025, 7, 8)
        )[0]
        == path
    )


def test_dataset_loader_detects_table_corruption(
    tmp_path: Path,
    calendars: tuple[CalendarSnapshot, CalendarSnapshot],
    sources: tuple[MarketSource, MarketSource],
) -> None:
    _, extended = calendars
    path, _ = materialize_market_dataset(
        tmp_path, extended, *sources, study_target_end=date(2025, 7, 8)
    )
    table = path / "labels.parquet"
    table.write_bytes(table.read_bytes() + b"corruption")
    with pytest.raises(DatasetIntegrityError, match="checksum/size"):
        load_market_dataset(path)

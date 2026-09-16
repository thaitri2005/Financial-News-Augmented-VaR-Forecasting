"""Synthetic catalog completeness boundaries; ordinary tests never call GDELT."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

PROBE_PATH = Path(__file__).resolve().parents[1] / "docs/research/probe_gdelt_catalog.py"
SPEC = importlib.util.spec_from_file_location("probe_gdelt_catalog", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def _catalog(*, missing_batch: str | None = None) -> bytes:
    days = [("2020-03-15", 1), ("2020-03-16", 96), ("2020-03-17", 1)]
    lines: list[str] = []
    for day, count in days:
        for step in range(count):
            batch = (
                datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(minutes=15 * step)
            ).strftime("%Y%m%d%H%M%S")
            if batch == missing_batch:
                continue
            lines.append(
                f"100 {'a' * 32} http://data.gdeltproject.org/gdeltv2/{batch}.gkg.csv.zip\n"
            )
    return "".join(lines).encode()


class FakeCatalog(probe.RangeCatalog):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.total_bytes = len(payload)

    def read(self, start: int) -> bytes:
        return self.payload[start : start + probe.RANGE_BYTES]


def test_all_quarter_hour_files_and_transfer_bytes() -> None:
    report = FakeCatalog(_catalog()).gkg_day("2020-03-16")
    assert report["gkg_batches_listed"] == 96
    assert report["missing_batches"] == []
    assert report["listed_compressed_bytes"] == 9600
    assert report["first_gkg_batch"] == "20200316000000"
    assert report["last_gkg_batch"] == "20200316234500"
    assert len(report["gkg_manifest"]) == 96
    assert report["gkg_manifest"][0] == {
        "batch": "20200316000000",
        "compressed_bytes": 100,
        "md5": "a" * 32,
    }


def test_missing_batch_is_not_a_complete_day() -> None:
    report = FakeCatalog(_catalog(missing_batch="20200316123000")).gkg_day("2020-03-16")
    assert report["gkg_batches_listed"] == 95
    assert report["missing_batches"] == ["20200316123000"]


def test_partial_and_out_of_order_catalog_lines_reject() -> None:
    payload = _catalog()
    assert probe._dates(b"broken-prefix\n" + payload[:300], starts_at_zero=False)[0] == "20200315"
    with pytest.raises(probe.CatalogProbeError, match="chronological"):
        probe._dates(
            payload.splitlines()[1] + b"\n" + payload.splitlines()[0] + b"\n", starts_at_zero=True
        )

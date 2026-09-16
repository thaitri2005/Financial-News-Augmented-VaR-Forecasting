"""Tiny source-quality fixtures; no retained period outcome analysis."""

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from newsvar.ingestion.market import (
    MarketSourceError,
    market_coverage,
    parse_market_csv,
    retained_market_sources,
)


def _csv(tmp_path: Path, name: str, contents: str) -> tuple[Path, str]:
    path = tmp_path / name
    payload = contents.encode()
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def _parse(path: Path, digest: str, series_id: str = "SP500"):
    return parse_market_csv(
        path,
        series_id=series_id,
        expected_sha256=digest,
        raw_relative_path=path.name,
        retrieved_at_utc="2026-09-15T14:48:20+00:00",
    )


def test_fred_dates_and_placeholders(tmp_path: Path) -> None:
    path, digest = _csv(
        tmp_path,
        "fred.csv",
        "observation_date,SP500\n2025-01-08,6000.25\n2025-01-09,.\n2025-01-10,6020.50\n",
    )
    source = _parse(path, digest)
    assert source.source_rows == 3
    assert source.placeholders == (date(2025, 1, 9),)
    assert source.value_at(date(2025, 1, 10)) == 6020.50
    assert source.value_at(date(2025, 1, 9)) is None
    assert source.raw_sha256 == digest


@pytest.mark.parametrize(
    "contents,reason",
    [
        ("observation_date,SP500\n2025-01-08,1\n2025-01-08,2\n", "Duplicate"),
        ("observation_date,SP500\n2025-01-08,0\n", "positive and finite"),
        ("observation_date,SP500\n2025-01-08,nan\n", "positive and finite"),
        ("observation_date,SP500\n2025-01-08,inf\n", "positive and finite"),
        ("observation_date,SP500\n2025-13-08,1\n", "date"),
        ("DATE,SP500\n2025-01-08,1\n", "schema"),
        ("observation_date,SP500\n2025-01-08,1,extra\n", "Malformed"),
    ],
)
def test_fred_rejects_invalid_source(tmp_path: Path, contents: str, reason: str) -> None:
    path, digest = _csv(tmp_path, "fred.csv", contents)
    with pytest.raises(MarketSourceError, match=reason):
        _parse(path, digest)


def test_hash_and_utc_are_required(tmp_path: Path) -> None:
    path, digest = _csv(tmp_path, "fred.csv", "observation_date,SP500\n2025-01-08,1\n")
    with pytest.raises(MarketSourceError, match="SHA-256"):
        _parse(path, "0" * 64)
    with pytest.raises(MarketSourceError, match="UTC-aware"):
        parse_market_csv(
            path,
            series_id="SP500",
            expected_sha256=digest,
            raw_relative_path=path.name,
            retrieved_at_utc="2025-01-08T18:00:00",
        )


def test_vix_uses_close_and_rejects_blank(tmp_path: Path) -> None:
    path, digest = _csv(
        tmp_path,
        "vix.csv",
        "DATE,OPEN,HIGH,LOW,CLOSE\n01/08/2025,10,40,8,17.5\n",
    )
    assert _parse(path, digest, "VIX").value_at(date(2025, 1, 8)) == 17.5
    path, digest = _csv(
        tmp_path,
        "vix.csv",
        "DATE,OPEN,HIGH,LOW,CLOSE\n01/08/2025,10,40,8,\n",
    )
    with pytest.raises(MarketSourceError, match="Invalid market"):
        _parse(path, digest, "VIX")


def test_date_key_coverage_does_not_create_missing_index_close(tmp_path: Path) -> None:
    fred, fred_hash = _csv(
        tmp_path,
        "fred.csv",
        "observation_date,SP500\n2025-01-08,100\n2025-01-09,.\n2025-01-10,102\n",
    )
    vix, vix_hash = _csv(
        tmp_path,
        "vix.csv",
        "DATE,OPEN,HIGH,LOW,CLOSE\n01/08/2025,1,1,1,16\n01/09/2025,1,1,1,17\n01/10/2025,1,1,1,18\n",
    )
    sp = _parse(fred, fred_hash)
    vi = _parse(vix, vix_hash, "VIX")
    snapshot = SimpleNamespace(
        calendar_id="synthetic",
        requested_start=date(2025, 1, 8),
        requested_end=date(2025, 1, 10),
        origins=[
            SimpleNamespace(session=date(2025, 1, 8)),
            SimpleNamespace(session=date(2025, 1, 10)),
        ],
    )
    coverage = market_coverage(snapshot, sp, vi)
    assert coverage.sp500_session_values == 2
    assert coverage.missing_sp500_sessions == ()
    assert coverage.vix_non_session_dates == (date(2025, 1, 9),)
    assert coverage.fred_placeholders_in_range == (date(2025, 1, 9),)
    assert "return" not in coverage.report(sp, vi)


def test_retained_manifest_rejects_escape_and_wrong_bytes(tmp_path: Path) -> None:
    fred, fred_hash = _csv(tmp_path, "fred.csv", "observation_date,SP500\n2025-01-08,100\n")
    vix, vix_hash = _csv(tmp_path, "vix.csv", "DATE,OPEN,HIGH,LOW,CLOSE\n01/08/2025,1,1,1,17\n")
    entries = [
        {
            "name": name,
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "audit": {"rows": 1, "valid_values": 1},
        }
        for name, path, digest in (
            ("fred_sp500.csv", fred, fred_hash),
            ("cboe_vix.csv", vix, vix_hash),
        )
    ]
    audit = tmp_path / "audit.json"
    report = {"retrieved_at_utc": "2026-09-15T14:48:20+00:00", "snapshots": entries}
    audit.write_text(json.dumps(report), encoding="utf-8")
    assert retained_market_sources(tmp_path, audit)[0].source_rows == 1
    entries[0]["path"] = "../fred.csv"
    audit.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(MarketSourceError, match="leaves project"):
        retained_market_sources(tmp_path, audit)
    entries[0]["path"] = "fred.csv"
    entries[0]["bytes"] = 1
    audit.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(MarketSourceError, match="byte count"):
        retained_market_sources(tmp_path, audit)

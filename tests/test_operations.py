"""Synthetic fixtures for daily operation: extraction reruns, bars, and live forecast gating."""

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from newsvar.data import gdelt, ohlc
from newsvar.study import operate
from newsvar.study import volatility as study
from tests.test_gdelt_stream import PAYLOAD
from tests.test_volatility import _synthetic_rows


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("batch.gkg.csv", text)
    return buffer.getvalue()


def _catalog(tmp_path: Path, stamps: list[str], body: bytes) -> dict[str, gdelt.CatalogEntry]:
    lines = [
        f"{len(body)} {hashlib.md5(body).hexdigest()} "
        f"http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip\n"
        for stamp in stamps
    ]
    path = tmp_path / f"catalog-{len(stamps)}.txt"
    path.write_text("".join(lines), encoding="utf-8")
    day = date(2020, 3, 16)
    return gdelt.read_catalog(path, start=day, end=day)


def test_rerun_fetches_only_new_batches_and_cannot_lose_verified_ones(tmp_path: Path) -> None:
    day, root, body = date(2020, 3, 16), tmp_path / "titles", _zip(PAYLOAD)
    early = _catalog(tmp_path, ["20200316000000", "20200316001500"], body)
    first = gdelt.extract_day(day, early, root, catalog_sha256="a" * 64, fetch=lambda s: body)
    assert gdelt.day_is_final(first, early) and first["title_rows"] == 4
    # Extracted before the day ended: the grown catalog makes the day non-final again.
    later = _catalog(tmp_path, ["20200316000000", "20200316001500", "20200316003000"], body)
    assert not gdelt.day_is_final(first, later)
    calls: list[str] = []

    def failing(stamp: str) -> bytes:
        calls.append(stamp)
        raise gdelt.GdeltError("offline")

    broken = gdelt.extract_day(day, later, root, catalog_sha256="b" * 64, fetch=failing)
    assert calls == ["20200316003000"]
    status = {batch["stamp"]: batch["status"] for batch in broken["batches"]}
    assert status["20200316000000"] == gdelt.OK and status["20200316003000"] == gdelt.FETCH_FAILED
    assert pq.read_table(root / "date=2020-03-16" / "titles.parquet").num_rows == 4
    assert broken["titles_sha256"] == first["titles_sha256"]

    def gone(stamp: str) -> bytes:
        raise gdelt.GdeltNotFound("404")

    missing = gdelt.extract_day(day, later, root, catalog_sha256="b" * 64, fetch=gone)
    assert gdelt.day_is_final(missing, later)
    assert {b["stamp"]: b["status"] for b in missing["batches"]}[
        "20200316003000"
    ] == gdelt.NOT_FOUND
    # A permanently missing batch is not retried.
    assert gdelt.extract_day(day, later, root, catalog_sha256="b" * 64, fetch=failing) == missing


def test_rerun_adds_newly_catalogued_batches(tmp_path: Path) -> None:
    day, root, body = date(2020, 3, 16), tmp_path / "titles", _zip(PAYLOAD)
    early = _catalog(tmp_path, ["20200316000000"], body)
    gdelt.extract_day(day, early, root, catalog_sha256="a" * 64, fetch=lambda s: body)
    later = _catalog(tmp_path, ["20200316000000", "20200316001500"], body)
    fetched: list[str] = []

    def fetch(stamp: str) -> bytes:
        fetched.append(stamp)
        return body

    done = gdelt.extract_day(day, later, root, catalog_sha256="b" * 64, fetch=fetch)
    assert fetched == ["20200316001500"] and done["title_rows"] == 4
    assert gdelt.day_is_final(gdelt.load_day(root, day), later)


def _chart(tmp_path: Path, name: str, bars: list[tuple[str, float, float, float, float]]) -> Path:
    stamps = [int(datetime.fromisoformat(f"{day}T09:30:00-05:00").timestamp()) for day, *_ in bars]
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": stamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [bar[1] for bar in bars],
                                "high": [bar[2] for bar in bars],
                                "low": [bar[3] for bar in bars],
                                "close": [bar[4] for bar in bars],
                            }
                        ]
                    },
                    "events": {"dividends": {str(stamps[1]): {"date": stamps[1], "amount": 1.5}}},
                }
            ]
        }
    }
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_bars_dividends_and_validators(tmp_path: Path) -> None:
    path = _chart(
        tmp_path,
        "bars.json",
        [("2024-01-02", 100.0, 102.0, 99.0, 101.0), ("2024-01-03", 101.5, 103.0, 100.5, 102.0)],
    )
    bars = ohlc.parse_chart(path)
    assert sorted(bars) == [date(2024, 1, 2), date(2024, 1, 3)]
    assert bars[date(2024, 1, 3)].open == 101.5
    assert ohlc.parse_dividends(path) == {date(2024, 1, 3): 1.5}
    with pytest.raises(ohlc.OhlcError):
        ohlc.Bar(100.0, 99.0, 98.0, 100.0)
    days = [date(2022, 1, 3) + timedelta(days=i) for i in range(400)]
    closes = {day: 100.0 * (1.0 + 0.01 * ((i * 7) % 5 - 2)) + i for i, day in enumerate(days)}
    good = {
        day: ohlc.Bar(value, value * 1.01, value * 0.99, value) for day, value in closes.items()
    }
    assert ohlc.validate_against_closes(good, closes)["sessions_over_1bp"] == 0
    assert ohlc.validate_tracking(good, closes)["return_correlation"] == pytest.approx(1.0)
    off = dict(good)
    off[days[10]] = ohlc.Bar(1.0, 500.0, 0.5, closes[days[10]] * 1.01)
    with pytest.raises(ohlc.OhlcError):
        ohlc.validate_against_closes(off, closes)
    scrambled = {
        day: ohlc.Bar(v, v * 1.01, v * 0.99, v)
        for day, v in zip(days, reversed(list(closes.values())), strict=True)
    }
    with pytest.raises(ohlc.OhlcError):
        ohlc.validate_tracking(scrambled, closes)


def _operational_rows() -> list[dict[str, object]]:
    rows = _synthetic_rows(size=620)
    for row in rows:
        session = row["session"]
        close = datetime(session.year, session.month, session.day, 21, tzinfo=UTC)
        opened = close - timedelta(hours=6, minutes=30)
        row["window_pre_close"] = (
            close - timedelta(hours=48, minutes=30),
            close - timedelta(hours=24, minutes=30),
        )
        row["window_at_open"] = (close - timedelta(hours=24), opened - timedelta(minutes=15))
        row["deadline_pre_close"] = close - timedelta(hours=24)
        row["deadline_at_open"] = opened + timedelta(minutes=30)
        row["ingested_pre_close"] = True
        row["ingested_at_open"] = True
    return rows


def test_unlabelled_forecast_equals_the_study_forecast() -> None:
    rows = _operational_rows()
    target = rows[-1]["session"]
    studied = study.forecast_all(rows, "at_open")[target]
    live_rows = [dict(row) for row in rows]
    live_rows[-1]["ret_at_open"] = None
    live_rows[-1]["var_at_open"] = None
    assert target not in study.forecast_all(live_rows, "at_open")
    live = study.forecast_all(live_rows, "at_open", include_unlabelled=True)[target]
    assert live == studied


def test_live_forecast_is_gated_on_time_freshness_and_ingestion() -> None:
    rows = _operational_rows()
    target = rows[-1]
    for name in ("ret_pre_close", "var_pre_close", "ret_at_open", "var_at_open"):
        target[name] = None
    pre_ready = target["window_pre_close"][1]
    open_ready = target["window_at_open"][1]
    text = {contract: __import__("numpy").zeros((len(rows), 5)) for contract in study.CONTRACTS}

    def run(as_of: datetime, data_as_of: datetime) -> dict[str, dict[str, object]]:
        return operate.forecast_session(
            None,
            target["session"],
            as_of=as_of,
            data_as_of=data_as_of,
            text=text,
            rows=rows,  # type: ignore[arg-type]
        )["contracts"]

    early = run(pre_ready - timedelta(minutes=1), pre_ready - timedelta(minutes=1))
    assert early["pre_close"]["reason"] == "information time not reached"
    on_time = run(pre_ready + timedelta(minutes=5), pre_ready + timedelta(minutes=1))
    assert on_time["pre_close"]["status"] == "ok" and on_time["pre_close"]["timing"] == "on_time"
    assert on_time["pre_close"]["models"]["har"]["var_95_return"] < 0
    assert on_time["at_open"]["reason"] == "information time not reached"
    stale = run(open_ready + timedelta(minutes=20), pre_ready + timedelta(minutes=1))
    assert stale["at_open"]["reason"].startswith("data were refreshed before")
    assert stale["pre_close"]["timing"] == "late"
    target["ingested_at_open"] = False
    waiting = run(open_ready + timedelta(minutes=20), open_ready + timedelta(minutes=18))
    assert waiting["at_open"]["reason"].startswith("news not yet ingested")
    target["ingested_at_open"] = True
    ready = run(open_ready + timedelta(minutes=20), open_ready + timedelta(minutes=18))
    assert ready["at_open"]["status"] == "ok" and ready["at_open"]["timing"] == "on_time"
    late = run(open_ready + timedelta(hours=3), open_ready + timedelta(hours=3))
    assert late["at_open"]["status"] == "ok" and late["at_open"]["timing"] == "late"
    with pytest.raises(study.VolatilityStudyError):
        operate.forecast_session(
            None,
            date(1999, 1, 1),
            as_of=pre_ready,
            text=text,
            rows=rows,  # type: ignore[arg-type]
        )

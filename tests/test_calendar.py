"""Exchange-session and cutoff fixtures around known irregular dates."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from newsvar.cli import app
from newsvar.data.calendar import build_xnys_snapshot, load_snapshot, write_snapshot
from newsvar.hashing import IntegrityError, canonical_json, sha256


def test_early_close_holiday_and_exact_news_boundaries() -> None:
    snap = build_xnys_snapshot(date(2025, 7, 2), date(2025, 7, 7))
    assert [origin.session.isoformat() for origin in snap.origins] == [
        "2025-07-02",
        "2025-07-03",
        "2025-07-07",
    ]
    early, monday = snap.origins[1:]
    assert early.close_utc == datetime(2025, 7, 3, 17, tzinfo=UTC)
    assert early.cutoff_utc == datetime(2025, 7, 3, 16, 30, tzinfo=UTC)
    assert early.issue_deadline_utc == datetime(2025, 7, 3, 16, 45, tzinfo=UTC)
    assert early.next_session == monday.session == date(2025, 7, 7)
    assert early.target_end_utc == monday.close_utc
    assert monday.previous_cutoff_utc == early.cutoff_utc
    assert monday.market_last_session == date(2025, 7, 3)
    assert monday.news_window_hours == 99
    assert not monday.includes_news_at(early.cutoff_utc)
    assert monday.includes_news_at(early.cutoff_utc + timedelta(microseconds=1))
    assert monday.includes_news_at(monday.cutoff_utc)
    assert not monday.includes_news_at(monday.cutoff_utc + timedelta(microseconds=1))
    assert early.includes_news_at(early.cutoff_utc)


def test_dst_keeps_new_york_cutoff_but_changes_utc() -> None:
    snap = build_xnys_snapshot(date(2025, 3, 7), date(2025, 3, 10))
    friday, monday = snap.origins
    ny = ZoneInfo("America/New_York")
    assert friday.cutoff_utc == datetime(2025, 3, 7, 20, 30, tzinfo=UTC)
    assert monday.cutoff_utc == datetime(2025, 3, 10, 19, 30, tzinfo=UTC)
    assert (friday.cutoff_utc.astimezone(ny).hour, friday.cutoff_utc.astimezone(ny).minute) == (
        15,
        30,
    )
    assert (monday.cutoff_utc.astimezone(ny).hour, monday.cutoff_utc.astimezone(ny).minute) == (
        15,
        30,
    )
    assert monday.news_window_hours == 71


def test_special_closure_does_not_create_a_target_session() -> None:
    snap = build_xnys_snapshot(date(2025, 1, 8), date(2025, 1, 10))
    assert [origin.session for origin in snap.origins] == [date(2025, 1, 8), date(2025, 1, 10)]
    assert snap.origins[0].next_session == date(2025, 1, 10)
    assert snap.origins[1].market_last_session == date(2025, 1, 8)


def test_saved_snapshot_is_immutable_and_checked_on_load(tmp_path: Path) -> None:
    snapshot = build_xnys_snapshot(date(2025, 7, 3), date(2025, 7, 7))
    file = write_snapshot(snapshot, tmp_path / "calendars")
    assert write_snapshot(snapshot, tmp_path / "calendars") == file
    assert load_snapshot(file) == snapshot
    record = json.loads(file.read_text())
    record["origins"][0]["cutoff_utc"] = "2025-07-03T16:31:00+00:00"
    file.write_text(json.dumps(record))
    with pytest.raises(IntegrityError, match="hash"):
        load_snapshot(file)
    with pytest.raises(IntegrityError, match="differs"):
        write_snapshot(snapshot, tmp_path / "calendars")


def test_range_and_timezone_inputs_fail_cleanly() -> None:
    with pytest.raises(ValueError, match="no XNYS"):
        build_xnys_snapshot(date(2025, 7, 4), date(2025, 7, 4))
    with pytest.raises(ValueError, match="coverage"):
        build_xnys_snapshot(date(2090, 9, 15), date(2090, 9, 15))
    with pytest.raises(ValueError, match="Cutoff"):
        build_xnys_snapshot(date(2025, 7, 3), date(2025, 7, 3), issue_minutes_before_close=30)
    origin = build_xnys_snapshot(date(2025, 7, 3), date(2025, 7, 3)).origins[0]
    with pytest.raises(ValueError, match="timezone-aware"):
        origin.includes_news_at(datetime(2025, 7, 3, 16, 30))


def test_matching_new_hash_cannot_hide_changed_cutoff_margin(tmp_path: Path) -> None:
    snap = build_xnys_snapshot(date(2025, 7, 3), date(2025, 7, 3))
    body = snap.body()
    body["origins"][0]["cutoff_utc"] = "2025-07-03T16:31:00+00:00"
    changed_id = sha256(canonical_json(body))
    file = tmp_path / f"{changed_id}.json"
    file.write_bytes(canonical_json({"calendar_id": changed_id, **body}) + b"\n")
    with pytest.raises(IntegrityError, match="margins"):
        load_snapshot(file)


def test_calendar_cli_build_inspect_and_invalid_range(tmp_path: Path) -> None:
    runner = CliRunner()
    built = runner.invoke(
        app,
        [
            "calendar",
            "build",
            "--start",
            "2025-07-03",
            "--end",
            "2025-07-07",
            "--output-dir",
            str(tmp_path),
        ],
    )
    assert built.exit_code == 0, built.stdout
    result = json.loads(built.stdout)
    assert result["origins"] == 2
    inspected = runner.invoke(app, ["calendar", "inspect", result["path"]])
    assert inspected.exit_code == 0
    assert json.loads(inspected.stdout)["calendar_id"] == result["calendar_id"]
    bad = runner.invoke(app, ["calendar", "build", "--start", "2025-07-07", "--end", "2025-07-03"])
    assert bad.exit_code == 2

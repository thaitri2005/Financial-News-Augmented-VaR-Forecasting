"""Resource boundary tests use synthetic measurements, independent of laptop load."""

import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from newsvar.cli import app
from newsvar.doctor import GIB, ResourceSnapshot, Stage, evaluate


@pytest.fixture
def snapshot() -> ResourceSnapshot:
    return ResourceSnapshot(
        "2026-09-15T00:00:00+00:00", "3.12.2", True, 16 * GIB, 5 * GIB, 15 * GIB, GIB
    )


@pytest.mark.parametrize(
    "stage,required", [(Stage.NORMALIZATION, 3 * GIB), (Stage.SENTIMENT, 5 * GIB)]
)
def test_ram_boundary(snapshot: ResourceSnapshot, stage: Stage, required: int) -> None:
    assert evaluate(replace(snapshot, ram_available_bytes=required), stage).ready
    assert not evaluate(replace(snapshot, ram_available_bytes=required - 1), stage).ready


def test_low_ram_allows_small_diagnostics_only(snapshot: ResourceSnapshot) -> None:
    low = replace(snapshot, ram_available_bytes=GIB)
    assert evaluate(low, Stage.DIAGNOSTICS).ready
    assert not evaluate(low, Stage.NORMALIZATION).ready
    assert not evaluate(low, Stage.SENTIMENT).ready


def test_rss_stop_boundary(snapshot: ResourceSnapshot) -> None:
    assert evaluate(replace(snapshot, process_tree_rss_bytes=6 * GIB), Stage.SENTIMENT).ready
    assert not evaluate(
        replace(snapshot, process_tree_rss_bytes=6 * GIB + 1), Stage.SENTIMENT
    ).ready


@pytest.mark.parametrize(
    "field,value",
    [
        ("disk_free_bytes", 15 * GIB - 1),
        ("python_supported", False),
        ("missing_timezones", ("America/New_York",)),
        ("measurement_errors", ("RAM measurement failed",)),
    ],
)
def test_environment_failures_block(snapshot: ResourceSnapshot, field: str, value: object) -> None:
    assert not evaluate(replace(snapshot, **{field: value}), Stage.SENTIMENT).ready


def test_cli_reports_all_gates_and_requested_exit(
    snapshot: ResourceSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "newsvar.cli.collect_snapshot", lambda _: replace(snapshot, ram_available_bytes=GIB)
    )
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["stages"]["diagnostics"]["ready"]
    assert not report["stages"]["sentiment"]["ready"]
    blocked = runner.invoke(app, ["doctor", "--stage", "sentiment", "--json"])
    assert blocked.exit_code == 3
    assert not json.loads(blocked.stdout)["ready"]


def test_invalid_stage_is_usage_error() -> None:
    assert CliRunner().invoke(app, ["doctor", "--stage", "unknown"]).exit_code == 2

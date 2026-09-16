"""Read-only resource preflight; no ingestion, model loading, or credential access.

Thresholds implement blueprint section 18.1. A snapshot does not enforce memory
limits on a later job: continuous process monitoring is a separate capability.
"""

import platform
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psutil

GIB = 1024**3
MIN_FREE_DISK = 15 * GIB
MAX_PROCESS_TREE_RSS = 6 * GIB
REQUIRED_TIMEZONES = ("UTC", "America/New_York", "Asia/Ho_Chi_Minh")


class Stage(StrEnum):
    DIAGNOSTICS = "diagnostics"
    NORMALIZATION = "normalization"
    SENTIMENT = "sentiment"


MIN_AVAILABLE_RAM = {
    Stage.DIAGNOSTICS: 0,
    Stage.NORMALIZATION: 3 * GIB,
    Stage.SENTIMENT: 5 * GIB,
}


@dataclass(frozen=True)
class ResourceSnapshot:
    collected_at_utc: str
    python_version: str
    python_supported: bool
    ram_total_bytes: int
    ram_available_bytes: int
    disk_free_bytes: int
    process_tree_rss_bytes: int
    missing_timezones: tuple[str, ...] = ()
    measurement_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateResult:
    stage: str
    ready: bool
    reasons: tuple[str, ...]


def collect_snapshot(project_root: Path) -> ResourceSnapshot:
    """Observe this invocation's process tree and the project's storage volume."""
    errors: list[str] = []
    ram_total = ram_available = disk_free = rss = 0
    try:
        memory = psutil.virtual_memory()
        ram_total, ram_available = memory.total, memory.available
    except (OSError, psutil.Error) as exc:
        errors.append(f"RAM measurement failed: {type(exc).__name__}")
    try:
        disk_free = psutil.disk_usage(str(project_root)).free
    except (OSError, psutil.Error) as exc:
        errors.append(f"Disk measurement failed: {type(exc).__name__}")
    try:
        process = psutil.Process()
        rss = process.memory_info().rss
        for child in process.children(recursive=True):
            try:
                rss += child.memory_info().rss
            except psutil.NoSuchProcess:
                # A process that exited during the snapshot consumes no later RSS.
                continue
    except (OSError, psutil.Error) as exc:
        errors.append(f"Process RSS measurement incomplete: {type(exc).__name__}")
    missing = []
    for name in REQUIRED_TIMEZONES:
        try:
            ZoneInfo(name)
        except ZoneInfoNotFoundError:
            missing.append(name)
    return ResourceSnapshot(
        collected_at_utc=datetime.now(UTC).isoformat(),
        python_version=platform.python_version(),
        python_supported=sys.version_info[:2] == (3, 12),
        ram_total_bytes=ram_total,
        ram_available_bytes=ram_available,
        disk_free_bytes=disk_free,
        process_tree_rss_bytes=rss,
        missing_timezones=tuple(missing),
        measurement_errors=tuple(errors),
    )


def evaluate(snapshot: ResourceSnapshot, stage: Stage) -> GateResult:
    """Evaluate exact byte boundaries; unknown measurements fail closed."""
    reasons = list(snapshot.measurement_errors)
    if not snapshot.python_supported:
        reasons.append("The project requires Python 3.12.")
    if snapshot.missing_timezones:
        reasons.append("Missing timezones: " + ", ".join(snapshot.missing_timezones))
    if snapshot.disk_free_bytes < MIN_FREE_DISK:
        reasons.append("Free project-volume disk is below the 15 GiB reserve.")
    required = MIN_AVAILABLE_RAM[stage]
    if snapshot.ram_available_bytes < required:
        reasons.append(f"Available RAM is below the {required / GIB:g} GiB stage requirement.")
    if stage != Stage.DIAGNOSTICS and snapshot.process_tree_rss_bytes > MAX_PROCESS_TREE_RSS:
        reasons.append("Observed process-tree RSS exceeds the 6 GiB stop threshold.")
    return GateResult(stage=stage.value, ready=not reasons, reasons=tuple(reasons))


def make_report(snapshot: ResourceSnapshot, requested_stage: Stage) -> dict[str, object]:
    """Expose every stage's readiness while returning the requested stage's status."""
    gates = {stage.value: asdict(evaluate(snapshot, stage)) for stage in Stage}
    return {
        "schema_version": "doctor_v1",
        "requested_stage": requested_stage.value,
        "ready": gates[requested_stage.value]["ready"],
        "snapshot": asdict(snapshot),
        "stages": gates,
        "limitations": [
            "Preflight only; source admission and model/runtime compatibility are not checked.",
            "RSS covers this invocation and children, not a future job or unrelated notebooks.",
            "Summed process RSS can double-count shared pages; live monitoring is not implemented.",
        ],
    }

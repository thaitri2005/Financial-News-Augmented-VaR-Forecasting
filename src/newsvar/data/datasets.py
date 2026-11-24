"""Versioned local Parquet market/label datasets with immutable lineage manifests."""

import hashlib
import json
import os
import uuid
from datetime import UTC, date, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.data.calendar import CalendarSnapshot
from newsvar.data.labels import LabelBuild, build_labels
from newsvar.data.market import MARKET_AVAILABILITY_BASIS, MarketSource
from newsvar.hashing import IntegrityError, canonical_json, sha256

DATASET_SCHEMA_VERSION = "market_dataset_v1"
MATERIALIZER_VERSION = "1"

MARKET_SCHEMA = pa.schema(
    [
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("series_id", pa.string(), nullable=False),
        pa.field("observation_date", pa.date32(), nullable=False),
        pa.field("value", pa.float64(), nullable=True),
        pa.field("unit", pa.string(), nullable=False),
        pa.field("observation_close_utc", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("available_at_utc", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("availability_basis", pa.string(), nullable=False),
        pa.field("retrieved_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("raw_sha256", pa.string(), nullable=False),
        pa.field("raw_relative_path", pa.string(), nullable=False),
        pa.field("source_rows", pa.int32(), nullable=False),
        pa.field("quality_status", pa.string(), nullable=False),
    ]
)

LABEL_SCHEMA = pa.schema(
    [
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("label_version_id", pa.string(), nullable=False),
        pa.field("target_vintage_id", pa.string(), nullable=False),
        pa.field("calendar_id", pa.string(), nullable=False),
        pa.field("profile_id", pa.string(), nullable=False),
        pa.field("origin_session", pa.date32(), nullable=False),
        pa.field("target_start_session", pa.date32(), nullable=False),
        pa.field("target_end_session", pa.date32(), nullable=False),
        pa.field("target_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("target_end_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("start_close", pa.float64(), nullable=False),
        pa.field("end_close", pa.float64(), nullable=False),
        pa.field("return_simple", pa.float64(), nullable=False),
        pa.field("label_available_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("label_availability_basis", pa.string(), nullable=False),
        pa.field("source_raw_sha256", pa.string(), nullable=False),
        pa.field("source_raw_relative_path", pa.string(), nullable=False),
        pa.field("source_retrieved_at_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("market_manifest_id", pa.string(), nullable=False),
        pa.field("target_end_in_study_horizon", pa.bool_(), nullable=False),
    ]
)

EXCLUSION_SCHEMA = pa.schema(
    [
        pa.field("dataset_id", pa.string(), nullable=False),
        pa.field("label_version_id", pa.string(), nullable=False),
        pa.field("origin_session", pa.date32(), nullable=False),
        pa.field("target_end_session", pa.date32(), nullable=False),
        pa.field("reason", pa.string(), nullable=False),
        pa.field("target_end_in_study_horizon", pa.bool_(), nullable=False),
    ]
)


class DatasetIntegrityError(IntegrityError):
    """A derived market dataset cannot be trusted or replayed."""


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != UTC.utcoffset(None):
        raise DatasetIntegrityError("Persisted timestamp must be UTC-aware.")
    return result.astimezone(UTC)


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _sync_file(path: Path) -> None:
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _source_identity(source: MarketSource) -> dict[str, object]:
    return {
        "series_id": source.series_id,
        "raw_sha256": source.raw_sha256,
        "raw_relative_path": source.raw_relative_path,
        "retrieved_at_utc": source.retrieved_at_utc,
        "source_rows": source.source_rows,
        "valid_values": len(source.values),
        "placeholders": [item.isoformat() for item in source.placeholders],
    }


def dataset_identity(
    snapshot: CalendarSnapshot,
    sp500: MarketSource,
    vix: MarketSource,
    *,
    study_target_end: date,
) -> dict[str, object]:
    """All semantic inputs that must change a derived market dataset ID."""
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "materializer_version": MATERIALIZER_VERSION,
        "pyarrow_version": version("pyarrow"),
        "calendar_id": snapshot.calendar_id,
        "calendar_requested_start": snapshot.requested_start.isoformat(),
        "calendar_requested_end": snapshot.requested_end.isoformat(),
        "availability_basis": MARKET_AVAILABILITY_BASIS,
        "study_target_end": study_target_end.isoformat(),
        "sources": {"sp500": _source_identity(sp500), "vix": _source_identity(vix)},
    }


def dataset_id(identity: dict[str, object]) -> str:
    return sha256(canonical_json(identity))


def verify_calendar_extension(original: CalendarSnapshot, extended: CalendarSnapshot) -> None:
    """Require a new schedule to preserve every earlier origin byte-for-byte semantically."""
    if original.requested_start != extended.requested_start:
        raise DatasetIntegrityError("Extended calendar changes the original requested start.")
    if extended.requested_end <= original.requested_end:
        raise DatasetIntegrityError("Extended calendar does not extend the original requested end.")
    if (
        original.calendar_package_version != extended.calendar_package_version
        or original.tzdata_version != extended.tzdata_version
        or original.cutoff_minutes_before_close != extended.cutoff_minutes_before_close
        or original.issue_minutes_before_close != extended.issue_minutes_before_close
    ):
        raise DatasetIntegrityError("Extended calendar changes package/timezone/profile identity.")
    old = {origin.session: origin.to_record() for origin in original.origins}
    new = {origin.session: origin.to_record() for origin in extended.origins}
    if any(new.get(session) != record for session, record in old.items()):
        raise DatasetIntegrityError("Extended calendar differs on an original origin.")


def source_availability(snapshot: CalendarSnapshot, source: MarketSource) -> dict[date, datetime]:
    """Historical proxy: a dated close becomes usable at the next XNYS cutoff."""
    cutoff_by_session = {origin.session: origin.cutoff_utc for origin in snapshot.origins}
    return {
        origin.session: cutoff_by_session[origin.next_session]
        for origin in snapshot.origins
        if origin.session in source.values and origin.next_session in cutoff_by_session
    }


def _market_records(
    dataset_id_value: str,
    snapshot: CalendarSnapshot,
    source: MarketSource,
    available: dict[date, datetime],
) -> list[dict[str, object]]:
    origins = {origin.session: origin for origin in snapshot.origins}
    days = sorted(
        day
        for day in set(source.values) | set(source.placeholders)
        if snapshot.requested_start <= day <= snapshot.requested_end
    )
    records: list[dict[str, object]] = []
    for day in days:
        origin = origins.get(day)
        value = source.values.get(day)
        if value is None:
            quality_status = (
                "source_placeholder_xnys_session"
                if origin is not None
                else "source_placeholder_off_xnys_session"
            )
        else:
            quality_status = (
                "valid_xnys_session" if origin is not None else "valid_off_xnys_session"
            )
        records.append(
            {
                "dataset_id": dataset_id_value,
                "series_id": source.series_id,
                "observation_date": day,
                "value": value,
                "unit": (
                    "sp500_price_index_points"
                    if source.series_id == "SP500"
                    else "vix_index_points"
                ),
                "observation_close_utc": origin.close_utc if origin is not None else None,
                "available_at_utc": available.get(day),
                "availability_basis": MARKET_AVAILABILITY_BASIS,
                "retrieved_at_utc": _parse_utc(source.retrieved_at_utc),
                "raw_sha256": source.raw_sha256,
                "raw_relative_path": source.raw_relative_path,
                "source_rows": source.source_rows,
                "quality_status": quality_status,
            }
        )
    return records


def _label_records(
    dataset_id_value: str,
    labels: LabelBuild,
    *,
    study_target_end: date,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for label in labels.labels:
        records.append(
            {
                "dataset_id": dataset_id_value,
                "label_version_id": label.label_version_id,
                "target_vintage_id": label.target_vintage_id,
                "calendar_id": label.calendar_id,
                "profile_id": label.profile_id,
                "origin_session": label.origin_session,
                "target_start_session": label.target_start_session,
                "target_end_session": label.target_end_session,
                "target_start_utc": label.target_start_utc,
                "target_end_utc": label.target_end_utc,
                "start_close": label.start_close,
                "end_close": label.end_close,
                "return_simple": label.return_simple,
                "label_available_at_utc": label.label_available_at_utc,
                "label_availability_basis": label.label_availability_basis,
                "source_raw_sha256": label.source_raw_sha256,
                "source_raw_relative_path": label.source_raw_relative_path,
                "source_retrieved_at_utc": _parse_utc(label.source_retrieved_at_utc),
                "market_manifest_id": dataset_id_value,
                "target_end_in_study_horizon": label.target_end_session <= study_target_end,
            }
        )
    return records


def _exclusion_records(
    dataset_id_value: str,
    snapshot: CalendarSnapshot,
    labels: LabelBuild,
    *,
    study_target_end: date,
) -> list[dict[str, object]]:
    targets = {origin.session: origin.next_session for origin in snapshot.origins}
    return [
        {
            "dataset_id": dataset_id_value,
            "label_version_id": labels.label_version_id,
            "origin_session": item.origin_session,
            "target_end_session": targets[item.origin_session],
            "reason": item.reason,
            "target_end_in_study_horizon": targets[item.origin_session] <= study_target_end,
        }
        for item in labels.skipped
    ]


def _write_table(path: Path, records: list[dict[str, object]], schema: pa.Schema) -> None:
    table = pa.Table.from_pylist(records, schema=schema)
    pq.write_table(table, path, compression="zstd", version="2.6", write_statistics=True)
    _sync_file(path)


def _manifest(
    identity: dict[str, object],
    dataset_id_value: str,
    tables: dict[str, Path],
    *,
    rows: dict[str, int],
) -> dict[str, object]:
    return {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_id": dataset_id_value,
        "identity": identity,
        "tables": {
            name: {
                "path": path.name,
                "sha256": _file_sha256(path),
                "bytes": path.stat().st_size,
                "rows": rows[name],
            }
            for name, path in tables.items()
        },
        "publication": {
            "format": "parquet",
            "compression": "zstd",
            "writer": f"pyarrow=={version('pyarrow')}",
            "publication_protocol": "same_volume_staged_directory_rename_v1",
        },
    }


def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
    payload = canonical_json(manifest) + b"\n"
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetIntegrityError("Dataset manifest is missing or invalid.") from exc
    if not isinstance(value, dict):
        raise DatasetIntegrityError("Dataset manifest must be an object.")
    return value


def load_market_dataset(path: Path, *, require_directory_id: bool = True) -> dict[str, Any]:
    """Verify a committed derived dataset before exposing its metadata to consumers."""
    root = path.resolve(strict=True)
    manifest = _load_manifest(root / "manifest.json")
    try:
        identity = manifest["identity"]
        dataset_id_value = manifest["dataset_id"]
        tables = manifest["tables"]
        if (
            manifest["schema_version"] != DATASET_SCHEMA_VERSION
            or not isinstance(identity, dict)
            or not isinstance(dataset_id_value, str)
            or dataset_id(identity) != dataset_id_value
            or (require_directory_id and root.name != dataset_id_value)
            or set(tables) != {"market_observations", "labels", "label_exclusions"}
        ):
            raise DatasetIntegrityError(
                "Dataset manifest identity/schema disagrees with directory."
            )
        for _name, info in tables.items():
            if not isinstance(info, dict) or set(info) != {"path", "sha256", "bytes", "rows"}:
                raise DatasetIntegrityError("Dataset table manifest has unsupported fields.")
            file_path = (root / info["path"]).resolve(strict=True)
            if not file_path.is_relative_to(root) or file_path.name != info["path"]:
                raise DatasetIntegrityError("Dataset table path leaves its committed directory.")
            if (
                file_path.stat().st_size != info["bytes"]
                or _file_sha256(file_path) != info["sha256"]
            ):
                raise DatasetIntegrityError("Dataset table checksum/size mismatch.")
            metadata = pq.ParquetFile(file_path).metadata
            if metadata is None or metadata.num_rows != info["rows"]:
                raise DatasetIntegrityError("Dataset table row count disagrees with manifest.")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        if isinstance(exc, DatasetIntegrityError):
            raise
        raise DatasetIntegrityError("Dataset manifest/table validation failed.") from exc
    return manifest


def materialize_market_dataset(
    root: Path,
    snapshot: CalendarSnapshot,
    sp500: MarketSource,
    vix: MarketSource,
    *,
    study_target_end: date,
) -> tuple[Path, dict[str, Any]]:
    """Publish or verify a complete dataset directory from frozen market inputs."""
    if snapshot.requested_end <= study_target_end:
        raise ValueError("Extended calendar must include a session after the study target end.")
    identity = dataset_identity(snapshot, sp500, vix, study_target_end=study_target_end)
    dataset_id_value = dataset_id(identity)
    root.mkdir(parents=True, exist_ok=True)
    storage_root = root.resolve(strict=True)
    destination = storage_root / dataset_id_value
    if destination.exists():
        return destination, load_market_dataset(destination)
    sp_available = source_availability(snapshot, sp500)
    vix_available = source_availability(snapshot, vix)
    label_build = build_labels(
        snapshot,
        sp500,
        sp_available,
        availability_basis=MARKET_AVAILABILITY_BASIS,
    )
    market_records = _market_records(dataset_id_value, snapshot, sp500, sp_available)
    market_records.extend(_market_records(dataset_id_value, snapshot, vix, vix_available))
    market_records.sort(key=lambda item: (str(item["series_id"]), item["observation_date"]))
    label_records = _label_records(dataset_id_value, label_build, study_target_end=study_target_end)
    exclusions = _exclusion_records(
        dataset_id_value, snapshot, label_build, study_target_end=study_target_end
    )
    staging = storage_root / f".{dataset_id_value}.{uuid.uuid4().hex}.staging"
    staging.mkdir(exist_ok=False)
    tables = {
        "market_observations": staging / "market_observations.parquet",
        "labels": staging / "labels.parquet",
        "label_exclusions": staging / "label_exclusions.parquet",
    }
    _write_table(tables["market_observations"], market_records, MARKET_SCHEMA)
    _write_table(tables["labels"], label_records, LABEL_SCHEMA)
    _write_table(tables["label_exclusions"], exclusions, EXCLUSION_SCHEMA)
    manifest = _manifest(
        identity,
        dataset_id_value,
        tables,
        rows={
            "market_observations": len(market_records),
            "labels": len(label_records),
            "label_exclusions": len(exclusions),
        },
    )
    _write_manifest(staging / "manifest.json", manifest)
    load_market_dataset(staging, require_directory_id=False)
    if destination.exists():
        return destination, load_market_dataset(destination)
    os.replace(staging, destination)
    return destination, load_market_dataset(destination)

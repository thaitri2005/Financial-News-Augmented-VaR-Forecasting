"""Bounded raw-payload commit/recovery with visible manifests and checksums."""

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from newsvar.contracts import CommittedArtifact, RawManifest, RequestValue

MAX_PAGE_BYTES = 32 * 1024 * 1024
ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
HEX_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
SECRET_KEY_PARTS = ("secret", "authorization", "api_key", "access_token", "page_token")


class IntegrityError(ValueError):
    """A manifest, expected payload, or committed file did not reconcile."""


class StoragePathError(ValueError):
    """A storage subdirectory resolved outside its configured root."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_id(value: str, field: str) -> None:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {field}; use lowercase ASCII letters, digits and underscores.")


def _validate_identity(identity: Mapping[str, RequestValue]) -> dict[str, RequestValue]:
    if not identity or len(identity) > 20:
        raise ValueError("Request identity must contain 1–20 nonsecret fields.")
    clean: dict[str, RequestValue] = {}
    for key, value in identity.items():
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("Invalid request-identity key.")
        if any(part in key for part in SECRET_KEY_PARTS):
            raise ValueError("Request identity may not contain credential/page-token fields.")
        if type(value) is int:
            if value < 0:
                raise ValueError("Negative request-identity integer.")
        elif type(value) is str:
            if not value or len(value) > 256 or "\x00" in value:
                raise ValueError("Invalid request-identity string.")
        else:
            raise ValueError("Request-identity values must be strings or nonnegative integers.")
        clean[key] = value
    return clean


def _raw_id(source_id: str, request_hash: str, payload_hash: str) -> str:
    return sha256(canonical_json([source_id, request_hash, payload_hash]))


def _sync_write(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class RawStore:
    """One-writer raw storage; consumers see only validated committed directories."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise StoragePathError("Configured storage root must be a directory.")

    def _inside(self, path: Path) -> Path:
        absolute = path.resolve()
        if not absolute.is_relative_to(self.root):
            raise StoragePathError("Storage path resolved outside configured root.")
        return absolute

    def _source_dir(self, area: str, source_id: str) -> Path:
        _validate_id(source_id, "source_id")
        directory = self.root / area / source_id
        directory.mkdir(parents=True, exist_ok=True)
        return self._inside(directory)

    def _manifest_from_dir(self, directory: Path, source_id: str, raw_id: str) -> RawManifest:
        directory = self._inside(directory)
        try:
            value: Any = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise IntegrityError("Manifest must be an object.")
            manifest = RawManifest(**value)
        except (OSError, json.JSONDecodeError, TypeError, UnicodeError) as exc:
            raise IntegrityError("Manifest is missing or invalid.") from exc
        if manifest.schema_version != "raw_v1" or manifest.state != "committed":
            raise IntegrityError("Unsupported manifest schema/state.")
        if manifest.source_id != source_id or manifest.raw_id != raw_id:
            raise IntegrityError("Manifest identity disagrees with storage path.")
        try:
            _validate_id(manifest.ingestion_run_id, "ingestion_run_id")
        except ValueError as exc:
            raise IntegrityError("Invalid ingestion run ID.") from exc
        if any(
            not isinstance(text, str) or not text or len(text) > 256
            for text in (manifest.source_terms_record, manifest.adapter_version)
        ):
            raise IntegrityError("Missing/invalid source terms or adapter version.")
        if manifest.payload_name != "payload.bin":
            raise IntegrityError("Unexpected payload filename.")
        if type(manifest.byte_count) is not int or not 0 <= manifest.byte_count <= MAX_PAGE_BYTES:
            raise IntegrityError("Invalid manifest byte count.")
        if type(manifest.row_count) is not int or manifest.row_count < 0:
            raise IntegrityError("Invalid manifest row count.")
        if type(manifest.is_interval_complete) is not bool or type(manifest.http_status) is not int:
            raise IntegrityError("Invalid manifest completeness/status fields.")
        if manifest.http_status != 200:
            raise IntegrityError("Only a successful page can be committed.")
        if not isinstance(manifest.request_identity, dict):
            raise IntegrityError("Invalid request identity.")
        try:
            identity = _validate_identity(manifest.request_identity)
        except ValueError as exc:
            raise IntegrityError("Invalid manifest request identity.") from exc
        request_hash = sha256(canonical_json(identity))
        if manifest.request_identity_sha256 != request_hash:
            raise IntegrityError("Request identity hash mismatch.")
        if not HEX_PATTERN.fullmatch(manifest.payload_sha256) or not HEX_PATTERN.fullmatch(raw_id):
            raise IntegrityError("Invalid payload/raw ID digest.")
        if _raw_id(source_id, request_hash, manifest.payload_sha256) != raw_id:
            raise IntegrityError("Raw ID does not match source/request/payload.")
        try:
            retrieved = datetime.fromisoformat(manifest.retrieved_at_utc)
        except ValueError as exc:
            raise IntegrityError("Invalid retrieval timestamp.") from exc
        if retrieved.tzinfo is None or retrieved.utcoffset() != UTC.utcoffset(None):
            raise IntegrityError("Retrieval timestamp must include UTC offset.")
        payload_path = self._inside(directory / "payload.bin")
        if not payload_path.is_file() or payload_path.stat().st_size != manifest.byte_count:
            raise IntegrityError("Payload missing or size differs from manifest.")
        with payload_path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != manifest.payload_sha256:
            raise IntegrityError("Payload checksum mismatch.")
        return manifest

    def load(self, source_id: str, raw_id: str) -> CommittedArtifact:
        """Read an artifact only after verifying its visible directory and payload."""
        _validate_id(source_id, "source_id")
        if not HEX_PATTERN.fullmatch(raw_id):
            raise ValueError("Invalid raw ID.")
        directory = self._inside(self.root / "committed" / source_id / raw_id)
        manifest = self._manifest_from_dir(directory, source_id, raw_id)
        return CommittedArtifact(directory, manifest)

    def _transition(self, boundary: str) -> None:
        """Fault-injection seam for restart fixtures; production does nothing."""

    def commit(
        self,
        *,
        source_id: str,
        ingestion_run_id: str,
        request_identity: Mapping[str, RequestValue],
        payload: bytes,
        row_count: int,
        is_interval_complete: bool,
        source_terms_record: str,
        adapter_version: str,
        retrieved_at: datetime | None = None,
        expected_sha256: str | None = None,
    ) -> CommittedArtifact:
        """Commit or recover exactly one bounded successful source response."""
        _validate_id(source_id, "source_id")
        _validate_id(ingestion_run_id, "ingestion_run_id")
        if type(payload) is not bytes or len(payload) > MAX_PAGE_BYTES:
            raise ValueError("Payload must be bytes no larger than 32 MiB.")
        if type(row_count) is not int or row_count < 0 or type(is_interval_complete) is not bool:
            raise ValueError("Invalid row count/interval-completeness type.")
        if any(
            not isinstance(text, str) or not text or len(text) > 256
            for text in (source_terms_record, adapter_version)
        ):
            raise ValueError("Source terms record and adapter version are required.")
        identity = _validate_identity(request_identity)
        request_hash, payload_hash = sha256(canonical_json(identity)), sha256(payload)
        if expected_sha256 is not None and payload_hash != expected_sha256:
            raise IntegrityError("Payload does not match caller's expected SHA-256.")
        raw_id = _raw_id(source_id, request_hash, payload_hash)
        observed = retrieved_at or datetime.now(UTC)
        if observed.tzinfo is None:
            raise ValueError("Retrieval timestamp must be timezone-aware.")
        observed_utc = observed.astimezone(UTC).isoformat()
        committed_source = self._source_dir("committed", source_id)
        destination = self._inside(committed_source / raw_id)
        if destination.exists():
            existing = self.load(source_id, raw_id)
            self._require_compatible(
                existing.manifest,
                row_count,
                is_interval_complete,
                source_terms_record,
                adapter_version,
            )
            return existing
        staged_source = self._source_dir(".staging", source_id)
        for staged in sorted(staged_source.glob(f"{raw_id}.*")):
            try:
                staged_manifest = self._manifest_from_dir(staged, source_id, raw_id)
            except (IntegrityError, StoragePathError):
                continue
            self._require_compatible(
                staged_manifest,
                row_count,
                is_interval_complete,
                source_terms_record,
                adapter_version,
            )
            if destination.exists():
                existing = self.load(source_id, raw_id)
                self._require_compatible(
                    existing.manifest,
                    row_count,
                    is_interval_complete,
                    source_terms_record,
                    adapter_version,
                )
                return existing
            os.replace(self._inside(staged), destination)
            return self.load(source_id, raw_id)
        staged = self._inside(staged_source / f"{raw_id}.{uuid.uuid4().hex}")
        staged.mkdir(exist_ok=False)
        _sync_write(staged / "payload.bin", payload)
        self._transition("payload_written")
        manifest = RawManifest(
            schema_version="raw_v1",
            raw_id=raw_id,
            source_id=source_id,
            ingestion_run_id=ingestion_run_id,
            request_identity=identity,
            request_identity_sha256=request_hash,
            payload_sha256=payload_hash,
            byte_count=len(payload),
            row_count=row_count,
            retrieved_at_utc=observed_utc,
            http_status=200,
            is_interval_complete=is_interval_complete,
            source_terms_record=source_terms_record,
            adapter_version=adapter_version,
        )
        _sync_write(staged / "manifest.json", canonical_json(asdict(manifest)) + b"\n")
        self._transition("ready_to_commit")
        if destination.exists():
            return self.load(source_id, raw_id)
        os.replace(staged, destination)
        self._transition("committed")
        return self.load(source_id, raw_id)

    @staticmethod
    def _require_compatible(
        manifest: RawManifest,
        row_count: int,
        is_interval_complete: bool,
        source_terms_record: str,
        adapter_version: str,
    ) -> None:
        if (
            manifest.row_count != row_count
            or manifest.is_interval_complete != is_interval_complete
            or manifest.source_terms_record != source_terms_record
            or manifest.adapter_version != adapter_version
        ):
            raise IntegrityError("Replay metadata disagrees with immutable artifact.")

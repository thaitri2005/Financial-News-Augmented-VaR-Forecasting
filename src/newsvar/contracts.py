"""Typed contracts for committed raw artifacts; later tables remain stage-specific."""

from dataclasses import dataclass
from pathlib import Path

type RequestValue = str | int


@dataclass(frozen=True)
class RawManifest:
    schema_version: str
    raw_id: str
    source_id: str
    ingestion_run_id: str
    request_identity: dict[str, RequestValue]
    request_identity_sha256: str
    payload_sha256: str
    byte_count: int
    row_count: int
    retrieved_at_utc: str
    http_status: int
    is_interval_complete: bool
    source_terms_record: str
    adapter_version: str
    payload_name: str = "payload.bin"
    state: str = "committed"


@dataclass(frozen=True)
class CommittedArtifact:
    directory: Path
    manifest: RawManifest

    @property
    def payload_path(self) -> Path:
        return self.directory / self.manifest.payload_name

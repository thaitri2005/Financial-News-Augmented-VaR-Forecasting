"""Resumable bulk FinBERT scoring into checksum-addressed Parquet parts.

Titles are keyed by content hash, scored once per model fingerprint, and
committed in bounded parts so an interrupted run resumes without rescoring.
"""

from __future__ import annotations

import hashlib
import math
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.hashing import canonical_json


class ScoreError(ValueError):
    """A score request, fingerprint or scorer output violates the score contract."""


@dataclass(frozen=True)
class ScoreFingerprint:
    model_weight_sha256: str
    tokenizer_sha256: str
    max_length: int
    preprocessing_version: str
    backend: str = "transformers"
    precision: str = "fp32"

    def __post_init__(self) -> None:
        if (
            len(self.model_weight_sha256) != 64
            or len(self.tokenizer_sha256) != 64
            or self.max_length < 1
            or not self.preprocessing_version
            or not self.backend
            or not self.precision
        ):
            raise ScoreError("Invalid score fingerprint.")

    @property
    def identity(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()


@dataclass(frozen=True)
class ScoreRequest:
    record_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.record_id or not self.text.strip():
            raise ScoreError("Score requests require a stable ID and nonempty text.")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScoreValue:
    positive: float
    negative: float
    neutral: float
    token_count: int
    truncated: bool

    def __post_init__(self) -> None:
        probabilities = (self.positive, self.negative, self.neutral)
        if (
            self.token_count < 1
            or not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in probabilities)
            or not math.isclose(sum(probabilities), 1.0, abs_tol=1e-5)
        ):
            raise ScoreError("Sentiment probabilities or token metadata are invalid.")


@dataclass(frozen=True)
class ScoredRecord:
    record_id: str
    content_sha256: str
    fingerprint_id: str
    score: ScoreValue
    cache_hit: bool


SCORE_SCHEMA = pa.schema(
    [
        pa.field("content_sha256", pa.string(), nullable=False),
        pa.field("positive", pa.float64(), nullable=False),
        pa.field("negative", pa.float64(), nullable=False),
        pa.field("neutral", pa.float64(), nullable=False),
        pa.field("token_count", pa.int32(), nullable=False),
        pa.field("truncated", pa.bool_(), nullable=False),
    ]
)
PART_ROWS = 5_000

ScoreBatch = Callable[[Sequence[ScoreRequest]], Sequence[ScoreValue]]


def score_directory(root: Path, fingerprint: ScoreFingerprint) -> Path:
    return root / fingerprint.identity


def load_scores(root: Path, fingerprint: ScoreFingerprint) -> pa.Table:
    """Read every committed score part for one fingerprint."""
    directory = score_directory(root, fingerprint)
    parts = sorted(directory.glob("part-*.parquet")) if directory.is_dir() else []
    if not parts:
        return SCORE_SCHEMA.empty_table()
    return pa.concat_tables([pq.read_table(part, schema=SCORE_SCHEMA) for part in parts])


def scored_hashes(root: Path, fingerprint: ScoreFingerprint) -> set[str]:
    directory = score_directory(root, fingerprint)
    hashes: set[str] = set()
    if directory.is_dir():
        for part in sorted(directory.glob("part-*.parquet")):
            hashes.update(pq.read_table(part, columns=["content_sha256"]).column(0).to_pylist())
    return hashes


def _commit_part(directory: Path, rows: list[dict[str, object]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = f"part-{uuid.uuid4().hex}.parquet"
    stage = directory / f".{name}.staging"
    pq.write_table(pa.Table.from_pylist(rows, schema=SCORE_SCHEMA), stage, compression="zstd")
    with stage.open("r+b") as stream:
        os.fsync(stream.fileno())
    destination = directory / name
    os.replace(stage, destination)
    return destination


def score_titles(
    titles: Sequence[tuple[str, str]],
    *,
    root: Path,
    fingerprint: ScoreFingerprint,
    score_batch: ScoreBatch,
    batch_size: int = 32,
    part_rows: int = PART_ROWS,
    max_new: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """Score unscored ``(content_sha256, text)`` pairs; return counts for this call."""
    if batch_size < 1 or part_rows < 1:
        raise ScoreError("Batch and part sizes must be positive.")
    done = scored_hashes(root, fingerprint)
    pending: dict[str, str] = {}
    for digest, text in titles:
        request = ScoreRequest(digest, text)
        if request.content_sha256 != digest:
            raise ScoreError("Title content hash does not match its text.")
        if digest not in done:
            pending.setdefault(digest, text)
    ordered = sorted(pending.items(), key=lambda item: (len(item[1]), item[0]))
    if max_new is not None:
        ordered = ordered[:max_new]
    directory = score_directory(root, fingerprint)
    buffer: list[dict[str, object]] = []
    scored = 0
    for offset in range(0, len(ordered), batch_size):
        batch = [
            ScoreRequest(digest, text) for digest, text in ordered[offset : offset + batch_size]
        ]
        values = tuple(score_batch(batch))
        if len(values) != len(batch):
            raise ScoreError("Scorer did not return one value for every batch request.")
        for request, value in zip(batch, values, strict=True):
            buffer.append(
                {
                    "content_sha256": request.record_id,
                    "positive": value.positive,
                    "negative": value.negative,
                    "neutral": value.neutral,
                    "token_count": value.token_count,
                    "truncated": value.truncated,
                }
            )
        scored += len(batch)
        if len(buffer) >= part_rows:
            _commit_part(directory, buffer)
            buffer = []
            if progress is not None:
                progress(scored, len(ordered))
            if should_stop is not None and should_stop():
                break
    if buffer:
        _commit_part(directory, buffer)
    return {
        "requested": len(titles),
        "already_scored": len(titles) - len(pending),
        "scored": scored,
    }

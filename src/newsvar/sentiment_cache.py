"""Content-addressed, atomic cache orchestration for frozen sentiment scores."""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from newsvar.provenance import canonical_json


class SentimentCacheError(ValueError):
    """A cache entry or scorer output violates the immutable score contract."""


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
            raise SentimentCacheError("Invalid score fingerprint.")

    @property
    def identity(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()


@dataclass(frozen=True)
class ScoreRequest:
    record_id: str
    text: str

    def __post_init__(self) -> None:
        if not self.record_id or not self.text.strip():
            raise SentimentCacheError("Score requests require a stable ID and nonempty text.")

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
            raise SentimentCacheError("Sentiment probabilities or token metadata are invalid.")


@dataclass(frozen=True)
class ScoredRecord:
    record_id: str
    content_sha256: str
    fingerprint_id: str
    score: ScoreValue
    cache_hit: bool


def cache_key(content_sha256: str, fingerprint: ScoreFingerprint) -> str:
    if len(content_sha256) != 64:
        raise SentimentCacheError("Content hash must be SHA-256 hexadecimal.")
    return hashlib.sha256(f"{content_sha256}:{fingerprint.identity}".encode()).hexdigest()


class FileScoreCache:
    """One atomically committed JSON entry per content/fingerprint pair."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, content_sha256: str, fingerprint: ScoreFingerprint) -> ScoreValue | None:
        path = self.root / f"{cache_key(content_sha256, fingerprint)}.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("content_sha256") != content_sha256
                or payload.get("fingerprint_id") != fingerprint.identity
                or not isinstance(payload.get("score"), dict)
            ):
                raise SentimentCacheError("Cache entry identity mismatch.")
            return ScoreValue(**payload["score"])
        except (OSError, TypeError, json.JSONDecodeError) as error:
            raise SentimentCacheError(f"Unreadable cache entry: {path}") from error

    def put(self, content_sha256: str, fingerprint: ScoreFingerprint, score: ScoreValue) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{cache_key(content_sha256, fingerprint)}.json"
        if destination.exists():
            if self.get(content_sha256, fingerprint) != score:
                raise SentimentCacheError("Immutable cache key conflicts with a different score.")
            return
        payload = {
            "content_sha256": content_sha256,
            "fingerprint_id": fingerprint.identity,
            "score": asdict(score),
        }
        stage = self.root / f".{destination.name}.{uuid.uuid4().hex}.staging"
        with stage.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(payload).decode("utf-8") + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, destination)


ScoreBatch = Callable[[Sequence[ScoreRequest]], Sequence[ScoreValue]]


def score_requests(
    requests: Sequence[ScoreRequest],
    *,
    fingerprint: ScoreFingerprint,
    cache: FileScoreCache,
    score_batch: ScoreBatch,
    batch_size: int = 8,
) -> tuple[ScoredRecord, ...]:
    """Score cache misses in deterministic batches and restore input alignment."""
    if batch_size < 1:
        raise SentimentCacheError("Score batch size must be positive.")
    resolved: dict[str, ScoreValue] = {}
    misses: dict[str, ScoreRequest] = {}
    for request in requests:
        content_hash = request.content_sha256
        if content_hash in resolved or content_hash in misses:
            continue
        cached = cache.get(content_hash, fingerprint)
        if cached is None:
            misses[content_hash] = request
        else:
            resolved[content_hash] = cached
    ordered = sorted(
        misses.values(), key=lambda request: (len(request.text), request.content_sha256)
    )
    for offset in range(0, len(ordered), batch_size):
        batch = ordered[offset : offset + batch_size]
        values = tuple(score_batch(batch))
        if len(values) != len(batch):
            raise SentimentCacheError("Scorer did not return one value for every batch request.")
        for request, value in zip(batch, values, strict=True):
            cache.put(request.content_sha256, fingerprint, value)
            resolved[request.content_sha256] = value
    return tuple(
        ScoredRecord(
            request.record_id,
            request.content_sha256,
            fingerprint.identity,
            resolved[request.content_sha256],
            request.content_sha256 not in misses,
        )
        for request in requests
    )

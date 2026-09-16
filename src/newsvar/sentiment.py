"""Pinned local FinBERT loading and batch scoring, isolated from source ingestion."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from newsvar.sentiment_cache import ScoreFingerprint, ScoreRequest, ScoreValue, SentimentCacheError

MODEL_REVISION = "5fcfed04a2ca89adf4170ec0a4715103ed7745db"
REQUIRED_MODEL_FILES = (
    "config.json",
    "pytorch_model.bin",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "vocab.txt",
)
EXPECTED_LABELS = {0: "positive", 1: "negative", 2: "neutral"}


def validate_label_map(id2label: object) -> None:
    if not isinstance(id2label, dict):
        raise SentimentCacheError("FinBERT config has no label mapping.")
    normalized = {int(key): str(value).lower() for key, value in id2label.items()}
    if normalized != EXPECTED_LABELS:
        raise SentimentCacheError(f"Unexpected FinBERT label mapping: {normalized!r}")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_fingerprint(snapshot: Path, *, max_length: int = 128) -> ScoreFingerprint:
    missing = [name for name in REQUIRED_MODEL_FILES if not (snapshot / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Pinned FinBERT snapshot is missing: {', '.join(missing)}")
    tokenizer = hashlib.sha256(
        "".join(
            _digest(snapshot / name) for name in REQUIRED_MODEL_FILES if name != "pytorch_model.bin"
        ).encode()
    ).hexdigest()
    return ScoreFingerprint(
        _digest(snapshot / "pytorch_model.bin"), tokenizer, max_length, "headline_text_v1"
    )


class FinbertEncoder:
    def __init__(self, tokenizer: Any, model: Any, fingerprint: ScoreFingerprint) -> None:
        validate_label_map(model.config.id2label)
        self.tokenizer, self.model, self.fingerprint = tokenizer, model, fingerprint

    @classmethod
    def load_local(cls, snapshot: Path, *, max_length: int = 128) -> FinbertEncoder:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        resolved = snapshot.resolve(strict=True)
        if resolved.name != MODEL_REVISION:
            raise SentimentCacheError(
                "Snapshot directory does not match the pinned FinBERT revision."
            )
        tokenizer = AutoTokenizer.from_pretrained(
            resolved, local_files_only=True, trust_remote_code=False
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            resolved, local_files_only=True, trust_remote_code=False
        )
        model.eval()
        return cls(tokenizer, model, model_fingerprint(resolved, max_length=max_length))

    def score_batch(self, requests: Sequence[ScoreRequest]) -> tuple[ScoreValue, ...]:
        if not requests:
            return ()
        import torch

        texts = [request.text for request in requests]
        counts = [
            len(self.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])
            for text in texts
        ]
        encoded = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.fingerprint.max_length,
            return_tensors="pt",
        )
        with torch.inference_mode():
            probabilities = torch.softmax(self.model(**encoded).logits, dim=1).tolist()
        return tuple(
            ScoreValue(
                float(row[0]),
                float(row[1]),
                float(row[2]),
                count,
                count > self.fingerprint.max_length,
            )
            for count, row in zip(counts, probabilities, strict=True)
        )

"""Canonical JSON and SHA-256 helpers used for content-addressed artifacts."""

import hashlib
import json


class IntegrityError(ValueError):
    """A manifest, expected payload, or committed file did not reconcile."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

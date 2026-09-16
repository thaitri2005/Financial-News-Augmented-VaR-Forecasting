import hashlib

import pytest

from newsvar.sentiment_cache import (
    FileScoreCache,
    ScoreFingerprint,
    ScoreRequest,
    ScoreValue,
    SentimentCacheError,
    score_requests,
)


def _fingerprint() -> ScoreFingerprint:
    digest = hashlib.sha256(b"fixture").hexdigest()
    return ScoreFingerprint(digest, digest, 128, "headline_text_v1")


def _value(request: ScoreRequest) -> ScoreValue:
    return ScoreValue(0.2, 0.3, 0.5, len(request.text), False)


def test_cache_deduplicates_content_and_restores_record_alignment(tmp_path) -> None:
    calls: list[list[str]] = []

    def scorer(batch):
        calls.append([request.record_id for request in batch])
        return [_value(request) for request in batch]

    requests = [
        ScoreRequest("b", "second title"),
        ScoreRequest("a", "first"),
        ScoreRequest("c", "first"),
    ]
    result = score_requests(
        requests, fingerprint=_fingerprint(), cache=FileScoreCache(tmp_path), score_batch=scorer
    )
    assert [item.record_id for item in result] == ["b", "a", "c"]
    assert len(calls[0]) == 2
    assert result[1].content_sha256 == result[2].content_sha256


def test_cache_recovers_completed_batches_after_later_failure(tmp_path) -> None:
    def interrupted(batch):
        if batch[0].record_id == "third":
            raise RuntimeError("fixture interruption")
        return [_value(request) for request in batch]

    requests = [
        ScoreRequest("first", "a"),
        ScoreRequest("second", "bb"),
        ScoreRequest("third", "ccc"),
    ]
    cache = FileScoreCache(tmp_path)
    with pytest.raises(RuntimeError):
        score_requests(
            requests, fingerprint=_fingerprint(), cache=cache, score_batch=interrupted, batch_size=1
        )
    calls: list[str] = []

    def resumed(batch):
        calls.extend(request.record_id for request in batch)
        return [_value(request) for request in batch]

    result = score_requests(
        requests, fingerprint=_fingerprint(), cache=cache, score_batch=resumed, batch_size=1
    )
    assert calls == ["third"]
    assert [item.record_id for item in result] == ["first", "second", "third"]


def test_cache_rejects_conflicting_immutable_value(tmp_path) -> None:
    cache = FileScoreCache(tmp_path)
    request = ScoreRequest("id", "title")
    cache.put(request.content_sha256, _fingerprint(), _value(request))
    with pytest.raises(SentimentCacheError):
        cache.put(request.content_sha256, _fingerprint(), ScoreValue(0.1, 0.3, 0.6, 5, False))

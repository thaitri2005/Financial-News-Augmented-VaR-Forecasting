import pytest

from newsvar.sentiment import EXPECTED_LABELS, validate_label_map
from newsvar.sentiment_cache import SentimentCacheError


def test_frozen_finbert_label_mapping_is_checked_by_class_id() -> None:
    validate_label_map(EXPECTED_LABELS)
    validate_label_map({"0": "positive", "1": "negative", "2": "neutral"})
    with pytest.raises(SentimentCacheError):
        validate_label_map({0: "negative", 1: "positive", 2: "neutral"})

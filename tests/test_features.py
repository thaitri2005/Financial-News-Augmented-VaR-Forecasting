import pytest

from newsvar.features.definitions import (
    FeatureInputError,
    HeadlineScore,
    NewsWindow,
    market_features,
    news_features,
)


def _window(*, complete: bool = True, retained: int = 1, negative: float = 0.2) -> NewsWindow:
    scores = () if retained == 0 else (HeadlineScore(0.3, negative, 0.7 - negative),)
    return NewsWindow(
        24.0,
        complete,
        retained,
        scores,
    )


def test_market_features_use_only_known_returns_and_decimal_vix() -> None:
    result = market_features([0.01] * 62 + [-0.02], [18.0, 20.0])
    assert result["return_last"] == -0.02
    assert result["downside_square_last"] == pytest.approx(0.0004)
    assert result["vix_last"] == 0.2
    assert result["vix_change"] == 0.02


def test_news_features_keep_failed_feed_distinct_from_empty_complete_window() -> None:
    preceding = [_window() for _ in range(63)]
    failed = news_features(_window(complete=False), preceding)
    empty = news_features(_window(retained=0), preceding)
    assert not failed.feed_complete
    assert failed.values["has_news"] is None
    assert empty.feed_complete
    assert empty.values["has_news"] == 0.0
    assert empty.scoring_coverage == 1.0
    assert empty.values["sentiment_mean"] is None


def test_news_features_use_fixed_lookbacks_and_label_id_tie_rule() -> None:
    preceding = [_window(negative=0.3) for _ in range(63)]
    current = NewsWindow(24.0, True, 1, (HeadlineScore(0.4, 0.4, 0.2),))
    result = news_features(current, preceding)
    assert result.values["news_rate_z63"] == 0.0
    assert result.values["negative_headline_ratio"] == 0.0
    assert result.values["sentiment_shock21"] == pytest.approx(0.0)
    with pytest.raises(FeatureInputError):
        news_features(current, preceding[:62])


def test_sampled_window_scales_intensity_and_measures_coverage_on_designated() -> None:
    from newsvar.features.definitions import (
        FeatureInputError,
        HeadlineScore,
        NewsWindow,
        news_features,
    )

    score = HeadlineScore(0.1, 0.6, 0.3)
    history = [NewsWindow(24.0, True, 10, (score,) * 10) for _ in range(63)]
    full = NewsWindow(24.0, True, 100, (score,) * 100)
    sampled = NewsWindow(24.0, True, 100, (score,) * 25, designated_count=25, sampling_rate=0.25)
    a, b = news_features(full, history), news_features(sampled, history)
    assert b.scoring_coverage == 1.0 and b.retained_count == 100 and b.scored_count == 25
    assert a.values["news_log_rate"] == b.values["news_log_rate"]
    assert a.values["negative_log_intensity"] == pytest.approx(b.values["negative_log_intensity"])
    assert a.values["sentiment_mean"] == pytest.approx(b.values["sentiment_mean"])
    with pytest.raises(FeatureInputError):
        NewsWindow(24.0, True, 100, (score,) * 30, designated_count=25, sampling_rate=0.25)
    with pytest.raises(FeatureInputError):
        NewsWindow(24.0, True, 100, (score,) * 25, sampling_rate=0.25)

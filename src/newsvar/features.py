"""Causal M/C/S feature calculations with explicit news-window quality semantics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


class FeatureInputError(ValueError):
    """Feature inputs violate the fixed causal feature contract."""


@dataclass(frozen=True)
class HeadlineScore:
    positive: float
    negative: float
    neutral: float

    def __post_init__(self) -> None:
        values = (self.positive, self.negative, self.neutral)
        valid = all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values)
        if not valid or not math.isclose(sum(values), 1.0, abs_tol=1e-5):
            raise FeatureInputError("Headline probabilities must be finite and sum to one.")

    @property
    def signed(self) -> float:
        return self.positive - self.negative

    @property
    def is_negative_label(self) -> bool:
        return max(range(3), key=(self.positive, self.negative, self.neutral).__getitem__) == 1


@dataclass(frozen=True)
class NewsWindow:
    duration_hours: float
    feed_complete: bool
    retained_count: int
    scored: tuple[HeadlineScore, ...]

    def __post_init__(self) -> None:
        invalid_duration = not math.isfinite(self.duration_hours) or self.duration_hours <= 0.0
        if invalid_duration or self.retained_count < 0:
            raise FeatureInputError("News window duration/count is invalid.")
        if len(self.scored) > self.retained_count:
            raise FeatureInputError("Scored headlines cannot exceed retained headlines.")

    @property
    def scoring_coverage(self) -> float:
        return 1.0 if self.retained_count == 0 else len(self.scored) / self.retained_count

    @property
    def rate(self) -> float:
        return 24.0 * self.retained_count / self.duration_hours

    @property
    def sentiment_mean(self) -> float | None:
        return float(np.mean([item.signed for item in self.scored])) if self.scored else None


@dataclass(frozen=True)
class FeatureRow:
    """Declared numeric M/C/S features plus non-predictive quality diagnostics."""

    values: dict[str, float | None]
    feed_complete: bool
    retained_count: int
    scored_count: int
    scoring_coverage: float


def market_features(
    returns: Sequence[float], vix: Sequence[float | None]
) -> dict[str, float | None]:
    """Build the nine market features from values known through the latest session."""
    values = np.asarray(returns, dtype=np.float64)
    if values.ndim != 1 or len(values) < 63 or not np.isfinite(values).all():
        raise FeatureInputError("Market features require at least 63 finite known returns.")
    if len(vix) < 2:
        raise FeatureInputError("Market features require two VIX observations, which may be null.")
    variance = float(np.mean(np.square(values[:63])))
    for observed in values[63:]:
        variance = 0.94 * variance + 0.06 * float(observed * observed)
    last_vix, previous_vix = vix[-1], vix[-2]
    return {
        "return_last": float(values[-1]),
        "abs_return_last": abs(float(values[-1])),
        "downside_square_last": min(float(values[-1]), 0.0) ** 2,
        "vol_5": float(np.std(values[-5:], ddof=1)),
        "vol_21": float(np.std(values[-21:], ddof=1)),
        "vol_63": float(np.std(values[-63:], ddof=1)),
        "ewma_sigma": math.sqrt(variance),
        "vix_last": None if last_vix is None else float(last_vix) / 100.0,
        "vix_change": None
        if last_vix is None or previous_vix is None
        else (float(last_vix) - float(previous_vix)) / 100.0,
    }


def news_features(current: NewsWindow, preceding: Sequence[NewsWindow]) -> FeatureRow:
    """Build C/S features using only the fixed preceding 63/21 origin windows."""
    if len(preceding) < 63:
        raise FeatureInputError("News controls require 63 preceding origin windows.")
    values: dict[str, float | None] = {
        "news_log_rate": None,
        "news_rate_z63": None,
        "log_window_hours": None,
        "has_news": None,
        "sentiment_mean": None,
        "negative_probability_mean": None,
        "sentiment_dispersion": None,
        "negative_headline_ratio": None,
        "sentiment_shock21": None,
        "negative_log_intensity": None,
    }
    if not current.feed_complete:
        return FeatureRow(
            values, False, current.retained_count, len(current.scored), current.scoring_coverage
        )
    values["news_log_rate"] = math.log1p(current.rate)
    values["log_window_hours"] = math.log(current.duration_hours)
    values["has_news"] = float(current.retained_count > 0)
    complete_rates = [item.rate for item in preceding[-63:] if item.feed_complete]
    if len(complete_rates) >= 20:
        mean, deviation = float(np.mean(complete_rates)), float(np.std(complete_rates, ddof=1))
        values["news_rate_z63"] = (
            0.0
            if deviation == 0.0 and current.rate == mean
            else (None if deviation == 0.0 else (current.rate - mean) / deviation)
        )
    if current.scored:
        signed = [item.signed for item in current.scored]
        values["sentiment_mean"] = float(np.mean(signed))
        negatives = [item.negative for item in current.scored]
        values["negative_probability_mean"] = float(np.mean(negatives))
        values["sentiment_dispersion"] = float(np.std(signed, ddof=0))
        values["negative_headline_ratio"] = float(
            np.mean([item.is_negative_label for item in current.scored])
        )
        values["negative_log_intensity"] = math.log1p(
            24.0 / current.duration_hours * sum(item.negative for item in current.scored)
        )
        prior_means = [
            item.sentiment_mean
            for item in preceding[-21:]
            if item.feed_complete and item.retained_count > 0 and item.sentiment_mean is not None
        ]
        if len(prior_means) >= 10:
            current_mean = values["sentiment_mean"]
            assert current_mean is not None
            values["sentiment_shock21"] = current_mean - float(np.mean(prior_means))
    return FeatureRow(
        values, True, current.retained_count, len(current.scored), current.scoring_coverage
    )

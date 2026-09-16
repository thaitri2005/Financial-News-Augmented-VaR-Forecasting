"""Pure, causal market-risk reference calculations in decimal return units."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

GAUSSIAN = NormalDist()


class BaselineInputError(ValueError):
    """Raised when a baseline cannot form a defined one-session forecast."""


@dataclass(frozen=True)
class TailForecast:
    """One lower-tail one-session return forecast with explicit method metadata."""

    model_id: str
    alpha: float
    q_return: float
    es_return: float
    observations: int
    variance_next: float | None


def _validated_returns(values: Sequence[float], *, minimum: int) -> np.ndarray:
    returns = np.asarray(values, dtype=np.float64)
    if returns.ndim != 1 or len(returns) < minimum:
        raise BaselineInputError(f"Expected at least {minimum} one-dimensional returns.")
    if not np.isfinite(returns).all():
        raise BaselineInputError("Returns must all be finite.")
    return returns


def _validate_alpha(alpha: float) -> None:
    if not math.isfinite(alpha) or not 0.0 < alpha < 0.5:
        raise BaselineInputError("Tail alpha must be finite and strictly between zero and 0.5.")


def _fractional_expected_shortfall(sorted_returns: np.ndarray, alpha: float) -> float:
    """Average the exact lowest alpha probability mass of equally weighted returns."""
    mass = alpha * len(sorted_returns)
    whole = math.floor(mass)
    fraction = mass - whole
    total = float(sorted_returns[:whole].sum())
    if fraction:
        total += fraction * float(sorted_returns[whole])
    return total / mass


def historical_simulation(
    history: Sequence[float],
    *,
    alpha: float = 0.05,
    window: int = 250,
) -> TailForecast:
    """Forecast from only the final eligible rolling window of known returns."""
    _validate_alpha(alpha)
    if window < 1:
        raise BaselineInputError("Historical-simulation window must be positive.")
    returns = _validated_returns(history, minimum=window)[-window:]
    ordered = np.sort(returns)
    return TailForecast(
        model_id=f"historical_simulation_linear_w{window}",
        alpha=alpha,
        q_return=float(np.quantile(returns, alpha, method="linear")),
        es_return=_fractional_expected_shortfall(ordered, alpha),
        observations=window,
        variance_next=None,
    )


def gaussian_ewma(
    history: Sequence[float],
    *,
    alpha: float = 0.05,
    decay: float = 0.94,
    initialization_window: int = 63,
) -> TailForecast:
    """Use known returns through t-1 to forecast one next-session Gaussian tail."""
    _validate_alpha(alpha)
    if not math.isfinite(decay) or not 0.0 < decay < 1.0:
        raise BaselineInputError("EWMA decay must be finite and strictly between zero and one.")
    if initialization_window < 1:
        raise BaselineInputError("EWMA initialization window must be positive.")
    returns = _validated_returns(history, minimum=initialization_window)
    variance = float(np.mean(np.square(returns[:initialization_window])))
    for value in returns[initialization_window:]:
        variance = decay * variance + (1.0 - decay) * float(value) ** 2
    if not math.isfinite(variance) or variance <= 0.0:
        raise BaselineInputError("EWMA next variance must be positive and finite.")
    sigma = math.sqrt(variance)
    z_score = GAUSSIAN.inv_cdf(alpha)
    normal_density = math.exp(-0.5 * z_score**2) / math.sqrt(2.0 * math.pi)
    return TailForecast(
        model_id=f"gaussian_ewma_d{decay:.2f}_i{initialization_window}",
        alpha=alpha,
        q_return=sigma * z_score,
        es_return=-sigma * normal_density / alpha,
        observations=len(returns),
        variance_next=variance,
    )

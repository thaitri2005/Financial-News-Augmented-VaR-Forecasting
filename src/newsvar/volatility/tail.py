"""Volatility-scaled VaR and expected shortfall by filtered historical simulation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StandardizedTail:
    """Lower-tail quantile and tail mean of returns divided by forecast volatility."""

    alpha: float
    quantile: float
    tail_mean: float
    observations: int

    def forecast(self, volatility: float) -> tuple[float, float]:
        """Return (VaR quantile, expected shortfall) in return units for one volatility."""
        if not np.isfinite(volatility) or volatility <= 0:
            raise ValueError("Forecast volatility must be positive and finite.")
        return volatility * self.quantile, volatility * self.tail_mean


def standardized_tail(
    returns: Sequence[float] | np.ndarray,
    volatilities: Sequence[float] | np.ndarray,
    *,
    alpha: float,
) -> StandardizedTail:
    """Empirical tail of standardized training returns; ES averages exactly alpha mass."""
    values = np.asarray(returns, dtype=np.float64) / np.asarray(volatilities, dtype=np.float64)
    if not 0.0 < alpha < 0.5 or len(values) < 100 or not np.isfinite(values).all():
        raise ValueError("Standardized tail needs 100 finite observations and a tail level.")
    ordered = np.sort(values)
    mass = alpha * len(ordered)
    whole = int(np.floor(mass))
    tail_sum = ordered[:whole].sum() + (mass - whole) * ordered[min(whole, len(ordered) - 1)]
    return StandardizedTail(
        alpha,
        float(np.quantile(values, alpha, method="linear")),
        float(tail_sum / mass),
        len(ordered),
    )

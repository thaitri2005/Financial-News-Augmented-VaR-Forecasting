"""Loss functions and predictive-ability tests for volatility and VaR/ES forecasts."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


class InferenceError(ValueError):
    """Inputs to a loss or test are outside its domain."""


def qlike(proxy: float, forecast: float) -> float:
    """QLIKE loss for a variance forecast; zero when the forecast equals the proxy."""
    if not (proxy > 0 and forecast > 0 and math.isfinite(proxy) and math.isfinite(forecast)):
        raise InferenceError("QLIKE needs positive finite variances.")
    ratio = proxy / forecast
    return ratio - math.log(ratio) - 1.0


def fz0(observed: float, quantile: float, shortfall: float, alpha: float) -> float:
    """Fissler-Ziegel FZ0 joint loss for a lower-tail VaR quantile and expected shortfall."""
    if not 0.0 < alpha < 1.0 or not all(math.isfinite(v) for v in (observed, quantile, shortfall)):
        raise InferenceError("FZ0 inputs must be finite with alpha in (0, 1).")
    if shortfall >= 0 or shortfall > quantile + 1e-12:
        raise InferenceError("FZ0 needs a negative expected shortfall no greater than the VaR.")
    hit = float(observed <= quantile)
    return (
        -hit * (quantile - observed) / (alpha * shortfall)
        + quantile / shortfall
        + math.log(-shortfall)
        - 1.0
    )


def _long_run_variance(values: np.ndarray, lags: int) -> float:
    centered = values - values.mean()
    size = len(centered)
    variance = float(centered @ centered / size)
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        variance += 2.0 * weight * float(centered[lag:] @ centered[:-lag] / size)
    return variance


def default_lags(size: int) -> int:
    return int(math.floor(4.0 * (size / 100.0) ** (2.0 / 9.0)))


def diebold_mariano(
    differences: Sequence[float] | np.ndarray, *, lags: int | None = None
) -> dict[str, float]:
    """Test of zero mean loss difference with a Newey-West long-run variance.

    ``differences`` are baseline loss minus challenger loss; a positive mean
    favors the challenger. Both the two-sided p-value and the one-sided p-value
    for "challenger better" are returned. For nested models estimated on an
    expanding window the normal approximation is conservative.
    """
    from scipy.stats import norm

    values = np.asarray(differences, dtype=np.float64)
    if len(values) < 30 or not np.isfinite(values).all():
        raise InferenceError("Diebold-Mariano needs at least 30 finite differences.")
    used = default_lags(len(values)) if lags is None else lags
    variance = _long_run_variance(values, used)
    if variance <= 0:
        raise InferenceError("Loss differences have no variation.")
    statistic = float(values.mean() / math.sqrt(variance / len(values)))
    return {
        "mean_difference": float(values.mean()),
        "statistic": statistic,
        "p_value_two_sided": float(2.0 * norm.sf(abs(statistic))),
        "p_value_challenger_better": float(norm.sf(statistic)),
        "lags": float(used),
        "observations": float(len(values)),
    }


def giacomini_white(
    differences: Sequence[float] | np.ndarray, instruments: np.ndarray, *, horizon: int = 1
) -> dict[str, float | list[float]]:
    """Conditional predictive ability test for loss differences.

    ``instruments`` holds variables known when the forecast was made; a constant
    is added. The statistic is n * mean(h*d)' * inv(S) * mean(h*d), chi-squared
    with (instruments + 1) degrees of freedom under equal conditional predictive
    ability. ``horizon`` is the number of steps between the information time and
    the outcome: for horizon h the moment series may be MA(h-1), so S includes
    h-1 autocovariances (truncated kernel, Bartlett if that is not positive
    definite).
    """
    from scipy.stats import chi2

    values = np.asarray(differences, dtype=np.float64)
    extra = np.asarray(instruments, dtype=np.float64)
    if extra.ndim == 1:
        extra = extra[:, None]
    if len(values) != len(extra) or len(values) < 50 or horizon < 1:
        raise InferenceError("Giacomini-White needs matching inputs with at least 50 rows.")
    design = np.column_stack([np.ones(len(values)), extra])
    if not np.isfinite(design).all() or not np.isfinite(values).all():
        raise InferenceError("Giacomini-White inputs must be finite.")
    moments = design * values[:, None]
    mean = moments.mean(axis=0)
    centered = moments - mean
    size = len(values)

    def long_run(bartlett: bool) -> np.ndarray:
        covariance = centered.T @ centered / size
        for lag in range(1, horizon):
            weight = 1.0 - lag / horizon if bartlett else 1.0
            cross = centered[lag:].T @ centered[:-lag] / size
            covariance = covariance + weight * (cross + cross.T)
        return np.asarray(covariance)

    covariance = long_run(bartlett=False)
    if np.linalg.eigvalsh(covariance).min() <= 0:
        covariance = long_run(bartlett=True)
    statistic = float(size * mean @ np.linalg.solve(covariance, mean))
    slopes, *_ = np.linalg.lstsq(design, values, rcond=None)
    return {
        "statistic": statistic,
        "degrees_of_freedom": float(design.shape[1]),
        "p_value": float(chi2.sf(statistic, design.shape[1])),
        "horizon": float(horizon),
        "projection_coefficients": [float(value) for value in slopes],
    }


def dynamic_quantile(
    hits: Sequence[bool], quantiles: Sequence[float], alpha: float
) -> dict[str, object]:
    """Engle-Manganelli dynamic quantile test with one lagged hit and the forecast itself."""
    from scipy.stats import chi2

    indicator = np.asarray(hits, dtype=np.float64) - alpha
    forecast = np.asarray(quantiles, dtype=np.float64)
    if len(indicator) < 100 or len(indicator) != len(forecast):
        raise InferenceError("Dynamic quantile test needs at least 100 aligned forecasts.")
    design = np.column_stack([np.ones(len(indicator) - 1), indicator[:-1], forecast[1:]])
    target = indicator[1:]
    gram = design.T @ design
    if np.linalg.matrix_rank(gram) < gram.shape[0]:
        return {"status": "not_estimable"}
    beta = np.linalg.solve(gram, design.T @ target)
    statistic = float(beta @ gram @ beta / (alpha * (1.0 - alpha)))
    return {
        "status": "estimated",
        "statistic": statistic,
        "p_value": float(chi2.sf(statistic, design.shape[1])),
    }

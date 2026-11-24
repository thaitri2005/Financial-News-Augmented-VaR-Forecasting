"""Log-linear HAR-X variance model: OLS on log variance with optional extra regressors."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


class HarError(ValueError):
    """Model inputs are not finite or there are too few rows."""


@dataclass(frozen=True)
class LogVarianceFit:
    """OLS coefficients on log variance with a lognormal mean correction."""

    names: tuple[str, ...]
    coefficients: np.ndarray
    residual_variance: float
    rows: int

    def log_forecast(self, features: Sequence[float]) -> float:
        row = np.asarray(features, dtype=np.float64)
        if row.shape != (len(self.names),) or not np.isfinite(row).all():
            raise HarError("Forecast features do not match the fitted design.")
        return float(self.coefficients[0] + row @ self.coefficients[1:])

    def variance_forecast(self, features: Sequence[float]) -> float:
        """Conditional mean of the variance under lognormal errors."""
        return float(np.exp(self.log_forecast(features) + 0.5 * self.residual_variance))


def fit_log_variance(
    names: Sequence[str], features: np.ndarray, variance: np.ndarray
) -> LogVarianceFit:
    """Fit log(variance) = a + b'x by least squares."""
    design = np.asarray(features, dtype=np.float64)
    target = np.asarray(variance, dtype=np.float64)
    if design.ndim != 2 or design.shape != (len(target), len(names)):
        raise HarError("Feature matrix shape does not match names and targets.")
    if len(target) <= len(names) + 5:
        raise HarError("Too few rows for the requested regressors.")
    if not np.isfinite(design).all() or not np.isfinite(target).all() or (target <= 0).any():
        raise HarError("Features must be finite and variances strictly positive.")
    full = np.column_stack([np.ones(len(target)), design])
    log_target = np.log(target)
    coefficients, *_ = np.linalg.lstsq(full, log_target, rcond=None)
    residuals = log_target - full @ coefficients
    degrees = len(target) - full.shape[1]
    return LogVarianceFit(
        tuple(names), coefficients, float(residuals @ residuals / degrees), len(target)
    )


def har_terms(history: Sequence[float]) -> tuple[float, float, float]:
    """Log of the last value and of the 5- and 22-observation means of a variance history."""
    values = np.asarray(history, dtype=np.float64)
    if len(values) < 22 or not np.isfinite(values[-22:]).all() or (values[-22:] <= 0).any():
        raise HarError("HAR terms need 22 positive finite variances.")
    return (
        float(np.log(values[-1])),
        float(np.log(values[-5:].mean())),
        float(np.log(values[-22:].mean())),
    )

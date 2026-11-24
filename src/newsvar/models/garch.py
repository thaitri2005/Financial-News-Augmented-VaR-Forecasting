"""Bounded two-step GARCH-t and filtered-historical tail simulations."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from newsvar.models.baselines import TailForecast, _fractional_expected_shortfall


class GarchFitError(ValueError):
    """The fitted volatility model cannot safely produce a tail forecast."""


MAX_PERSISTENCE = 0.999


def _strict_garch_model(values: np.ndarray) -> Any:
    """Build a GARCH(1,1) whose fitted persistence stays inside stationarity.

    The upstream ARCH constraint allows its optimizer to settle numerically on a
    unit-root boundary.  A finite-horizon forecast can still be produced there,
    but it is not the stationary GARCH model this project specifies.
    """
    from arch.univariate import GARCH, StudentsT, ZeroMean

    class StrictGARCH(GARCH):
        def constraints(self) -> tuple[np.ndarray, np.ndarray]:
            coefficients, bounds = super().constraints()
            bounds[-1] = -MAX_PERSISTENCE
            return coefficients, bounds

    return ZeroMean(
        values * 100.0,
        volatility=StrictGARCH(p=1, q=1),
        distribution=StudentsT(),
        rescale=False,
    )


@dataclass(frozen=True)
class GarchFit:
    """Validated fitted parameters in percentage-point fitting units."""

    result: Any
    omega: float
    alpha: float
    beta: float
    degrees_of_freedom: float


def origin_seed(experiment_seed: int, model_id: str, origin_session: date) -> int:
    """Derive a stable 32-bit simulation seed from explicit model identity."""
    payload = f"{experiment_seed}:{model_id}:{origin_session.isoformat()}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def fit_garch_t(
    history: Sequence[float], *, starting_values: Sequence[float] | None = None
) -> GarchFit:
    """Fit zero-mean GARCH-t on eligible decimal returns, scaled for stability."""
    values = np.asarray(history, dtype=np.float64)
    if values.ndim != 1 or len(values) < 100 or not np.isfinite(values).all():
        raise GarchFitError("GARCH-t requires at least 100 finite one-dimensional returns.")
    result = _strict_garch_model(values).fit(disp="off", starting_values=starting_values)
    params = result.params
    omega, alpha, beta, nu = (
        float(params[name]) for name in ("omega", "alpha[1]", "beta[1]", "nu")
    )
    if (
        result.convergence_flag != 0
        or not all(math.isfinite(value) for value in (omega, alpha, beta, nu))
        or omega < 0.0
        or alpha < 0.0
        or beta < 0.0
        or alpha + beta > MAX_PERSISTENCE + 1e-10
        or nu <= 2.0
    ):
        raise GarchFitError("GARCH-t fit failed convergence or parameter validation.")
    return GarchFit(result, omega, alpha, beta, nu)


def fixed_garch_state(history: Sequence[float], fitted: GarchFit) -> GarchFit:
    """Update daily volatility state using fixed monthly parameters and known returns."""
    values = np.asarray(history, dtype=np.float64)
    if values.ndim != 1 or len(values) < 100 or not np.isfinite(values).all():
        raise GarchFitError("Fixed GARCH state requires at least 100 finite returns.")
    result = _strict_garch_model(values).fix(fitted.result.params)
    return GarchFit(result, fitted.omega, fitted.alpha, fitted.beta, fitted.degrees_of_freedom)


def _second_step(paths: np.ndarray) -> np.ndarray:
    if paths.ndim != 3 or paths.shape[0] != 1 or paths.shape[2] != 2:
        raise GarchFitError("Expected one origin, paths, and exactly two simulated horizons.")
    result = np.asarray(paths[0, :, 1], dtype=np.float64) / 100.0
    if not np.isfinite(result).all():
        raise GarchFitError("Simulated second-step returns must be finite.")
    return result


def simulated_tail_forecast(
    fitted: GarchFit,
    *,
    origin_session: date,
    model_id: str,
    alpha: float = 0.05,
    simulations: int = 50_000,
    experiment_seed: int = 1729,
    filtered_historical: bool = False,
) -> TailForecast:
    """Build a second-step return tail forecast from parametric or FHS paths."""
    if not 0.0 < alpha < 0.5 or simulations < 1:
        raise GarchFitError("Invalid tail probability or simulation count.")
    seed = origin_seed(experiment_seed, model_id, origin_session)
    if filtered_historical:
        forecast = fitted.result.forecast(
            horizon=2,
            method="bootstrap",
            simulations=simulations,
            random_state=np.random.RandomState(seed),
        )
    else:
        generator = np.random.default_rng(seed)
        scale = math.sqrt(fitted.degrees_of_freedom / (fitted.degrees_of_freedom - 2.0))

        def rng(size: tuple[int, ...]) -> np.ndarray:
            return generator.standard_t(fitted.degrees_of_freedom, size=size) / scale

        forecast = fitted.result.forecast(
            horizon=2, method="simulation", simulations=simulations, rng=rng
        )
    paths = _second_step(forecast.simulations.values)
    ordered = np.sort(paths)
    return TailForecast(
        model_id=model_id,
        alpha=alpha,
        q_return=float(np.quantile(paths, alpha, method="linear")),
        es_return=_fractional_expected_shortfall(ordered, alpha),
        observations=simulations,
        variance_next=None,
    )

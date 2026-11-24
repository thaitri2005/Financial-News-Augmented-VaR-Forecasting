"""Causal market-only walk-forward attempts for the B0-B3 baselines."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from newsvar.data.calendar import ForecastOrigin
from newsvar.models.baselines import (
    BaselineInputError,
    TailForecast,
    gaussian_ewma,
    historical_simulation,
)
from newsvar.models.garch import (
    GarchFitError,
    fit_garch_t,
    fixed_garch_state,
    simulated_tail_forecast,
)


@dataclass(frozen=True)
class AvailableLabel:
    """A known future outcome becomes training data only at its recorded availability."""

    origin_session: date
    target_end_session: date
    return_simple: float
    available_at_utc: datetime


@dataclass(frozen=True)
class ForecastAttempt:
    """One model/origin record, including visible insufficient-history failures."""

    origin_session: date
    cutoff_utc: datetime
    refit_month: bool
    model_id: str
    status: str
    eligible_labels: int
    q_return: float | None
    es_return: float | None


def eligible_labels(
    labels: Iterable[AvailableLabel], *, origin: ForecastOrigin
) -> tuple[AvailableLabel, ...]:
    """Select only earlier origins whose outcomes were usable by this cutoff."""
    selected = tuple(
        sorted(
            (
                label
                for label in labels
                if label.origin_session < origin.session
                and label.available_at_utc <= origin.cutoff_utc
            ),
            key=lambda label: label.origin_session,
        )
    )
    if len({label.origin_session for label in selected}) != len(selected):
        raise ValueError("Walk-forward labels must have unique origin sessions.")
    return selected


def _attempt(
    model: str, history: Sequence[float], *, alpha: float, refit_month: bool
) -> TailForecast:
    if model == "historical":
        return historical_simulation(history, alpha=alpha, window=250)
    if model == "ewma":
        return gaussian_ewma(history, alpha=alpha, initialization_window=63)
    raise ValueError(f"Unsupported walk-forward model: {model}")


def build_attempts(
    origins: Sequence[ForecastOrigin],
    labels: Iterable[AvailableLabel],
    *,
    alpha: float = 0.05,
    models: tuple[str, ...] = ("historical", "ewma"),
) -> tuple[ForecastAttempt, ...]:
    """Create chronological attempts without reading outcomes of their own targets."""
    if not origins:
        raise ValueError("Walk-forward origins cannot be empty.")
    labels_tuple = tuple(labels)
    if any(label.available_at_utc.tzinfo is None for label in labels_tuple):
        raise ValueError("Label availability must be timezone-aware.")
    attempts: list[ForecastAttempt] = []
    previous_month: tuple[int, int] | None = None
    for origin in origins:
        month = (origin.session.year, origin.session.month)
        refit_month = month != previous_month
        previous_month = month
        history = eligible_labels(labels_tuple, origin=origin)
        returns = [label.return_simple for label in history]
        for model in models:
            try:
                forecast = _attempt(model, returns, alpha=alpha, refit_month=refit_month)
            except BaselineInputError:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        model,
                        "insufficient_or_invalid_history",
                        len(history),
                        None,
                        None,
                    )
                )
            else:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        forecast.model_id,
                        "ready",
                        len(history),
                        forecast.q_return,
                        forecast.es_return,
                    )
                )
    return tuple(attempts)


def build_garch_attempts(
    origins: Sequence[ForecastOrigin],
    labels: Iterable[AvailableLabel],
    *,
    simulations: int = 50_000,
    alpha: float = 0.05,
) -> tuple[ForecastAttempt, ...]:
    """Monthly GARCH parameter refits with daily state updates from eligible labels."""
    if not origins:
        raise ValueError("Walk-forward origins cannot be empty.")
    labels_tuple = tuple(labels)
    fitted = None
    used_fallback_at_previous_refit = False
    previous_month: tuple[int, int] | None = None
    attempts: list[ForecastAttempt] = []
    for origin in origins:
        month = (origin.session.year, origin.session.month)
        refit_month = month != previous_month
        previous_month = month
        history = eligible_labels(labels_tuple, origin=origin)
        returns = [label.return_simple for label in history]
        fit_status = "ready"
        if refit_month or fitted is None:
            try:
                fitted = fit_garch_t(returns)
                used_fallback_at_previous_refit = False
            except GarchFitError:
                try:
                    if fitted is None:
                        raise
                    fitted = fit_garch_t(returns, starting_values=fitted.result.params)
                    used_fallback_at_previous_refit = False
                    fit_status = "ready_after_retry"
                except GarchFitError:
                    if fitted is None or used_fallback_at_previous_refit:
                        for model_id in ("garch_t", "filtered_historical"):
                            attempts.append(
                                ForecastAttempt(
                                    origin.session,
                                    origin.cutoff_utc,
                                    refit_month,
                                    model_id,
                                    "garch_refit_failed",
                                    len(history),
                                    None,
                                    None,
                                )
                            )
                        continue
                    used_fallback_at_previous_refit = True
                    fit_status = "fallback_previous_refit"
        try:
            state = fixed_garch_state(returns, fitted)
        except GarchFitError:
            for model_id in ("garch_t", "filtered_historical"):
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        model_id,
                        "garch_state_update_failed",
                        len(history),
                        None,
                        None,
                    )
                )
            continue
        for model_id, filtered in (("garch_t", False), ("filtered_historical", True)):
            try:
                forecast = simulated_tail_forecast(
                    state,
                    origin_session=origin.session,
                    model_id=model_id,
                    alpha=alpha,
                    simulations=simulations,
                    filtered_historical=filtered,
                )
            except GarchFitError:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        model_id,
                        "garch_simulation_failed",
                        len(history),
                        None,
                        None,
                    )
                )
            else:
                attempts.append(
                    ForecastAttempt(
                        origin.session,
                        origin.cutoff_utc,
                        refit_month,
                        forecast.model_id,
                        fit_status,
                        len(history),
                        forecast.q_return,
                        forecast.es_return,
                    )
                )
    return tuple(attempts)

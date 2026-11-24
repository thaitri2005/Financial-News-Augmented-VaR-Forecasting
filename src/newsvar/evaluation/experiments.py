"""Causal walk-forward experiments for the Q0/Q1/Q2 and tree quantile models.

A forecast for an origin uses a model refitted on the first origin of that
calendar month from rows whose labels were available by that refit cutoff. All
feature groups share one eligibility mask, so paired comparisons use identical
target dates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from newsvar.data.calendar import CalendarSnapshot
from newsvar.evaluation.metrics import (
    QuantileObservation,
    block_bootstrap_mean,
    breach,
    calibration_summary,
    christoffersen_test,
    kupiec_test,
    max_breach_run,
    pinball_loss,
    transition_counts,
)
from newsvar.evaluation.walkforward import (
    AvailableLabel,
    ForecastAttempt,
    build_attempts,
    build_garch_attempts,
)
from newsvar.features.table import ALL_FEATURES, FEATURE_GROUPS
from newsvar.models.quantile import QuantileModelError, QuantileTrainingRow, fit_linear_quantile

MIN_TRAINING_ROWS = 250
TIE_TOLERANCE = 0.005
SEED = 1729
READY = "ready"
LINEAR_PENALTIES = (0.001, 0.01, 0.1)
TREE_GRID = tuple((depth, trees) for depth in (1, 2) for trees in (100, 200))
BASELINE_IDS = (
    "historical_simulation_linear_w250",
    "gaussian_ewma_d0.94_i63",
    "garch_t",
    "filtered_historical",
)


class ExperimentError(ValueError):
    """Experiment inputs violate the frozen walk-forward protocol."""


@dataclass(frozen=True)
class StudyRow:
    origin_session: date
    target_end_session: date
    cutoff_utc: datetime
    features: Mapping[str, float | None]
    eligible: bool
    label_return: float | None
    label_available_at: datetime | None


Predictor = Callable[[Mapping[str, float | None]], float]
Fitter = Callable[[Sequence[QuantileTrainingRow]], Predictor]


def load_labels(market_dataset: Path) -> tuple[AvailableLabel, ...]:
    table = pq.read_table(
        market_dataset / "labels.parquet",
        columns=[
            "origin_session",
            "target_end_session",
            "return_simple",
            "label_available_at_utc",
        ],
    )
    return tuple(
        AvailableLabel(
            row["origin_session"],
            row["target_end_session"],
            float(row["return_simple"]),
            row["label_available_at_utc"],
        )
        for row in table.to_pylist()
    )


def load_study_rows(feature_table: Path, labels: Sequence[AvailableLabel]) -> list[StudyRow]:
    """Join each feature row to its own label by forecast-origin session."""
    by_origin = {label.origin_session: label for label in labels}
    rows: list[StudyRow] = []
    for record in pq.read_table(feature_table / "features.parquet").to_pylist():
        label = by_origin.get(record["origin_session"])
        if label is not None and label.target_end_session != record["target_end_session"]:
            raise ExperimentError("Feature row and label disagree on the target-end session.")
        rows.append(
            StudyRow(
                record["origin_session"],
                record["target_end_session"],
                record["cutoff_utc"],
                {name: record[name] for name in ALL_FEATURES},
                bool(record["eligible"]),
                None if label is None else label.return_simple,
                None if label is None else label.available_at_utc,
            )
        )
    rows.sort(key=lambda row: row.origin_session)
    return rows


def linear_fitter(feature_names: Sequence[str], *, alpha: float, penalty: float) -> Fitter:
    def fit(rows: Sequence[QuantileTrainingRow]) -> Predictor:
        return fit_linear_quantile(
            rows, feature_names=feature_names, alpha=alpha, penalty=penalty
        ).predict

    return fit


def tree_fitter(feature_names: Sequence[str], *, alpha: float, depth: int, trees: int) -> Fitter:
    names = tuple(feature_names)

    def matrix(rows: Sequence[Mapping[str, float | None]]) -> np.ndarray:
        values: list[list[float]] = []
        for row in rows:
            values.append([float("nan") if row[n] is None else float(row[n] or 0.0) for n in names])
        return np.asarray(values, dtype=np.float64)

    def fit(rows: Sequence[QuantileTrainingRow]) -> Predictor:
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.impute import SimpleImputer

        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        features = imputer.fit_transform(matrix([row.features for row in rows]))
        model = GradientBoostingRegressor(
            loss="quantile",
            alpha=alpha,
            learning_rate=0.05,
            max_depth=depth,
            n_estimators=trees,
            min_samples_leaf=50,
            subsample=1.0,
            random_state=SEED,
        )
        model.fit(features, np.asarray([row.target_return for row in rows]) * 100.0)

        def predict(row: Mapping[str, float | None]) -> float:
            return float(model.predict(imputer.transform(matrix([row])))[0]) / 100.0

        return predict

    return fit


def walk_forward(
    rows: Sequence[StudyRow],
    *,
    model_id: str,
    feature_names: Sequence[str],
    fitter: Fitter,
    target_start: date,
    target_end: date,
    min_training_rows: int = MIN_TRAINING_ROWS,
) -> tuple[ForecastAttempt, ...]:
    """Monthly-refit expanding-window forecasts for target-end sessions in the range."""
    names = tuple(feature_names)
    attempts: list[ForecastAttempt] = []
    predictor: Predictor | None = None
    fit_status, training_size = "not_fitted", 0
    previous_month: tuple[int, int] | None = None
    for row in rows:
        if not target_start <= row.target_end_session <= target_end:
            continue
        month = (row.origin_session.year, row.origin_session.month)
        refit = month != previous_month
        previous_month = month
        if refit:
            training = [
                QuantileTrainingRow(
                    {name: item.features[name] for name in names}, item.label_return
                )
                for item in rows
                if item.eligible
                and item.origin_session < row.origin_session
                and item.label_return is not None
                and item.label_available_at is not None
                and item.label_available_at <= row.cutoff_utc
            ]
            training_size = len(training)
            if training_size < min_training_rows:
                predictor, fit_status = None, "insufficient_training_rows"
            else:
                try:
                    predictor, fit_status = fitter(training), READY
                except (QuantileModelError, ValueError):
                    predictor, fit_status = None, "fit_failed"
        status, quantile = fit_status, None
        if not row.eligible:
            status = "ineligible_inputs"
        elif predictor is not None:
            quantile = predictor({name: row.features[name] for name in names})
            if not np.isfinite(quantile):
                status, quantile = "nonfinite_forecast", None
        attempts.append(
            ForecastAttempt(
                row.origin_session,
                row.cutoff_utc,
                refit,
                model_id,
                status,
                training_size,
                quantile,
                None,
            )
        )
    return tuple(attempts)


def baseline_attempts(
    calendar: CalendarSnapshot,
    labels: Sequence[AvailableLabel],
    *,
    alpha: float,
    target_start: date,
    target_end: date,
    simulations: int = 50_000,
) -> tuple[ForecastAttempt, ...]:
    """B0–B3 market-only attempts for the same target-end range."""
    origins = tuple(
        origin for origin in calendar.origins if target_start <= origin.next_session <= target_end
    )
    simple = build_attempts(origins, labels, alpha=alpha)
    garch = build_garch_attempts(origins, labels, simulations=simulations, alpha=alpha)
    return simple + garch


def observations(
    attempts: Sequence[ForecastAttempt], labels: Sequence[AvailableLabel], *, model_id: str
) -> dict[date, QuantileObservation]:
    """Ready forecasts of one model joined to realized labels, keyed by target-end session."""
    by_origin = {label.origin_session: label for label in labels}
    result: dict[date, QuantileObservation] = {}
    for attempt in attempts:
        if attempt.model_id != model_id or attempt.q_return is None:
            continue
        label = by_origin.get(attempt.origin_session)
        if label is None:
            continue
        if label.target_end_session in result:
            raise ExperimentError("A model has two forecasts for one target-end session.")
        result[label.target_end_session] = QuantileObservation(
            label.target_end_session, label.return_simple, attempt.q_return
        )
    return result


def mean_pinball(
    rows: Mapping[date, QuantileObservation], sessions: Sequence[date], alpha: float
) -> float:
    if not sessions:
        raise ExperimentError("Mean pinball loss needs at least one session.")
    return float(
        np.mean(
            [
                pinball_loss(rows[session].return_simple, rows[session].q_return, alpha)
                for session in sessions
            ]
        )
    )


def select_candidate(losses: Mapping[Any, float], *, simplicity: Callable[[Any], Any]) -> Any:
    """Lowest development loss; within 0.5% relative, prefer the simpler candidate."""
    best = min(losses.values())
    near = [key for key, loss in losses.items() if loss <= best * (1.0 + TIE_TOLERANCE)]
    return max(near, key=simplicity)


def model_summary(
    rows: Mapping[date, QuantileObservation],
    *,
    alpha: float,
    calendar: CalendarSnapshot,
    grid: Sequence[date],
) -> dict[str, object]:
    """Calibration and exceedance diagnostics for one model on its own valid forecasts."""
    ordered = [rows[session] for session in sorted(rows)]
    if not ordered:
        return {"forecasts": 0, "missing_forecasts": len(grid)}
    calibration = calibration_summary(ordered, alpha=alpha)
    transitions = transition_counts(ordered, calendar=calendar)
    return {
        **calibration,
        "missing_forecasts": len(grid) - len(ordered),
        "mean_pinball": mean_pinball(rows, sorted(rows), alpha),
        "kupiec": kupiec_test(int(calibration["breaches"]), len(ordered), alpha),  # type: ignore[call-overload]
        "christoffersen": christoffersen_test(transitions, alpha),
        "max_breach_run": max_breach_run(ordered, calendar=calendar),
    }


def paired_summary(
    baseline: Mapping[date, QuantileObservation],
    challenger: Mapping[date, QuantileObservation],
    *,
    alpha: float,
    grid: Sequence[date],
    block_lengths: Sequence[int] = (20, 10, 5),
) -> dict[str, object]:
    """Common-date pinball comparison; positive improvement favors the challenger."""
    common = [session for session in grid if session in baseline and session in challenger]
    if not common:
        return {"common_forecasts": 0}
    differences: list[float | None] = []
    yearly: dict[int, list[float]] = {}
    for session in grid:
        if session in baseline and session in challenger:
            base, candidate = baseline[session], challenger[session]
            if base.return_simple != candidate.return_simple:
                raise ExperimentError("Paired forecasts disagree on a realized outcome.")
            value = pinball_loss(base.return_simple, base.q_return, alpha) - pinball_loss(
                candidate.return_simple, candidate.q_return, alpha
            )
            differences.append(value)
            yearly.setdefault(session.year, []).append(value)
        else:
            differences.append(None)
    base_loss = mean_pinball(baseline, common, alpha)
    challenger_loss = mean_pinball(challenger, common, alpha)
    result: dict[str, object] = {
        "common_forecasts": len(common),
        "baseline_mean_pinball": base_loss,
        "challenger_mean_pinball": challenger_loss,
        "mean_improvement": base_loss - challenger_loss,
        "relative_gain": (base_loss - challenger_loss) / base_loss if base_loss else None,
        "yearly_mean_improvement": {
            str(year): float(np.mean(values)) for year, values in sorted(yearly.items())
        },
        "yearly_pairs": {str(year): len(values) for year, values in sorted(yearly.items())},
    }
    if len(grid) >= max(block_lengths):
        result["bootstrap"] = {
            f"block_{length}": block_bootstrap_mean(differences, block_length=length)
            for length in block_lengths
        }
    return result


def crossing_rate(
    lower_tail: Mapping[date, QuantileObservation], upper_tail: Mapping[date, QuantileObservation]
) -> dict[str, object]:
    """Share of common sessions where the 1% quantile lies above the 5% quantile."""
    common = sorted(set(lower_tail).intersection(upper_tail))
    crossings = sum(lower_tail[s].q_return > upper_tail[s].q_return for s in common)
    return {
        "common_forecasts": len(common),
        "crossings": crossings,
        "rate": crossings / len(common) if common else None,
    }


def breach_series(rows: Mapping[date, QuantileObservation]) -> dict[str, bool]:
    return {
        session.isoformat(): breach(row.return_simple, row.q_return)
        for session, row in sorted(rows.items())
    }


def target_grid(calendar: CalendarSnapshot, start: date, end: date) -> list[date]:
    return [
        origin.next_session for origin in calendar.origins if start <= origin.next_session <= end
    ]


def feature_names(group: str, *, without_vix: bool = False) -> tuple[str, ...]:
    names = FEATURE_GROUPS[group]
    if without_vix:
        names = tuple(name for name in names if not name.startswith("vix_"))
    return names

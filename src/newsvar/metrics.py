"""Protected risk-forecast metrics with explicit paired-date semantics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from newsvar.calendar import CalendarSnapshot


class MetricInputError(ValueError):
    """Metric inputs are incomplete, misaligned, or outside their declared domain."""


@dataclass(frozen=True)
class QuantileObservation:
    """A realized target paired with one ready lower-tail quantile forecast."""

    target_end_session: date
    return_simple: float
    q_return: float


@dataclass(frozen=True)
class PairedComparison:
    """Common-date pinball comparison; positive difference favors the challenger."""

    sessions: tuple[date, ...]
    baseline_mean_loss: float
    challenger_mean_loss: float
    mean_improvement: float
    relative_gain: float | None


def pinball_loss(observed: float, quantile: float, alpha: float) -> float:
    """Lower-tail quantile loss in the original decimal return units."""
    if not 0.0 < alpha < 1.0 or not all(math.isfinite(v) for v in (observed, quantile)):
        raise MetricInputError("Pinball inputs must be finite and alpha must lie in (0, 1).")
    return (alpha - float(observed < quantile)) * (observed - quantile)


def breach(observed: float, quantile: float) -> bool:
    """A strict VaR exception: equality is not a breach."""
    if not all(math.isfinite(v) for v in (observed, quantile)):
        raise MetricInputError("Breach inputs must be finite.")
    return observed < quantile


def paired_pinball(
    baseline: Sequence[QuantileObservation],
    challenger: Sequence[QuantileObservation],
    *,
    alpha: float,
) -> PairedComparison:
    """Compare only identical target-end sessions with identical realized outcomes."""

    def index(rows: Sequence[QuantileObservation]) -> Mapping[date, QuantileObservation]:
        result = {row.target_end_session: row for row in rows}
        if len(result) != len(rows):
            raise MetricInputError(
                "Each model may have at most one forecast per target-end session."
            )
        return result

    base, candidate = index(baseline), index(challenger)
    sessions = tuple(sorted(set(base).intersection(candidate)))
    if not sessions:
        raise MetricInputError("Paired comparison requires at least one common target-end session.")
    if any(base[session].return_simple != candidate[session].return_simple for session in sessions):
        raise MetricInputError("Paired forecasts disagree on a realized outcome.")
    baseline_losses = [
        pinball_loss(base[s].return_simple, base[s].q_return, alpha) for s in sessions
    ]
    challenger_losses = [
        pinball_loss(candidate[s].return_simple, candidate[s].q_return, alpha) for s in sessions
    ]
    base_mean, challenger_mean = float(np.mean(baseline_losses)), float(np.mean(challenger_losses))
    improvement = base_mean - challenger_mean
    return PairedComparison(
        sessions,
        base_mean,
        challenger_mean,
        improvement,
        improvement / base_mean if base_mean != 0.0 else None,
    )


def calibration_summary(rows: Sequence[QuantileObservation], *, alpha: float) -> dict[str, object]:
    """Exact binomial calibration summary; no pseudo-counts for sparse tails."""
    if not rows:
        raise MetricInputError("Calibration requires at least one forecast.")
    hits = sum(breach(row.return_simple, row.q_return) for row in rows)
    from scipy.stats import binomtest

    interval = binomtest(hits, len(rows), alpha).proportion_ci(
        confidence_level=0.95, method="exact"
    )
    return {
        "forecasts": len(rows),
        "breaches": hits,
        "breach_rate": hits / len(rows),
        "expected_breaches": alpha * len(rows),
        "exact_interval": (interval.low, interval.high),
    }


def transition_counts(
    rows: Sequence[QuantileObservation], *, calendar: CalendarSnapshot
) -> dict[str, int]:
    """Count breach transitions only across adjacent saved XNYS target sessions."""
    by_session = {row.target_end_session: breach(row.return_simple, row.q_return) for row in rows}
    if len(by_session) != len(rows):
        raise MetricInputError("Transition input has duplicate target-end sessions.")
    origins = {origin.session: origin for origin in calendar.origins}
    counts = {"n00": 0, "n01": 0, "n10": 0, "n11": 0, "eligible_pairs": 0}
    for session in sorted(by_session):
        origin = origins.get(session)
        if origin is None or origin.previous_session not in by_session:
            continue
        previous, current = by_session[origin.previous_session], by_session[session]
        counts[f"n{int(previous)}{int(current)}"] += 1
        counts["eligible_pairs"] += 1
    return counts

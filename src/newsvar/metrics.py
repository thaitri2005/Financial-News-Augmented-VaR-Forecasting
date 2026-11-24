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


def _xlogy(count: float, probability: float) -> float:
    """``count * log(probability)`` with the 0*log(0) = 0 convention."""
    return 0.0 if count == 0 else count * math.log(probability)


def kupiec_test(breaches: int, forecasts: int, alpha: float) -> dict[str, object]:
    """Unconditional-coverage likelihood ratio; no pseudo-counts for empty cells."""
    if forecasts < 1 or not 0 <= breaches <= forecasts or not 0.0 < alpha < 1.0:
        raise MetricInputError("Kupiec inputs are outside their domain.")
    from scipy.stats import chi2

    observed = breaches / forecasts
    null = _xlogy(breaches, alpha) + _xlogy(forecasts - breaches, 1.0 - alpha)
    alternative = _xlogy(breaches, observed) + _xlogy(forecasts - breaches, 1.0 - observed)
    statistic = max(0.0, -2.0 * (null - alternative))
    return {"statistic": statistic, "p_value": float(chi2.sf(statistic, 1))}


def christoffersen_test(counts: Mapping[str, int], alpha: float) -> dict[str, object]:
    """Independence and conditional-coverage diagnostics from adjacent-session transitions."""
    n00, n01, n10, n11 = (counts[key] for key in ("n00", "n01", "n10", "n11"))
    total = n00 + n01 + n10 + n11
    if total == 0 or n00 + n01 == 0 or n10 + n11 == 0:
        return {"status": "not_estimable", "transitions": dict(counts)}
    from scipy.stats import chi2

    pi01, pi11 = n01 / (n00 + n01), n11 / (n10 + n11)
    pooled = (n01 + n11) / total
    restricted = _xlogy(n00 + n10, 1.0 - pooled) + _xlogy(n01 + n11, pooled)
    unrestricted = (
        _xlogy(n00, 1.0 - pi01) + _xlogy(n01, pi01) + _xlogy(n10, 1.0 - pi11) + _xlogy(n11, pi11)
    )
    independence = max(0.0, -2.0 * (restricted - unrestricted))
    coverage = _xlogy(n00 + n10, 1.0 - alpha) + _xlogy(n01 + n11, alpha)
    conditional = max(0.0, -2.0 * (coverage - unrestricted))
    return {
        "status": "estimated",
        "transitions": dict(counts),
        "independence_statistic": independence,
        "independence_p_value": float(chi2.sf(independence, 1)),
        "conditional_coverage_statistic": conditional,
        "conditional_coverage_p_value": float(chi2.sf(conditional, 2)),
    }


def max_breach_run(rows: Sequence[QuantileObservation], *, calendar: CalendarSnapshot) -> int:
    """Longest run of breaches over adjacent saved sessions; a gap ends the run."""
    hits = {row.target_end_session: breach(row.return_simple, row.q_return) for row in rows}
    previous = {origin.session: origin.previous_session for origin in calendar.origins}
    longest = current = 0
    last: date | None = None
    for session in sorted(hits):
        if not hits[session]:
            current, last = 0, session
            continue
        current = current + 1 if last is not None and previous.get(session) == last else 1
        longest, last = max(longest, current), session
    return longest


def block_bootstrap_mean(
    differences: Sequence[float | None],
    *,
    block_length: int = 20,
    replications: int = 2_000,
    seed: int = 1729,
) -> dict[str, object]:
    """Moving-block bootstrap of a paired score difference on the full origin grid.

    ``differences`` follows the full session grid; ``None`` marks an origin without
    a valid pair. Blocks are drawn on the grid so gaps stay where they occurred,
    and each resample averages only its valid entries.
    """
    values = np.asarray([np.nan if item is None else float(item) for item in differences])
    size = len(values)
    if size < block_length or block_length < 1 or replications < 1:
        raise MetricInputError("Block bootstrap needs a grid at least one block long.")
    if not np.isfinite(values).any():
        raise MetricInputError("Block bootstrap needs at least one valid paired score.")
    generator = np.random.default_rng(seed)
    blocks = math.ceil(size / block_length)
    offsets = np.arange(block_length)
    means = np.empty(replications)
    for replication in range(replications):
        starts = generator.integers(0, size - block_length + 1, size=blocks)
        sample = values[(starts[:, None] + offsets[None, :]).ravel()[:size]]
        valid = sample[np.isfinite(sample)]
        means[replication] = np.nan if valid.size == 0 else float(valid.mean())
    usable = means[np.isfinite(means)]
    low, high = np.quantile(usable, [0.025, 0.975])
    return {
        "mean": float(np.nanmean(values)),
        "valid_pairs": int(np.isfinite(values).sum()),
        "grid_size": size,
        "block_length": block_length,
        "replications": replications,
        "seed": seed,
        "interval_95": (float(low), float(high)),
        "share_positive": float((usable > 0).mean()),
    }

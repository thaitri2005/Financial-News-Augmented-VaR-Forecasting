from datetime import date

import pytest

from newsvar.calendar import build_xnys_snapshot
from newsvar.metrics import (
    MetricInputError,
    QuantileObservation,
    breach,
    calibration_summary,
    paired_pinball,
    pinball_loss,
    transition_counts,
)


def test_pinball_and_breach_use_lower_tail_strict_inequality() -> None:
    assert pinball_loss(-0.03, -0.02, 0.05) == pytest.approx(0.0095)
    assert breach(-0.03, -0.02)
    assert not breach(-0.02, -0.02)


def test_paired_pinball_intersects_dates_and_requires_same_outcome() -> None:
    base = [
        QuantileObservation(date(2021, 1, 4), -0.03, -0.02),
        QuantileObservation(date(2021, 1, 5), 0.01, -0.02),
    ]
    challenger = [
        QuantileObservation(date(2021, 1, 4), -0.03, -0.04),
        QuantileObservation(date(2021, 1, 6), 0.01, -0.02),
    ]
    result = paired_pinball(base, challenger, alpha=0.05)
    assert result.sessions == (date(2021, 1, 4),)
    assert result.mean_improvement > 0
    with pytest.raises(MetricInputError):
        paired_pinball(base, [QuantileObservation(date(2021, 1, 4), 0.0, -0.04)], alpha=0.05)


def test_calibration_keeps_zero_breach_interval_defined() -> None:
    rows = [QuantileObservation(date(2021, 1, day), 0.01, -0.02) for day in range(4, 9)]
    summary = calibration_summary(rows, alpha=0.05)
    assert summary["breaches"] == 0
    assert summary["exact_interval"][0] == 0.0


def test_transition_counts_do_not_bridge_missing_xnys_session() -> None:
    calendar = build_xnys_snapshot(date(2021, 1, 4), date(2021, 1, 8))
    rows = [
        QuantileObservation(date(2021, 1, 4), -0.03, -0.02),
        QuantileObservation(date(2021, 1, 6), 0.01, -0.02),
    ]
    counts = transition_counts(rows, calendar=calendar)
    assert counts["eligible_pairs"] == 0

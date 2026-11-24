import math
from datetime import date

import pytest

from newsvar.data.calendar import build_xnys_snapshot
from newsvar.evaluation.metrics import (
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


def test_coverage_tests_handle_empty_cells_without_pseudocounts() -> None:
    from newsvar.evaluation.metrics import christoffersen_test, kupiec_test

    exact = kupiec_test(25, 500, 0.05)
    assert exact["statistic"] == pytest.approx(0.0, abs=1e-9) and exact["p_value"] == 1.0
    assert kupiec_test(0, 250, 0.05)["statistic"] == pytest.approx(-2 * 250 * math.log(0.95))
    assert kupiec_test(60, 500, 0.05)["p_value"] < 0.001
    sparse = christoffersen_test({"n00": 10, "n01": 0, "n10": 0, "n11": 0}, 0.05)
    assert sparse["status"] == "not_estimable"
    clustered = christoffersen_test({"n00": 440, "n01": 10, "n10": 10, "n11": 15}, 0.05)
    assert clustered["status"] == "estimated" and clustered["independence_p_value"] < 0.001


def test_block_bootstrap_keeps_gaps_and_is_seeded() -> None:
    from newsvar.evaluation.metrics import MetricInputError, block_bootstrap_mean

    grid = [0.001] * 100 + [None] * 20 + [0.001] * 100
    result = block_bootstrap_mean(grid, block_length=20, replications=200)
    assert result["valid_pairs"] == 200 and result["grid_size"] == 220
    assert result["interval_95"] == pytest.approx((0.001, 0.001))
    assert result == block_bootstrap_mean(grid, block_length=20, replications=200)
    mixed = block_bootstrap_mean([1.0, -1.0] * 100, block_length=5, replications=500)
    low, high = mixed["interval_95"]
    assert low < 0.0 < high
    with pytest.raises(MetricInputError):
        block_bootstrap_mean([None] * 40)

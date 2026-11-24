"""Synthetic walk-forward chronology fixtures for the quantile experiment runner."""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

import pytest

from newsvar import experiments
from newsvar.metrics import QuantileObservation
from newsvar.quantile_models import QuantileTrainingRow

NAMES = ("x",)


def _rows(count: int = 420, *, poison_after: int | None = None) -> list[experiments.StudyRow]:
    rows = []
    day = date(2020, 1, 1)
    for index in range(count):
        cutoff = datetime(day.year, day.month, day.day, 20, 30, tzinfo=UTC)
        value = float(index % 7)
        label = 1000.0 if poison_after is not None and index >= poison_after else value / 100.0
        rows.append(
            experiments.StudyRow(
                origin_session=day,
                target_end_session=day + timedelta(days=1),
                cutoff_utc=cutoff,
                features={"x": value},
                eligible=index % 50 != 49,
                label_return=label,
                # Labels become usable two origins later, as in the pre-close design.
                label_available_at=cutoff + timedelta(days=2),
            )
        )
        day += timedelta(days=1)
    return rows


def _recording_fitter(log: list[Sequence[QuantileTrainingRow]]) -> experiments.Fitter:
    def fit(training: Sequence[QuantileTrainingRow]) -> experiments.Predictor:
        log.append(training)
        mean = sum(row.target_return for row in training) / len(training)

        def predict(features: Mapping[str, float | None]) -> float:
            return mean

        return predict

    return fit


def test_refits_monthly_from_labels_available_at_the_refit_cutoff() -> None:
    rows, log = _rows(), []
    attempts = experiments.walk_forward(
        rows,
        model_id="m",
        feature_names=NAMES,
        fitter=_recording_fitter(log),
        target_start=date(2020, 11, 1),
        target_end=date(2021, 1, 31),
    )
    refits = [attempt for attempt in attempts if attempt.refit_month]
    assert [a.origin_session for a in refits] == [
        date(2020, 10, 31),
        date(2020, 11, 1),
        date(2020, 12, 1),
        date(2021, 1, 1),
    ]
    by_origin = {row.origin_session: row for row in rows}
    for attempt, training in zip(refits, log, strict=True):
        usable = [
            row
            for row in rows
            if row.eligible
            and row.origin_session < attempt.origin_session
            and row.label_available_at <= by_origin[attempt.origin_session].cutoff_utc
        ]
        assert len(training) == len(usable) == attempt.eligible_labels
        # The two newest origins are not yet labelled at a pre-close refit.
        assert max(row.origin_session for row in usable) <= attempt.origin_session - timedelta(
            days=2
        )
    skipped = [a for a in attempts if a.status == "ineligible_inputs"]
    assert skipped and all(a.q_return is None for a in skipped)
    assert all(not by_origin[a.origin_session].eligible for a in skipped)


def test_future_outcomes_cannot_change_earlier_forecasts() -> None:
    kwargs = dict(
        model_id="m",
        feature_names=NAMES,
        target_start=date(2020, 11, 1),
        target_end=date(2021, 1, 31),
    )
    clean = experiments.walk_forward(_rows(), fitter=_recording_fitter([]), **kwargs)
    poisoned_rows = _rows(poison_after=360)
    poisoned = experiments.walk_forward(poisoned_rows, fitter=_recording_fitter([]), **kwargs)
    boundary = poisoned_rows[360].label_available_at
    for before, after in zip(clean, poisoned, strict=True):
        if after.cutoff_utc < boundary:
            assert before == after


def test_too_little_history_is_a_visible_failure_not_a_forecast() -> None:
    attempts = experiments.walk_forward(
        _rows(120),
        model_id="m",
        feature_names=NAMES,
        fitter=_recording_fitter([]),
        target_start=date(2020, 3, 1),
        target_end=date(2020, 3, 31),
    )
    assert attempts and {a.status for a in attempts} <= {
        "insufficient_training_rows",
        "ineligible_inputs",
    }
    assert all(a.q_return is None for a in attempts)


def test_selection_prefers_simpler_candidate_inside_half_percent() -> None:
    losses = {0.001: 1.000, 0.01: 1.004, 0.1: 1.02}
    assert experiments.select_candidate(losses, simplicity=lambda penalty: penalty) == 0.01
    assert experiments.select_candidate({0.001: 1.0, 0.1: 1.1}, simplicity=lambda p: p) == 0.001


def test_paired_summary_uses_only_common_sessions_and_reports_gaps() -> None:
    grid = [date(2021, 1, 1) + timedelta(days=i) for i in range(60)]
    base = {s: QuantileObservation(s, -0.01, -0.02) for s in grid}
    challenger = {s: QuantileObservation(s, -0.01, -0.015) for s in grid[:40]}
    summary = experiments.paired_summary(base, challenger, alpha=0.05, grid=grid)
    assert summary["common_forecasts"] == 40
    assert summary["mean_improvement"] == pytest.approx(0.05 * 0.005)
    assert summary["bootstrap"]["block_20"]["valid_pairs"] == 40
    assert summary["bootstrap"]["block_20"]["grid_size"] == 60
    crossing = experiments.crossing_rate(base, challenger)
    assert crossing["crossings"] == 0 and crossing["common_forecasts"] == 40

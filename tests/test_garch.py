from datetime import date

import numpy as np
import pytest

from newsvar.models.garch import (
    MAX_PERSISTENCE,
    GarchFitError,
    _second_step,
    fit_garch_t,
    fixed_garch_state,
    origin_seed,
    simulated_tail_forecast,
)


def test_seed_is_stable_and_origin_specific() -> None:
    assert origin_seed(1729, "garch_t", date(2021, 1, 4)) == origin_seed(
        1729, "garch_t", date(2021, 1, 4)
    )
    assert origin_seed(1729, "garch_t", date(2021, 1, 4)) != origin_seed(
        1729, "garch_t", date(2021, 1, 5)
    )


def test_second_step_extracts_only_the_second_horizon_and_rescales() -> None:
    paths = np.array([[[100.0, 1.0], [200.0, -2.0]]])

    assert _second_step(paths).tolist() == [0.01, -0.02]


def test_second_step_rejects_wrong_path_layout() -> None:
    with pytest.raises(GarchFitError):
        _second_step(np.zeros((2, 10, 2)))


def test_garch_fit_and_parametric_paths_are_seeded() -> None:
    history = np.random.default_rng(91).standard_t(8, size=600) * 0.01
    fitted = fit_garch_t(history)

    first = simulated_tail_forecast(
        fitted, origin_session=date(2021, 1, 4), model_id="garch_t", simulations=1000
    )
    repeated = simulated_tail_forecast(
        fitted, origin_session=date(2021, 1, 4), model_id="garch_t", simulations=1000
    )

    assert fitted.degrees_of_freedom > 2
    assert fitted.alpha + fitted.beta <= MAX_PERSISTENCE + 1e-10
    assert first == repeated
    assert first.q_return < 0
    assert first.es_return < first.q_return


def test_garch_rejects_short_history() -> None:
    with pytest.raises(GarchFitError):
        fit_garch_t([0.01] * 99)


def test_fixed_state_accepts_new_known_history_with_frozen_parameters() -> None:
    history = np.random.default_rng(11).standard_t(8, size=300) * 0.01
    fitted = fit_garch_t(history)
    updated = fixed_garch_state(np.append(history, -0.01), fitted)
    assert updated.degrees_of_freedom == fitted.degrees_of_freedom

import math

import pytest

from newsvar.baselines import (
    BaselineInputError,
    gaussian_ewma,
    historical_simulation,
)


def test_historical_simulation_uses_linear_quantile_and_fractional_es() -> None:
    forecast = historical_simulation([-0.10, -0.05, 0.00, 0.02], alpha=0.375, window=4)

    assert forecast.q_return == pytest.approx(-0.04375)
    assert forecast.es_return == pytest.approx((-0.10 - 0.025) / 1.5)
    assert forecast.variance_next is None


def test_historical_simulation_uses_only_the_declared_final_window() -> None:
    history = [-0.20, -0.10, -0.02, 0.01, 0.02]

    assert historical_simulation(history, window=4) == historical_simulation(history[1:], window=4)


def test_ewma_initialization_and_one_known_return_update() -> None:
    initial = [0.01] * 3
    forecast = gaussian_ewma(initial + [0.02], alpha=0.05, decay=0.94, initialization_window=3)

    expected_variance = 0.94 * 0.0001 + 0.06 * 0.0004
    assert forecast.variance_next == pytest.approx(expected_variance)
    assert forecast.q_return < 0
    assert forecast.es_return < forecast.q_return


def test_ewma_prefix_forecast_is_unchanged_by_a_later_unknown_return() -> None:
    known = [0.01] * 63 + [-0.02]
    forecast = gaussian_ewma(known)

    assert forecast == gaussian_ewma(known)
    assert gaussian_ewma(known + [0.50]).variance_next != forecast.variance_next


@pytest.mark.parametrize(
    ("baseline", "kwargs"),
    [
        (historical_simulation, {"history": [0.01], "window": 2}),
        (historical_simulation, {"history": [math.nan, 0.01], "window": 2}),
        (gaussian_ewma, {"history": [0.0] * 63}),
        (gaussian_ewma, {"history": [0.01] * 63, "decay": 1.0}),
    ],
)
def test_baselines_reject_undefined_inputs(baseline: object, kwargs: dict[str, object]) -> None:
    with pytest.raises(BaselineInputError):
        baseline(**kwargs)  # type: ignore[operator]

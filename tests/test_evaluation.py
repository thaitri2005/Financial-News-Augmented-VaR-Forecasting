from datetime import UTC, date, datetime

import pytest

from newsvar.evaluation import quantile_observations_from_attempts
from newsvar.metrics import MetricInputError
from newsvar.walkforward import AvailableLabel, ForecastAttempt


def _label(origin: date, target: date, observed: float = -0.02) -> AvailableLabel:
    return AvailableLabel(origin, target, observed, datetime(2021, 1, 8, tzinfo=UTC))


def _attempt(origin: date, *, status: str = "ready") -> ForecastAttempt:
    return ForecastAttempt(
        origin, datetime(2021, 1, 4, tzinfo=UTC), False, "historical", status, 250, -0.01, -0.02
    )


def test_evaluation_join_uses_exact_forecast_origin_and_target_end_key() -> None:
    rows = quantile_observations_from_attempts(
        [_attempt(date(2021, 1, 4))],
        [_label(date(2021, 1, 4), date(2021, 1, 5))],
        model_id="historical",
    )

    assert rows[0].target_end_session == date(2021, 1, 5)
    assert rows[0].return_simple == -0.02


def test_evaluation_join_rejects_duplicate_forecasts_and_missing_labels() -> None:
    attempt = _attempt(date(2021, 1, 4))
    with pytest.raises(MetricInputError):
        quantile_observations_from_attempts(
            [attempt, attempt], [_label(date(2021, 1, 4), date(2021, 1, 5))], model_id="historical"
        )
    with pytest.raises(MetricInputError):
        quantile_observations_from_attempts([attempt], [], model_id="historical")

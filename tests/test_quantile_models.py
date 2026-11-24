from pathlib import Path

import pytest

from newsvar.models.quantile import (
    QuantileModelError,
    QuantileTrainingRow,
    fit_linear_quantile,
)


def _rows() -> list[QuantileTrainingRow]:
    return [
        QuantileTrainingRow(
            {"varying": float(index), "constant": 1.0, "nullable": None}, -0.01 * index
        )
        for index in range(1, 21)
    ]


def test_linear_quantile_drops_training_constant_and_returns_decimal_prediction(
    tmp_path: Path,
) -> None:
    fitted = fit_linear_quantile(_rows(), feature_names=("varying", "constant", "nullable"))
    assert fitted.retained_feature_names == ("varying",)
    assert abs(fitted.predict({"varying": 3.0, "constant": 1.0, "nullable": None})) < 1.0
    destination = tmp_path / "fit.joblib"
    fitted.save(destination)
    assert destination.is_file()


def test_fit_uses_training_only_preprocessing_and_rejects_future_schema_drift() -> None:
    fitted = fit_linear_quantile(_rows(), feature_names=("varying", "constant", "nullable"))
    assert fitted.imputer.statistics_[0] == pytest.approx(10.5)
    with pytest.raises(QuantileModelError):
        fitted.predict({"varying": 3.0, "constant": 1.0})


def test_all_constant_training_data_is_rejected() -> None:
    rows = [
        QuantileTrainingRow({"constant": 1.0}, -0.01),
        QuantileTrainingRow({"constant": 1.0}, -0.02),
    ]
    with pytest.raises(QuantileModelError):
        fit_linear_quantile(rows, feature_names=("constant",))

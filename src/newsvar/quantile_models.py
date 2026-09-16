"""Small training-only linear quantile models for the declared M4 feature groups."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class QuantileModelError(ValueError):
    """Training or inference violates the frozen linear-quantile contract."""


@dataclass(frozen=True)
class QuantileTrainingRow:
    features: Mapping[str, float | None]
    target_return: float


@dataclass
class LinearQuantileFit:
    """Fitted training-only preprocessing and decimal-unit prediction boundary."""

    feature_names: tuple[str, ...]
    retained_feature_names: tuple[str, ...]
    alpha: float
    penalty: float
    imputer: Any
    constant_filter: Any
    scaler: Any
    model: Any

    def predict(self, features: Mapping[str, float | None]) -> float:
        """Transform one feature row with stored training state and return decimal q."""
        matrix = _feature_matrix([features], self.feature_names)
        imputed = self.imputer.transform(matrix)
        variable = self.constant_filter.transform(imputed)
        transformed = self.scaler.transform(variable)
        return float(self.model.predict(transformed)[0]) / 100.0

    def save(self, path: Path) -> None:
        """Atomically persist the exact preprocessing/model object for a monthly refit."""
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        stage = path.parent / f".{path.name}.{uuid.uuid4().hex}.staging"
        joblib.dump(self, stage)
        with stage.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(stage, path)


def _feature_matrix(rows: Sequence[Mapping[str, float | None]], names: Sequence[str]) -> np.ndarray:
    if not names:
        raise QuantileModelError("Quantile model requires at least one declared feature.")
    result: list[list[float]] = []
    expected = set(names)
    for row in rows:
        if set(row) != expected:
            raise QuantileModelError("Feature row keys do not match the frozen feature order.")
        values: list[float] = []
        for name in names:
            value = row[name]
            if value is None:
                values.append(float("nan"))
            elif np.isfinite(value):
                values.append(float(value))
            else:
                raise QuantileModelError("Feature values must be finite or null.")
        result.append(values)
    if not result:
        raise QuantileModelError("Quantile model requires at least one training row.")
    return np.asarray(result, dtype=np.float64)


def fit_linear_quantile(
    rows: Sequence[QuantileTrainingRow],
    *,
    feature_names: Sequence[str],
    alpha: float = 0.05,
    penalty: float = 0.01,
) -> LinearQuantileFit:
    """Fit median-imputed, constant-filtered, standardized quantile regression.

    Targets are converted to percentage points for the solver and converted back
    only at the public prediction boundary.
    """
    if not 0.0 < alpha < 1.0 or penalty < 0.0:
        raise QuantileModelError("Quantile level and L1 penalty are invalid.")
    names = tuple(feature_names)
    matrix = _feature_matrix([row.features for row in rows], names)
    targets = np.asarray([row.target_return for row in rows], dtype=np.float64)
    if not np.isfinite(targets).all():
        raise QuantileModelError("Quantile targets must be finite decimal returns.")
    from sklearn.feature_selection import VarianceThreshold
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import QuantileRegressor
    from sklearn.preprocessing import StandardScaler

    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    imputed = imputer.fit_transform(matrix)
    constant_filter = VarianceThreshold(threshold=0.0)
    try:
        variable = constant_filter.fit_transform(imputed)
    except ValueError as error:
        raise QuantileModelError("All training features are constant after imputation.") from error
    retained = tuple(
        name for name, keep in zip(names, constant_filter.get_support(), strict=True) if keep
    )
    scaler = StandardScaler()
    standardized = scaler.fit_transform(variable)
    model = QuantileRegressor(quantile=alpha, alpha=penalty, solver="highs", fit_intercept=True)
    model.fit(standardized, targets * 100.0)
    return LinearQuantileFit(
        names, retained, alpha, penalty, imputer, constant_filter, scaler, model
    )

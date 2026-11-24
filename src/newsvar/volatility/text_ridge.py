"""Ridge regression of HAR residuals on window term shares, with out-of-fold stacking."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ALPHAS = (1e1, 1e2, 1e3, 1e4)
FOLDS = 5
STACKING_CAP = 1.5
SHARE_SCALE = 1000.0


@dataclass(frozen=True)
class TextResidualFit:
    """Standardization, ridge weights and the out-of-fold stacking coefficient."""

    mean: np.ndarray
    scale: np.ndarray
    weights: np.ndarray
    alpha: float
    stacking: float
    out_of_fold: np.ndarray

    def predict(self, shares: np.ndarray) -> np.ndarray:
        return np.asarray(
            self.stacking * (_standardize(shares, self.mean, self.scale) @ self.weights)
        )


def _transform(shares: np.ndarray) -> np.ndarray:
    return np.log1p(SHARE_SCALE * np.asarray(shares, dtype=np.float64))


def _standardize(shares: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return np.asarray((_transform(shares) - mean) / scale)


def _ridge(features: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    """Dual-form ridge weights; rows are far fewer than columns."""
    gram = features @ features.T
    dual = np.linalg.solve(gram + alpha * np.eye(len(target)), target)
    return features.T @ dual


def fit_text_residual(shares: np.ndarray, residual: np.ndarray) -> TextResidualFit:
    """Fit residual ~ text with the penalty and stacking weight chosen out of fold.

    Folds are contiguous blocks in time order. The stacking coefficient is the
    slope of the residual on its out-of-fold prediction, capped at 1.5. It is set
    to zero unless the stacked out-of-fold prediction has a lower squared error
    than predicting zero and the slope is positive; on pure noise this still
    lets some weight through, which can only hurt the challenger.
    """
    target = np.asarray(residual, dtype=np.float64)
    target = target - target.mean()
    transformed = _transform(shares)
    mean = transformed.mean(axis=0)
    scale = transformed.std(axis=0)
    scale[scale < 1e-9] = 1.0
    features = (transformed - mean) / scale
    size = len(target)
    bounds = np.linspace(0, size, FOLDS + 1).astype(int)
    best_alpha, best_error, best_prediction = ALPHAS[-1], np.inf, np.zeros(size)
    for alpha in ALPHAS:
        prediction = np.zeros(size)
        for fold in range(FOLDS):
            held = np.arange(bounds[fold], bounds[fold + 1])
            kept = np.setdiff1d(np.arange(size), held)
            fold_mean = transformed[kept].mean(axis=0)
            fold_scale = transformed[kept].std(axis=0)
            fold_scale[fold_scale < 1e-9] = 1.0
            weights = _ridge((transformed[kept] - fold_mean) / fold_scale, target[kept], alpha)
            prediction[held] = ((transformed[held] - fold_mean) / fold_scale) @ weights
        error = float(np.mean((target - prediction) ** 2))
        if error < best_error:
            best_alpha, best_error, best_prediction = alpha, error, prediction
    variance = float(best_prediction @ best_prediction)
    stacking = max(0.0, float(target @ best_prediction) / variance) if variance > 0 else 0.0
    stacking = min(stacking, STACKING_CAP)
    stacked_error = float(np.mean((target - stacking * best_prediction) ** 2))
    if stacked_error >= float(np.mean(target**2)):
        stacking = 0.0
    return TextResidualFit(
        mean,
        scale,
        _ridge(features, target, best_alpha),
        best_alpha,
        stacking,
        stacking * best_prediction,
    )

"""Range-based daily variance measures built from open-high-low-close bars."""

from __future__ import annotations

import math

GK_WEIGHT = 2.0 * math.log(2.0) - 1.0
VARIANCE_FLOOR = 1e-8


def garman_klass(opened: float, high: float, low: float, close: float) -> float:
    """Garman-Klass estimate of the open-to-close variance of one session."""
    if min(opened, high, low, close) <= 0 or high < low:
        raise ValueError("Invalid bar for a range-based variance.")
    value = 0.5 * math.log(high / low) ** 2 - GK_WEIGHT * math.log(close / opened) ** 2
    return max(value, VARIANCE_FLOOR)


def overnight_variance(previous_close: float, opened: float) -> float:
    """Squared close-to-open log return."""
    if previous_close <= 0 or opened <= 0:
        raise ValueError("Invalid prices for the overnight return.")
    return math.log(opened / previous_close) ** 2


def close_to_close_variance(
    previous_close: float, opened: float, high: float, low: float, close: float
) -> float:
    """Overnight squared return plus the Garman-Klass intraday variance."""
    return max(
        overnight_variance(previous_close, opened) + garman_klass(opened, high, low, close),
        VARIANCE_FLOOR,
    )

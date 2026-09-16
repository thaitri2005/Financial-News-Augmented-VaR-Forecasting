"""Join immutable forecast attempts to the matching realized market labels."""

from __future__ import annotations

from collections.abc import Iterable

from newsvar.metrics import MetricInputError, QuantileObservation
from newsvar.walkforward import AvailableLabel, ForecastAttempt

EVALUABLE_STATUSES = frozenset({"ready", "ready_after_retry", "fallback_previous_refit"})


def quantile_observations_from_attempts(
    attempts: Iterable[ForecastAttempt],
    labels: Iterable[AvailableLabel],
    *,
    model_id: str,
) -> tuple[QuantileObservation, ...]:
    """Match one ready forecast to its label by forecast-origin session.

    This deliberately does not search by date proximity: the persisted label's
    origin is the forecast origin and its target-end session is the metric key.
    """
    labels_tuple = tuple(labels)
    labels_by_origin = {label.origin_session: label for label in labels_tuple}
    if len(labels_by_origin) != len(labels_tuple):
        raise MetricInputError("Evaluation labels must have unique origin sessions.")
    selected = [
        item for item in attempts if item.model_id == model_id and item.status in EVALUABLE_STATUSES
    ]
    origins = {item.origin_session for item in selected}
    if len(origins) != len(selected):
        raise MetricInputError("A model has duplicate evaluable forecast origins.")
    observations: list[QuantileObservation] = []
    for item in selected:
        label = labels_by_origin.get(item.origin_session)
        if label is None:
            raise MetricInputError("Forecast attempt has no matching market label.")
        if item.q_return is None:
            raise MetricInputError("An evaluable forecast is missing its quantile.")
        observations.append(
            QuantileObservation(label.target_end_session, label.return_simple, item.q_return)
        )
    return tuple(sorted(observations, key=lambda item: item.target_end_session))

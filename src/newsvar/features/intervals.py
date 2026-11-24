"""News tone aggregated over arbitrary availability intervals, and its surprise component."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.data.news import (
    BATCH_STEP,
    RETAINED,
    WINDOW_COMPLETENESS_MIN,
    ok_batch_times,
    sample_threshold,
    utc_seconds,
)


@dataclass(frozen=True)
class IntervalTone:
    """Counts and tone of retained headlines available in one (start, end] interval."""

    retained: int
    designated: int
    scored: int
    negative_share: float | None
    negative_mean: float | None
    expected_batches: int
    ok_batches: int

    @property
    def complete(self) -> bool:
        return (
            self.expected_batches > 0
            and self.ok_batches / self.expected_batches >= WINDOW_COMPLETENESS_MIN
        )


class ToneIndex:
    """Prefix sums over time-ordered events for fast interval queries."""

    def __init__(
        self, corpus: Path, scores: pa.Table, *, sampling_rate: float, buffer_minutes: int = 15
    ) -> None:
        import pandas as pd

        events = pq.read_table(
            corpus / "events.parquet",
            columns=["batch_time_utc", "content_sha256", "sample_key", "status"],
        ).to_pandas(types_mapper=pd.ArrowDtype)
        events = events[events["status"] == RETAINED]
        unit = str(events["batch_time_utc"].dtype)
        if "[ns" in unit:
            raise ValueError("Nanosecond batch times are not supported by this index.")
        divisor = 1 if "[s" in unit else 1_000 if "[ms" in unit else 1_000_000
        seconds = events["batch_time_utc"].astype("int64").to_numpy() // divisor
        designated = events["sample_key"].to_numpy(dtype=np.int64) < sample_threshold(sampling_rate)
        frame = pd.DataFrame(
            {"second": seconds, "content_sha256": events["content_sha256"].to_numpy()}
        )
        score_frame = scores.select(["content_sha256", "positive", "negative", "neutral"])
        merged = frame[designated].merge(
            score_frame.to_pandas().drop_duplicates("content_sha256"),
            on="content_sha256",
            how="inner",
        )
        shift = buffer_minutes * 60
        self._buffer = shift
        self._retained = np.sort(seconds) + shift
        self._designated = np.sort(seconds[designated]) + shift
        order = np.argsort(merged["second"].to_numpy(), kind="stable")
        negative = merged["negative"].to_numpy()[order]
        is_negative = (negative > merged["positive"].to_numpy()[order]) & (
            negative > merged["neutral"].to_numpy()[order]
        )
        self._scored = merged["second"].to_numpy()[order] + shift
        self._negative_sum = np.concatenate([[0.0], np.cumsum(negative)])
        self._negative_count = np.concatenate([[0.0], np.cumsum(is_negative.astype(float))])
        self._ok = np.asarray(sorted(utc_seconds(item) for item in ok_batch_times(corpus))) + shift

    def ingested_through(self, end: datetime) -> bool:
        """True when verified batches reach the last 15-minute slot of a window ending at ``end``.

        A window can pass the 95% completeness rule while its most recent batches
        are still missing; a live forecast must not go out in that state.
        """
        if len(self._ok) == 0:
            return False
        step = int(BATCH_STEP.total_seconds())
        last_slot = (utc_seconds(end) - self._buffer) // step * step + self._buffer
        return bool(self._ok[-1] >= last_slot)

    def query(self, start: datetime, end: datetime) -> IntervalTone:
        """Aggregate headlines whose availability time lies in (start, end]."""
        low, high = utc_seconds(start), utc_seconds(end)
        if high <= low:
            raise ValueError("Interval end must follow its start.")
        retained = int(
            np.searchsorted(self._retained, high, "right")
            - np.searchsorted(self._retained, low, "right")
        )
        first = int(np.searchsorted(self._scored, low, "right"))
        last = int(np.searchsorted(self._scored, high, "right"))
        scored = last - first
        step = int(BATCH_STEP.total_seconds())
        expected = (high - self._buffer) // step - (low - self._buffer) // step
        ok = int(np.searchsorted(self._ok, high, "right") - np.searchsorted(self._ok, low, "right"))
        designated = int(
            np.searchsorted(self._designated, high, "right")
            - np.searchsorted(self._designated, low, "right")
        )
        return IntervalTone(
            retained,
            designated,
            scored,
            None
            if scored == 0
            else float((self._negative_count[last] - self._negative_count[first]) / scored),
            None
            if scored == 0
            else float((self._negative_sum[last] - self._negative_sum[first]) / scored),
            int(expected),
            ok,
        )


def expanding_surprise(
    tone: Sequence[float | None],
    controls: np.ndarray,
    refit: Sequence[bool],
    known_through: Sequence[int],
    *,
    min_rows: int = 120,
) -> list[float | None]:
    """Standardized residual of tone on controls, using only rows known at each refit.

    At each row flagged in ``refit`` the regression is re-estimated on rows with
    index at most ``known_through[i]`` and kept until the next refit. A row's
    surprise is its tone minus the fitted value, divided by the training
    residual standard deviation. Rows with missing inputs yield ``None``.
    """
    values = np.asarray([np.nan if item is None else item for item in tone], dtype=np.float64)
    design = np.column_stack([np.ones(len(values)), np.asarray(controls, dtype=np.float64)])
    valid = np.isfinite(values) & np.isfinite(design).all(axis=1)
    result: list[float | None] = []
    beta: np.ndarray | None = None
    scale = 1.0
    for index in range(len(values)):
        if refit[index] or beta is None:
            rows = valid.copy()
            rows[max(known_through[index] + 1, 0) :] = False
            if rows.sum() >= min_rows:
                beta, *_ = np.linalg.lstsq(design[rows], values[rows], rcond=None)
                residual = values[rows] - design[rows] @ beta
                scale = float(residual.std(ddof=design.shape[1])) or 1.0
            else:
                beta = None
        if beta is None or not valid[index]:
            result.append(None)
        else:
            result.append(float((values[index] - design[index] @ beta) / scale))
    return result

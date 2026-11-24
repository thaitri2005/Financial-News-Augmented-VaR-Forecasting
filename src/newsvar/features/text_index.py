"""Window-level term shares of retained headlines for a supervised text-to-volatility model.

The vocabulary is fixed from titles first seen on or before a declared date, so
no later wording can enter it. Each window is described by the share of its
retained headlines that contain each vocabulary term.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from newsvar.data.news import RETAINED, utc_seconds

TOKEN_PATTERN = r"(?u)\b[a-z][a-z'&\-]{2,}\b"


class TextIndex:
    """Sparse title-term matrix plus time-ordered retained events."""

    def __init__(
        self,
        corpus: Path,
        *,
        vocabulary_end: datetime,
        max_features: int = 5000,
        min_document_count: int = 200,
        buffer_minutes: int = 15,
    ) -> None:
        import pandas as pd
        from sklearn.feature_extraction.text import CountVectorizer

        titles = pq.read_table(corpus / "titles.parquet").to_pandas()
        early = titles["first_batch_time_utc"] <= pd.Timestamp(vocabulary_end)
        vectorizer = CountVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            binary=True,
            stop_words="english",
            token_pattern=TOKEN_PATTERN,
            min_df=min_document_count,
            max_features=max_features,
            dtype=np.float32,
        )
        vectorizer.fit(titles.loc[early, "title_clean"])
        self.terms: tuple[str, ...] = tuple(vectorizer.get_feature_names_out())
        self._matrix = vectorizer.transform(titles["title_clean"]).tocsr()
        position = pd.Series(np.arange(len(titles)), index=titles["content_sha256"])
        events = pq.read_table(
            corpus / "events.parquet", columns=["batch_time_utc", "content_sha256", "status"]
        ).to_pandas()
        events = events[events["status"] == RETAINED]
        seconds = events["batch_time_utc"].astype("int64").to_numpy() // (
            10 ** {"s": 0, "ms": 3, "us": 6, "ns": 9}[events["batch_time_utc"].dt.unit]
        )
        order = np.argsort(seconds, kind="stable")
        self._available = seconds[order] + buffer_minutes * 60
        self._title_row = position.loc[events["content_sha256"].to_numpy()[order]].to_numpy()

    def shares(self, intervals: Sequence[tuple[datetime, datetime]]) -> np.ndarray:
        """Term shares for each (start, end] availability interval; zeros when empty."""
        output = np.zeros((len(intervals), len(self.terms)), dtype=np.float64)
        for index, (start, end) in enumerate(intervals):
            first = int(np.searchsorted(self._available, utc_seconds(start), "right"))
            last = int(np.searchsorted(self._available, utc_seconds(end), "right"))
            if last > first:
                block = self._matrix[self._title_row[first:last]]
                output[index] = np.asarray(block.sum(axis=0)).ravel() / (last - first)
        return output

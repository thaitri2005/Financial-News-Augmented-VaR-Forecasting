"""GDELT title normalization, frozen relevance, chronological dedup and window assignment.

Everything here is outcome-blind: no market return is read. The rules are fixed
identifiers recorded in each corpus manifest; changing one creates a new corpus
version instead of editing an old one.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import unicodedata
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.calendar import ForecastOrigin
from newsvar.ingestion.gdelt import OK, batch_time, day_directory, iter_days, load_day
from newsvar.provenance import canonical_json, sha256

RELEVANCE_RULE_ID = "gdelt_en_web_us_stockmarket_title_v1"
NORMALIZATION_ID = "headline_text_v1"
DEDUP_RULE_ID = "exact_casefold_title_or_url_72h_v1"
DEDUP_LOOKBACK = timedelta(hours=72)
MIN_TITLE_CHARACTERS = 10
WINDOW_COMPLETENESS_MIN = 0.95
BATCH_STEP = timedelta(minutes=15)

RETAINED = "retained"
DUPLICATE_TITLE = "duplicate_title"
DUPLICATE_URL = "duplicate_url"

_TAG = re.compile(r"<[^>]{0,200}>")
_SPACE = re.compile(r"\s+")

EVENT_SCHEMA = pa.schema(
    [
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("batch_time_utc", pa.timestamp("s", tz="UTC"), nullable=False),
        pa.field("source_common_name", pa.string(), nullable=False),
        pa.field("content_sha256", pa.string(), nullable=False),
        pa.field("sample_key", pa.uint32(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("gdelt_tone", pa.float64(), nullable=True),
    ]
)
TITLE_SCHEMA = pa.schema(
    [
        pa.field("content_sha256", pa.string(), nullable=False),
        pa.field("title_clean", pa.string(), nullable=False),
        pa.field("first_batch_time_utc", pa.timestamp("s", tz="UTC"), nullable=False),
    ]
)


class NewsError(ValueError):
    """News corpus inputs or committed artifacts violate the fixed contract."""


def normalize_title(raw: str | None) -> str | None:
    """Decode entities, drop markup, NFC-normalize and collapse whitespace; keep case."""
    if raw is None:
        return None
    text = html.unescape(html.unescape(raw))
    text = _TAG.sub(" ", text)
    text = unicodedata.normalize("NFC", text).replace("�", " ")
    text = _SPACE.sub(" ", text).strip()
    return text or None


def exclusion_reason(record: Mapping[str, object], title: str | None) -> str | None:
    """Return why a matched GKG row is outside the frozen relevance rule, else None."""
    if record["source_collection"] != "1":
        return "not_web_collection"
    if record["is_translated"]:
        return "translated"
    if not record["has_us_location"]:
        return "no_us_location"
    if title is None:
        return "no_title"
    if len(title) < MIN_TITLE_CHARACTERS or not any(character.isalpha() for character in title):
        return "title_too_short_or_nonalphabetic"
    return None


class Deduplicator:
    """Chronological exact-duplicate suppression using only already-seen records."""

    def __init__(self, lookback: timedelta = DEDUP_LOOKBACK) -> None:
        self.lookback = lookback
        self._titles: dict[str, datetime] = {}
        self._urls: dict[str, datetime] = {}
        self._latest: datetime | None = None

    def observe(self, when: datetime, title: str, url: str) -> str:
        if self._latest is not None and when < self._latest:
            raise NewsError("Deduplication requires nondecreasing availability order.")
        self._latest = when
        title_key = title.casefold()
        previous_title, previous_url = self._titles.get(title_key), self._urls.get(url)
        self._titles[title_key] = when
        self._urls[url] = when
        if previous_url is not None and when - previous_url <= self.lookback:
            return DUPLICATE_URL
        if previous_title is not None and when - previous_title <= self.lookback:
            return DUPLICATE_TITLE
        return RETAINED

    def prune(self) -> None:
        if self._latest is None:
            return
        floor = self._latest - self.lookback
        self._titles = {key: seen for key, seen in self._titles.items() if seen >= floor}
        self._urls = {key: seen for key, seen in self._urls.items() if seen >= floor}


def content_hash(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()


def sample_key(content_sha256: str) -> int:
    """Uniform 32-bit key from the content hash for frozen probability sampling."""
    return int(content_sha256[:8], 16)


def sample_threshold(rate: float) -> int:
    """Keys strictly below this threshold are designated for scoring at ``rate``."""
    if not 0.0 < rate <= 1.0:
        raise NewsError("Sampling rate must lie in (0, 1].")
    return int(round(rate * 2**32))


def day_events(
    records: Iterable[Mapping[str, object]], deduplicator: Deduplicator
) -> tuple[list[dict[str, object]], dict[str, str], dict[str, int]]:
    """Convert one UTC day's ordered matched rows into events, new titles and exclusion counts."""
    events: list[dict[str, object]] = []
    titles: dict[str, str] = {}
    exclusions: dict[str, int] = {}
    for record in records:
        title = normalize_title(record["page_title_raw"])  # type: ignore[arg-type]
        reason = exclusion_reason(record, title)
        if reason is not None:
            exclusions[reason] = exclusions.get(reason, 0) + 1
            continue
        assert title is not None
        when = batch_time(str(record["batch_stamp"]))
        status = deduplicator.observe(when, title, str(record["document_identifier"]))
        digest = content_hash(title)
        events.append(
            {
                "event_id": record["gkg_record_id"],
                "batch_time_utc": when,
                "source_common_name": record["source_common_name"],
                "content_sha256": digest,
                "sample_key": sample_key(digest),
                "status": status,
                "gdelt_tone": record["gdelt_tone"],
            }
        )
        if status == RETAINED:
            titles.setdefault(digest, title)
    return events, titles, exclusions


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_corpus(
    title_root: Path, output_root: Path, *, start: date, end: date
) -> tuple[Path, dict[str, object]]:
    """Materialize the versioned event/title corpus from committed, verified GDELT days."""
    day_ids: list[str] = []
    manifests: dict[date, dict[str, object]] = {}
    for day in iter_days(start, end):
        manifest = load_day(title_root, day)
        if manifest is None:
            raise NewsError(f"GDELT day {day} is not committed; extract it first.")
        manifests[day] = manifest
        day_ids.append(f"{day.isoformat()}:{manifest['titles_sha256']}")
    identity: dict[str, object] = {
        "schema_version": "news_corpus_v2",
        "source": "gdelt_gkg_v2_english",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "relevance_rule": RELEVANCE_RULE_ID,
        "normalization": NORMALIZATION_ID,
        "dedup_rule": DEDUP_RULE_ID,
        "min_title_characters": MIN_TITLE_CHARACTERS,
        "day_tables_sha256": sha256("\n".join(day_ids).encode()),
    }
    corpus_id = sha256(canonical_json(identity))
    destination = output_root / corpus_id
    if destination.exists():
        return destination, load_corpus(destination)
    output_root.mkdir(parents=True, exist_ok=True)
    stage = output_root / f".{corpus_id}.{uuid.uuid4().hex}.staging"
    stage.mkdir()
    deduplicator = Deduplicator()
    seen_titles: set[str] = set()
    exclusions: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    batch_rows: list[dict[str, object]] = []
    event_writer = pq.ParquetWriter(stage / "events.parquet", EVENT_SCHEMA, compression="zstd")
    title_writer = pq.ParquetWriter(stage / "titles.parquet", TITLE_SCHEMA, compression="zstd")
    title_count = 0
    try:
        for index, day in enumerate(iter_days(start, end)):
            table = pq.read_table(day_directory(title_root, day) / "titles.parquet")
            events, titles, day_exclusions = day_events(table.to_pylist(), deduplicator)
            for reason, count in day_exclusions.items():
                exclusions[reason] = exclusions.get(reason, 0) + count
            first_seen: dict[str, datetime] = {}
            for event in events:
                status = str(event["status"])
                status_counts[status] = status_counts.get(status, 0) + 1
                if status == RETAINED:
                    first_seen.setdefault(str(event["content_sha256"]), event["batch_time_utc"])  # type: ignore[arg-type]
            event_writer.write_table(pa.Table.from_pylist(events, schema=EVENT_SCHEMA))
            new_titles = [
                {
                    "content_sha256": digest,
                    "title_clean": text,
                    "first_batch_time_utc": first_seen[digest],
                }
                for digest, text in titles.items()
                if digest not in seen_titles
            ]
            seen_titles.update(item["content_sha256"] for item in new_titles)  # type: ignore[misc]
            title_count += len(new_titles)
            title_writer.write_table(pa.Table.from_pylist(new_titles, schema=TITLE_SCHEMA))
            batches = manifests[day]["batches"]
            assert isinstance(batches, list)
            batch_rows.extend(
                {"stamp": item["stamp"], "status": item["status"]} for item in batches
            )
            if index % 30 == 0:
                deduplicator.prune()
    finally:
        event_writer.close()
        title_writer.close()
    pq.write_table(pa.Table.from_pylist(batch_rows), stage / "batches.parquet", compression="zstd")
    tables = {}
    for name in ("events", "titles", "batches"):
        path = stage / f"{name}.parquet"
        metadata = pq.ParquetFile(path).metadata
        tables[name] = {"rows": metadata.num_rows, "sha256": _file_sha256(path)}
    manifest_out: dict[str, object] = {
        "corpus_id": corpus_id,
        "identity": identity,
        "tables": tables,
        "event_status": dict(sorted(status_counts.items())),
        "excluded_matched_rows": dict(sorted(exclusions.items())),
        "unique_retained_titles": title_count,
    }
    with (stage / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest_out).decode("utf-8") + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stage, destination)
    return destination, load_corpus(destination)


def load_corpus(path: Path) -> dict[str, object]:
    """Verify a committed corpus identity and table checksums."""
    root = path.resolve(strict=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or sha256(canonical_json(manifest["identity"])) != manifest["corpus_id"]
        or root.name != manifest["corpus_id"]
    ):
        raise NewsError("News corpus manifest identity mismatch.")
    for name, info in manifest["tables"].items():
        if _file_sha256(root / f"{name}.parquet") != info["sha256"]:
            raise NewsError(f"News corpus table {name} fails its checksum.")
    return manifest


@dataclass(frozen=True)
class WindowCoverage:
    expected_batches: int
    ok_batches: int

    @property
    def fraction(self) -> float:
        return self.ok_batches / self.expected_batches if self.expected_batches else 0.0

    @property
    def feed_complete(self) -> bool:
        return self.expected_batches > 0 and self.fraction >= WINDOW_COMPLETENESS_MIN


def assign_windows(
    batch_times: np.ndarray, origins: Sequence[ForecastOrigin], *, buffer_minutes: int
) -> np.ndarray:
    """Map batch times to origin indexes with (previous cutoff, cutoff] availability.

    ``batch_times`` are UTC epoch seconds. Availability is batch time plus the
    declared Class B buffer. The result is -1 when no origin window contains it.
    """
    if buffer_minutes < 0:
        raise NewsError("Availability buffer cannot be negative.")
    cutoffs = np.asarray([int(origin.cutoff_utc.timestamp()) for origin in origins], dtype=np.int64)
    lower = np.asarray(
        [int(origin.previous_cutoff_utc.timestamp()) for origin in origins], dtype=np.int64
    )
    if np.any(np.diff(cutoffs) <= 0):
        raise NewsError("Origins must be strictly increasing.")
    available = np.asarray(batch_times, dtype=np.int64) + buffer_minutes * 60
    index = np.searchsorted(cutoffs, available, side="left")
    inside = index < len(cutoffs)
    safe = np.where(inside, index, 0)
    inside &= available > lower[safe]
    return np.where(inside, index, -1)


def window_coverage(
    ok_batch_times: Iterable[datetime], origins: Sequence[ForecastOrigin], *, buffer_minutes: int
) -> list[WindowCoverage]:
    """Count expected and verified 15-minute batches whose availability falls in each window."""
    ok_seconds = np.asarray(sorted(int(item.timestamp()) for item in ok_batch_times), np.int64)
    ok_index = assign_windows(ok_seconds, origins, buffer_minutes=buffer_minutes)
    ok_counts = np.bincount(ok_index[ok_index >= 0], minlength=len(origins))
    result: list[WindowCoverage] = []
    step, shift = int(BATCH_STEP.total_seconds()), buffer_minutes * 60
    for position, origin in enumerate(origins):
        low = int(origin.previous_cutoff_utc.timestamp()) - shift
        high = int(origin.cutoff_utc.timestamp()) - shift
        expected = high // step - low // step
        result.append(WindowCoverage(int(expected), int(ok_counts[position])))
    return result


def ok_batch_times(corpus: Path) -> Iterator[datetime]:
    table = pq.read_table(corpus / "batches.parquet")
    for stamp, status in zip(
        table.column("stamp").to_pylist(), table.column("status").to_pylist(), strict=True
    ):
        if status == OK:
            yield batch_time(stamp)


def utc_seconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise NewsError("Timestamps must be timezone-aware.")
    return int(value.astimezone(UTC).timestamp())

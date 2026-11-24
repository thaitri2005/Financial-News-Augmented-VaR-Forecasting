"""Streaming GDELT GKG title extraction: verify, filter, commit per UTC day, discard payload.

The public archive publishes one English GKG ZIP per 15-minute batch and a master
catalog with each file's byte count and MD5. This adapter never keeps the raw
multi-year archive. For every catalogued batch it downloads the ZIP, verifies the
catalog size/MD5, retains only rows carrying the frozen relevance theme, and
records a per-batch ledger so that a missing or failed batch is never mistaken
for an interval with no news.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from newsvar.hashing import canonical_json

ADAPTER_VERSION = "gdelt_gkg_stream_v1"
ARCHIVE_URL = "https://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"
RELEVANCE_THEME = b"ECON_STOCKMARKET"
SECONDARY_THEMES = (b"ECON_INTEREST_RATES", b"ECON_INFLATION", b"ECON_CENTRALBANK")
GKG_FIELDS = 27
MAX_ZIP_BYTES = 256 * 1024 * 1024
MAX_UNZIPPED_BYTES = 1024 * 1024 * 1024
BATCHES_PER_DAY = 96

_CATALOG_LINE = re.compile(
    rb"^(\d+) ([0-9a-f]{32}) http://data\.gdeltproject\.org/gdeltv2/(\d{14})\.gkg\.csv\.zip$"
)
_TITLE = re.compile(rb"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.DOTALL)

OK = "ok"
ABSENT = "absent_from_catalog"
FETCH_FAILED = "fetch_failed"
SIZE_MISMATCH = "size_mismatch"
MD5_MISMATCH = "md5_mismatch"
BAD_ARCHIVE = "bad_archive"

TITLE_SCHEMA = pa.schema(
    [
        pa.field("batch_stamp", pa.string(), nullable=False),
        pa.field("gkg_record_id", pa.string(), nullable=False),
        pa.field("source_collection", pa.string(), nullable=False),
        pa.field("source_common_name", pa.string(), nullable=False),
        pa.field("document_identifier", pa.string(), nullable=False),
        pa.field("has_us_location", pa.bool_(), nullable=False),
        pa.field("theme_interest_rates", pa.bool_(), nullable=False),
        pa.field("theme_inflation", pa.bool_(), nullable=False),
        pa.field("theme_central_bank", pa.bool_(), nullable=False),
        pa.field("is_translated", pa.bool_(), nullable=False),
        pa.field("gdelt_tone", pa.float64(), nullable=True),
        pa.field("page_title_raw", pa.string(), nullable=True),
    ]
)


class GdeltError(ValueError):
    """A catalog, archive payload, or committed day violates the adapter contract."""


@dataclass(frozen=True)
class CatalogEntry:
    stamp: str
    byte_count: int
    md5: str


@dataclass(frozen=True)
class BatchResult:
    stamp: str
    status: str
    byte_count: int
    md5: str
    rows: int
    malformed_rows: int
    titled_rows: int
    matched_rows: int


def batch_time(stamp: str) -> datetime:
    """Parse a 14-digit archive batch stamp as its UTC batch time."""
    if len(stamp) != 14 or not stamp.isdigit():
        raise GdeltError(f"Invalid GDELT batch stamp: {stamp!r}")
    parsed = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    if parsed.minute % 15 or parsed.second:
        raise GdeltError(f"GDELT batch stamp is off the 15-minute grid: {stamp!r}")
    return parsed


def expected_stamps(day: date) -> tuple[str, ...]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return tuple(
        (start + timedelta(minutes=15 * index)).strftime("%Y%m%d%H%M%S")
        for index in range(BATCHES_PER_DAY)
    )


def read_catalog(path: Path, *, start: date, end: date) -> dict[str, CatalogEntry]:
    """Read English GKG entries inside an inclusive UTC date range from the master list."""
    if end < start:
        raise GdeltError("Catalog range end precedes its start.")
    low, high = start.strftime("%Y%m%d").encode(), end.strftime("%Y%m%d").encode()
    entries: dict[str, CatalogEntry] = {}
    with path.open("rb") as stream:
        for line in stream:
            if b".gkg.csv.zip" not in line:
                continue
            match = _CATALOG_LINE.match(line.strip())
            if match is None:
                raise GdeltError(f"Unparseable GKG catalog line: {line[:120]!r}")
            stamp = match.group(3)
            if not low <= stamp[:8] <= high:
                continue
            key = stamp.decode()
            entry = CatalogEntry(key, int(match.group(1)), match.group(2).decode())
            if key in entries and entries[key] != entry:
                raise GdeltError(f"Conflicting catalog entries for batch {key}.")
            entries[key] = entry
    return entries


def _country_is_us(locations: bytes) -> bool:
    for location in locations.split(b";"):
        parts = location.split(b"#")
        if len(parts) >= 3 and parts[2] == b"US":
            return True
    return False


def _tone(field: bytes) -> float | None:
    head = field.split(b",", 1)[0]
    try:
        value = float(head)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def parse_gkg(stamp: str, payload: bytes) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Return relevance-matched rows and whole-batch counts from decompressed GKG bytes."""
    rows = malformed = 0
    matched: list[dict[str, object]] = []
    for line in payload.split(b"\n"):
        if not line.strip():
            continue
        rows += 1
        if RELEVANCE_THEME not in line:
            if line.count(b"\t") != GKG_FIELDS - 1:
                malformed += 1
            continue
        fields = line.rstrip(b"\r").split(b"\t")
        if len(fields) != GKG_FIELDS:
            malformed += 1
            continue
        themes = set(fields[7].split(b";"))
        if RELEVANCE_THEME not in themes:
            continue
        title = _TITLE.search(fields[26])
        matched.append(
            {
                "batch_stamp": stamp,
                "gkg_record_id": fields[0].decode("utf-8", "replace"),
                "source_collection": fields[2].decode("utf-8", "replace"),
                "source_common_name": fields[3].decode("utf-8", "replace"),
                "document_identifier": fields[4].decode("utf-8", "replace"),
                "has_us_location": _country_is_us(fields[9]),
                "theme_interest_rates": SECONDARY_THEMES[0] in themes,
                "theme_inflation": SECONDARY_THEMES[1] in themes,
                "theme_central_bank": SECONDARY_THEMES[2] in themes,
                "is_translated": bool(fields[25].strip()),
                "gdelt_tone": _tone(fields[15]),
                "page_title_raw": None
                if title is None
                else title.group(1).decode("utf-8", "replace"),
            }
        )
    counts = {
        "rows": rows,
        "malformed_rows": malformed,
        "titled_rows": payload.count(b"<PAGE_TITLE>"),
        "matched_rows": len(matched),
    }
    return matched, counts


def unzip_single(payload: bytes) -> bytes:
    """Decompress a one-member archive with an explicit expansion bound."""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].file_size > MAX_UNZIPPED_BYTES:
                raise GdeltError("GKG archive must hold one bounded member.")
            return archive.read(members[0])
    except (zipfile.BadZipFile, OSError, EOFError) as error:
        raise GdeltError("Unreadable GKG archive.") from error


Fetcher = Callable[[str], bytes]


def http_fetch(stamp: str, *, attempts: int = 4, timeout: float = 120.0) -> bytes:
    """Fetch one batch ZIP with bounded size and backoff on transient failures."""
    url = ARCHIVE_URL.format(stamp=stamp)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
                payload: bytes = response.read(MAX_ZIP_BYTES + 1)
            if len(payload) > MAX_ZIP_BYTES:
                raise GdeltError("GKG archive exceeds the per-batch byte bound.")
            return payload
        except urllib.error.HTTPError as error:
            last = error
            if error.code in {403, 404, 407}:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            last = error
        time.sleep(min(30.0, 2.0**attempt))
    raise GdeltError(f"Batch {stamp} could not be fetched: {last!r}")


def process_batch(
    entry: CatalogEntry, fetch: Fetcher
) -> tuple[BatchResult, list[dict[str, object]]]:
    """Fetch, verify against the catalog, and parse one batch; failures stay visible."""

    def failed(
        status: str, size: int = 0, digest: str = ""
    ) -> tuple[BatchResult, list[dict[str, object]]]:
        return BatchResult(entry.stamp, status, size, digest, 0, 0, 0, 0), []

    try:
        payload = fetch(entry.stamp)
    except GdeltError:
        return failed(FETCH_FAILED)
    digest = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    if len(payload) != entry.byte_count:
        return failed(SIZE_MISMATCH, len(payload), digest)
    if digest != entry.md5:
        return failed(MD5_MISMATCH, len(payload), digest)
    try:
        records, counts = parse_gkg(entry.stamp, unzip_single(payload))
    except GdeltError:
        return failed(BAD_ARCHIVE, len(payload), digest)
    return BatchResult(entry.stamp, OK, len(payload), digest, **counts), records


def _sync_write(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def day_directory(root: Path, day: date) -> Path:
    return root / f"date={day.isoformat()}"


def load_day(root: Path, day: date) -> dict[str, object] | None:
    """Load a committed day manifest after verifying its title table checksum."""
    directory = day_directory(root, day)
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table_path = directory / "titles.parquet"
    with table_path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if not isinstance(manifest, dict) or manifest.get("titles_sha256") != digest:
        raise GdeltError(f"Committed GDELT day {day} fails its checksum.")
    return manifest


def day_is_final(manifest: Mapping[str, object]) -> bool:
    """A day needs no retry when every catalogued batch was verified and parsed."""
    batches = manifest["batches"]
    assert isinstance(batches, list)
    return all(batch["status"] in {OK, ABSENT} for batch in batches)


def extract_day(
    day: date,
    catalog: Mapping[str, CatalogEntry],
    root: Path,
    *,
    catalog_sha256: str,
    fetch: Fetcher = http_fetch,
    threads: int = 8,
    force: bool = False,
) -> dict[str, object]:
    """Extract one UTC day and atomically commit its titles plus per-batch ledger.

    A committed day whose catalogued batches all verified is returned unchanged
    unless ``force`` is set. Force is needed for recent days: a day extracted
    before it ended lists only the batches published so far.
    """
    existing = load_day(root, day)
    if existing is not None and day_is_final(existing) and not force:
        return existing
    stamps = expected_stamps(day)
    listed = [catalog[stamp] for stamp in stamps if stamp in catalog]
    with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
        outcomes = list(pool.map(lambda entry: process_batch(entry, fetch), listed))
    results = {result.stamp: result for result, _ in outcomes}
    records = [record for _, batch_records in outcomes for record in batch_records]
    records.sort(key=lambda record: (str(record["batch_stamp"]), str(record["gkg_record_id"])))
    batches = [
        results[stamp].__dict__
        if stamp in results
        else BatchResult(stamp, ABSENT, 0, "", 0, 0, 0, 0).__dict__
        for stamp in stamps
    ]
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".{day.isoformat()}.{uuid.uuid4().hex}.staging"
    stage.mkdir()
    table_path = stage / "titles.parquet"
    pq.write_table(
        pa.Table.from_pylist(records, schema=TITLE_SCHEMA), table_path, compression="zstd"
    )
    with table_path.open("r+b") as stream:
        os.fsync(stream.fileno())
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest: dict[str, object] = {
        "schema_version": "gdelt_title_day_v1",
        "adapter_version": ADAPTER_VERSION,
        "utc_date": day.isoformat(),
        "catalog_sha256": catalog_sha256,
        "relevance_theme": RELEVANCE_THEME.decode(),
        "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "titles_sha256": digest,
        "title_rows": len(records),
        "batches": batches,
    }
    _sync_write(stage / "manifest.json", canonical_json(manifest) + b"\n")
    destination = day_directory(root, day)
    if destination.exists():
        retired = root / f".{day.isoformat()}.{uuid.uuid4().hex}.retired"
        os.replace(destination, retired)
        os.replace(stage, destination)
        for leftover in retired.iterdir():
            leftover.unlink()
        retired.rmdir()
    else:
        os.replace(stage, destination)
    return manifest


def iter_days(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def summarize(manifests: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate committed day ledgers into outcome-blind extraction evidence."""
    status: dict[str, int] = {}
    totals = {"days": 0, "bytes": 0, "rows": 0, "titled_rows": 0, "matched_rows": 0}
    for manifest in manifests:
        totals["days"] += 1
        batches = manifest["batches"]
        assert isinstance(batches, list)
        for batch in batches:
            status[batch["status"]] = status.get(batch["status"], 0) + 1
            totals["bytes"] += batch["byte_count"]
            totals["rows"] += batch["rows"]
            totals["titled_rows"] += batch["titled_rows"]
            totals["matched_rows"] += batch["matched_rows"]
    return {**totals, "batch_status": dict(sorted(status.items()))}

"""Capped HTTP-range probe of historical GDELT 2.0 GKG daily file listings.

This is archive *catalog* completeness and transfer sizing, not news admission.
The full mutable masterfilelist is never downloaded or stored here.
"""

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

CATALOG_URL = "https://data.gdeltproject.org/gdeltv2/masterfilelist.txt"
RANGE_BYTES = 65_536
RANGE_OVERLAP = 512
MAX_REQUESTS = 48
MAX_TRANSFER_BYTES = 4 * 1024 * 1024
FILE_DATE = re.compile(rb"/gdeltv2/(\d{14})\.")
GKG_LINE = re.compile(
    rb"^(\d+) ([a-f0-9]{32}) https?://data\.gdeltproject\.org/gdeltv2/"
    rb"(\d{14})\.gkg\.csv\.zip$"
)


class CatalogProbeError(ValueError):
    """Catalog range, chronology, or bounded-probe guarantee failed."""


def _complete_lines(payload: bytes, *, starts_at_zero: bool) -> list[bytes]:
    lines = payload.split(b"\n")
    if not starts_at_zero:
        lines = lines[1:]
    if not payload.endswith(b"\n"):
        lines = lines[:-1]
    return [line.rstrip(b"\r") for line in lines if line]


def _dates(payload: bytes, *, starts_at_zero: bool) -> tuple[str, str]:
    found = [
        match.group(1).decode()[:8]
        for line in _complete_lines(payload, starts_at_zero=starts_at_zero)
        if (match := FILE_DATE.search(line))
    ]
    if not found or found != sorted(found):
        raise CatalogProbeError("Catalog range has no chronological file rows.")
    return found[0], found[-1]


class RangeCatalog:
    def __init__(self) -> None:
        self.total_bytes: int | None = None
        self.last_modified: str | None = None
        self.calls = 0
        self.bytes_received = 0
        self.range_hashes: list[dict[str, object]] = []
        self._cache: dict[int, bytes] = {}
        self.read(0)

    def read(self, start: int) -> bytes:
        if start in self._cache:
            return self._cache[start]
        if (
            start < 0
            or self.calls >= MAX_REQUESTS
            or self.bytes_received + RANGE_BYTES > MAX_TRANSFER_BYTES
        ):
            raise CatalogProbeError("Catalog request/transfer cap reached.")
        end = start + RANGE_BYTES - 1
        request = urllib.request.Request(
            CATALOG_URL,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "newsvar-public-feasibility/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                if response.status != 206 or not match or int(match.group(1)) != start:
                    raise CatalogProbeError("GDELT server did not honor bounded HTTP range.")
                total = int(match.group(3))
                returned_end = int(match.group(2))
                if returned_end != min(end, total - 1):
                    raise CatalogProbeError("Catalog returned an unexpected byte range.")
                if self.total_bytes is not None and self.total_bytes != total:
                    raise CatalogProbeError(
                        "Mutable catalog changed size during probe; rerun later."
                    )
                modified = response.headers.get("Last-Modified")
                if self.last_modified is not None and modified != self.last_modified:
                    raise CatalogProbeError(
                        "Mutable catalog changed version during probe; rerun later."
                    )
                payload = response.read(RANGE_BYTES + 1)
        except OSError as exc:
            raise CatalogProbeError("Bounded public GDELT catalog request failed.") from exc
        if len(payload) != returned_end - start + 1 or len(payload) > RANGE_BYTES:
            raise CatalogProbeError("Catalog response body disagrees with Content-Range.")
        self.total_bytes = total
        self.last_modified = modified
        self.calls += 1
        self.bytes_received += len(payload)
        self.range_hashes.append(
            {"start": start, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
        self._cache[start] = payload
        return payload

    def gkg_day(self, day: str) -> dict[str, object]:
        if self.total_bytes is None:
            raise CatalogProbeError("Catalog total length was not established.")
        target = day.replace("-", "")
        low, high = 0, max(0, self.total_bytes - RANGE_BYTES)
        while high - low > RANGE_BYTES:
            midpoint = (low + high) // 2
            first, _ = _dates(self.read(midpoint), starts_at_zero=midpoint == 0)
            if first <= target:
                low = midpoint
            else:
                high = midpoint
        start = max(0, low - RANGE_BYTES)
        seen: dict[str, tuple[int, str]] = {}
        scanned = 0
        while True:
            payload = self.read(start)
            first, last = _dates(payload, starts_at_zero=start == 0)
            scanned += 1
            for line in _complete_lines(payload, starts_at_zero=start == 0):
                match = GKG_LINE.fullmatch(line)
                if not match:
                    continue
                batch = match.group(3).decode()
                if batch[:8] != target:
                    continue
                metadata = (int(match.group(1)), match.group(2).decode())
                if batch in seen and seen[batch] != metadata:
                    raise CatalogProbeError("Conflicting catalog entries for one GKG batch.")
                seen[batch] = metadata
            if last > target:
                break
            if first > target or scanned >= 8 or start + RANGE_BYTES >= self.total_bytes:
                raise CatalogProbeError("Could not bound the requested GKG calendar day.")
            start += RANGE_BYTES - RANGE_OVERLAP
        expected = [
            (datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(minutes=15 * i)).strftime(
                "%Y%m%d%H%M%S"
            )
            for i in range(96)
        ]
        missing = [batch for batch in expected if batch not in seen]
        unexpected = sorted(set(seen) - set(expected))
        return {
            "day_utc": day,
            "first_catalog_day_in_scan": first,
            "last_catalog_day_in_scan": last,
            "gkg_batches_listed": len(seen),
            "expected_quarter_hour_batches": 96,
            "missing_batches": missing,
            "unexpected_batches": unexpected,
            "listed_compressed_bytes": sum(size for size, _ in seen.values()),
            "first_gkg_batch": min(seen) if seen else None,
            "last_gkg_batch": max(seen) if seen else None,
            "gkg_manifest": [
                {"batch": batch, "compressed_bytes": seen[batch][0], "md5": seen[batch][1]}
                for batch in sorted(seen)
            ],
            "scope": "Public catalog listing only; archive payloads/titles not fetched.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dates", nargs="+", required=True, help="UTC days YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path, help="New dated JSON report path")
    args = parser.parse_args()
    if len(args.dates) > 2 or len(set(args.dates)) != len(args.dates):
        parser.error("Probe exactly one or two distinct days per bounded run.")
    for day in args.dates:
        try:
            datetime.fromisoformat(day)
        except ValueError:
            parser.error("Dates must be valid YYYY-MM-DD days.")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day < "2019-09-08":
            parser.error("Title pilot dates must be YYYY-MM-DD and >=2019-09-08.")
    catalog = RangeCatalog()
    days = [catalog.gkg_day(day) for day in args.dates]
    report = {
        "schema_version": "gdelt_catalog_pilot_v1",
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "catalog_url": CATALOG_URL,
        "catalog_total_bytes": catalog.total_bytes,
        "catalog_last_modified": catalog.last_modified,
        "range_requests": catalog.calls,
        "transferred_bytes": catalog.bytes_received,
        "range_sha256": catalog.range_hashes,
        "days": days,
        "interpretation": (
            "Listing/transfer sizing only. Complete title retrieval, stable relevance, "
            "release semantics and BigQuery scan bytes remain unverified."
        ),
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps({"output": str(args.output), "requests": catalog.calls, "days": days}, indent=2)
    )


if __name__ == "__main__":
    main()

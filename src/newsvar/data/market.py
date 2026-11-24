"""Bounded FRED/Cboe CSV parsing and outcome-blind XNYS coverage audit."""

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from newsvar.data.calendar import CalendarSnapshot

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 100_000
MARKET_AVAILABILITY_BASIS = "historical_prior_session_assumption"


class MarketSourceError(ValueError):
    """A retained market source failed schema/integrity/date/value checks."""


@dataclass(frozen=True)
class MarketSource:
    series_id: str
    values: dict[date, float]
    placeholders: tuple[date, ...]
    source_rows: int
    raw_sha256: str
    raw_relative_path: str
    retrieved_at_utc: str
    availability_basis: str = MARKET_AVAILABILITY_BASIS

    def value_at(self, session: date) -> float | None:
        return self.values.get(session)


@dataclass(frozen=True)
class MarketCoverage:
    calendar_id: str
    requested_start: date
    requested_end: date
    origin_sessions: int
    sp500_session_values: int
    vix_session_values: int
    missing_sp500_sessions: tuple[date, ...]
    missing_vix_on_sp500_sessions: tuple[date, ...]
    sp500_non_session_dates: tuple[date, ...]
    vix_non_session_dates: tuple[date, ...]
    fred_placeholders_in_range: tuple[date, ...]
    fred_outside_grid_values: int
    vix_outside_grid_values: int
    sp500_by_year: dict[int, int]

    def report(self, sp500: MarketSource, vix: MarketSource) -> dict[str, object]:
        return {
            "schema_version": "market_coverage_v1",
            "calendar_id": self.calendar_id,
            "requested_interval": [
                self.requested_start.isoformat(),
                self.requested_end.isoformat(),
            ],
            "origin_sessions": self.origin_sessions,
            "sp500_session_values": self.sp500_session_values,
            "vix_session_values": self.vix_session_values,
            "missing_sp500_sessions": [d.isoformat() for d in self.missing_sp500_sessions],
            "missing_vix_on_sp500_sessions": [
                d.isoformat() for d in self.missing_vix_on_sp500_sessions
            ],
            "sp500_non_session_dates": [d.isoformat() for d in self.sp500_non_session_dates],
            "vix_non_session_dates": [d.isoformat() for d in self.vix_non_session_dates],
            "fred_placeholders_in_range": [d.isoformat() for d in self.fred_placeholders_in_range],
            "fred_outside_grid_values": self.fred_outside_grid_values,
            "vix_outside_grid_values": self.vix_outside_grid_values,
            "sp500_by_year": {str(year): count for year, count in self.sp500_by_year.items()},
            "source_lineage": {
                "fred": {
                    "sha256": sp500.raw_sha256,
                    "path": sp500.raw_relative_path,
                    "retrieved_at_utc": sp500.retrieved_at_utc,
                    "source_rows": sp500.source_rows,
                    "availability_basis": sp500.availability_basis,
                },
                "cboe": {
                    "sha256": vix.raw_sha256,
                    "path": vix.raw_relative_path,
                    "retrieved_at_utc": vix.retrieved_at_utc,
                    "source_rows": vix.source_rows,
                    "availability_basis": vix.availability_basis,
                },
            },
            "scope": "Source-date/value validity and calendar coverage only; no return EDA.",
        }


def _validate_retrieved_at(value: str) -> None:
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MarketSourceError("Invalid source retrieval timestamp.") from exc
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise MarketSourceError("Source retrieval timestamp must be UTC-aware.")


def _hash_file(path: Path, expected_sha256: str) -> str:
    if not path.is_file() or path.stat().st_size > MAX_CSV_BYTES:
        raise MarketSourceError("Source CSV missing or larger than bounded importer cap.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected_sha256:
        raise MarketSourceError("Retained source SHA-256 mismatch.")
    return digest


def _parse_value(raw: str, *, allow_placeholder: bool) -> float | None:
    text = raw.strip()
    if text in ("", ".") and allow_placeholder:
        return None
    try:
        result = float(text)
    except ValueError as exc:
        raise MarketSourceError("Invalid market source value.") from exc
    if not math.isfinite(result) or result <= 0:
        raise MarketSourceError("Market source value must be positive and finite.")
    return result


def parse_market_csv(
    path: Path,
    *,
    series_id: str,
    expected_sha256: str,
    raw_relative_path: str,
    retrieved_at_utc: str,
) -> MarketSource:
    """Parse one audited source schema; no index/VIX substitution or return EDA."""
    if series_id not in ("SP500", "VIX"):
        raise MarketSourceError("Only FRED SP500 and Cboe VIX schemas are admitted here.")
    _validate_retrieved_at(retrieved_at_utc)
    digest = _hash_file(path, expected_sha256)
    values: dict[date, float] = {}
    placeholders: list[date] = []
    seen: set[date] = set()
    count = 0
    expected_columns = (
        ["observation_date", "SP500"]
        if series_id == "SP500"
        else ["DATE", "OPEN", "HIGH", "LOW", "CLOSE"]
    )
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_columns:
            raise MarketSourceError("CSV schema changed; inspect source before accepting it.")
        for row in reader:
            count += 1
            if count > MAX_ROWS:
                raise MarketSourceError("Source row count exceeds bounded importer cap.")
            if None in row or any(value is None for value in row.values()):
                raise MarketSourceError("Malformed CSV row or unexpected number of columns.")
            try:
                session = (
                    date.fromisoformat(row["observation_date"])
                    if series_id == "SP500"
                    else datetime.strptime(row["DATE"], "%m/%d/%Y").date()
                )
            except ValueError as exc:
                raise MarketSourceError("Invalid source observation date.") from exc
            if session in seen:
                raise MarketSourceError(f"Duplicate source date: {session.isoformat()}")
            seen.add(session)
            result = _parse_value(
                row["SP500"] if series_id == "SP500" else row["CLOSE"],
                allow_placeholder=series_id == "SP500",
            )
            if result is None:
                placeholders.append(session)
            else:
                values[session] = result
    return MarketSource(
        series_id=series_id,
        values=values,
        placeholders=tuple(sorted(placeholders)),
        source_rows=count,
        raw_sha256=digest,
        raw_relative_path=raw_relative_path,
        retrieved_at_utc=retrieved_at_utc,
    )


def retained_market_sources(
    project_root: Path, audit_path: Path
) -> tuple[MarketSource, MarketSource]:
    """Use the unchanged retained-source manifest; never refresh public URLs here."""
    try:
        root = project_root.resolve(strict=True)
        report = json.loads(audit_path.read_text(encoding="utf-8"))
        snapshots = {item["name"]: item for item in report["snapshots"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MarketSourceError("Retained source manifest is missing or malformed.") from exc
    result: list[MarketSource] = []
    for name, series_id in (("fred_sp500.csv", "SP500"), ("cboe_vix.csv", "VIX")):
        try:
            item = snapshots[name]
            relative_path = Path(item["path"])
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise MarketSourceError("Source manifest path leaves project root.")
            source_path = (root / relative_path).resolve(strict=True)
            if not source_path.is_relative_to(root):
                raise MarketSourceError("Source manifest path resolved outside project root.")
            if source_path.stat().st_size != item["bytes"]:
                raise MarketSourceError("Source byte count disagrees with retained audit.")
        except (OSError, KeyError, TypeError) as exc:
            raise MarketSourceError("Retained source entry is missing or malformed.") from exc
        source = parse_market_csv(
            source_path,
            series_id=series_id,
            expected_sha256=item["sha256"],
            raw_relative_path=item["path"],
            retrieved_at_utc=report["retrieved_at_utc"],
        )
        try:
            if source.source_rows != item["audit"]["rows"]:
                raise MarketSourceError("Parsed source row count disagrees with retained audit.")
            if len(source.values) != item["audit"]["valid_values"]:
                raise MarketSourceError("Valid source count disagrees with retained audit.")
        except (KeyError, TypeError) as exc:
            raise MarketSourceError("Retained source counts are missing or malformed.") from exc
        result.append(source)
    return result[0], result[1]


def market_coverage(
    snapshot: "CalendarSnapshot", sp500: MarketSource, vix: MarketSource
) -> MarketCoverage:
    """Classify source-date coverage; no returns or outcome relationships are computed."""
    if sp500.series_id != "SP500" or vix.series_id != "VIX":
        raise MarketSourceError("Market series IDs disagree with target/control roles.")
    sessions = {origin.session for origin in snapshot.origins}
    start, end = snapshot.requested_start, snapshot.requested_end
    sp_in = {d for d in sp500.values if start <= d <= end}
    vix_in = {d for d in vix.values if start <= d <= end}
    sp_session = sessions & sp_in
    vix_session = sessions & vix_in
    years: dict[int, int] = {}
    for day in sp_session:
        years[day.year] = years.get(day.year, 0) + 1
    return MarketCoverage(
        calendar_id=snapshot.calendar_id,
        requested_start=start,
        requested_end=end,
        origin_sessions=len(sessions),
        sp500_session_values=len(sp_session),
        vix_session_values=len(vix_session),
        missing_sp500_sessions=tuple(sorted(sessions - sp_session)),
        missing_vix_on_sp500_sessions=tuple(sorted(sp_session - vix_session)),
        sp500_non_session_dates=tuple(sorted(sp_in - sessions)),
        vix_non_session_dates=tuple(sorted(vix_in - sessions)),
        fred_placeholders_in_range=tuple(d for d in sp500.placeholders if start <= d <= end),
        fred_outside_grid_values=len(sp500.values) - len(sp_in),
        vix_outside_grid_values=len(vix.values) - len(vix_in),
        sp500_by_year=dict(sorted(years.items())),
    )

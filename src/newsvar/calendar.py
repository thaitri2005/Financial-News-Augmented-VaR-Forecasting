"""Versioned XNYS session origins and immutable UTC schedule snapshots."""

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

from newsvar.provenance import IntegrityError, canonical_json, sha256

PROFILE_ID = "preclose_v1"
MARKET_TIMEZONE = "America/New_York"


def _utc(timestamp: object) -> datetime:
    """Convert a pandas Timestamp or aware datetime without a fixed NY offset."""
    if not hasattr(timestamp, "to_pydatetime"):
        if not isinstance(timestamp, datetime):
            raise TypeError("Exchange schedule timestamp must be a datetime.")
        result = timestamp
    else:
        result = timestamp.to_pydatetime()
    if result.tzinfo is None:
        raise ValueError("Exchange schedule timestamp must be timezone-aware.")
    return result.astimezone(UTC)


def _parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise IntegrityError("Calendar timestamp must include UTC offset.")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class ForecastOrigin:
    session: date
    previous_session: date
    next_session: date
    open_utc: datetime
    close_utc: datetime
    previous_cutoff_utc: datetime
    cutoff_utc: datetime
    issue_deadline_utc: datetime
    next_close_utc: datetime

    def __post_init__(self) -> None:
        if not self.previous_session < self.session < self.next_session:
            raise ValueError("Forecast origin requires adjacent ordered exchange sessions.")
        if not (
            self.previous_cutoff_utc
            < self.open_utc
            < self.cutoff_utc
            < self.issue_deadline_utc
            < self.close_utc
            < self.next_close_utc
        ):
            raise ValueError("Forecast origin times violate the pre-close/target contract.")
        for timestamp in (
            self.open_utc,
            self.close_utc,
            self.previous_cutoff_utc,
            self.cutoff_utc,
            self.issue_deadline_utc,
            self.next_close_utc,
        ):
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError("Forecast origin timestamps must be UTC-aware.")

    @property
    def news_window_hours(self) -> float:
        return (self.cutoff_utc - self.previous_cutoff_utc).total_seconds() / 3600

    @property
    def market_last_session(self) -> date:
        return self.previous_session

    @property
    def target_start_utc(self) -> datetime:
        return self.close_utc

    @property
    def target_end_utc(self) -> datetime:
        return self.next_close_utc

    def includes_news_at(self, available_at: datetime) -> bool:
        if available_at.tzinfo is None:
            raise ValueError("News availability must be timezone-aware.")
        instant = available_at.astimezone(UTC)
        return self.previous_cutoff_utc < instant <= self.cutoff_utc

    def to_record(self) -> dict[str, str]:
        return {
            "session": self.session.isoformat(),
            "previous_session": self.previous_session.isoformat(),
            "next_session": self.next_session.isoformat(),
            "open_utc": self.open_utc.isoformat(),
            "close_utc": self.close_utc.isoformat(),
            "previous_cutoff_utc": self.previous_cutoff_utc.isoformat(),
            "cutoff_utc": self.cutoff_utc.isoformat(),
            "issue_deadline_utc": self.issue_deadline_utc.isoformat(),
            "next_close_utc": self.next_close_utc.isoformat(),
        }

    @classmethod
    def from_record(cls, record: dict[str, str]) -> "ForecastOrigin":
        return cls(
            session=date.fromisoformat(record["session"]),
            previous_session=date.fromisoformat(record["previous_session"]),
            next_session=date.fromisoformat(record["next_session"]),
            open_utc=_parse_utc(record["open_utc"]),
            close_utc=_parse_utc(record["close_utc"]),
            previous_cutoff_utc=_parse_utc(record["previous_cutoff_utc"]),
            cutoff_utc=_parse_utc(record["cutoff_utc"]),
            issue_deadline_utc=_parse_utc(record["issue_deadline_utc"]),
            next_close_utc=_parse_utc(record["next_close_utc"]),
        )


@dataclass(frozen=True)
class CalendarSnapshot:
    requested_start: date
    requested_end: date
    calendar_package_version: str
    tzdata_version: str
    cutoff_minutes_before_close: int
    issue_minutes_before_close: int
    origins: tuple[ForecastOrigin, ...]
    calendar_id: str

    def body(self) -> dict[str, object]:
        return {
            "schema_version": "xnys_preclose_v1",
            "profile_id": PROFILE_ID,
            "calendar": "XNYS",
            "market_timezone": MARKET_TIMEZONE,
            "requested_start": self.requested_start.isoformat(),
            "requested_end": self.requested_end.isoformat(),
            "calendar_package_version": self.calendar_package_version,
            "tzdata_version": self.tzdata_version,
            "cutoff_minutes_before_close": self.cutoff_minutes_before_close,
            "issue_minutes_before_close": self.issue_minutes_before_close,
            "origins": [origin.to_record() for origin in self.origins],
        }

    def record(self) -> dict[str, object]:
        return {"calendar_id": self.calendar_id, **self.body()}


def build_xnys_snapshot(
    start: date,
    end: date,
    *,
    cutoff_minutes_before_close: int = 30,
    issue_minutes_before_close: int = 15,
) -> CalendarSnapshot:
    import exchange_calendars as xcals

    if start > end:
        raise ValueError("Requested calendar start is after end.")
    if not 0 < issue_minutes_before_close < cutoff_minutes_before_close:
        raise ValueError("Cutoff must precede issue deadline, which precedes close.")
    calendar = xcals.get_calendar("XNYS")
    first_covered, last_covered = calendar.first_session.date(), calendar.last_session.date()
    if not first_covered < start <= end < last_covered:
        raise ValueError("XNYS coverage needs previous/next edge sessions.")
    requested = calendar.sessions_in_range(start.isoformat(), end.isoformat())
    if len(requested) == 0:
        raise ValueError("Requested interval contains no XNYS sessions.")
    rows: list[ForecastOrigin] = []
    for label in requested:
        session = label.date()
        previous_label = calendar.previous_session(label)
        next_label = calendar.next_session(label)
        close = _utc(calendar.session_close(label))
        previous_close = _utc(calendar.session_close(previous_label))
        next_close = _utc(calendar.session_close(next_label))
        cutoff = close - timedelta(minutes=cutoff_minutes_before_close)
        rows.append(
            ForecastOrigin(
                session=session,
                previous_session=previous_label.date(),
                next_session=next_label.date(),
                open_utc=_utc(calendar.session_open(label)),
                close_utc=close,
                previous_cutoff_utc=previous_close - timedelta(minutes=cutoff_minutes_before_close),
                cutoff_utc=cutoff,
                issue_deadline_utc=close - timedelta(minutes=issue_minutes_before_close),
                next_close_utc=next_close,
            )
        )
    unversioned = CalendarSnapshot(
        requested_start=start,
        requested_end=end,
        calendar_package_version=version("exchange_calendars"),
        tzdata_version=version("tzdata"),
        cutoff_minutes_before_close=cutoff_minutes_before_close,
        issue_minutes_before_close=issue_minutes_before_close,
        origins=tuple(rows),
        calendar_id="",
    )
    return replace(unversioned, calendar_id=sha256(canonical_json(unversioned.body())))


def write_snapshot(snapshot: CalendarSnapshot, directory: Path) -> Path:
    """Publish a small immutable schedule file after verifying its content ID."""
    payload = canonical_json(snapshot.record()) + b"\n"
    if sha256(canonical_json(snapshot.body())) != snapshot.calendar_id:
        raise IntegrityError("Calendar body does not match its identity.")
    directory.mkdir(parents=True, exist_ok=True)
    root = directory.resolve(strict=True)
    target = root / f"{snapshot.calendar_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise IntegrityError("Existing calendar file differs from matching identity.")
        return target
    staged = root / f".{snapshot.calendar_id}.{uuid.uuid4().hex}.tmp"
    with staged.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, target)
    return target


def load_snapshot(path: Path) -> CalendarSnapshot:
    """Validate a saved calendar's identity and temporal contracts on read."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        calendar_id = record.pop("calendar_id")
        if path.stem != calendar_id or sha256(canonical_json(record)) != calendar_id:
            raise IntegrityError("Calendar file/name/body hash mismatch.")
        if (
            record["schema_version"] != "xnys_preclose_v1"
            or record["profile_id"] != PROFILE_ID
            or record["calendar"] != "XNYS"
            or record["market_timezone"] != MARKET_TIMEZONE
        ):
            raise IntegrityError("Unsupported calendar profile/schema.")
        origins = tuple(ForecastOrigin.from_record(item) for item in record["origins"])
        cutoff_minutes = record["cutoff_minutes_before_close"]
        issue_minutes = record["issue_minutes_before_close"]
        if (
            type(cutoff_minutes) is not int
            or type(issue_minutes) is not int
            or not 0 < issue_minutes < cutoff_minutes
        ):
            raise IntegrityError("Invalid saved cutoff/issue margins.")
        if not origins or any(
            origin.cutoff_utc != origin.close_utc - timedelta(minutes=cutoff_minutes)
            or origin.issue_deadline_utc != origin.close_utc - timedelta(minutes=issue_minutes)
            for origin in origins
        ):
            raise IntegrityError("Saved origin timing disagrees with its profile margins.")
        if any(
            a.next_session != b.session
            or b.previous_session != a.session
            or b.previous_cutoff_utc != a.cutoff_utc
            or a.next_close_utc != b.close_utc
            for a, b in zip(origins[:-1], origins[1:], strict=True)
        ):
            raise IntegrityError("Saved origin grid has a session gap.")
        start = date.fromisoformat(record["requested_start"])
        end = date.fromisoformat(record["requested_end"])
        if not start <= origins[0].session <= origins[-1].session <= end:
            raise IntegrityError("Saved origins are outside requested bounds.")
        result = CalendarSnapshot(
            requested_start=start,
            requested_end=end,
            calendar_package_version=record["calendar_package_version"],
            tzdata_version=record["tzdata_version"],
            cutoff_minutes_before_close=cutoff_minutes,
            issue_minutes_before_close=issue_minutes,
            origins=origins,
            calendar_id=calendar_id,
        )
        if result.body() != record:
            raise IntegrityError("Calendar record has unrecognized/changed fields.")
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, IntegrityError):
            raise
        raise IntegrityError("Calendar snapshot is missing or invalid.") from exc

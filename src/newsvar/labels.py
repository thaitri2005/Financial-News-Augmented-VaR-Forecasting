"""Adjacent XNYS price labels kept apart from causal forecast features."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from newsvar.calendar import PROFILE_ID, CalendarSnapshot
from newsvar.ingestion.market import MarketSource
from newsvar.provenance import canonical_json, sha256

HISTORICAL_AVAILABILITY_BASIS = "historical_prior_session_assumption"


@dataclass(frozen=True)
class TargetLabel:
    label_version_id: str
    target_vintage_id: str
    calendar_id: str
    profile_id: str
    origin_session: date
    target_start_session: date
    target_end_session: date
    target_start_utc: datetime
    target_end_utc: datetime
    start_close: float
    end_close: float
    return_simple: float
    label_available_at_utc: datetime
    label_availability_basis: str
    source_raw_sha256: str
    source_raw_relative_path: str
    source_retrieved_at_utc: str
    market_manifest_id: str | None

    def eligible_for_refit(self, refit_cutoff: datetime) -> bool:
        """A trainer may read this future return only after both closes are available."""
        if refit_cutoff.tzinfo is None:
            raise ValueError("Refit cutoff must be timezone-aware.")
        return self.label_available_at_utc <= refit_cutoff.astimezone(UTC)


@dataclass(frozen=True)
class SkippedLabel:
    origin_session: date
    reason: str


@dataclass(frozen=True)
class LabelBuild:
    label_version_id: str
    target_vintage_id: str
    calendar_id: str
    source_raw_sha256: str
    source_raw_relative_path: str
    source_retrieved_at_utc: str
    labels: tuple[TargetLabel, ...]
    skipped: tuple[SkippedLabel, ...]

    def quality_report(self) -> dict[str, object]:
        """Date/reason admission report without any return values or scores."""
        return {
            "schema_version": "label_quality_v1",
            "label_version_id": self.label_version_id,
            "target_vintage_id": self.target_vintage_id,
            "calendar_id": self.calendar_id,
            "source_lineage": {
                "sha256": self.source_raw_sha256,
                "path": self.source_raw_relative_path,
                "retrieved_at_utc": self.source_retrieved_at_utc,
            },
            "labels_with_availability": len(self.labels),
            "skipped": [
                {"origin_session": item.origin_session.isoformat(), "reason": item.reason}
                for item in self.skipped
            ],
            "scope": "Label admission only; no return distribution or model evaluation.",
        }


def historical_prior_session_availability(
    snapshot: CalendarSnapshot, source: MarketSource
) -> dict[date, datetime]:
    """Conservative proxy: a close is usable at the next origin's cutoff."""
    if source.series_id != "SP500":
        raise ValueError("Historical target-price availability requires SP500.")
    cutoff_by_session = {origin.session: origin.cutoff_utc for origin in snapshot.origins}
    return {
        origin.session: cutoff_by_session[origin.next_session]
        for origin in snapshot.origins
        if origin.session in source.values and origin.next_session in cutoff_by_session
    }


def _validated_availability(
    available_at_by_session: Mapping[date, datetime],
) -> dict[date, datetime]:
    result: dict[date, datetime] = {}
    for session, timestamp in available_at_by_session.items():
        if not isinstance(session, date) or not isinstance(timestamp, datetime):
            raise ValueError("Price availability map requires date/datetime entries.")
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
            raise ValueError("Price availability must be UTC-aware.")
        result[session] = timestamp.astimezone(UTC)
    return result


def build_labels(
    snapshot: CalendarSnapshot,
    source: MarketSource,
    available_at_by_session: Mapping[date, datetime],
    *,
    availability_basis: str,
) -> LabelBuild:
    """Build only labels with adjacent real closes and explicit price availability."""
    if source.series_id != "SP500":
        raise ValueError("Target labels require FRED SP500, never a VIX/ETF substitute.")
    if not availability_basis or not availability_basis.isascii():
        raise ValueError("Label availability basis must be a nonempty ASCII policy ID.")
    available = _validated_availability(available_at_by_session)
    target_vintage_id = sha256(
        canonical_json(
            {
                "series_id": source.series_id,
                "raw_sha256": source.raw_sha256,
                "raw_relative_path": source.raw_relative_path,
                "retrieved_at_utc": source.retrieved_at_utc,
            }
        )
    )
    label_version_id = sha256(
        canonical_json(
            {
                "target_vintage_id": target_vintage_id,
                "calendar_id": snapshot.calendar_id,
                "profile_id": PROFILE_ID,
                "availability_basis": availability_basis,
                "price_available_at": {
                    session.isoformat(): available[session].isoformat()
                    for session in sorted(available)
                },
            }
        )
    )
    labels: list[TargetLabel] = []
    skipped: list[SkippedLabel] = []
    for origin in snapshot.origins:
        start = source.value_at(origin.session)
        end = source.value_at(origin.next_session)
        if start is None:
            skipped.append(SkippedLabel(origin.session, "missing_start_close"))
            continue
        if end is None:
            skipped.append(SkippedLabel(origin.session, "missing_end_close"))
            continue
        if not math.isfinite(start) or start <= 0:
            skipped.append(SkippedLabel(origin.session, "invalid_start_close"))
            continue
        if not math.isfinite(end) or end <= 0:
            skipped.append(SkippedLabel(origin.session, "invalid_end_close"))
            continue
        start_available = available.get(origin.session)
        end_available = available.get(origin.next_session)
        if start_available is None:
            skipped.append(SkippedLabel(origin.session, "unknown_start_availability"))
            continue
        if end_available is None:
            skipped.append(SkippedLabel(origin.session, "unknown_end_availability"))
            continue
        if start_available < origin.close_utc or end_available < origin.next_close_utc:
            skipped.append(SkippedLabel(origin.session, "availability_before_scheduled_close"))
            continue
        return_simple = end / start - 1.0
        if not math.isfinite(return_simple):
            skipped.append(SkippedLabel(origin.session, "invalid_return"))
            continue
        labels.append(
            TargetLabel(
                label_version_id=label_version_id,
                target_vintage_id=target_vintage_id,
                calendar_id=snapshot.calendar_id,
                profile_id=PROFILE_ID,
                origin_session=origin.session,
                target_start_session=origin.session,
                target_end_session=origin.next_session,
                target_start_utc=origin.close_utc,
                target_end_utc=origin.next_close_utc,
                start_close=start,
                end_close=end,
                return_simple=return_simple,
                label_available_at_utc=max(start_available, end_available),
                label_availability_basis=availability_basis,
                source_raw_sha256=source.raw_sha256,
                source_raw_relative_path=source.raw_relative_path,
                source_retrieved_at_utc=source.retrieved_at_utc,
                market_manifest_id=None,
            )
        )
    return LabelBuild(
        label_version_id=label_version_id,
        target_vintage_id=target_vintage_id,
        calendar_id=snapshot.calendar_id,
        source_raw_sha256=source.raw_sha256,
        source_raw_relative_path=source.raw_relative_path,
        source_retrieved_at_utc=source.retrieved_at_utc,
        labels=tuple(labels),
        skipped=tuple(skipped),
    )

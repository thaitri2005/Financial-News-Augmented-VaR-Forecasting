from datetime import UTC, date, datetime, timedelta

from newsvar.walkforward import AvailableLabel, build_attempts, eligible_labels


def _origin(day: int, month: int = 1) -> object:
    from newsvar.calendar import ForecastOrigin

    session = date(2021, month, day)
    return ForecastOrigin(
        session=session,
        previous_session=session - timedelta(days=1),
        next_session=session + timedelta(days=1),
        open_utc=datetime(2021, month, day, 14, tzinfo=UTC),
        close_utc=datetime(2021, month, day, 21, tzinfo=UTC),
        previous_cutoff_utc=datetime(2021, month, day - 1, 20, 30, tzinfo=UTC),
        cutoff_utc=datetime(2021, month, day, 20, 30, tzinfo=UTC),
        issue_deadline_utc=datetime(2021, month, day, 20, 45, tzinfo=UTC),
        next_close_utc=datetime(2021, month, day + 1, 21, tzinfo=UTC),
    )


def test_eligible_labels_excludes_current_and_not_yet_available_outcome() -> None:
    origin = _origin(5)
    labels = [
        AvailableLabel(date(2021, 1, 3), date(2021, 1, 4), -0.01, origin.cutoff_utc),
        AvailableLabel(date(2021, 1, 4), date(2021, 1, 5), -0.02, origin.cutoff_utc + timedelta(1)),
        AvailableLabel(date(2021, 1, 5), date(2021, 1, 6), -0.03, origin.cutoff_utc),
    ]

    assert [item.origin_session for item in eligible_labels(labels, origin=origin)] == [
        date(2021, 1, 3)
    ]


def test_walkforward_records_visible_warmup_failures_and_month_refits() -> None:
    origins = [_origin(4), _origin(5), _origin(4, 2)]
    labels = [
        AvailableLabel(
            date(2021, 1, 3),
            date(2021, 1, 4),
            -0.01,
            datetime(2021, 1, 3, 20, tzinfo=UTC),
        )
    ]

    attempts = build_attempts(origins, labels)

    assert len(attempts) == 6
    assert all(item.status == "insufficient_or_invalid_history" for item in attempts)
    assert [item.refit_month for item in attempts] == [True, True, False, False, True, True]

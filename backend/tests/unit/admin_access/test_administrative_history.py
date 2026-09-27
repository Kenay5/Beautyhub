"""Unit evidence for owner-only history queries and official date boundaries."""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from backend.app.application.admin_access.administrative_history import (
    AdministrativeHistoryEntry,
    AdministrativeHistoryFilters,
    QueryAdministrativeHistory,
)
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.audit.history_period import (
    ADMINISTRATIVE_HISTORY_TIMEZONE,
    history_period_utc_bounds,
)


NOW = datetime(2026, 9, 26, 16, tzinfo=timezone.utc)
ENTRY = AdministrativeHistoryEntry(
    event_id=31,
    actor_account_id=7,
    action="login",
    result="succeeded",
    occurred_at=NOW,
    target_reference=None,
)


class HistoryStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_events(self, *, filters, current_time):
        self.calls.append(("list", filters))
        return (ENTRY,)

    def list_actor_account_ids(self, *, current_time):
        self.calls.append(("accounts", current_time))
        return (7,)

    def get_event(self, *, event_id, current_time):
        self.calls.append(("detail", event_id))
        return ENTRY if event_id == ENTRY.event_id else None


class DenialRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[int | None, str, str]] = []

    def record(self, *, actor_account_id, action, result) -> None:
        self.events.append((actor_account_id, action, result))


def test_history_period_uses_local_midnight_and_inclusive_end_date() -> None:
    start, end = history_period_utc_bounds(
        start_date=date(2026, 9, 26), end_date=date(2026, 9, 26)
    )

    assert start == datetime.combine(
        date(2026, 9, 26), time.min, ADMINISTRATIVE_HISTORY_TIMEZONE
    ).astimezone(timezone.utc)
    assert end == datetime.combine(
        date(2026, 9, 27), time.min, ADMINISTRATIVE_HISTORY_TIMEZONE
    ).astimezone(timezone.utc)
    assert end - start == timedelta(days=1)


def test_history_period_accepts_open_ends_and_rejects_reversed_dates() -> None:
    assert history_period_utc_bounds(
        start_date=date(2026, 9, 26), end_date=None
    )[1] is None
    assert history_period_utc_bounds(
        start_date=None, end_date=date(2026, 9, 26)
    )[0] is None
    with pytest.raises(ValueError, match="start must not follow"):
        history_period_utc_bounds(
            start_date=date(2026, 9, 27), end_date=date(2026, 9, 26)
        )
    with pytest.raises(ValueError, match="out of range"):
        history_period_utc_bounds(start_date=None, end_date=date.max)


def test_history_filters_reject_invalid_account_or_naive_time() -> None:
    with pytest.raises(ValueError, match="account filter"):
        AdministrativeHistoryFilters(account_id=0)
    with pytest.raises(ValueError, match="must be aware"):
        AdministrativeHistoryFilters(
            start_inclusive=datetime(2026, 9, 26, tzinfo=None)
        )


def test_owner_can_query_minimum_events_without_audit_side_effect() -> None:
    store = HistoryStore()
    denials = DenialRecorder()
    query = QueryAdministrativeHistory(
        store=store, clock=FixedClock(NOW), denial_recorder=denials
    )
    filters = AdministrativeHistoryFilters(account_id=7, action="login")

    events, account_ids = query.list_events(
        actor=AdministrativeActor(account_id=1, role="owner"), filters=filters
    )
    detail = query.get_event(
        actor=AdministrativeActor(account_id=1, role="owner"), event_id=ENTRY.event_id
    )

    assert events == (ENTRY,)
    assert account_ids == (7,)
    assert detail == ENTRY
    assert denials.events == []
    assert store.calls[0] == ("list", filters)
    assert store.calls[2] == ("detail", ENTRY.event_id)


@pytest.mark.parametrize("query_kind", ("list", "detail"))
def test_staff_cannot_query_history_and_records_only_minimum_denial(
    query_kind: str,
) -> None:
    store = HistoryStore()
    denials = DenialRecorder()
    query = QueryAdministrativeHistory(
        store=store, clock=FixedClock(NOW), denial_recorder=denials
    )
    actor = AdministrativeActor(account_id=8, role="staff")

    with pytest.raises(AdministrativeAuthorizationError):
        if query_kind == "list":
            query.list_events(actor=actor, filters=AdministrativeHistoryFilters())
        else:
            query.get_event(actor=actor, event_id=ENTRY.event_id)

    assert store.calls == []
    assert denials.events == [(8, "authorization_denied", "denied")]

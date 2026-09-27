"""PostgreSQL read adapter for owner-visible administrative history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, func, literal_column, select

from backend.app.application.admin_access.administrative_history import (
    AdministrativeHistoryEntry,
    AdministrativeHistoryFilters,
)
from backend.app.domain.audit.history_period import (
    ADMINISTRATIVE_HISTORY_TIMEZONE,
)
from backend.app.infrastructure.persistence.models import AdminAuditEvent


_TIMEZONE_NAME = ADMINISTRATIVE_HISTORY_TIMEZONE.key
_ONE_CALENDAR_YEAR = literal_column("INTERVAL '1 year'")
_EVENT_COLUMNS = (
    AdminAuditEvent.admin_audit_event_id,
    AdminAuditEvent.actor_account_id,
    AdminAuditEvent.action,
    AdminAuditEvent.result,
    AdminAuditEvent.occurred_at,
    AdminAuditEvent.target_reference,
)


class PostgresAdministrativeHistoryStore:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_events(
        self, *, filters: AdministrativeHistoryFilters, current_time: datetime
    ) -> tuple[AdministrativeHistoryEntry, ...]:
        statement = (
            select(*_EVENT_COLUMNS)
            .where(administrative_event_expiration_time() > current_time)
            .order_by(
                AdminAuditEvent.occurred_at.desc(),
                AdminAuditEvent.admin_audit_event_id.desc(),
            )
        )
        if filters.account_id is not None:
            statement = statement.where(
                AdminAuditEvent.actor_account_id == filters.account_id
            )
        if filters.action is not None:
            statement = statement.where(AdminAuditEvent.action == filters.action)
        if filters.start_inclusive is not None:
            statement = statement.where(
                AdminAuditEvent.occurred_at >= filters.start_inclusive
            )
        if filters.end_exclusive is not None:
            statement = statement.where(
                AdminAuditEvent.occurred_at < filters.end_exclusive
            )
        rows = self._connection.execute(statement).mappings().all()
        return tuple(_entry(row) for row in rows)

    def list_actor_account_ids(self, *, current_time: datetime) -> tuple[int, ...]:
        statement = (
            select(AdminAuditEvent.actor_account_id)
            .where(
                AdminAuditEvent.actor_account_id.is_not(None),
                administrative_event_expiration_time() > current_time,
            )
            .distinct()
            .order_by(AdminAuditEvent.actor_account_id)
        )
        return tuple(self._connection.execute(statement).scalars().all())

    def get_event(
        self, *, event_id: int, current_time: datetime
    ) -> AdministrativeHistoryEntry | None:
        statement = select(*_EVENT_COLUMNS).where(
            AdminAuditEvent.admin_audit_event_id == event_id,
            administrative_event_expiration_time() > current_time,
        )
        event = self._connection.execute(statement).mappings().one_or_none()
        return _entry(event) if event is not None else None


def administrative_event_expiration_time():
    """Translate local calendar-year retention into a timestamptz SQL expression."""

    local_event_time = func.timezone(_TIMEZONE_NAME, AdminAuditEvent.occurred_at)
    local_expiration = local_event_time + _ONE_CALENDAR_YEAR
    return func.timezone(_TIMEZONE_NAME, local_expiration)


def _entry(event: Mapping[str, Any]) -> AdministrativeHistoryEntry:
    return AdministrativeHistoryEntry(
        event_id=event["admin_audit_event_id"],
        actor_account_id=event["actor_account_id"],
        action=event["action"],
        result=event["result"],
        occurred_at=event["occurred_at"],
        target_reference=event["target_reference"],
    )

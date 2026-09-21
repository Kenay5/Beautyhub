"""PostgreSQL persistence for minimum administrative audit evidence."""

from __future__ import annotations

from sqlalchemy import Connection, insert

from backend.app.application.admin_access.audit import AdministrativeAuditStore
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditEvent
from backend.app.infrastructure.persistence.models import AdminAuditEvent


class PostgresAdministrativeAuditStore(AdministrativeAuditStore):
    """Append only the approved, non-private fields of an audit event."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def append(self, *, event: AdministrativeAuditEvent) -> None:
        """Persist one validated event in the caller's transaction."""

        self._connection.execute(
            insert(AdminAuditEvent).values(
                actor_account_id=event.actor_account_id,
                action=event.action,
                result=event.result,
                occurred_at=event.occurred_at,
                target_reference=event.target_reference,
            )
        )

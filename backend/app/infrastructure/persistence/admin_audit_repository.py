"""PostgreSQL persistence for minimum administrative audit evidence."""

from __future__ import annotations

from sqlalchemy import Connection, insert, update

from backend.app.application.admin_access.audit import AdministrativeAuditStore
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditEvent
from backend.app.domain.audit.retention import administrative_retention_deadline
from backend.app.infrastructure.persistence.models import (
    AdminAuditEvent,
    DeactivatedStaffIdentity,
)


class PostgresAdministrativeAuditStore(AdministrativeAuditStore):
    """Append only the approved, non-private fields of an audit event."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def append(self, *, event: AdministrativeAuditEvent) -> None:
        """Persist one validated event in the caller's transaction."""

        event_expiration = administrative_retention_deadline(event.occurred_at)
        self._connection.execute(
            insert(AdminAuditEvent).values(
                actor_account_id=event.actor_account_id,
                action=event.action,
                result=event.result,
                occurred_at=event.occurred_at,
                target_reference=event.target_reference,
            )
        )
        associated_account_ids = {event.actor_account_id}
        if event.target_reference is not None:
            target_kind, _, target_id = event.target_reference.partition(":")
            if target_kind == "admin_account":
                associated_account_ids.add(int(target_id))
        associated_account_ids.discard(None)
        if associated_account_ids:
            self._connection.execute(
                update(DeactivatedStaffIdentity)
                .where(
                    DeactivatedStaffIdentity.admin_account_id.in_(
                        associated_account_ids
                    ),
                    DeactivatedStaffIdentity.identifiable_until < event_expiration,
                )
                .values(identifiable_until=event_expiration)
            )

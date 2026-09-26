"""PostgreSQL invalidation after an administrative security change."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, update

from backend.app.application.admin_access.security_change_invalidation import (
    SecurityChangeInvalidationStore,
)
from backend.app.infrastructure.persistence.models import AdminSession
from backend.app.infrastructure.persistence.pending_security_state_repository import (
    PostgresPendingSecurityStateStore,
)


class PostgresSecurityChangeInvalidationStore(SecurityChangeInvalidationStore):
    """Invalidate sessions and temporary artifacts in the caller transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._pending_state = PostgresPendingSecurityStateStore(connection)

    def invalidate_after_security_change(
        self, *, account_id: int, current_time: datetime
    ) -> None:
        """Lock the account, discard pending state, then close every live session."""

        self._pending_state.discard_after_completed_security_change(
            account_id=account_id,
            current_time=current_time,
        )
        self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.admin_account_id == account_id,
                AdminSession.status == "active",
            )
            .values(status="invalidated", invalidated_at=current_time)
        )

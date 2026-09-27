"""PostgreSQL batches for event and deactivated-staff identity retention."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, func, select

from backend.app.application.admin_access.administrative_history_retention import (
    AdministrativeHistoryRetentionStore,
)
from backend.app.infrastructure.persistence.administrative_history_repository import (
    administrative_event_expiration_time,
)
from backend.app.infrastructure.persistence.deactivated_staff_retention_repository import (
    PostgresDeactivatedStaffRetentionStore,
)


AUDIT_EVENT_PURGE_BATCH_SIZE = 500


class PostgresAdministrativeHistoryRetentionStore(
    AdministrativeHistoryRetentionStore
):
    """Delete expired audit rows through the T085-authorized retention path."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._identity_store = PostgresDeactivatedStaffRetentionStore(connection)

    def purge_expired_batch(self, *, current_time: datetime) -> int:
        effective_current_time = self._connection.execute(
            select(func.least(current_time, func.clock_timestamp()))
        ).scalar_one()
        event_count = self._purge_expired_event_batch(
            current_time=effective_current_time
        )
        identity_count = self._identity_store.purge_expired_identity_batch(
            current_time=effective_current_time
        )
        return event_count + identity_count

    def next_expiration(self, *, current_time: datetime) -> datetime | None:
        event_expiration = self._connection.execute(
            select(func.min(administrative_event_expiration_time())).where(
                administrative_event_expiration_time() > current_time
            )
        ).scalar_one_or_none()
        identity_expiration = self._identity_store.next_identity_expiration(
            current_time=current_time
        )
        if event_expiration is None:
            return identity_expiration
        if identity_expiration is None:
            return event_expiration
        return min(event_expiration, identity_expiration)

    def _purge_expired_event_batch(self, *, current_time: datetime) -> int:
        return self._connection.execute(
            select(
                func.purge_expired_administrative_history_event_batch(
                    current_time, AUDIT_EVENT_PURGE_BATCH_SIZE
                )
            )
        ).scalar_one()

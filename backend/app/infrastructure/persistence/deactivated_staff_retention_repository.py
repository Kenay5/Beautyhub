"""PostgreSQL retention operations for deactivated staff identity archives."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, delete, func, select

from backend.app.application.admin_access.deactivated_staff_retention import (
    DeactivatedStaffRetentionStore,
)
from backend.app.infrastructure.persistence.models import DeactivatedStaffIdentity


IDENTITY_PURGE_BATCH_SIZE = 500


class PostgresDeactivatedStaffRetentionStore(DeactivatedStaffRetentionStore):
    """Delete expired encrypted email archives while preserving account IDs."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def purge_expired_identity_batch(self, *, current_time: datetime) -> int:
        due_ids = (
            select(DeactivatedStaffIdentity.admin_account_id)
            .where(DeactivatedStaffIdentity.identifiable_until <= current_time)
            .order_by(
                DeactivatedStaffIdentity.identifiable_until,
                DeactivatedStaffIdentity.admin_account_id,
            )
            .limit(IDENTITY_PURGE_BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .cte("expired_staff_identity_batch")
        )
        result = self._connection.execute(
            delete(DeactivatedStaffIdentity)
            .where(DeactivatedStaffIdentity.admin_account_id == due_ids.c.admin_account_id)
            .returning(DeactivatedStaffIdentity.admin_account_id)
        )
        return len(result.fetchall())

    def next_identity_expiration(self, *, current_time: datetime) -> datetime | None:
        return self._connection.execute(
            select(func.min(DeactivatedStaffIdentity.identifiable_until)).where(
                DeactivatedStaffIdentity.identifiable_until > current_time
            )
        ).scalar_one_or_none()

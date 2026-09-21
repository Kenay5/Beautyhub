"""PostgreSQL writer for immediate notification delivery results."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine, update

from backend.app.domain.notification_delivery import (
    NotificationDeliveryStatus,
    PENDING_DELIVERY_STATUS,
)
from backend.app.infrastructure.persistence.models import NotificationDelivery


class PostgresNotificationDeliveryResultWriter:
    """Persist one immediate result without touching its appointment."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record_result(
        self,
        *,
        delivery_id: int,
        status: NotificationDeliveryStatus,
        status_changed_at: datetime,
        sanitized_error: str | None,
    ) -> None:
        """Transition exactly one still-pending delivery in its own transaction."""

        with self._engine.begin() as connection:
            result = connection.execute(
                update(NotificationDelivery)
                .where(
                    NotificationDelivery.notification_delivery_id == delivery_id,
                    NotificationDelivery.status == PENDING_DELIVERY_STATUS,
                )
                .values(
                    status=status,
                    status_changed_at=status_changed_at,
                    sanitized_error=sanitized_error,
                    updated_at=status_changed_at,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("notification delivery result could not be recorded.")

"""PostgreSQL persistence for an auditable failed-delivery retry intent."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, insert, select
from sqlalchemy.engine import Connection

from backend.app.application.prepare_notification_retry import (
    CurrentAppointmentContact,
    LockedFailedNotificationDelivery,
    NotificationRetryRepository,
)
from backend.app.application.transactional_notifications import NotificationChannel
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.infrastructure.persistence.models import Appointment, NotificationDelivery


class PostgresNotificationRetryRepository:
    """Record one retry delivery using a caller-owned PostgreSQL transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_delivery(
        self, delivery_id: int
    ) -> LockedFailedNotificationDelivery | None:
        row = self._connection.execute(
            select(
                NotificationDelivery.notification_delivery_id,
                NotificationDelivery.appointment_id,
                NotificationDelivery.event,
                NotificationDelivery.channel,
                NotificationDelivery.status,
                NotificationDelivery.appointment_reminder_id,
            )
            .where(NotificationDelivery.notification_delivery_id == delivery_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return LockedFailedNotificationDelivery(
            delivery_id=row.notification_delivery_id,
            appointment_id=row.appointment_id,
            event=row.event,
            channel=row.channel,
            status=row.status,
            appointment_reminder_id=row.appointment_reminder_id,
        )

    def lock_current_appointment_contact(
        self, appointment_id: int
    ) -> CurrentAppointmentContact | None:
        row = self._connection.execute(
            select(Appointment.appointment_id, Appointment.email, Appointment.phone)
            .where(Appointment.appointment_id == appointment_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return CurrentAppointmentContact(
            appointment_id=row.appointment_id,
            email=row.email,
            phone=row.phone,
        )

    def create_pending_retry(
        self,
        *,
        appointment_id: int,
        event: str,
        channel: NotificationChannel,
        previous_delivery_id: int,
        status_changed_at: datetime,
    ) -> int:
        return self._connection.execute(
            insert(NotificationDelivery)
            .values(
                appointment_id=appointment_id,
                event=event,
                channel=channel,
                status=PENDING_DELIVERY_STATUS,
                status_changed_at=status_changed_at,
                appointment_reminder_id=None,
                previous_delivery_id=previous_delivery_id,
                sanitized_error=None,
                updated_at=status_changed_at,
            )
            .returning(NotificationDelivery.notification_delivery_id)
        ).scalar_one()


class PostgresNotificationRetryUnitOfWork:
    """Own the short transaction that records one retry intent."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[NotificationRetryRepository]:
        with self._engine.begin() as connection:
            yield PostgresNotificationRetryRepository(connection)

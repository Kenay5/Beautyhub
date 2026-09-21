"""PostgreSQL persistence for bounded manual appointment-reminder retries."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, func, insert, select, text
from sqlalchemy.engine import Connection

from backend.app.application.retry_failed_appointment_reminder import (
    AppointmentReminderRetryRepository,
    LockedReminderRetry,
)
from backend.app.application.transactional_notifications import NotificationChannel
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
)


class PostgresAppointmentReminderRetryRepository:
    """Lock a reminder-channel retry chain and append one retry safely."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_retry_context(
        self,
        *,
        delivery_id: int,
    ) -> LockedReminderRetry | None:
        lineage = _read_lineage(self._connection, delivery_id)
        if not lineage:
            return None
        root = lineage[-1]
        reminder_id = root["appointment_reminder_id"]
        if reminder_id is None:
            return None

        appointment = self._connection.execute(
            select(
                Appointment.appointment_id,
                Appointment.status,
                Appointment.scheduled_start,
                Appointment.email,
                Appointment.phone,
                Appointment.service_snapshot_name,
                Appointment.service_snapshot_duration_minutes,
                Appointment.service_snapshot_price,
                Appointment.branch,
            )
            .where(Appointment.appointment_id == root["appointment_id"])
            .with_for_update()
        ).mappings().one_or_none()
        if appointment is None:
            return None

        reminder = self._connection.execute(
            select(
                AppointmentReminder.appointment_reminder_id,
                AppointmentReminder.appointment_id,
                AppointmentReminder.appointment_scheduled_start,
                AppointmentReminder.status,
            )
            .where(
                AppointmentReminder.appointment_reminder_id == reminder_id,
                AppointmentReminder.appointment_id == appointment["appointment_id"],
            )
            .with_for_update()
        ).mappings().one_or_none()
        if reminder is None:
            return None

        delivery = self._connection.execute(
            select(
                NotificationDelivery.notification_delivery_id,
                NotificationDelivery.appointment_id,
                NotificationDelivery.event,
                NotificationDelivery.channel,
                NotificationDelivery.status,
            )
            .where(NotificationDelivery.notification_delivery_id == delivery_id)
            .with_for_update()
        ).mappings().one_or_none()
        if delivery is None:
            return None

        lineage = _read_lineage(self._connection, delivery_id)
        if not lineage or lineage[-1]["appointment_reminder_id"] != reminder_id:
            return None
        if any(row["appointment_id"] != appointment["appointment_id"] for row in lineage):
            return None
        retry_rows = lineage[:-1]
        return LockedReminderRetry(
            delivery_id=delivery["notification_delivery_id"],
            appointment_id=appointment["appointment_id"],
            reminder_id=reminder["appointment_reminder_id"],
            event=delivery["event"],
            channel=delivery["channel"],
            delivery_status=delivery["status"],
            appointment_status=appointment["status"],
            appointment_scheduled_start=appointment["scheduled_start"],
            reminder_scheduled_start=reminder["appointment_scheduled_start"],
            reminder_status=reminder["status"],
            retry_count=len(retry_rows),
            last_retry_started_at=(
                retry_rows[0]["created_at"] if retry_rows else None
            ),
            has_later_attempt=self._connection.execute(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(NotificationDelivery.previous_delivery_id == delivery_id)
            ).scalar_one()
            > 0,
            email=appointment["email"],
            phone=appointment["phone"],
            service_name=appointment["service_snapshot_name"],
            duration_minutes=appointment["service_snapshot_duration_minutes"],
            price=appointment["service_snapshot_price"],
            branch=appointment["branch"],
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
                created_at=status_changed_at,
                updated_at=status_changed_at,
            )
            .returning(NotificationDelivery.notification_delivery_id)
        ).scalar_one()


class PostgresAppointmentReminderRetryUnitOfWork:
    """Own the atomic transaction that records one manual retry intent."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[AppointmentReminderRetryRepository]:
        with self._engine.begin() as connection:
            yield PostgresAppointmentReminderRetryRepository(connection)


def _read_lineage(connection: Connection, delivery_id: int):
    statement = text(
        """
        WITH RECURSIVE delivery_lineage AS (
            SELECT notification_delivery_id, appointment_id,
                   appointment_reminder_id, previous_delivery_id, created_at, 0 AS depth
            FROM notification_deliveries
            WHERE notification_delivery_id = :delivery_id
            UNION ALL
            SELECT parent.notification_delivery_id, parent.appointment_id,
                   parent.appointment_reminder_id, parent.previous_delivery_id,
                   parent.created_at, child.depth + 1
            FROM notification_deliveries AS parent
            JOIN delivery_lineage AS child
              ON child.previous_delivery_id = parent.notification_delivery_id
        )
        SELECT notification_delivery_id, appointment_id, appointment_reminder_id,
               previous_delivery_id, created_at, depth
        FROM delivery_lineage
        ORDER BY depth ASC
        """
    )
    return list(connection.execute(statement, {"delivery_id": delivery_id}).mappings())

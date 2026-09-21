"""PostgreSQL registered-start transaction for claimed reminders."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import Connection

from backend.app.application.process_claimed_appointment_reminder import (
    ClaimedAppointmentReminderRepository,
    LockedClaimedReminder,
    ReminderDeliveryIntent,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.appointment_reminder import CLAIMED_REMINDER_STATUS
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
)


APPOINTMENT_REMINDER_EVENT = "appointment_reminder"


class PostgresClaimedAppointmentReminderRepository:
    """Persist reminder start while holding appointment and reminder locks."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_reminder_and_appointment(
        self,
        *,
        reminder_id: int,
    ) -> LockedClaimedReminder | None:
        appointment_id = self._connection.execute(
            select(AppointmentReminder.appointment_id).where(
                AppointmentReminder.appointment_reminder_id == reminder_id
            )
        ).scalar_one_or_none()
        if appointment_id is None:
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
            .where(Appointment.appointment_id == appointment_id)
            .with_for_update()
        ).one_or_none()
        if appointment is None:
            return None

        reminder = self._connection.execute(
            select(
                AppointmentReminder.appointment_reminder_id,
                AppointmentReminder.status,
                AppointmentReminder.claimed_at,
                AppointmentReminder.appointment_scheduled_start,
            )
            .where(
                AppointmentReminder.appointment_reminder_id == reminder_id,
                AppointmentReminder.appointment_id == appointment_id,
            )
            .with_for_update()
        ).one_or_none()
        if reminder is None:
            return None

        return LockedClaimedReminder(
            reminder_id=reminder.appointment_reminder_id,
            appointment_id=appointment.appointment_id,
            reminder_status=reminder.status,
            reminder_claimed_at=reminder.claimed_at,
            reminder_scheduled_start=reminder.appointment_scheduled_start,
            appointment_status=appointment.status,
            appointment_scheduled_start=appointment.scheduled_start,
            email=appointment.email,
            phone=appointment.phone,
            service_name=appointment.service_snapshot_name,
            duration_minutes=appointment.service_snapshot_duration_minutes,
            price=appointment.service_snapshot_price,
            branch=appointment.branch,
        )

    def finish_claim(
        self,
        *,
        reminder_id: int,
        claimed_at: datetime,
        status: str,
        status_changed_at: datetime,
    ) -> bool:
        result = self._connection.execute(
            update(AppointmentReminder)
            .where(
                AppointmentReminder.appointment_reminder_id == reminder_id,
                AppointmentReminder.status == CLAIMED_REMINDER_STATUS,
                AppointmentReminder.claimed_at == claimed_at,
            )
            .values(
                status=status,
                status_changed_at=status_changed_at,
                claimed_at=None,
                claim_expires_at=None,
                updated_at=status_changed_at,
            )
        )
        return result.rowcount == 1

    def create_delivery_intents(
        self,
        *,
        appointment_id: int,
        reminder_id: int,
        status_changed_at: datetime,
    ) -> tuple[ReminderDeliveryIntent, ReminderDeliveryIntent]:
        rows = self._connection.execute(
            insert(NotificationDelivery)
            .values(
                [
                    _delivery_values(
                        appointment_id=appointment_id,
                        reminder_id=reminder_id,
                        channel=EMAIL_CHANNEL,
                        status_changed_at=status_changed_at,
                    ),
                    _delivery_values(
                        appointment_id=appointment_id,
                        reminder_id=reminder_id,
                        channel=WHATSAPP_CHANNEL,
                        status_changed_at=status_changed_at,
                    ),
                ]
            )
            .returning(
                NotificationDelivery.notification_delivery_id,
                NotificationDelivery.channel,
                NotificationDelivery.status,
            )
        ).all()
        deliveries = tuple(
            ReminderDeliveryIntent(
                delivery_id=row.notification_delivery_id,
                channel=row.channel,
                status=row.status,
            )
            for row in rows
        )
        if len(deliveries) != 2:
            raise RuntimeError("appointment reminder requires two deliveries.")
        return deliveries  # type: ignore[return-value]


class PostgresClaimedAppointmentReminderUnitOfWork:
    """Own the transaction that registers reminder processing start."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[ClaimedAppointmentReminderRepository]:
        with self._engine.begin() as connection:
            yield PostgresClaimedAppointmentReminderRepository(connection)


def _delivery_values(
    *,
    appointment_id: int,
    reminder_id: int,
    channel: str,
    status_changed_at: datetime,
) -> dict[str, object]:
    return {
        "appointment_id": appointment_id,
        "appointment_reminder_id": reminder_id,
        "event": APPOINTMENT_REMINDER_EVENT,
        "channel": channel,
        "status": PENDING_DELIVERY_STATUS,
        "status_changed_at": status_changed_at,
        "updated_at": status_changed_at,
    }

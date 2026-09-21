"""PostgreSQL transaction adapter for public appointment cancellation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import Connection

from backend.app.application.cancel_public_appointment import (
    LockedAppointmentForCancellation,
    PublicAppointmentCancellationRepository,
)
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.domain.appointment_reminder import (
    INVALIDATED_REMINDER_STATUS,
    PENDING_REMINDER_STATUSES,
)
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
)
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresScheduleRepository,
)


APPOINTMENT_CANCELLED_EVENT = "appointment_cancelled"


class PostgresPublicAppointmentCancellationRepository:
    """Persist one cancellation through a caller-owned connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._schedule_repository = PostgresScheduleRepository(connection)

    def lock_schedule(self) -> None:
        self._schedule_repository.lock_schedule()

    def lock_appointment_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> LockedAppointmentForCancellation | None:
        row = self._connection.execute(
            select(
                Appointment.appointment_id,
                Appointment.phone,
                Appointment.email,
                Appointment.service_snapshot_name,
                Appointment.service_snapshot_duration_minutes,
                Appointment.service_snapshot_price,
                Appointment.branch,
                Appointment.scheduled_start,
                Appointment.scheduled_end,
                Appointment.status,
            )
            .where(Appointment.private_code_digest == private_code_digest)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return LockedAppointmentForCancellation(
            appointment_id=row.appointment_id,
            phone=row.phone,
            email=row.email,
            service_snapshot_name=row.service_snapshot_name,
            service_snapshot_duration_minutes=row.service_snapshot_duration_minutes,
            service_snapshot_price=row.service_snapshot_price,
            branch=row.branch,
            scheduled_start=row.scheduled_start,
            scheduled_end=row.scheduled_end,
            status=row.status,
        )

    def cancel_appointment(
        self,
        *,
        appointment_id: int,
        reason: str | None,
        changed_at: datetime,
    ) -> bool:
        result = self._connection.execute(
            update(Appointment)
            .where(
                Appointment.appointment_id == appointment_id,
                Appointment.status == "scheduled",
            )
            .values(
                status="cancelled",
                cancellation_reason=reason,
                updated_at=changed_at,
            )
        )
        return result.rowcount == 1

    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[ChangeNotificationDelivery, ChangeNotificationDelivery]:
        rows = self._connection.execute(
            insert(NotificationDelivery)
            .values(
                [
                    _pending_delivery_values(
                        appointment_id, EMAIL_CHANNEL, status_changed_at
                    ),
                    _pending_delivery_values(
                        appointment_id, WHATSAPP_CHANNEL, status_changed_at
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
            ChangeNotificationDelivery(
                delivery_id=row.notification_delivery_id,
                channel=row.channel,
                status=row.status,
            )
            for row in rows
        )
        if len(deliveries) != 2:
            raise RuntimeError("appointment cancellation requires two deliveries.")
        return deliveries  # type: ignore[return-value]

    def invalidate_pending_reminders(
        self,
        *,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> None:
        self._connection.execute(
            update(AppointmentReminder)
            .where(
                AppointmentReminder.appointment_id == appointment_id,
                AppointmentReminder.status.in_(PENDING_REMINDER_STATUSES),
            )
            .values(
                status=INVALIDATED_REMINDER_STATUS,
                status_changed_at=status_changed_at,
                claimed_at=None,
                claim_expires_at=None,
                updated_at=status_changed_at,
            )
        )


class PostgresPublicAppointmentCancellationUnitOfWork:
    """Own the atomic PostgreSQL transaction for one public cancellation."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentCancellationRepository]:
        with self._engine.begin() as connection:
            yield PostgresPublicAppointmentCancellationRepository(connection)


def _pending_delivery_values(
    appointment_id: int,
    channel: str,
    status_changed_at: datetime,
) -> dict[str, object]:
    return {
        "appointment_id": appointment_id,
        "event": APPOINTMENT_CANCELLED_EVENT,
        "channel": channel,
        "status": PENDING_DELIVERY_STATUS,
        "status_changed_at": status_changed_at,
        "updated_at": status_changed_at,
    }

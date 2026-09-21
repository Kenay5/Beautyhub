"""PostgreSQL transaction adapter for public appointment reprogramming."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import Connection

from backend.app.application.reschedule_public_appointment import (
    LockedAppointmentForReschedule,
    LockedServiceForReschedule,
    PublicAppointmentRescheduleRepository,
)
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.domain.appointment import AppointmentServiceSnapshot
from backend.app.domain.appointment_reminder import (
    INVALIDATED_REMINDER_STATUS,
    PENDING_REMINDER_STATUSES,
    SCHEDULED_REMINDER_STATUS,
)
from backend.app.domain.schedule import ScheduledInterval, TimeInterval
from backend.app.domain.service import ServiceDraft
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
    NotificationDelivery,
    Service,
)


APPOINTMENT_MODIFIED_EVENT = "appointment_modified"
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresScheduleRepository,
)


class PostgresPublicAppointmentRescheduleRepository:
    """Persist one reprogramming through a caller-owned connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._schedule_repository = PostgresScheduleRepository(connection)

    def lock_schedule(self) -> None:
        self._schedule_repository.lock_schedule()

    def lock_appointment_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> LockedAppointmentForReschedule | None:
        row = self._connection.execute(
            select(
                Appointment.appointment_id,
                Appointment.phone,
                Appointment.email,
                Appointment.service_id,
                Appointment.service_snapshot_name,
                Appointment.service_snapshot_duration_minutes,
                Appointment.service_snapshot_price,
                Appointment.scheduled_start,
                Appointment.status,
            )
            .where(Appointment.private_code_digest == private_code_digest)
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return LockedAppointmentForReschedule(
            appointment_id=row.appointment_id,
            phone=row.phone,
            email=row.email,
            service_id=row.service_id,
            service_snapshot_name=row.service_snapshot_name,
            service_snapshot_duration_minutes=(
                row.service_snapshot_duration_minutes
            ),
            service_snapshot_price=row.service_snapshot_price,
            scheduled_start=row.scheduled_start,
            status=row.status,
        )

    def get_service_for_update(
        self,
        *,
        service_name: str,
    ) -> LockedServiceForReschedule | None:
        row = self._connection.execute(
            select(
                Service.service_id,
                Service.name,
                Service.description,
                Service.duration_minutes,
                Service.price,
                Service.is_active,
                Service.available_chiconcuac,
                Service.available_texcoco,
            )
            .where(Service.canonical_name == service_name.lower())
            .with_for_update()
        ).one_or_none()
        if row is None:
            return None
        return LockedServiceForReschedule(
            service_id=row.service_id,
            service=ServiceDraft(
                name=row.name,
                description=row.description,
                duration_minutes=row.duration_minutes,
                price=row.price,
                is_active=row.is_active,
                available_chiconcuac=row.available_chiconcuac,
                available_texcoco=row.available_texcoco,
            ),
        )

    def list_other_scheduled_intervals_for_update(
        self,
        *,
        excluding_appointment_id: int,
    ) -> tuple[ScheduledInterval, ...]:
        rows = self._connection.execute(
            select(
                Appointment.scheduled_start,
                Appointment.scheduled_end,
                Appointment.branch,
                Appointment.status,
            )
            .where(
                Appointment.status == "scheduled",
                Appointment.appointment_id != excluding_appointment_id,
            )
            .with_for_update()
        )
        return tuple(
            ScheduledInterval(
                interval=TimeInterval(row.scheduled_start, row.scheduled_end),
                branch=row.branch,
                status=row.status,
            )
            for row in rows
        )

    def list_applicable_blocks_for_update(
        self,
        branch: str,
    ) -> tuple[TimeInterval, ...]:
        return self._schedule_repository.list_applicable_blocks(branch, lock=True)

    def update_schedule(
        self,
        *,
        appointment_id: int,
        service_snapshot: AppointmentServiceSnapshot,
        branch: str,
        scheduled_start: datetime,
        scheduled_end: datetime,
        changed_at: datetime,
    ) -> bool:
        result = self._connection.execute(
            update(Appointment)
            .where(
                Appointment.appointment_id == appointment_id,
                Appointment.status == "scheduled",
            )
            .values(
                service_id=service_snapshot.service_id,
                service_snapshot_name=service_snapshot.name,
                service_snapshot_duration_minutes=(
                    service_snapshot.duration_minutes
                ),
                service_snapshot_price=service_snapshot.price,
                branch=branch,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_end,
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
            raise RuntimeError("appointment modification requires two deliveries.")
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

    def create_initial_reminder(
        self,
        *,
        appointment_id: int,
        appointment_scheduled_start: datetime,
        send_at: datetime,
        status_changed_at: datetime,
    ) -> None:
        self._connection.execute(
            insert(AppointmentReminder).values(
                appointment_id=appointment_id,
                appointment_scheduled_start=appointment_scheduled_start,
                send_at=send_at,
                status=SCHEDULED_REMINDER_STATUS,
                status_changed_at=status_changed_at,
                claimed_at=None,
                claim_expires_at=None,
            )
        )


class PostgresPublicAppointmentRescheduleUnitOfWork:
    """Own the atomic PostgreSQL transaction for one public reprogramming."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentRescheduleRepository]:
        with self._engine.begin() as connection:
            yield PostgresPublicAppointmentRescheduleRepository(connection)


def _pending_delivery_values(
    appointment_id: int,
    channel: str,
    status_changed_at: datetime,
) -> dict[str, object]:
    return {
        "appointment_id": appointment_id,
        "event": APPOINTMENT_MODIFIED_EVENT,
        "channel": channel,
        "status": PENDING_DELIVERY_STATUS,
        "status_changed_at": status_changed_at,
        "updated_at": status_changed_at,
    }

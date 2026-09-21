"""PostgreSQL claim adapter for durable appointment reminders."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import Engine, and_, or_, select, update
from sqlalchemy.engine import Connection

from backend.app.application.claim_due_appointment_reminder import (
    ClaimedDueReminder,
    DueAppointmentReminderClaimRepository,
)
from backend.app.domain.appointment_reminder import (
    CLAIMED_REMINDER_STATUS,
    OMITTED_REMINDER_STATUS,
    SCHEDULED_REMINDER_STATUS,
)
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AppointmentReminder,
)


class PostgresDueAppointmentReminderClaimRepository:
    """Claim one reminder using a caller-owned PostgreSQL transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def claim_next_due_reminder(
        self,
        *,
        claimed_at: datetime,
        claim_expires_at: datetime,
    ) -> ClaimedDueReminder | None:
        row = self._connection.execute(
            select(
                AppointmentReminder.appointment_reminder_id,
                AppointmentReminder.appointment_id,
                AppointmentReminder.appointment_scheduled_start,
            )
            .join(
                Appointment,
                Appointment.appointment_id == AppointmentReminder.appointment_id,
            )
            .where(
                AppointmentReminder.send_at <= claimed_at,
                Appointment.status == "scheduled",
                Appointment.scheduled_start
                == AppointmentReminder.appointment_scheduled_start,
                or_(
                    AppointmentReminder.status == SCHEDULED_REMINDER_STATUS,
                    and_(
                        AppointmentReminder.status == CLAIMED_REMINDER_STATUS,
                        AppointmentReminder.claim_expires_at <= claimed_at,
                    ),
                ),
            )
            .order_by(
                AppointmentReminder.send_at,
                AppointmentReminder.appointment_reminder_id,
            )
            .limit(1)
            .with_for_update(of=AppointmentReminder, skip_locked=True)
        ).one_or_none()
        if row is None:
            return None

        result = self._connection.execute(
            update(AppointmentReminder)
            .where(
                AppointmentReminder.appointment_reminder_id
                == row.appointment_reminder_id,
            )
            .values(
                status=CLAIMED_REMINDER_STATUS,
                status_changed_at=claimed_at,
                claimed_at=claimed_at,
                claim_expires_at=claim_expires_at,
                updated_at=claimed_at,
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("due reminder could not be claimed.")
        return ClaimedDueReminder(
            reminder_id=row.appointment_reminder_id,
            appointment_id=row.appointment_id,
            appointment_scheduled_start=row.appointment_scheduled_start,
        )

    def omit_claimed_reminder(
        self,
        *,
        reminder_id: int,
        claimed_at: datetime,
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
                status=OMITTED_REMINDER_STATUS,
                status_changed_at=status_changed_at,
                claimed_at=None,
                claim_expires_at=None,
                updated_at=status_changed_at,
            )
        )
        return result.rowcount == 1


class PostgresDueAppointmentReminderClaimUnitOfWork:
    """Own the short transaction used to claim one reminder."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def transaction(self) -> Iterator[DueAppointmentReminderClaimRepository]:
        with self._engine.begin() as connection:
            yield PostgresDueAppointmentReminderClaimRepository(connection)

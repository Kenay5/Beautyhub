"""Claim one due appointment reminder through a recoverable lease."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, TypeAlias

from backend.app.application.clock import Clock
from backend.app.domain.appointment_reminder import is_due_reminder_timely
from backend.app.domain.time import normalize_instant


ReminderClaimOutcome: TypeAlias = Literal["claimed", "omitted"]


class ReminderClaimConfigurationError(ValueError):
    """Raised when the internal claim lease is invalid."""


@dataclass(frozen=True)
class ClaimedDueReminder:
    """A due reminder protected by the current PostgreSQL claim."""

    reminder_id: int
    appointment_id: int
    appointment_scheduled_start: datetime


@dataclass(frozen=True)
class DueReminderClaimResult:
    """The durable result of attempting to start one due reminder."""

    reminder_id: int
    appointment_id: int
    appointment_scheduled_start: datetime
    outcome: ReminderClaimOutcome
    claimed_at: datetime | None
    claim_expires_at: datetime | None


class DueAppointmentReminderClaimRepository(Protocol):
    """Persistence operations for one short reminder-claim transaction."""

    def claim_next_due_reminder(
        self,
        *,
        claimed_at: datetime,
        claim_expires_at: datetime,
    ) -> ClaimedDueReminder | None:
        """Claim one scheduled or abandoned reminder without waiting on peers."""

    def omit_claimed_reminder(
        self,
        *,
        reminder_id: int,
        claimed_at: datetime,
        status_changed_at: datetime,
    ) -> bool:
        """Permanently omit the reminder only if this claim still owns it."""


class DueAppointmentReminderClaimUnitOfWork(Protocol):
    """Open one atomic PostgreSQL reminder-claim transaction."""

    def transaction(
        self,
    ) -> AbstractContextManager[DueAppointmentReminderClaimRepository]:
        """Commit one claim or omission, rolling back on failure."""


class ClaimDueAppointmentReminder:
    """Claim one due reminder or omit it when the appointment is too close."""

    def __init__(
        self,
        *,
        unit_of_work: DueAppointmentReminderClaimUnitOfWork,
        clock: Clock,
        claim_lease: timedelta,
    ) -> None:
        if not isinstance(claim_lease, timedelta) or claim_lease <= timedelta():
            raise ReminderClaimConfigurationError(
                "reminder claim lease must be positive."
            )
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._claim_lease = claim_lease

    def execute(self) -> DueReminderClaimResult | None:
        """Atomically claim the oldest eligible due reminder, if one exists."""

        claimed_at = normalize_instant(self._clock.now())
        claim_expires_at = claimed_at + self._claim_lease
        with self._unit_of_work.transaction() as repository:
            reminder = repository.claim_next_due_reminder(
                claimed_at=claimed_at,
                claim_expires_at=claim_expires_at,
            )
            if reminder is None:
                return None
            if not is_due_reminder_timely(
                scheduled_start=reminder.appointment_scheduled_start,
                current_time=claimed_at,
            ):
                if not repository.omit_claimed_reminder(
                    reminder_id=reminder.reminder_id,
                    claimed_at=claimed_at,
                    status_changed_at=claimed_at,
                ):
                    raise RuntimeError("claimed reminder could not be omitted.")
                return DueReminderClaimResult(
                    reminder_id=reminder.reminder_id,
                    appointment_id=reminder.appointment_id,
                    appointment_scheduled_start=(
                        reminder.appointment_scheduled_start
                    ),
                    outcome="omitted",
                    claimed_at=None,
                    claim_expires_at=None,
                )

        return DueReminderClaimResult(
            reminder_id=reminder.reminder_id,
            appointment_id=reminder.appointment_id,
            appointment_scheduled_start=reminder.appointment_scheduled_start,
            outcome="claimed",
            claimed_at=claimed_at,
            claim_expires_at=claim_expires_at,
        )

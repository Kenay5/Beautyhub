"""Atomically start and then independently dispatch one claimed reminder."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, TypeAlias

from backend.app.application.clock import Clock
from backend.app.application.dispatch_notifications import (
    DispatchedNotificationDelivery,
    NotificationDispatcher,
    PendingNotificationDelivery,
)
from backend.app.application.reminder_notification_templates import (
    ReminderNotificationData,
    prepare_reminder_notifications_from_data,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationChannel,
)
from backend.app.domain.appointment_reminder import (
    CLAIMED_REMINDER_STATUS,
    COMPLETED_REMINDER_STATUS,
    INVALIDATED_REMINDER_STATUS,
    OMITTED_REMINDER_STATUS,
    is_due_reminder_timely,
)
from backend.app.domain.notification_delivery import NotificationDeliveryStatus
from backend.app.domain.time import normalize_instant


ReminderProcessingOutcome: TypeAlias = Literal["processed", "skipped"]


@dataclass(frozen=True)
class ProcessClaimedReminderCommand:
    """Ownership token returned by the durable claim step."""

    reminder_id: int
    claimed_at: datetime


@dataclass(frozen=True)
class LockedClaimedReminder:
    """Reminder and appointment state reloaded under PostgreSQL locks."""

    reminder_id: int
    appointment_id: int
    reminder_status: str
    reminder_claimed_at: datetime | None
    reminder_scheduled_start: datetime
    appointment_status: str
    appointment_scheduled_start: datetime
    email: str = field(repr=False)
    phone: str = field(repr=False)
    service_name: str
    duration_minutes: int
    price: Decimal
    branch: str


@dataclass(frozen=True)
class ReminderDeliveryIntent:
    """One reminder delivery durably registered before provider contact."""

    delivery_id: int
    channel: NotificationChannel
    status: NotificationDeliveryStatus


@dataclass(frozen=True)
class ProcessedAppointmentReminder:
    """Sanitized result of one claimed reminder processing attempt."""

    reminder_id: int
    outcome: ReminderProcessingOutcome
    deliveries: tuple[DispatchedNotificationDelivery, ...]


class ClaimedAppointmentReminderRepository(Protocol):
    """Persistence operations for the brief registered-start transaction."""

    def lock_reminder_and_appointment(
        self,
        *,
        reminder_id: int,
    ) -> LockedClaimedReminder | None:
        """Lock the appointment first, then its reminder, and return current state."""

    def finish_claim(
        self,
        *,
        reminder_id: int,
        claimed_at: datetime,
        status: str,
        status_changed_at: datetime,
    ) -> bool:
        """Finish only the claim identified by its ownership timestamp."""

    def create_delivery_intents(
        self,
        *,
        appointment_id: int,
        reminder_id: int,
        status_changed_at: datetime,
    ) -> tuple[ReminderDeliveryIntent, ReminderDeliveryIntent]:
        """Register exactly one pending intent per reminder channel."""


class ClaimedAppointmentReminderUnitOfWork(Protocol):
    """Open the transaction that records reminder processing start."""

    def transaction(
        self,
    ) -> AbstractContextManager[ClaimedAppointmentReminderRepository]:
        """Commit the reminder start before any provider is contacted."""


class ProcessClaimedAppointmentReminder:
    """Resolve current appointment state, commit delivery intents, then dispatch."""

    def __init__(
        self,
        *,
        unit_of_work: ClaimedAppointmentReminderUnitOfWork,
        dispatcher: NotificationDispatcher,
        clock: Clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(
        self,
        command: ProcessClaimedReminderCommand,
    ) -> ProcessedAppointmentReminder:
        started_at = normalize_instant(self._clock.now())
        notification_data: ReminderNotificationData | None = None
        delivery_intents: tuple[ReminderDeliveryIntent, ...] = ()

        with self._unit_of_work.transaction() as repository:
            locked = repository.lock_reminder_and_appointment(
                reminder_id=command.reminder_id,
            )
            if not _owns_current_claim(locked=locked, command=command):
                return _skipped(command.reminder_id)

            assert locked is not None
            if (
                locked.appointment_status != "scheduled"
                or locked.appointment_scheduled_start
                != locked.reminder_scheduled_start
            ):
                _require_finished(
                    repository=repository,
                    command=command,
                    status=INVALIDATED_REMINDER_STATUS,
                    status_changed_at=started_at,
                )
                return _skipped(command.reminder_id)

            if not is_due_reminder_timely(
                scheduled_start=locked.appointment_scheduled_start,
                current_time=started_at,
            ):
                _require_finished(
                    repository=repository,
                    command=command,
                    status=OMITTED_REMINDER_STATUS,
                    status_changed_at=started_at,
                )
                return _skipped(command.reminder_id)

            delivery_intents = repository.create_delivery_intents(
                appointment_id=locked.appointment_id,
                reminder_id=locked.reminder_id,
                status_changed_at=started_at,
            )
            if {delivery.channel for delivery in delivery_intents} != {
                EMAIL_CHANNEL,
                WHATSAPP_CHANNEL,
            }:
                raise RuntimeError("appointment reminder requires both channels.")
            _require_finished(
                repository=repository,
                command=command,
                status=COMPLETED_REMINDER_STATUS,
                status_changed_at=started_at,
            )
            notification_data = ReminderNotificationData(
                email=locked.email,
                phone=locked.phone,
                service_name=locked.service_name,
                duration_minutes=locked.duration_minutes,
                price=locked.price,
                branch=locked.branch,
                scheduled_start=locked.appointment_scheduled_start,
            )

        assert notification_data is not None
        notifications = prepare_reminder_notifications_from_data(
            data=notification_data
        )
        notifications_by_channel = {
            notification.channel: notification for notification in notifications
        }
        dispatched = self._dispatcher.dispatch(
            deliveries=tuple(
                PendingNotificationDelivery(
                    delivery_id=delivery.delivery_id,
                    notification=notifications_by_channel[delivery.channel],
                )
                for delivery in delivery_intents
            ),
            dispatched_at=started_at,
        )
        return ProcessedAppointmentReminder(
            reminder_id=command.reminder_id,
            outcome="processed",
            deliveries=dispatched,
        )


def _owns_current_claim(
    *,
    locked: LockedClaimedReminder | None,
    command: ProcessClaimedReminderCommand,
) -> bool:
    return bool(
        locked is not None
        and locked.reminder_status == CLAIMED_REMINDER_STATUS
        and locked.reminder_claimed_at == normalize_instant(command.claimed_at)
    )


def _require_finished(
    *,
    repository: ClaimedAppointmentReminderRepository,
    command: ProcessClaimedReminderCommand,
    status: str,
    status_changed_at: datetime,
) -> None:
    if not repository.finish_claim(
        reminder_id=command.reminder_id,
        claimed_at=normalize_instant(command.claimed_at),
        status=status,
        status_changed_at=status_changed_at,
    ):
        raise RuntimeError("claimed reminder could not be finalized.")


def _skipped(reminder_id: int) -> ProcessedAppointmentReminder:
    return ProcessedAppointmentReminder(
        reminder_id=reminder_id,
        outcome="skipped",
        deliveries=(),
    )

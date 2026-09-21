"""Authorize and dispatch one bounded manual retry of a reminder channel."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
from backend.app.application.transactional_notifications import NotificationChannel
from backend.app.domain.appointment_reminder import is_due_reminder_timely
from backend.app.domain.notification_delivery import (
    FAILED_DELIVERY_STATUS,
    NotificationDeliveryStatus,
)
from backend.app.domain.time import normalize_instant


MAXIMUM_REMINDER_RETRIES = 3
MINIMUM_REMINDER_RETRY_INTERVAL = timedelta(minutes=5)
AdministrativeReminderRetryRole: TypeAlias = Literal["owner", "staff"]


class AdministrativeReminderRetryNotAuthorizedError(PermissionError):
    """Raised when the administrative session cannot retry appointment notices."""


class AdministrativeAppointmentNotificationRateLimitError(ValueError):
    """Raised when the account has exhausted appointment-notification capacity."""


class AppointmentReminderRetryNotPermittedError(ValueError):
    """Raised when a reminder delivery cannot receive another manual retry."""


@dataclass(frozen=True)
class AdministrativeReminderRetryActor:
    """Verified administrative identity supplied by the future session boundary."""

    account_id: int
    role: AdministrativeReminderRetryRole


@dataclass(frozen=True)
class LockedReminderRetry:
    """Current retry chain and appointment state under one transaction lock set."""

    delivery_id: int
    appointment_id: int
    reminder_id: int
    event: str
    channel: NotificationChannel
    delivery_status: NotificationDeliveryStatus
    appointment_status: str
    appointment_scheduled_start: datetime
    reminder_scheduled_start: datetime
    reminder_status: str
    retry_count: int
    last_retry_started_at: datetime | None
    has_later_attempt: bool
    email: str = field(repr=False)
    phone: str = field(repr=False)
    service_name: str
    duration_minutes: int
    price: Decimal
    branch: str


@dataclass(frozen=True)
class PreparedAppointmentReminderRetry:
    """One distinct retry attempt and its sanitized immediate outcome."""

    delivery_id: int
    previous_delivery_id: int
    appointment_id: int
    reminder_id: int
    channel: NotificationChannel
    status: NotificationDeliveryStatus


class AdministrativeReminderRetryAuthorizer(Protocol):
    """Authorize only a verified owner or staff session for this capability."""

    def ensure_allowed(self, actor: AdministrativeReminderRetryActor) -> None:
        """Raise a permission error without starting a retry when denied."""


class AdministrativeAppointmentNotificationLimiter(Protocol):
    """Reserve exactly one account-level appointment-notification action."""

    def ensure_allowed(self, *, account_id: int) -> None:
        """Raise before data access when the 30-per-15-minute window is full."""


class AppointmentReminderRetryRepository(Protocol):
    """Persistence operations for one serialized reminder retry."""

    def lock_retry_context(
        self,
        *,
        delivery_id: int,
    ) -> LockedReminderRetry | None:
        """Lock appointment, reminder and delivery chain before evaluating a retry."""

    def create_pending_retry(
        self,
        *,
        appointment_id: int,
        event: str,
        channel: NotificationChannel,
        previous_delivery_id: int,
        status_changed_at: datetime,
    ) -> int:
        """Create one auditable retry without duplicating the initial delivery."""


class AppointmentReminderRetryUnitOfWork(Protocol):
    """Provide the short transaction that records a manual reminder retry."""

    def transaction(
        self,
    ) -> AbstractContextManager[AppointmentReminderRetryRepository]:
        """Commit one valid retry before provider contact."""


class RetryFailedAppointmentReminder:
    """Retry only the current failed reminder channel within approved bounds."""

    def __init__(
        self,
        *,
        authorizer: AdministrativeReminderRetryAuthorizer,
        limiter: AdministrativeAppointmentNotificationLimiter,
        unit_of_work: AppointmentReminderRetryUnitOfWork,
        dispatcher: NotificationDispatcher,
        clock: Clock,
    ) -> None:
        self._authorizer = authorizer
        self._limiter = limiter
        self._unit_of_work = unit_of_work
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(
        self,
        *,
        actor: AdministrativeReminderRetryActor,
        delivery_id: int,
    ) -> PreparedAppointmentReminderRetry:
        """Authorize, reserve one rate-limit action, commit, then dispatch once."""

        _require_actor(actor)
        _require_delivery_id(delivery_id)
        self._authorizer.ensure_allowed(actor)
        self._limiter.ensure_allowed(account_id=actor.account_id)

        attempted_at = normalize_instant(self._clock.now())
        notification_data: ReminderNotificationData | None = None
        retry_delivery_id: int | None = None
        channel: NotificationChannel | None = None
        reminder_id: int | None = None
        appointment_id: int | None = None

        with self._unit_of_work.transaction() as repository:
            context = repository.lock_retry_context(delivery_id=delivery_id)
            _validate_retry_context(context=context, attempted_at=attempted_at)
            assert context is not None
            retry_delivery_id = repository.create_pending_retry(
                appointment_id=context.appointment_id,
                event=context.event,
                channel=context.channel,
                previous_delivery_id=context.delivery_id,
                status_changed_at=attempted_at,
            )
            notification_data = ReminderNotificationData(
                email=context.email,
                phone=context.phone,
                service_name=context.service_name,
                duration_minutes=context.duration_minutes,
                price=context.price,
                branch=context.branch,
                scheduled_start=context.appointment_scheduled_start,
            )
            channel = context.channel
            reminder_id = context.reminder_id
            appointment_id = context.appointment_id

        assert notification_data is not None
        assert retry_delivery_id is not None
        assert channel is not None
        assert reminder_id is not None
        assert appointment_id is not None
        notifications = prepare_reminder_notifications_from_data(data=notification_data)
        notification = next(
            candidate for candidate in notifications if candidate.channel == channel
        )
        dispatched = self._dispatcher.dispatch(
            deliveries=(
                PendingNotificationDelivery(
                    delivery_id=retry_delivery_id,
                    notification=notification,
                ),
            ),
            dispatched_at=attempted_at,
        )
        result = dispatched[0]
        return PreparedAppointmentReminderRetry(
            delivery_id=result.delivery_id,
            previous_delivery_id=delivery_id,
            appointment_id=appointment_id,
            reminder_id=reminder_id,
            channel=result.channel,
            status=result.status,
        )


def _validate_retry_context(
    *,
    context: LockedReminderRetry | None,
    attempted_at: datetime,
) -> None:
    if context is None:
        raise AppointmentReminderRetryNotPermittedError(
            "appointment reminder retry is not permitted."
        )
    if (
        context.event != "appointment_reminder"
        or context.delivery_status != FAILED_DELIVERY_STATUS
        or context.has_later_attempt
        or context.reminder_status != "completed"
        or context.appointment_status != "scheduled"
        or context.appointment_scheduled_start != context.reminder_scheduled_start
        or not is_due_reminder_timely(
            scheduled_start=context.appointment_scheduled_start,
            current_time=attempted_at,
        )
        or context.retry_count >= MAXIMUM_REMINDER_RETRIES
        or (
            context.last_retry_started_at is not None
            and attempted_at - context.last_retry_started_at
            < MINIMUM_REMINDER_RETRY_INTERVAL
        )
    ):
        raise AppointmentReminderRetryNotPermittedError(
            "appointment reminder retry is not permitted."
        )


def _require_actor(actor: AdministrativeReminderRetryActor) -> None:
    if (
        not isinstance(actor, AdministrativeReminderRetryActor)
        or isinstance(actor.account_id, bool)
        or not isinstance(actor.account_id, int)
        or actor.account_id <= 0
        or actor.role not in {"owner", "staff"}
    ):
        raise AdministrativeReminderRetryNotAuthorizedError(
            "administrative reminder retry is not authorized."
        )


def _require_delivery_id(delivery_id: int) -> None:
    if isinstance(delivery_id, bool) or not isinstance(delivery_id, int) or delivery_id <= 0:
        raise AppointmentReminderRetryNotPermittedError(
            "appointment reminder retry is not permitted."
        )

"""Create one auditable retry intent for a failed notification delivery."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AuthorizationDenialRecorder,
    require_capability,
)
from backend.app.application.clock import Clock
from backend.app.application.transactional_notifications import NotificationChannel
from backend.app.domain.notification_delivery import (
    FAILED_DELIVERY_STATUS,
    PENDING_DELIVERY_STATUS,
    NotificationDeliveryStatus,
)


class NotificationRetryNotPermittedError(ValueError):
    """Raised when a delivery cannot originate a retry intent."""


@dataclass(frozen=True)
class LockedFailedNotificationDelivery:
    """The original delivery locked before a retry is created."""

    delivery_id: int
    appointment_id: int
    event: str
    channel: NotificationChannel
    status: NotificationDeliveryStatus
    appointment_reminder_id: int | None


@dataclass(frozen=True)
class CurrentAppointmentContact:
    """The appointment contact read under lock for the selected channel."""

    appointment_id: int
    email: str = field(repr=False)
    phone: str = field(repr=False)


@dataclass(frozen=True)
class PreparedNotificationRetry:
    """A durable retry intent; it contains neither a private code nor message body."""

    delivery_id: int
    previous_delivery_id: int
    appointment_id: int
    event: str
    channel: NotificationChannel
    recipient: str = field(repr=False)
    status: NotificationDeliveryStatus = PENDING_DELIVERY_STATUS


class NotificationRetryRepository(Protocol):
    """Persistence boundary for one short retry-intent transaction."""

    def lock_delivery(
        self, delivery_id: int
    ) -> LockedFailedNotificationDelivery | None:
        """Lock the failed original delivery."""

    def lock_current_appointment_contact(
        self, appointment_id: int
    ) -> CurrentAppointmentContact | None:
        """Lock the appointment so the retry uses its current contact."""

    def create_pending_retry(
        self,
        *,
        appointment_id: int,
        event: str,
        channel: NotificationChannel,
        previous_delivery_id: int,
        status_changed_at: datetime,
    ) -> int:
        """Create a new pending delivery linked to its failed original."""


class NotificationRetryUnitOfWork(Protocol):
    """Provide the transaction that records one retry intent."""

    def transaction(
        self,
    ) -> AbstractContextManager[NotificationRetryRepository]:
        """Commit the retry intent without changing the appointment."""


class PrepareNotificationRetry:
    """Prepare, but do not dispatch, one retry for a failed non-reminder delivery."""

    def __init__(
        self,
        *,
        unit_of_work: NotificationRetryUnitOfWork,
        clock: Clock,
        audit: AuthorizationDenialRecorder,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._audit = audit

    def execute(
        self, *, actor: AdministrativeActor, delivery_id: int
    ) -> PreparedNotificationRetry:
        """Persist a distinct, linked retry addressed to the current contact."""

        require_capability(
            actor=actor,
            capability="retry_appointment_notifications",
            audit=self._audit,
        )
        _require_delivery_id(delivery_id)
        attempted_at = self._clock.now()
        with self._unit_of_work.transaction() as repository:
            original = repository.lock_delivery(delivery_id)
            if (
                original is None
                or original.status != FAILED_DELIVERY_STATUS
                or original.appointment_reminder_id is not None
                or original.event == "appointment_reminder"
            ):
                raise NotificationRetryNotPermittedError(
                    "notification retry is not permitted."
                )
            contact = repository.lock_current_appointment_contact(
                original.appointment_id
            )
            if contact is None or contact.appointment_id != original.appointment_id:
                raise NotificationRetryNotPermittedError(
                    "notification retry is not permitted."
                )
            retry_delivery_id = repository.create_pending_retry(
                appointment_id=original.appointment_id,
                event=original.event,
                channel=original.channel,
                previous_delivery_id=original.delivery_id,
                status_changed_at=attempted_at,
            )

        return PreparedNotificationRetry(
            delivery_id=retry_delivery_id,
            previous_delivery_id=original.delivery_id,
            appointment_id=original.appointment_id,
            event=original.event,
            channel=original.channel,
            recipient=(contact.email if original.channel == "email" else contact.phone),
        )


def _require_delivery_id(delivery_id: int) -> None:
    if isinstance(delivery_id, bool) or not isinstance(delivery_id, int) or delivery_id <= 0:
        raise NotificationRetryNotPermittedError("notification retry is not permitted.")

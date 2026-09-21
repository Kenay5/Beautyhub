"""Atomic public appointment cancellation required by RF-02 and RF-07."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
    require_matching_public_appointment_phone,
)
from backend.app.domain.appointment import SCHEDULED_APPOINTMENT_STATUS
from backend.app.domain.cancellation_reason import normalize_cancellation_reason
from backend.app.domain.time import InstantValidationError, normalize_instant


PUBLIC_APPOINTMENT_CANCELLATION_MINIMUM_NOTICE = timedelta(hours=1)
CANCELLED_APPOINTMENT_STATUS = "cancelled"


class PublicAppointmentCancellationNotPermittedError(ValueError):
    """Raised when current appointment state or notice rejects cancellation."""


class PublicAppointmentCancellationPersistenceError(RuntimeError):
    """Raised when a locked appointment cannot be cancelled as expected."""


@dataclass(frozen=True)
class PublicAppointmentCancellationCommand:
    """Validated internal input for one public cancellation transaction."""

    private_code_digest: bytes = field(repr=False)
    phone: str = field(repr=False)
    reason: str | None = None


@dataclass(frozen=True)
class LockedAppointmentForCancellation:
    """Current appointment state reloaded while its row is locked."""

    appointment_id: int
    phone: str = field(repr=False)
    service_snapshot_name: str
    service_snapshot_duration_minutes: int
    service_snapshot_price: Decimal
    branch: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    email: str = field(repr=False)


@dataclass(frozen=True)
class CancelledAppointment:
    """Internal result of a committed public cancellation."""

    appointment_id: int
    service_name: str
    duration_minutes: int
    price: Decimal
    branch: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    email: str = field(repr=False)
    phone: str = field(repr=False)
    deliveries: tuple[ChangeNotificationDelivery, ...]


class PublicAppointmentCancellationRepository(Protocol):
    """Persistence operations required inside one cancellation transaction."""

    def lock_schedule(self) -> None:
        """Serialize cancellation with every other schedule mutation."""

    def lock_appointment_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> LockedAppointmentForCancellation | None:
        """Reload and lock the exact appointment addressed by the digest."""

    def cancel_appointment(
        self,
        *,
        appointment_id: int,
        reason: str | None,
        changed_at: datetime,
    ) -> bool:
        """Persist the final status and optional normalized reason."""

    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[ChangeNotificationDelivery, ChangeNotificationDelivery]:
        """Persist exactly one pending delivery for each approved channel."""

    def invalidate_pending_reminders(
        self,
        *,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> None:
        """Prevent pending reminders for the cancelled appointment from running."""


class PublicAppointmentCancellationUnitOfWork(Protocol):
    """Open the single transaction used by one public cancellation."""

    def transaction(
        self,
    ) -> AbstractContextManager[PublicAppointmentCancellationRepository]:
        """Commit on success and roll back all writes after an error."""


class CancelPublicAppointment:
    """Validate and cancel one public appointment atomically."""

    def __init__(
        self,
        *,
        unit_of_work: PublicAppointmentCancellationUnitOfWork,
        clock: Clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def execute(
        self,
        command: PublicAppointmentCancellationCommand,
    ) -> CancelledAppointment:
        """Cancel only a credentialed, scheduled appointment with enough notice."""

        _require_private_code_digest(command.private_code_digest)
        normalized_reason = normalize_cancellation_reason(command.reason)
        current_time = self._clock.now()

        with self._unit_of_work.transaction() as repository:
            repository.lock_schedule()
            appointment = repository.lock_appointment_by_private_code_digest(
                command.private_code_digest,
            )
            if appointment is None:
                raise PublicAppointmentCredentialError()
            require_matching_public_appointment_phone(
                provided_phone=command.phone,
                registered_phone=appointment.phone,
            )
            if not is_public_appointment_cancellation_allowed(
                status=appointment.status,
                scheduled_start=appointment.scheduled_start,
                current_time=current_time,
            ):
                raise PublicAppointmentCancellationNotPermittedError(
                    "public appointment cancellation is not permitted."
                )
            if not repository.cancel_appointment(
                appointment_id=appointment.appointment_id,
                reason=normalized_reason,
                changed_at=current_time,
            ):
                raise PublicAppointmentCancellationPersistenceError(
                    "locked appointment could not be cancelled."
                )
            repository.invalidate_pending_reminders(
                appointment_id=appointment.appointment_id,
                status_changed_at=current_time,
            )
            deliveries = repository.create_pending_deliveries(
                appointment.appointment_id,
                current_time,
            )

        return CancelledAppointment(
            appointment_id=appointment.appointment_id,
            service_name=appointment.service_snapshot_name,
            duration_minutes=appointment.service_snapshot_duration_minutes,
            price=appointment.service_snapshot_price,
            branch=appointment.branch,
            scheduled_start=appointment.scheduled_start,
            scheduled_end=appointment.scheduled_end,
            status=CANCELLED_APPOINTMENT_STATUS,
            email=appointment.email,
            phone=appointment.phone,
            deliveries=deliveries,
        )


def is_public_appointment_cancellation_allowed(
    *,
    status: str,
    scheduled_start: datetime,
    current_time: datetime,
) -> bool:
    """Accept the exact 60-minute boundary for scheduled appointments only."""

    if status != SCHEDULED_APPOINTMENT_STATUS:
        return False
    try:
        normalized_start = normalize_instant(scheduled_start)
        normalized_current_time = normalize_instant(current_time)
    except InstantValidationError:
        return False
    return (
        normalized_start - normalized_current_time
        >= PUBLIC_APPOINTMENT_CANCELLATION_MINIMUM_NOTICE
    )


def _require_private_code_digest(private_code_digest: bytes) -> None:
    if not isinstance(private_code_digest, bytes) or not private_code_digest:
        raise PublicAppointmentCredentialError()

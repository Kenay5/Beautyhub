"""Transactional appointment confirmation without provider side effects."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.application.entropy import SecretGenerator
from backend.app.application.private_code import PrivateCode, generate_private_code
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.domain.appointment import (
    ScheduledAppointment,
    create_scheduled_appointment,
)
from backend.app.domain.appointment_reminder import (
    initial_reminder_send_at,
    is_initial_reminder_eligible,
)
from backend.app.domain.privacy_consent import (
    ADMINISTRATIVE_APPOINTMENT_ORIGIN,
    PUBLIC_APPOINTMENT_ORIGIN,
    PrivacyConsentEvidence,
)
from backend.app.domain.schedule import (
    ScheduledInterval,
    TimeInterval,
    has_neighbor_separation_conflict,
    has_schedule_conflict,
    occupying_intervals,
    validate_administrative_appointment_timing,
    validate_public_appointment_timing,
)
from backend.app.domain.service import ServiceDraft


APPOINTMENT_CREATED_EVENT = "appointment_created"


class AppointmentConfirmationError(ValueError):
    """Base error for a rejected appointment confirmation."""


class AppointmentConfirmationReferenceError(AppointmentConfirmationError):
    """Raised when a confirmation reference cannot authorize creation."""


class AppointmentServiceNotFoundError(AppointmentConfirmationError):
    """Raised when the selected service no longer exists."""


class AppointmentScheduleConflictError(AppointmentConfirmationError):
    """Raised when current schedule state rejects the requested interval."""


@dataclass(frozen=True)
class ConfirmAppointmentCommand:
    """Validated input needed to confirm one appointment."""

    reference_digest: bytes = field(repr=False)
    first_name: str
    last_name: str
    phone: str
    email: str
    service_id: int
    branch: str
    scheduled_start: datetime
    privacy_consent: PrivacyConsentEvidence


@dataclass(frozen=True)
class LockedBookingConfirmationReference:
    """Reference state reloaded while its PostgreSQL row is locked."""

    reference_id: int
    expires_at: datetime
    consumed_at: datetime | None
    appointment_id: int | None


@dataclass(frozen=True)
class ConfirmationDeliveryResult:
    """One original delivery intent returned by a confirmation."""

    delivery_id: int
    channel: str
    status: str


@dataclass(frozen=True)
class StoredConfirmedAppointment:
    """Persisted confirmation data required for an idempotent retry."""

    appointment_id: int
    appointment: ScheduledAppointment
    private_code_ciphertext: bytes = field(repr=False)
    deliveries: tuple[ConfirmationDeliveryResult, ConfirmationDeliveryResult]


@dataclass(frozen=True)
class ConfirmedAppointment:
    """Committed appointment and its original delivery intents."""

    appointment_id: int
    appointment: ScheduledAppointment
    private_code: PrivateCode = field(repr=False)
    deliveries: tuple[ConfirmationDeliveryResult, ConfirmationDeliveryResult]
    notification_dispatch_required: bool = field(default=True, compare=False, repr=False)

    @property
    def delivery_ids(self) -> tuple[int, int]:
        """Return stable delivery identifiers for internal callers."""

        return tuple(delivery.delivery_id for delivery in self.deliveries)  # type: ignore[return-value]


class PrivateCodeProtection(Protocol):
    """Protect a generated private code for persistence and exact lookup."""

    def digest(self, secret: str) -> bytes:
        """Return a keyed lookup digest."""

    def encrypt(self, private_code: PrivateCode) -> bytes:
        """Return authenticated ciphertext for later authorized recovery."""

    def decrypt(self, ciphertext: bytes) -> PrivateCode:
        """Recover a code from authenticated ciphertext."""


class AppointmentConfirmationRepository(Protocol):
    """Persistence operations required inside one confirmation transaction."""

    def lock_schedule(self) -> None:
        """Serialize all schedule-changing operations."""

    def lock_confirmation_reference(
        self,
        reference_digest: bytes,
    ) -> LockedBookingConfirmationReference | None:
        """Reload and lock the exact confirmation reference."""

    def get_service_for_update(self, service_id: int) -> ServiceDraft | None:
        """Reload and lock the selected service."""

    def list_scheduled_intervals_for_update(self) -> tuple[ScheduledInterval, ...]:
        """Reload scheduled appointments while the agenda is protected."""

    def list_applicable_blocks_for_update(
        self,
        branch: str,
    ) -> tuple[TimeInterval, ...]:
        """Reload global and selected-branch blocks."""

    def create_appointment(self, appointment: ScheduledAppointment) -> int:
        """Persist the confirmed appointment aggregate."""

    def create_pending_deliveries(
        self,
        appointment_id: int,
        status_changed_at: datetime,
    ) -> tuple[ConfirmationDeliveryResult, ConfirmationDeliveryResult]:
        """Persist one pending delivery for each approved channel."""

    def create_initial_reminder(
        self,
        *,
        appointment_id: int,
        appointment_scheduled_start: datetime,
        send_at: datetime,
        status_changed_at: datetime,
    ) -> None:
        """Persist the sole eligible initial reminder for this appointment start."""

    def get_confirmed_appointment(
        self,
        appointment_id: int,
    ) -> StoredConfirmedAppointment | None:
        """Reload the result already associated with a consumed reference."""

    def consume_confirmation_reference(
        self,
        reference_id: int,
        appointment_id: int,
        consumed_at: datetime,
    ) -> bool:
        """Associate and consume an unused reference."""


class AppointmentConfirmationUnitOfWork(Protocol):
    """Open the single transaction used for appointment confirmation."""

    def transaction(
        self,
    ) -> AbstractContextManager[AppointmentConfirmationRepository]:
        """Commit on success and roll back on failure."""


class ConfirmAppointment:
    """Confirm one appointment and its delivery intents atomically."""

    def __init__(
        self,
        *,
        unit_of_work: AppointmentConfirmationUnitOfWork,
        clock: Clock,
        secret_generator: SecretGenerator,
        private_code_protection: PrivateCodeProtection,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._secret_generator = secret_generator
        self._private_code_protection = private_code_protection

    def execute(self, command: ConfirmAppointmentCommand) -> ConfirmedAppointment:
        """Revalidate mutable state and commit all local effects together."""

        current_time = self._clock.now()
        with self._unit_of_work.transaction() as repository:
            repository.lock_schedule()
            reference = repository.lock_confirmation_reference(
                command.reference_digest,
            )
            _require_current_reference(reference, current_time)
            if _reference_was_consumed(reference):
                return _load_original_confirmation(
                    repository=repository,
                    reference=reference,
                    private_code_protection=self._private_code_protection,
                )

            service = repository.get_service_for_update(command.service_id)
            if service is None:
                raise AppointmentServiceNotFoundError("selected service is unavailable.")

            private_code = generate_private_code(self._secret_generator)
            appointment = create_scheduled_appointment(
                private_code_ciphertext=self._private_code_protection.encrypt(
                    private_code,
                ),
                private_code_digest=self._private_code_protection.digest(
                    private_code.value,
                ),
                first_name=command.first_name,
                last_name=command.last_name,
                phone=command.phone,
                email=command.email,
                service_id=command.service_id,
                service=service,
                branch=command.branch,
                scheduled_start=command.scheduled_start,
                privacy_consent=command.privacy_consent,
            )
            _validate_timing(appointment, current_time)
            _require_available_schedule(
                appointment,
                repository.list_scheduled_intervals_for_update(),
                repository.list_applicable_blocks_for_update(appointment.branch),
            )

            appointment_id = repository.create_appointment(appointment)
            deliveries = repository.create_pending_deliveries(
                appointment_id,
                current_time,
            )
            if is_initial_reminder_eligible(
                scheduled_start=appointment.scheduled_start,
                current_time=current_time,
            ):
                repository.create_initial_reminder(
                    appointment_id=appointment_id,
                    appointment_scheduled_start=appointment.scheduled_start,
                    send_at=initial_reminder_send_at(appointment.scheduled_start),
                    status_changed_at=current_time,
                )
            if not repository.consume_confirmation_reference(
                reference.reference_id,
                appointment_id,
                current_time,
            ):
                raise AppointmentConfirmationReferenceError(
                    "confirmation reference is invalid."
                )

        return ConfirmedAppointment(
            appointment_id=appointment_id,
            appointment=appointment,
            private_code=private_code,
            deliveries=deliveries,
            notification_dispatch_required=True,
        )


def _require_current_reference(
    reference: LockedBookingConfirmationReference | None,
    current_time: datetime,
) -> None:
    if reference is None or current_time >= reference.expires_at:
        raise AppointmentConfirmationReferenceError(
            "confirmation reference is invalid."
        )
    if (reference.consumed_at is None) != (reference.appointment_id is None):
        raise AppointmentConfirmationReferenceError(
            "confirmation reference is invalid."
        )


def _reference_was_consumed(
    reference: LockedBookingConfirmationReference,
) -> bool:
    return reference.consumed_at is not None


def _load_original_confirmation(
    *,
    repository: AppointmentConfirmationRepository,
    reference: LockedBookingConfirmationReference,
    private_code_protection: PrivateCodeProtection,
) -> ConfirmedAppointment:
    if reference.appointment_id is None:
        raise AppointmentConfirmationReferenceError(
            "confirmation reference is invalid."
        )
    stored = repository.get_confirmed_appointment(reference.appointment_id)
    if stored is None:
        raise AppointmentConfirmationReferenceError(
            "confirmation reference is invalid."
        )
    return ConfirmedAppointment(
        appointment_id=stored.appointment_id,
        appointment=stored.appointment,
        private_code=private_code_protection.decrypt(
            stored.private_code_ciphertext,
        ),
        deliveries=stored.deliveries,
        notification_dispatch_required=False,
    )


def _validate_timing(
    appointment: ScheduledAppointment,
    current_time: datetime,
) -> None:
    if appointment.privacy_consent.origin == PUBLIC_APPOINTMENT_ORIGIN:
        validate_public_appointment_timing(appointment.scheduled_start, current_time)
        return
    if appointment.privacy_consent.origin == ADMINISTRATIVE_APPOINTMENT_ORIGIN:
        validate_administrative_appointment_timing(
            appointment.scheduled_start,
            current_time,
        )


def _require_available_schedule(
    appointment: ScheduledAppointment,
    scheduled_intervals: tuple[ScheduledInterval, ...],
    applicable_blocks: tuple[TimeInterval, ...],
) -> None:
    candidate = ScheduledInterval(
        interval=TimeInterval(
            appointment.scheduled_start,
            appointment.scheduled_end,
        ),
        branch=appointment.branch,
    )
    if has_schedule_conflict(
        candidate.interval,
        occupying_intervals(scheduled_intervals),
    ) or has_schedule_conflict(candidate.interval, applicable_blocks):
        raise AppointmentScheduleConflictError("requested schedule is unavailable.")

    previous = max(
        (
            interval
            for interval in scheduled_intervals
            if interval.interval.end <= candidate.interval.start
        ),
        key=lambda interval: interval.interval.end,
        default=None,
    )
    following = min(
        (
            interval
            for interval in scheduled_intervals
            if interval.interval.start >= candidate.interval.end
        ),
        key=lambda interval: interval.interval.start,
        default=None,
    )
    if has_neighbor_separation_conflict(candidate, previous, following):
        raise AppointmentScheduleConflictError("requested schedule is unavailable.")

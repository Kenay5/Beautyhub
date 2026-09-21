"""Transactional revalidation for one public appointment reschedule."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from backend.app.application.authorize_public_appointment_modification import (
    PublicAppointmentModificationNotPermittedError,
    is_public_appointment_state_modifiable,
)
from backend.app.application.clock import Clock
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
    require_matching_public_appointment_phone,
)
from backend.app.domain.schedule import (
    ScheduledInterval,
    TimeInterval,
    appointment_end,
    has_neighbor_separation_conflict,
    has_schedule_conflict,
    occupying_intervals,
    validate_public_appointment_timing,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot
from backend.app.domain.appointment_reminder import (
    initial_reminder_send_at,
    is_initial_reminder_eligible,
)
from backend.app.domain.service import (
    AppointmentServiceSelectionError,
    ServiceDraft,
    validate_service_for_appointment,
)
from backend.app.domain.service_configuration import validate_service_branch
from backend.app.domain.service_text import validate_service_text


class PublicAppointmentRescheduleConflictError(ValueError):
    """Raised when current schedule state rejects a public reschedule."""


class PublicAppointmentReschedulePersistenceError(RuntimeError):
    """Raised when a locked appointment cannot be updated as expected."""


@dataclass(frozen=True)
class PublicAppointmentRescheduleCommand:
    """Validated internal input for the public reschedule transaction."""

    private_code_digest: bytes = field(repr=False)
    phone: str = field(repr=False)
    service_name: str
    branch: str
    scheduled_start: datetime


@dataclass(frozen=True)
class LockedAppointmentForReschedule:
    """Current appointment state reloaded while its row is locked."""

    appointment_id: int
    phone: str = field(repr=False)
    service_id: int
    service_snapshot_name: str
    service_snapshot_duration_minutes: int
    service_snapshot_price: Decimal
    scheduled_start: datetime
    status: str
    email: str = field(repr=False)


@dataclass(frozen=True)
class LockedServiceForReschedule:
    """Current service state reloaded under the schedule guard."""

    service_id: int
    service: ServiceDraft


@dataclass(frozen=True)
class RescheduledAppointment:
    """Minimum internal result of a committed public schedule change."""

    appointment_id: int
    service_snapshot: AppointmentServiceSnapshot
    branch: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    email: str = field(repr=False)
    phone: str = field(repr=False)
    deliveries: tuple[ChangeNotificationDelivery, ...]


class PublicAppointmentRescheduleRepository(Protocol):
    """Persistence operations required inside one reschedule transaction."""

    def lock_schedule(self) -> None:
        """Serialize this operation with every other schedule mutation."""

    def lock_appointment_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> LockedAppointmentForReschedule | None:
        """Reload and lock the exact appointment authorized by the code digest."""

    def get_service_for_update(
        self,
        *,
        service_name: str,
    ) -> LockedServiceForReschedule | None:
        """Reload and lock the exact selected service."""

    def list_other_scheduled_intervals_for_update(
        self,
        *,
        excluding_appointment_id: int,
    ) -> tuple[ScheduledInterval, ...]:
        """Read occupying appointments except the appointment being moved."""

    def list_applicable_blocks_for_update(
        self,
        branch: str,
    ) -> tuple[TimeInterval, ...]:
        """Read global and selected-branch blocks under the agenda guard."""

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
        """Persist the revalidated schedule fields on the locked appointment."""

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
        """Prevent any reminder for the previous appointment start from running."""

    def create_initial_reminder(
        self,
        *,
        appointment_id: int,
        appointment_scheduled_start: datetime,
        send_at: datetime,
        status_changed_at: datetime,
    ) -> None:
        """Persist one eligible reminder for the new appointment start."""


class PublicAppointmentRescheduleUnitOfWork(Protocol):
    """Open the single transaction used by a public reprogramming request."""

    def transaction(
        self,
    ) -> AbstractContextManager[PublicAppointmentRescheduleRepository]:
        """Commit on success and roll back every write after an error."""


class ReschedulePublicAppointment:
    """Revalidate mutable state and persist one public schedule change atomically."""

    def __init__(
        self,
        *,
        unit_of_work: PublicAppointmentRescheduleUnitOfWork,
        clock: Clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def execute(
        self,
        command: PublicAppointmentRescheduleCommand,
    ) -> RescheduledAppointment:
        """Apply only a currently valid and available public reprogramming."""

        current_time = self._clock.now()
        _require_private_code_digest(command.private_code_digest)
        normalized_branch = validate_service_branch(command.branch)
        normalized_service_name, _ = validate_service_text(
            command.service_name,
            None,
        )
        validate_public_appointment_timing(command.scheduled_start, current_time)

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
            if not is_public_appointment_state_modifiable(
                status=appointment.status,
                scheduled_start=appointment.scheduled_start,
                current_time=current_time,
            ):
                raise PublicAppointmentModificationNotPermittedError(
                    "public appointment modification is not permitted."
                )

            selected_service = repository.get_service_for_update(
                service_name=normalized_service_name,
            )
            if selected_service is None:
                raise AppointmentServiceSelectionError(
                    "selected service is unavailable."
                )
            validate_service_for_appointment(
                selected_service.service,
                normalized_branch,
            )
            service_snapshot = _service_snapshot_for_reschedule(
                appointment=appointment,
                selected_service=selected_service,
            )
            candidate = ScheduledInterval(
                interval=TimeInterval(
                    command.scheduled_start,
                    appointment_end(
                        command.scheduled_start,
                        timedelta(minutes=service_snapshot.duration_minutes),
                    ),
                ),
                branch=normalized_branch,
            )
            _require_available_candidate(
                candidate=candidate,
                scheduled_intervals=(
                    repository.list_other_scheduled_intervals_for_update(
                        excluding_appointment_id=appointment.appointment_id,
                    )
                ),
                applicable_blocks=repository.list_applicable_blocks_for_update(
                    normalized_branch,
                ),
            )
            if not repository.update_schedule(
                appointment_id=appointment.appointment_id,
                service_snapshot=service_snapshot,
                branch=candidate.branch,
                scheduled_start=candidate.interval.start,
                scheduled_end=candidate.interval.end,
                changed_at=current_time,
            ):
                raise PublicAppointmentReschedulePersistenceError(
                    "locked appointment could not be rescheduled."
                )
            if candidate.interval.start != appointment.scheduled_start:
                repository.invalidate_pending_reminders(
                    appointment_id=appointment.appointment_id,
                    status_changed_at=current_time,
                )
                if is_initial_reminder_eligible(
                    scheduled_start=candidate.interval.start,
                    current_time=current_time,
                ):
                    repository.create_initial_reminder(
                        appointment_id=appointment.appointment_id,
                        appointment_scheduled_start=candidate.interval.start,
                        send_at=initial_reminder_send_at(candidate.interval.start),
                        status_changed_at=current_time,
                    )
            deliveries = repository.create_pending_deliveries(
                appointment.appointment_id,
                current_time,
            )

        return RescheduledAppointment(
            appointment_id=appointment.appointment_id,
            service_snapshot=service_snapshot,
            branch=candidate.branch,
            scheduled_start=candidate.interval.start,
            scheduled_end=candidate.interval.end,
            status=appointment.status,
            email=appointment.email,
            phone=appointment.phone,
            deliveries=deliveries,
        )


def _require_private_code_digest(private_code_digest: bytes) -> None:
    if not isinstance(private_code_digest, bytes) or not private_code_digest:
        raise PublicAppointmentCredentialError()


def _service_snapshot_for_reschedule(
    *,
    appointment: LockedAppointmentForReschedule,
    selected_service: LockedServiceForReschedule,
) -> AppointmentServiceSnapshot:
    """Keep agreed terms unless a different current service is selected."""

    if selected_service.service_id == appointment.service_id:
        return AppointmentServiceSnapshot(
            service_id=appointment.service_id,
            name=appointment.service_snapshot_name,
            duration_minutes=appointment.service_snapshot_duration_minutes,
            price=appointment.service_snapshot_price,
        )
    return AppointmentServiceSnapshot(
        service_id=selected_service.service_id,
        name=selected_service.service.name,
        duration_minutes=selected_service.service.duration_minutes,
        price=selected_service.service.price,
    )


def _require_available_candidate(
    *,
    candidate: ScheduledInterval,
    scheduled_intervals: tuple[ScheduledInterval, ...],
    applicable_blocks: tuple[TimeInterval, ...],
) -> None:
    if has_schedule_conflict(
        candidate.interval,
        occupying_intervals(scheduled_intervals),
    ) or has_schedule_conflict(candidate.interval, applicable_blocks):
        raise PublicAppointmentRescheduleConflictError(
            "requested schedule is unavailable."
        )

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
        raise PublicAppointmentRescheduleConflictError(
            "requested schedule is unavailable."
        )

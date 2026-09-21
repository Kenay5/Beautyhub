"""Authorize the approved public precondition for changing an appointment."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.application.clock import Clock
from backend.app.application.lookup_public_appointment import (
    LookupPublicAppointment,
    PublicAppointmentCredentialError,
    PublicAppointmentRecord,
    require_matching_public_appointment_phone,
)
from backend.app.domain.appointment import SCHEDULED_APPOINTMENT_STATUS
from backend.app.domain.time import InstantValidationError, normalize_instant


PUBLIC_APPOINTMENT_MODIFICATION_MINIMUM_NOTICE = timedelta(hours=1)


class PublicAppointmentModificationNotPermittedError(ValueError):
    """Reject a public modification that is outside its allowed appointment state."""


class AuthorizePublicAppointmentModification:
    """Check public credentials, appointment state, and the exact notice boundary."""

    def __init__(
        self,
        *,
        lookup: LookupPublicAppointment,
        clock: Clock,
    ) -> None:
        self._lookup = lookup
        self._clock = clock

    def execute(self, *, private_code: str, phone: str) -> None:
        """Authorize only a scheduled appointment with at least one hour remaining."""

        appointment = self._lookup.execute(private_code)
        require_matching_public_appointment_phone(
            provided_phone=phone,
            registered_phone=appointment.phone,
        )
        if not is_public_appointment_modification_allowed(
            appointment=appointment,
            current_time=self._clock.now(),
        ):
            raise PublicAppointmentModificationNotPermittedError(
                "public appointment modification is not permitted."
            )


def is_public_appointment_modification_allowed(
    *,
    appointment: PublicAppointmentRecord,
    current_time: datetime,
) -> bool:
    """Return whether the appointment is scheduled and has the approved notice."""

    return is_public_appointment_state_modifiable(
        status=appointment.status,
        scheduled_start=appointment.scheduled_start,
        current_time=current_time,
    )


def is_public_appointment_state_modifiable(
    *,
    status: str,
    scheduled_start: datetime,
    current_time: datetime,
) -> bool:
    """Evaluate mutable appointment state without depending on a read projection."""

    if status != SCHEDULED_APPOINTMENT_STATUS:
        return False
    try:
        normalized_scheduled_start = normalize_instant(scheduled_start)
        normalized_current_time = normalize_instant(current_time)
    except InstantValidationError:
        return False
    return (
        normalized_scheduled_start - normalized_current_time
        >= PUBLIC_APPOINTMENT_MODIFICATION_MINIMUM_NOTICE
    )

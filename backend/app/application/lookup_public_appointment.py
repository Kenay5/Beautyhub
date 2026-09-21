"""Exact public appointment lookup through an opaque private-code digest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from hmac import compare_digest
from typing import Protocol

from backend.app.application.booking_confirmation_reference import SecretDigester
from backend.app.application.clock import Clock
from backend.app.domain.mexican_phone import (
    MexicanPhoneValidationError,
    normalize_mexican_phone,
)
from backend.app.domain.time import business_datetime, to_business_time


PUBLIC_APPOINTMENT_LOOKUP_LIFETIME_DAYS = 30


PUBLIC_APPOINTMENT_CREDENTIAL_ERROR_DETAIL = (
    "No fue posible validar las credenciales de la cita."
)


class PublicAppointmentCredentialError(ValueError):
    """One sanitized outcome for every rejected public appointment credential."""

    def __init__(self) -> None:
        super().__init__(PUBLIC_APPOINTMENT_CREDENTIAL_ERROR_DETAIL)


class PublicAppointmentLookupError(PublicAppointmentCredentialError):
    """Compatibility name for a rejected lookup credential."""


@dataclass(frozen=True)
class PublicAppointmentRecord:
    """Appointment data needed by the later public presentation boundary.

    The record intentionally excludes internal identifiers, private-code material,
    consent evidence, and customer names. Contacts are retained only for the
    application boundary that applies the T062 mask before any public response.
    """

    service_name: str
    duration_minutes: int
    price: Decimal
    branch: str
    scheduled_start: datetime
    status: str
    phone: str
    email: str


class PublicAppointmentLookupReader(Protocol):
    """Read one appointment using only a keyed private-code digest."""

    def find_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> PublicAppointmentRecord | None:
        """Return the exactly matching appointment, if it exists."""


class LookupPublicAppointment:
    """Resolve one public appointment without HTTP or persistence concerns."""

    def __init__(
        self,
        *,
        reader: PublicAppointmentLookupReader,
        secret_digester: SecretDigester,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._secret_digester = secret_digester
        self._clock = clock

    def execute(self, private_code: str) -> PublicAppointmentRecord:
        """Return only the appointment associated with the supplied private code."""

        if not isinstance(private_code, str) or not private_code:
            raise PublicAppointmentLookupError()

        try:
            private_code_digest = self._secret_digester.digest(private_code)
        except (TypeError, ValueError) as error:
            raise PublicAppointmentLookupError() from error

        appointment = self._reader.find_by_private_code_digest(private_code_digest)
        if appointment is None:
            raise PublicAppointmentLookupError()
        if not is_public_appointment_lookup_current(
            appointment=appointment,
            current_time=self._clock.now(),
        ):
            raise PublicAppointmentLookupError()
        return appointment


def require_matching_public_appointment_phone(
    *,
    provided_phone: str,
    registered_phone: str,
) -> None:
    """Reject an incorrect public phone credential without revealing which failed."""

    try:
        normalized_phone = normalize_mexican_phone(provided_phone)
    except MexicanPhoneValidationError as error:
        raise PublicAppointmentCredentialError() from error

    if not isinstance(registered_phone, str) or not compare_digest(
        normalized_phone,
        registered_phone,
    ):
        raise PublicAppointmentCredentialError()


def is_public_appointment_lookup_current(
    *,
    appointment: PublicAppointmentRecord,
    current_time: datetime,
) -> bool:
    """Allow lookup until the next local midnight after the 30th calendar day."""

    appointment_date = to_business_time(appointment.scheduled_start).date()
    lookup_expires_at = business_datetime(
        appointment_date + timedelta(days=PUBLIC_APPOINTMENT_LOOKUP_LIFETIME_DAYS + 1),
        time.min,
    )
    return to_business_time(current_time) < lookup_expires_at

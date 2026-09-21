"""Appointment aggregate creation with immutable service terms."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from backend.app.domain.customer_name import normalize_customer_names
from backend.app.domain.email_address import normalize_email_address
from backend.app.domain.mexican_phone import normalize_mexican_phone
from backend.app.domain.privacy_consent import PrivacyConsentEvidence
from backend.app.domain.schedule import appointment_end
from backend.app.domain.service import ServiceDraft, validate_service_for_appointment
from backend.app.domain.service_configuration import validate_service_branch
from backend.app.domain.time import to_business_time


SCHEDULED_APPOINTMENT_STATUS = "scheduled"


class AppointmentValidationError(ValueError):
    """Raised when an appointment aggregate cannot be created safely."""


@dataclass(frozen=True)
class AppointmentServiceSnapshot:
    """The service terms agreed when an appointment is created."""

    service_id: int
    name: str
    duration_minutes: int
    price: Decimal


@dataclass(frozen=True)
class ScheduledAppointment:
    """A not-yet-persisted scheduled appointment aggregate."""

    private_code_ciphertext: bytes
    private_code_digest: bytes
    first_name: str
    last_name: str
    phone: str
    email: str
    service_snapshot: AppointmentServiceSnapshot
    branch: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
    privacy_consent: PrivacyConsentEvidence


def create_scheduled_appointment(
    *,
    private_code_ciphertext: bytes,
    private_code_digest: bytes,
    first_name: str,
    last_name: str,
    phone: str,
    email: str,
    service_id: int,
    service: ServiceDraft,
    branch: str,
    scheduled_start: datetime,
    privacy_consent: PrivacyConsentEvidence,
) -> ScheduledAppointment:
    """Create an appointment with contact and service terms frozen at creation."""

    _validate_protected_private_code(private_code_ciphertext, private_code_digest)
    _validate_service_id(service_id)
    normalized_branch = validate_service_branch(branch)
    selected_service = validate_service_for_appointment(service, normalized_branch)
    _validate_privacy_consent(privacy_consent)
    normalized_first_name, normalized_last_name = normalize_customer_names(
        first_name,
        last_name,
    )
    normalized_scheduled_start = to_business_time(scheduled_start)

    return ScheduledAppointment(
        private_code_ciphertext=private_code_ciphertext,
        private_code_digest=private_code_digest,
        first_name=normalized_first_name,
        last_name=normalized_last_name,
        phone=normalize_mexican_phone(phone),
        email=normalize_email_address(email),
        service_snapshot=AppointmentServiceSnapshot(
            service_id=service_id,
            name=selected_service.name,
            duration_minutes=selected_service.duration_minutes,
            price=selected_service.price,
        ),
        branch=normalized_branch,
        scheduled_start=normalized_scheduled_start,
        scheduled_end=appointment_end(
            normalized_scheduled_start,
            timedelta(minutes=selected_service.duration_minutes),
        ),
        status=SCHEDULED_APPOINTMENT_STATUS,
        privacy_consent=privacy_consent,
    )


def _validate_protected_private_code(ciphertext: bytes, digest: bytes) -> None:
    if not isinstance(ciphertext, bytes) or not ciphertext:
        raise AppointmentValidationError("private code ciphertext is required.")
    if not isinstance(digest, bytes) or not digest:
        raise AppointmentValidationError("private code digest is required.")


def _validate_service_id(service_id: int) -> None:
    if isinstance(service_id, bool) or not isinstance(service_id, int) or service_id <= 0:
        raise AppointmentValidationError("service identifier must be a positive integer.")


def _validate_privacy_consent(privacy_consent: PrivacyConsentEvidence) -> None:
    if not isinstance(privacy_consent, PrivacyConsentEvidence):
        raise AppointmentValidationError("privacy consent evidence is required.")

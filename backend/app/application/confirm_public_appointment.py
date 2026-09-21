"""Public appointment confirmation orchestration without HTTP or PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from backend.app.application.booking_confirmation_reference import SecretDigester
from backend.app.application.clock import Clock
from backend.app.application.confirm_appointment import (
    ConfirmAppointmentCommand,
    ConfirmedAppointment,
)
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.service_configuration import validate_service_branch
from backend.app.domain.service_text import validate_service_text


class PublicAppointmentConfirmationValidationError(ValueError):
    """Raised when a public confirmation cannot use approved current data."""


class PublicAppointmentSelectionReader(Protocol):
    """Resolve public choices without exposing persistence identifiers to HTTP."""

    def get_active_service_id(self, *, branch: str, service_name: str) -> int | None:
        """Return the selected currently active service identifier, if any."""

    def get_current_privacy_notice_version_id(
        self,
        *,
        version: str,
        accepted_at: datetime,
    ) -> int | None:
        """Return the accepted, currently valid notice version identifier, if any."""


class AppointmentConfirmation(Protocol):
    """Confirm an appointment through the configured post-commit orchestration."""

    def execute(self, command: ConfirmAppointmentCommand) -> ConfirmedAppointment:
        """Return the committed confirmation and current delivery results."""


@dataclass(frozen=True)
class ConfirmPublicAppointmentCommand:
    """Approved data received from a public appointment confirmation form."""

    confirmation_reference: str = field(repr=False)
    first_name: str
    last_name: str
    phone: str
    email: str
    service_name: str
    branch: str
    scheduled_start: datetime
    privacy_notice_version: str
    privacy_notice_accepted: bool
    contact_processing_authorized: bool
    adult_responsibility_declared: bool


class ConfirmPublicAppointment:
    """Adapt public choices into the existing transaction-safe confirmation use case."""

    def __init__(
        self,
        *,
        confirmation: AppointmentConfirmation,
        selection_reader: PublicAppointmentSelectionReader,
        clock: Clock,
        secret_digester: SecretDigester,
    ) -> None:
        self._confirmation = confirmation
        self._selection_reader = selection_reader
        self._clock = clock
        self._secret_digester = secret_digester

    def execute(self, command: ConfirmPublicAppointmentCommand) -> ConfirmedAppointment:
        """Confirm a public request after resolving only its approved choices."""

        if not isinstance(command.confirmation_reference, str) or not command.confirmation_reference:
            raise PublicAppointmentConfirmationValidationError(
                "confirmation reference is required."
            )
        if command.privacy_notice_accepted is not True:
            raise PublicAppointmentConfirmationValidationError(
                "privacy notice acceptance is required."
            )
        normalized_branch = validate_service_branch(command.branch)
        normalized_service_name, _ = validate_service_text(command.service_name, None)
        accepted_at = self._clock.now()

        service_id = self._selection_reader.get_active_service_id(
            branch=normalized_branch,
            service_name=normalized_service_name,
        )
        if service_id is None:
            raise PublicAppointmentConfirmationValidationError(
                "selected service is unavailable."
            )
        privacy_notice_version_id = (
            self._selection_reader.get_current_privacy_notice_version_id(
                version=command.privacy_notice_version,
                accepted_at=accepted_at,
            )
        )
        if privacy_notice_version_id is None:
            raise PublicAppointmentConfirmationValidationError(
                "privacy notice version is invalid."
            )

        return self._confirmation.execute(
            ConfirmAppointmentCommand(
                reference_digest=self._secret_digester.digest(
                    command.confirmation_reference
                ),
                first_name=command.first_name,
                last_name=command.last_name,
                phone=command.phone,
                email=command.email,
                service_id=service_id,
                branch=normalized_branch,
                scheduled_start=command.scheduled_start,
                privacy_consent=create_privacy_consent_evidence(
                    privacy_notice_version_id=privacy_notice_version_id,
                    accepted_at=accepted_at,
                    origin=PUBLIC_APPOINTMENT_ORIGIN,
                    contact_processing_authorized=(
                        command.contact_processing_authorized
                    ),
                    adult_responsibility_declared=(
                        command.adult_responsibility_declared
                    ),
                    confirmed_by_account_id=None,
                ),
            )
        )

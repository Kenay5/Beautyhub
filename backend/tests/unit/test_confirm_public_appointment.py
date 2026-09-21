"""T055A unit evidence for adapting the approved public request fields."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.confirm_public_appointment import (
    ConfirmPublicAppointment,
    ConfirmPublicAppointmentCommand,
    PublicAppointmentConfirmationValidationError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
START = NOW + timedelta(days=1, hours=1)


class RecordingConfirmer:
    """Application double that exposes the command, never an HTTP concern."""

    def __init__(self) -> None:
        self.commands: list[object] = []

    def execute(self, command: object) -> str:
        self.commands.append(command)
        return "confirmed"


class FakeSelectionReader:
    """Public-choice double with a visible notice version and no exposed IDs."""

    def __init__(self, service_id: int | None = 13, notice_id: int | None = 7) -> None:
        self.service_id = service_id
        self.notice_id = notice_id

    def get_active_service_id(self, *, branch: str, service_name: str) -> int | None:
        assert branch == "chiconcuac"
        assert service_name == "Manicure"
        return self.service_id

    def get_current_privacy_notice_version_id(
        self,
        *,
        version: str,
        accepted_at: datetime,
    ) -> int | None:
        assert version == "privacy-example-v1"
        assert accepted_at == NOW
        return self.notice_id


class FixedDigester:
    """Digest double that makes the reference boundary observable."""

    def digest(self, secret: str) -> bytes:
        assert secret == "synthetic-confirmation-reference"
        return b"reference-digest"


def test_t055a_resolves_only_public_choices_and_records_server_side_consent_time() -> None:
    confirmer = RecordingConfirmer()
    result = ConfirmPublicAppointment(
        confirmation=confirmer,  # type: ignore[arg-type]
        selection_reader=FakeSelectionReader(),
        clock=FixedClock(NOW),
        secret_digester=FixedDigester(),
    ).execute(_command())

    assert result == "confirmed"
    command = confirmer.commands[0]
    assert command.reference_digest == b"reference-digest"
    assert command.service_id == 13
    assert command.privacy_consent.privacy_notice_version_id == 7
    assert command.privacy_consent.accepted_at == NOW
    assert command.privacy_consent.origin == "public"
    assert command.privacy_consent.confirmed_by_account_id is None


@pytest.mark.parametrize("service_id,notice_id", [(None, 7), (13, None)])
def test_t055a_rejects_unavailable_public_choices_before_confirming(
    service_id: int | None,
    notice_id: int | None,
) -> None:
    confirmer = RecordingConfirmer()
    public_confirmer = ConfirmPublicAppointment(
        confirmation=confirmer,  # type: ignore[arg-type]
        selection_reader=FakeSelectionReader(service_id, notice_id),
        clock=FixedClock(NOW),
        secret_digester=FixedDigester(),
    )

    with pytest.raises(PublicAppointmentConfirmationValidationError):
        public_confirmer.execute(_command())

    assert confirmer.commands == []


def test_t055a_requires_each_explicit_public_privacy_confirmation() -> None:
    confirmer = RecordingConfirmer()
    public_confirmer = ConfirmPublicAppointment(
        confirmation=confirmer,  # type: ignore[arg-type]
        selection_reader=FakeSelectionReader(),
        clock=FixedClock(NOW),
        secret_digester=FixedDigester(),
    )

    with pytest.raises(PublicAppointmentConfirmationValidationError):
        public_confirmer.execute(replace(_command(), privacy_notice_accepted=False))

    assert confirmer.commands == []


def _command() -> ConfirmPublicAppointmentCommand:
    return ConfirmPublicAppointmentCommand(
        confirmation_reference="synthetic-confirmation-reference",
        first_name="Clienta",
        last_name="Ejemplo",
        phone="5510000000",
        email="clienta@example.test",
        service_name="Manicure",
        branch="chiconcuac",
        scheduled_start=START,
        privacy_notice_version="privacy-example-v1",
        privacy_notice_accepted=True,
        contact_processing_authorized=True,
        adult_responsibility_declared=True,
    )

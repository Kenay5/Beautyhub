"""T055 unit evidence for issuing and persisting a public reference."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from backend.app.application.booking_confirmation_reference import (
    IssueBookingConfirmationReference,
    IssuedBookingConfirmationReference,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.private_code_protection import PrivateCodeProtector
from backend.app.infrastructure.settings import SecretValue


NOW = datetime(2030, 6, 1, 12, tzinfo=timezone.utc)


class RecordingReferenceWriter:
    """Narrow persistence double that never receives a recoverable reference value."""

    def __init__(self) -> None:
        self.references: list[IssuedBookingConfirmationReference] = []

    def create(self, reference: IssuedBookingConfirmationReference) -> None:
        self.references.append(reference)


def test_t055_issues_and_persists_only_the_protected_reference_record() -> None:
    writer = RecordingReferenceWriter()
    secret_generator = SequenceSecretGenerator([b"\x17" * 16])
    protector = PrivateCodeProtector(
        master_key=SecretValue(base64.urlsafe_b64encode(b"\x18" * 32).decode("ascii")),
        secret_generator=secret_generator,
    )

    issued = IssueBookingConfirmationReference(
        writer=writer,
        clock=FixedClock(NOW),
        secret_generator=secret_generator,
        secret_digester=protector,
    ).execute()

    assert writer.references == [issued]
    assert issued.expires_at == NOW + timedelta(hours=24)
    assert issued.value not in repr(issued)

"""T049 and T050 tests for booking confirmation reference secrecy and expiry."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.booking_confirmation_reference import (
    BookingConfirmationReferenceError,
    StoredBookingConfirmationReference,
    issue_booking_confirmation_reference,
    require_current_booking_confirmation_reference,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.private_code_protection import PrivateCodeProtector
from backend.app.infrastructure.settings import SecretValue


FIXED_INSTANT = datetime(2030, 6, 1, 12, tzinfo=timezone.utc)


class FakeBookingConfirmationReferenceReader:
    """In-memory reader that records the digest-only lookup request."""

    def __init__(self, reference: StoredBookingConfirmationReference | None) -> None:
        self.reference = reference
        self.looked_up_digests: list[bytes] = []

    def find_by_reference_digest(
        self,
        reference_digest: bytes,
    ) -> StoredBookingConfirmationReference | None:
        self.looked_up_digests.append(reference_digest)
        if self.reference is None or self.reference.reference_digest != reference_digest:
            return None
        return self.reference


def private_code_protector() -> PrivateCodeProtector:
    return PrivateCodeProtector(
        master_key=SecretValue(
            base64.urlsafe_b64encode(b"\x14" * 32).decode("ascii")
        ),
        secret_generator=SequenceSecretGenerator([]),
    )


def test_t049_issues_an_opaque_128_bit_reference_with_exact_24_hour_expiry() -> None:
    protector = private_code_protector()
    issued = issue_booking_confirmation_reference(
        clock=FixedClock(FIXED_INSTANT),
        secret_generator=SequenceSecretGenerator([b"\x15" * 16]),
        secret_digester=protector,
    )

    assert len(base64.urlsafe_b64decode(issued.value + "==")) == 16
    assert issued.generated_at == FIXED_INSTANT
    assert issued.expires_at == FIXED_INSTANT + timedelta(hours=24)
    assert issued.reference_digest == protector.digest(issued.value)
    assert "5510000000" not in issued.value
    assert "clienta@example.test" not in issued.value
    assert issued.value not in repr(issued)


def test_t050_rejects_a_missing_reference_without_a_lookup() -> None:
    reader = FakeBookingConfirmationReferenceReader(reference=None)

    with pytest.raises(BookingConfirmationReferenceError) as error:
        require_current_booking_confirmation_reference(
            provided_reference=None,
            reader=reader,
            clock=FixedClock(FIXED_INSTANT),
            secret_digester=private_code_protector(),
        )

    assert str(error.value) == "confirmation reference is invalid."
    assert reader.looked_up_digests == []


def test_t050_rejects_a_reference_at_its_exact_expiry() -> None:
    protector = private_code_protector()
    reference_value = "synthetic-confirmation-reference"
    expires_at = FIXED_INSTANT + timedelta(hours=24)
    reader = FakeBookingConfirmationReferenceReader(
        StoredBookingConfirmationReference(
            reference_digest=protector.digest(reference_value),
            generated_at=FIXED_INSTANT,
            expires_at=expires_at,
        )
    )

    with pytest.raises(BookingConfirmationReferenceError) as error:
        require_current_booking_confirmation_reference(
            provided_reference=reference_value,
            reader=reader,
            clock=FixedClock(expires_at),
            secret_digester=protector,
        )

    assert str(error.value) == "confirmation reference is invalid."
    assert reader.looked_up_digests == [protector.digest(reference_value)]


def test_t050_returns_only_a_matching_reference_before_expiry_using_its_digest() -> None:
    protector = private_code_protector()
    reference_value = "synthetic-confirmation-reference"
    stored = StoredBookingConfirmationReference(
        reference_digest=protector.digest(reference_value),
        generated_at=FIXED_INSTANT,
        expires_at=FIXED_INSTANT + timedelta(hours=24),
    )
    reader = FakeBookingConfirmationReferenceReader(stored)

    resolved = require_current_booking_confirmation_reference(
        provided_reference=reference_value,
        reader=reader,
        clock=FixedClock(FIXED_INSTANT + timedelta(hours=24, microseconds=-1)),
        secret_digester=protector,
    )

    assert resolved == stored
    assert reader.looked_up_digests == [protector.digest(reference_value)]


def test_t050_rejects_a_nonmatching_reference_with_the_same_generic_error() -> None:
    protector = private_code_protector()
    reader = FakeBookingConfirmationReferenceReader(
        StoredBookingConfirmationReference(
            reference_digest=protector.digest("valid-reference"),
            generated_at=FIXED_INSTANT,
            expires_at=FIXED_INSTANT + timedelta(hours=24),
        )
    )

    with pytest.raises(BookingConfirmationReferenceError) as error:
        require_current_booking_confirmation_reference(
            provided_reference="wrong-reference",
            reader=reader,
            clock=FixedClock(FIXED_INSTANT),
            secret_digester=protector,
        )

    assert str(error.value) == "confirmation reference is invalid."

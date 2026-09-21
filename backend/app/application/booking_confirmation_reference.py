"""Secret confirmation references and their exact validity window."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from backend.app.application.clock import Clock
from backend.app.application.entropy import SecretGenerator


BOOKING_CONFIRMATION_REFERENCE_ENTROPY_BYTES = 16
BOOKING_CONFIRMATION_REFERENCE_LIFETIME = timedelta(hours=24)


class SecretDigester(Protocol):
    """Create a keyed digest for exact secret lookup."""

    def digest(self, secret: str) -> bytes:
        """Return the non-reversible lookup value for one secret."""


class BookingConfirmationReferenceReader(Protocol):
    """Lookup boundary that accepts only a reference digest."""

    def find_by_reference_digest(
        self,
        reference_digest: bytes,
    ) -> "StoredBookingConfirmationReference | None":
        """Return one stored reference by its keyed digest, if it exists."""


class BookingConfirmationReferenceWriter(Protocol):
    """Persistence boundary for a newly issued confirmation reference."""

    def create(self, reference: "IssuedBookingConfirmationReference") -> None:
        """Persist only the protected representation of a reference."""


class BookingConfirmationReferenceError(ValueError):
    """Raised for a missing, invalid, or expired confirmation reference."""


@dataclass(frozen=True)
class IssuedBookingConfirmationReference:
    """A one-time booking secret returned only to its reservation flow."""

    value: str = field(repr=False)
    reference_digest: bytes
    generated_at: datetime
    expires_at: datetime
    entropy_bytes: int = BOOKING_CONFIRMATION_REFERENCE_ENTROPY_BYTES


@dataclass(frozen=True)
class StoredBookingConfirmationReference:
    """Persisted reference data without the recoverable secret."""

    reference_digest: bytes
    generated_at: datetime
    expires_at: datetime


def issue_booking_confirmation_reference(
    *,
    clock: Clock,
    secret_generator: SecretGenerator,
    secret_digester: SecretDigester,
) -> IssuedBookingConfirmationReference:
    """Issue a 128-bit opaque booking reference that expires in exactly 24 hours."""

    generated_at = clock.now()
    _require_aware_instant(generated_at)
    token = secret_generator.token_bytes(BOOKING_CONFIRMATION_REFERENCE_ENTROPY_BYTES)
    if (
        not isinstance(token, bytes)
        or len(token) != BOOKING_CONFIRMATION_REFERENCE_ENTROPY_BYTES
    ):
        raise BookingConfirmationReferenceError(
            "confirmation reference generator did not return the required entropy."
        )

    value = urlsafe_b64encode(token).decode("ascii").rstrip("=")
    return IssuedBookingConfirmationReference(
        value=value,
        reference_digest=secret_digester.digest(value),
        generated_at=generated_at,
        expires_at=generated_at + BOOKING_CONFIRMATION_REFERENCE_LIFETIME,
    )


class IssueBookingConfirmationReference:
    """Issue and persist one public booking reference without HTTP concerns."""

    def __init__(
        self,
        *,
        writer: BookingConfirmationReferenceWriter,
        clock: Clock,
        secret_generator: SecretGenerator,
        secret_digester: SecretDigester,
    ) -> None:
        self._writer = writer
        self._clock = clock
        self._secret_generator = secret_generator
        self._secret_digester = secret_digester

    def execute(self) -> IssuedBookingConfirmationReference:
        """Return the sole recoverable copy after storing its digest and expiry."""

        issued = issue_booking_confirmation_reference(
            clock=self._clock,
            secret_generator=self._secret_generator,
            secret_digester=self._secret_digester,
        )
        self._writer.create(issued)
        return issued


def require_current_booking_confirmation_reference(
    *,
    provided_reference: str | None,
    reader: BookingConfirmationReferenceReader,
    clock: Clock,
    secret_digester: SecretDigester,
) -> StoredBookingConfirmationReference:
    """Return only a matching reference that remains valid at the current instant."""

    if not isinstance(provided_reference, str) or not provided_reference:
        raise BookingConfirmationReferenceError("confirmation reference is invalid.")

    current_time = clock.now()
    _require_aware_instant(current_time)
    reference = reader.find_by_reference_digest(secret_digester.digest(provided_reference))
    if reference is None or current_time >= reference.expires_at:
        raise BookingConfirmationReferenceError("confirmation reference is invalid.")

    return reference


def _require_aware_instant(instant: datetime) -> None:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise BookingConfirmationReferenceError(
            "confirmation reference time must include a timezone."
        )

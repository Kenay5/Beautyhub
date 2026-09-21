"""PostgreSQL persistence for newly issued booking confirmation references."""

from __future__ import annotations

from sqlalchemy import Connection, insert

from backend.app.application.booking_confirmation_reference import (
    BookingConfirmationReferenceWriter,
    IssuedBookingConfirmationReference,
)
from backend.app.infrastructure.persistence.models import BookingConfirmationReference


class PostgresBookingConfirmationReferenceWriter(
    BookingConfirmationReferenceWriter
):
    """Store only digest, timestamps, and future appointment association."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create(self, reference: IssuedBookingConfirmationReference) -> None:
        """Persist a one-time reference without its recoverable value."""

        self._connection.execute(
            insert(BookingConfirmationReference).values(
                reference_digest=reference.reference_digest,
                generated_at=reference.generated_at,
                expires_at=reference.expires_at,
                consumed_at=None,
                appointment_id=None,
            )
        )

"""Public HTTP contract for issuing appointment confirmation references."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from backend.app.application.booking_confirmation_reference import (
    IssueBookingConfirmationReference,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.public_request_limit import (
    PublicRequestLimiter,
    PublicRequestRateLimitError,
)
from backend.app.infrastructure.persistence.booking_confirmation_reference_repository import (
    PostgresBookingConfirmationReferenceWriter,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.security.private_code_protection import PrivateCodeProtector
from backend.app.infrastructure.settings import (
    load_private_code_master_key,
    load_settings,
)
from backend.app.web.public_request_protection import get_public_request_limiter


router = APIRouter(prefix="/api/public/booking-confirmation-references")
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class BookingConfirmationReferenceResponse(BaseModel):
    """Only the one-time value and its visible expiry leave this endpoint."""

    model_config = ConfigDict(populate_by_name=False)

    confirmation_reference: str = Field(serialization_alias="confirmationReference")
    expires_at: datetime = Field(serialization_alias="expiresAt")


def get_booking_confirmation_reference_issuer() -> Iterator[
    IssueBookingConfirmationReference
]:
    """Compose one short PostgreSQL write transaction around reference issuance."""

    engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.begin() as connection:
            yield _build_issuer(connection)
    finally:
        engine.dispose()


def _build_issuer(connection: Connection) -> IssueBookingConfirmationReference:
    secret_generator = SystemSecretGenerator()
    protector = PrivateCodeProtector(
        master_key=load_private_code_master_key(),
        secret_generator=secret_generator,
    )
    return IssueBookingConfirmationReference(
        writer=PostgresBookingConfirmationReferenceWriter(connection),
        clock=SystemClock(),
        secret_generator=secret_generator,
        secret_digester=protector,
    )


@router.post("", response_model=BookingConfirmationReferenceResponse, status_code=status.HTTP_201_CREATED)
def issue_booking_confirmation_reference(
    issuer: Annotated[
        IssueBookingConfirmationReference,
        Depends(get_booking_confirmation_reference_issuer),
    ],
    limiter: Annotated[PublicRequestLimiter, Depends(get_public_request_limiter)],
) -> BookingConfirmationReferenceResponse:
    """Issue one opaque reference before a public appointment confirmation."""

    try:
        limiter.ensure_allowed("booking_confirmation_reference")
    except PublicRequestRateLimitError as error:
        raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error

    issued = issuer.execute()
    return BookingConfirmationReferenceResponse(
        confirmation_reference=issued.value,
        expires_at=issued.expires_at,
    )

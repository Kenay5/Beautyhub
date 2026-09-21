"""Public HTTP contract for one private-code appointment lookup."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection

from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.lookup_public_appointment import (
    LookupPublicAppointment,
    PublicAppointmentCredentialError,
    PublicAppointmentRecord,
)
from backend.app.application.mask_public_contacts import (
    PublicContactMaskingError,
    mask_public_email,
    mask_public_phone,
)
from backend.app.application.public_access_restrictions import (
    ProtectPublicAppointmentLookup,
)
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.public_appointment_lookup_repository import (
    PostgresPublicAppointmentLookupReader,
)
from backend.app.infrastructure.security.private_code_protection import PrivateCodeProtector
from backend.app.infrastructure.settings import (
    load_private_code_master_key,
    load_settings,
)
from backend.app.web.public_request_protection import (
    get_public_appointment_lookup_protection,
)


router = APIRouter(prefix="/api/public/appointments")
_CREDENTIAL_DETAIL = "No fue posible validar las credenciales de la cita."
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class PublicAppointmentLookupRequest(BaseModel):
    """Accept the opaque appointment code only in a request body."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    private_code: object | None = Field(default=None, validation_alias="privateCode")


class PublicAppointmentContactResponse(BaseModel):
    """Public contacts after their approved deterministic masking."""

    phone: str
    email: str


class PublicAppointmentLookupResponse(BaseModel):
    """The approved public appointment projection without protected material."""

    model_config = ConfigDict(populate_by_name=False)

    service_name: str = Field(serialization_alias="serviceName")
    branch: str
    scheduled_start: datetime = Field(serialization_alias="scheduledStart")
    duration_minutes: int = Field(serialization_alias="durationMinutes")
    price: str
    status: str
    contact: PublicAppointmentContactResponse


def get_public_appointment_lookup() -> Iterator[LookupPublicAppointment]:
    """Compose exact lookup using the external private-code key."""

    engine = create_postgres_engine(load_settings().database_url)
    connection: Connection | None = None
    try:
        connection = engine.connect()
        protector = PrivateCodeProtector(
            master_key=load_private_code_master_key(),
            secret_generator=SystemSecretGenerator(),
        )
        yield LookupPublicAppointment(
            reader=PostgresPublicAppointmentLookupReader(connection),
            secret_digester=protector,
            clock=SystemClock(),
        )
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


@router.post("/lookup", response_model=PublicAppointmentLookupResponse)
def lookup_public_appointment(
    request: PublicAppointmentLookupRequest,
    protection: Annotated[
        ProtectPublicAppointmentLookup,
        Depends(get_public_appointment_lookup_protection),
    ],
    lookup: Annotated[
        LookupPublicAppointment,
        Depends(get_public_appointment_lookup),
    ],
) -> PublicAppointmentLookupResponse:
    """Return one safe projection without placing the code in the URL or logs."""

    try:
        protection.ensure_allowed()
        appointment = lookup.execute(request.private_code)  # type: ignore[arg-type]
    except PublicRequestRateLimitError as error:
        raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error
    except PublicAppointmentCredentialError as error:
        try:
            protection.record_invalid_credential()
        except PublicRequestRateLimitError as block_error:
            raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from block_error
        raise HTTPException(status_code=404, detail=_CREDENTIAL_DETAIL) from error

    protection.record_valid_credential()
    try:
        return _to_response(appointment)
    except PublicContactMaskingError as error:
        raise HTTPException(status_code=404, detail=_CREDENTIAL_DETAIL) from error


def _to_response(appointment: PublicAppointmentRecord) -> PublicAppointmentLookupResponse:
    """Filter the application record into the exact public response contract."""

    return PublicAppointmentLookupResponse(
        service_name=appointment.service_name,
        branch=appointment.branch,
        scheduled_start=appointment.scheduled_start,
        duration_minutes=appointment.duration_minutes,
        price=_format_price(appointment.price),
        status=appointment.status,
        contact=PublicAppointmentContactResponse(
            phone=mask_public_phone(appointment.phone),
            email=mask_public_email(appointment.email),
        ),
    )


def _format_price(price: Decimal) -> str:
    """Render the agreed MXN amount with the approved two decimal places."""

    return f"{price:.2f}"

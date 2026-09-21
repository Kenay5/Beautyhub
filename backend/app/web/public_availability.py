"""Public HTTP contract for the active BeautyHub availability query."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Connection

from backend.app.application.clock import Clock, SystemClock
from backend.app.application.list_public_availability import (
    ListPublicAvailability,
    PublicAvailabilityReader,
    PublicAvailabilityValidationError,
)
from backend.app.application.public_request_limit import (
    PublicRequestLimiter,
    PublicRequestRateLimitError,
)
from backend.app.domain.service_configuration import ServiceConfigurationValidationError
from backend.app.domain.service_duration import ServiceDurationValidationError
from backend.app.domain.service_text import ServiceTextValidationError
from backend.app.domain.time import InstantValidationError
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresPublicAvailabilityReader,
)
from backend.app.infrastructure.settings import load_settings
from backend.app.web.public_request_protection import get_public_read_request_limiter


router = APIRouter(prefix="/api/public/availability")
_SANITIZED_ERROR_DETAIL = "No fue posible consultar la disponibilidad solicitada."
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class PublicAvailabilityResponse(BaseModel):
    """Safe public representation of bookable appointment starts."""

    starts: list[datetime]


def get_public_availability_reader() -> Iterator[PublicAvailabilityReader]:
    """Open a short-lived PostgreSQL read connection for one public request."""

    engine = create_postgres_engine(load_settings().database_url)
    connection: Connection | None = None
    try:
        connection = engine.connect()
        yield PostgresPublicAvailabilityReader(connection)
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


def get_clock() -> Clock:
    """Provide the system clock at the HTTP composition boundary."""

    return SystemClock()


@router.get("", response_model=PublicAvailabilityResponse)
def list_public_availability(
    branch: str | None = None,
    service: str | None = None,
    date: str | None = None,
    limiter: Annotated[
        PublicRequestLimiter, Depends(get_public_read_request_limiter)
    ] = None,
    reader: Annotated[
        PublicAvailabilityReader, Depends(get_public_availability_reader)
    ] = None,
    clock: Annotated[Clock, Depends(get_clock)] = None,
) -> PublicAvailabilityResponse:
    """Return only starts currently valid for a public reservation request."""

    try:
        limiter.ensure_allowed("availability")  # type: ignore[union-attr]
        appointment_date = _parse_date(date)
        starts = ListPublicAvailability(reader, clock).execute(  # type: ignore[arg-type]
            branch=branch,  # type: ignore[arg-type]
            service_name=service,  # type: ignore[arg-type]
            appointment_date=appointment_date,
        )
    except PublicRequestRateLimitError as error:
        raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error
    except (
        PublicAvailabilityValidationError,
        ServiceConfigurationValidationError,
        ServiceDurationValidationError,
        ServiceTextValidationError,
        InstantValidationError,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(status_code=422, detail=_SANITIZED_ERROR_DETAIL) from error

    return PublicAvailabilityResponse(starts=list(starts))


def _parse_date(value: str | None) -> date:
    """Accept only an ISO calendar date without exposing parser details."""

    if not isinstance(value, str):
        raise PublicAvailabilityValidationError("appointment date is required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise PublicAvailabilityValidationError("appointment date is invalid") from error

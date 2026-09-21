"""Public HTTP contract for the active BeautyHub service catalog."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Connection

from backend.app.application.list_active_services import (
    ActiveServiceCatalog,
    ListActiveServices,
    PublicService,
)
from backend.app.application.public_request_limit import (
    PublicRequestLimiter,
    PublicRequestRateLimitError,
)
from backend.app.domain.service_configuration import ServiceConfigurationValidationError
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.service_repository import (
    PostgresActiveServiceCatalog,
)
from backend.app.infrastructure.settings import load_settings
from backend.app.web.public_request_protection import get_public_read_request_limiter


router = APIRouter(prefix="/api/public/services")
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class PublicServiceResponse(BaseModel):
    """Safe public representation of an active service."""

    name: str
    duration_minutes: int
    price: str


def get_active_service_catalog() -> Iterator[ActiveServiceCatalog]:
    """Open a short-lived PostgreSQL read connection for one public request."""

    engine = create_postgres_engine(load_settings().database_url)
    connection: Connection | None = None
    try:
        connection = engine.connect()
        yield PostgresActiveServiceCatalog(connection)
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


@router.get("", response_model=list[PublicServiceResponse])
def list_public_services(
    branch: str | None = None,
    limiter: Annotated[
        PublicRequestLimiter, Depends(get_public_read_request_limiter)
    ] = None,
    catalog: Annotated[ActiveServiceCatalog, Depends(get_active_service_catalog)] = None,
) -> list[PublicServiceResponse]:
    """List services that a client may select for the requested branch."""

    try:
        limiter.ensure_allowed("service_catalog")  # type: ignore[union-attr]
        services = ListActiveServices(catalog).execute(branch)  # type: ignore[arg-type]
    except PublicRequestRateLimitError as error:
        raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error
    except ServiceConfigurationValidationError as error:
        raise HTTPException(
            status_code=422,
            detail="Selecciona una sucursal válida.",
        ) from error
    return [_to_response(service) for service in services]


def _to_response(service: PublicService) -> PublicServiceResponse:
    return PublicServiceResponse(
        name=service.name,
        duration_minutes=service.duration_minutes,
        price=f"{service.price:.2f}",
    )

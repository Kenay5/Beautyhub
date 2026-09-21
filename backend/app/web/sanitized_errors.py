"""Shared sanitized HTTP errors for BeautyHub adapters."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.app.infrastructure.security.sanitized_observability import (
    log_security_event,
)


UNEXPECTED_ERROR_DETAIL = "No fue posible completar la solicitud."


async def unexpected_error_response(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Return a safe response without logging an exception or external values."""

    del request, error
    log_security_event(event="unexpected_http_error", outcome="failed")
    return JSONResponse(
        status_code=500,
        content={"detail": UNEXPECTED_ERROR_DETAIL},
    )

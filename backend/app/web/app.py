"""Minimal FastAPI entry point for the BeautyHub backend."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from backend.app.web.admin_security_headers import (
    register_administrative_security_headers,
)
from backend.app.web.frontend import register_frontend
from backend.app.web.admin_auth.owner_activation_setup import (
    router as owner_activation_setup_router,
)
from backend.app.web.admin_auth.login import router as administrative_login_router
from backend.app.web.admin_auth.password_recovery_request import (
    router as administrative_password_recovery_request_router,
)
from backend.app.web.admin_auth.password_recovery_completion import (
    router as administrative_password_recovery_completion_router,
)
from backend.app.web.admin_auth.change_password import (
    router as administrative_password_change_router,
)
from backend.app.web.admin_auth.own_email_change import (
    router as administrative_own_email_change_router,
)
from backend.app.web.admin_auth.own_email_change_confirmation import (
    router as administrative_own_email_change_confirmation_router,
)
from backend.app.web.admin_auth.recovery_code_regeneration import (
    router as administrative_recovery_code_regeneration_router,
)
from backend.app.web.admin_auth.totp_replacement import (
    router as administrative_totp_replacement_router,
)
from backend.app.web.admin_auth.totp_replacement_confirmation import (
    router as administrative_totp_replacement_confirmation_router,
)
from backend.app.web.admin_auth.lost_factor_replacement_request import (
    router as administrative_lost_factor_replacement_request_router,
)
from backend.app.web.admin_auth.logout import (
    router as administrative_logout_router,
)
from backend.app.web.admin_auth.session_context import (
    router as administrative_session_context_router,
)
from backend.app.web.admin_auth.staff_activation import (
    router as staff_activation_router,
)
from backend.app.web.admin_auth.staff_invitations import (
    router as staff_invitations_router,
)
from backend.app.web.admin_auth.forced_staff_password_reset import (
    router as forced_staff_password_reset_router,
)
from backend.app.web.admin_auth.staff_deactivation import (
    router as staff_deactivation_router,
)
from backend.app.web.admin_auth.administrative_history import (
    router as administrative_history_router,
)
from backend.app.web.public_appointment_confirmations import (
    router as public_appointment_confirmations_router,
)
from backend.app.web.public_appointment_cancellation import (
    router as public_appointment_cancellation_router,
)
from backend.app.web.public_appointment_lookup import (
    router as public_appointment_lookup_router,
)
from backend.app.web.public_appointment_reschedule import (
    router as public_appointment_reschedule_router,
)
from backend.app.web.public_availability import router as public_availability_router
from backend.app.web.public_booking_references import (
    router as public_booking_references_router,
)
from backend.app.web.public_services import router as public_services_router
from backend.app.web.public_privacy_notice import router as public_privacy_notice_router
from backend.app.infrastructure.settings import load_cryptography_key_configuration
from backend.app.infrastructure.settings import load_settings
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.application.admin_access.administrative_history_retention import (
    PurgeExpiredAdministrativeHistory,
)
from backend.app.infrastructure.persistence.administrative_history_retention_repository import (
    PostgresAdministrativeHistoryRetentionStore,
)
from backend.app.web.sanitized_errors import unexpected_error_response


_RETENTION_RECHECK_SECONDS = 60
_RETENTION_LOGGER = logging.getLogger(__name__)


def _purge_administrative_history_batch(
    engine: Engine, *, current_time: datetime
) -> int:
    with engine.begin() as connection:
        return PurgeExpiredAdministrativeHistory(
            store=PostgresAdministrativeHistoryRetentionStore(connection)
        ).purge_batch(current_time=current_time)


def _next_administrative_history_expiration(
    engine: Engine, *, current_time: datetime
) -> datetime | None:
    with engine.connect() as connection:
        return PurgeExpiredAdministrativeHistory(
            store=PostgresAdministrativeHistoryRetentionStore(connection)
        ).next_expiration(current_time=current_time)


async def _purge_all_due_administrative_history_batches(engine: Engine) -> None:
    while True:
        removed = await asyncio.to_thread(
            _purge_administrative_history_batch,
            engine,
            current_time=datetime.now(timezone.utc),
        )
        if removed == 0:
            return


async def _run_administrative_history_retention(engine: Engine) -> None:
    """Recheck due retention promptly without logging identifying payloads."""

    while True:
        try:
            await _purge_all_due_administrative_history_batches(engine)
            now = datetime.now(timezone.utc)
            next_expiration = await asyncio.to_thread(
                _next_administrative_history_expiration, engine, current_time=now
            )
            wait_seconds = _RETENTION_RECHECK_SECONDS
            if next_expiration is not None:
                wait_seconds = min(
                    wait_seconds,
                    max(0.0, (next_expiration - now).total_seconds()),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            _RETENTION_LOGGER.error(
                "Administrative history retention pass failed; it will retry."
            )
            wait_seconds = _RETENTION_RECHECK_SECONDS
        await asyncio.sleep(wait_seconds)


@asynccontextmanager
async def _application_lifespan(_app: FastAPI):
    """Recover due history-retention work before admitting application traffic."""

    engine = create_postgres_engine(load_settings().database_url)
    try:
        await _purge_all_due_administrative_history_batches(engine)
    except Exception:
        engine.dispose()
        raise
    worker = asyncio.create_task(_run_administrative_history_retention(engine))
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await asyncio.to_thread(engine.dispose)


def _request_validation_error(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    """Keep malformed public input and its original values out of responses."""

    locations = tuple(tuple(item.get("loc", ())) for item in error.errors())
    detail = "No fue posible validar la solicitud."
    if ("body", "scheduledStart") in locations:
        detail = "Indica una fecha y hora válida con zona horaria."
    return JSONResponse(
        status_code=422,
        content={"detail": detail},
    )


def create_app() -> FastAPI:
    """Create the HTTP adapter without registering feature routes."""
    load_cryptography_key_configuration()
    app = FastAPI(
        title="BeautyHub",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_application_lifespan,
    )
    app.add_exception_handler(RequestValidationError, _request_validation_error)
    app.add_exception_handler(Exception, unexpected_error_response)
    register_administrative_security_headers(app)
    app.include_router(owner_activation_setup_router)
    app.include_router(administrative_login_router)
    app.include_router(administrative_password_recovery_request_router)
    app.include_router(administrative_password_recovery_completion_router)
    app.include_router(administrative_password_change_router)
    app.include_router(administrative_own_email_change_router)
    app.include_router(administrative_own_email_change_confirmation_router)
    app.include_router(administrative_recovery_code_regeneration_router)
    app.include_router(administrative_totp_replacement_router)
    app.include_router(administrative_totp_replacement_confirmation_router)
    app.include_router(administrative_lost_factor_replacement_request_router)
    app.include_router(administrative_logout_router)
    app.include_router(administrative_session_context_router)
    app.include_router(staff_activation_router)
    app.include_router(staff_invitations_router)
    app.include_router(forced_staff_password_reset_router)
    app.include_router(staff_deactivation_router)
    app.include_router(administrative_history_router)
    app.include_router(public_appointment_confirmations_router)
    app.include_router(public_appointment_cancellation_router)
    app.include_router(public_appointment_lookup_router)
    app.include_router(public_appointment_reschedule_router)
    app.include_router(public_availability_router)
    app.include_router(public_booking_references_router)
    app.include_router(public_services_router)
    app.include_router(public_privacy_notice_router)
    register_frontend(app)
    return app


app = create_app()

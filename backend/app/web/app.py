"""Minimal FastAPI entry point for the BeautyHub backend."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
from backend.app.web.sanitized_errors import unexpected_error_response


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

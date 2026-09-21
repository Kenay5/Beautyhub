"""Public HTTP contract for one authorized appointment cancellation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import Engine

from backend.app.application.cancel_public_appointment import (
    CancelPublicAppointment,
    CancelledAppointment,
    PublicAppointmentCancellationCommand,
    PublicAppointmentCancellationNotPermittedError,
    PublicAppointmentCancellationPersistenceError,
)
from backend.app.application.booking_confirmation_reference import SecretDigester
from backend.app.application.clock import SystemClock
from backend.app.application.change_appointment_with_notifications import (
    CancelPublicAppointmentWithNotifications,
)
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
)
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.cancellation_reason import CancellationReasonValidationError
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator
from backend.app.infrastructure.persistence.notification_delivery_result_writer import (
    PostgresNotificationDeliveryResultWriter,
)
from backend.app.infrastructure.persistence.public_appointment_cancellation_repository import (
    PostgresPublicAppointmentCancellationUnitOfWork,
)
from backend.app.infrastructure.security.private_code_protection import (
    PrivateCodeProtector,
    PrivateCodeProtectionError,
)
from backend.app.infrastructure.settings import (
    load_private_code_master_key,
    load_settings,
)
from backend.app.web.public_request_protection import (
    get_public_appointment_cancellation_protection,
)
from backend.app.web.public_appointment_confirmations import (
    PublicNotificationStatusResponse,
)
from backend.app.application.public_access_restrictions import (
    ProtectPublicAppointmentLookup,
)


router = APIRouter(prefix="/api/public/appointments")
_CREDENTIAL_DETAIL = "No fue posible validar las credenciales de la cita."
_VALIDATION_DETAIL = "No fue posible cancelar la cita."
_REASON_DETAIL = "No fue posible validar el motivo de cancelación."
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class PublicAppointmentCancellationRequest(BaseModel):
    """Accept only the public cancellation credentials and optional reason."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    private_code: object | None = Field(default=None, validation_alias="privateCode")
    phone: object | None = None
    reason: StrictStr | None = None


class PublicAppointmentCancellationSummaryResponse(BaseModel):
    """Safe public cancellation summary without code, contacts, or reason."""

    model_config = ConfigDict(populate_by_name=False)

    service_name: str = Field(serialization_alias="serviceName")
    branch: str
    scheduled_start: datetime = Field(serialization_alias="scheduledStart")
    duration_minutes: int = Field(serialization_alias="durationMinutes")
    price: str
    status: str


class PublicAppointmentCancellationResponse(BaseModel):
    """Return the cancelled appointment without re-exposing protected data."""

    appointment: PublicAppointmentCancellationSummaryResponse
    notifications: list[PublicNotificationStatusResponse]


def get_public_appointment_canceller() -> Iterator[object]:
    """Compose the approved atomic PostgreSQL cancellation use case."""

    engine: Engine = create_postgres_engine(load_settings().database_url)
    try:
        clock = SystemClock()
        yield CancelPublicAppointmentWithNotifications(
            canceller=CancelPublicAppointment(
                unit_of_work=PostgresPublicAppointmentCancellationUnitOfWork(engine),
                clock=clock,
            ),
            dispatcher=NotificationDispatcher(
                email_port=EmailSimulator(outcome="accepted"),
                whatsapp_port=WhatsAppSimulator(outcome="accepted"),
                result_writer=PostgresNotificationDeliveryResultWriter(engine),
            ),
            clock=clock,
        )
    finally:
        engine.dispose()


def get_private_code_digester() -> SecretDigester:
    """Provide the keyed digest operation without exposing the root key."""

    return PrivateCodeProtector(
        master_key=load_private_code_master_key(),
        secret_generator=SystemSecretGenerator(),
    )


@router.post("/cancel", response_model=PublicAppointmentCancellationResponse)
def cancel_public_appointment(
    request: PublicAppointmentCancellationRequest,
    protection: Annotated[
        ProtectPublicAppointmentLookup,
        Depends(get_public_appointment_cancellation_protection),
    ],
    canceller: Annotated[
        CancelPublicAppointment,
        Depends(get_public_appointment_canceller),
    ],
    secret_digester: Annotated[SecretDigester, Depends(get_private_code_digester)],
) -> PublicAppointmentCancellationResponse:
    """Cancel one appointment without exposing private cancellation data."""

    try:
        protection.ensure_allowed()
        private_code_digest = _digest_private_code(request.private_code, secret_digester)
        cancelled = canceller.execute(
            PublicAppointmentCancellationCommand(
                private_code_digest=private_code_digest,
                phone=request.phone,  # type: ignore[arg-type]
                reason=request.reason,
            )
        )
    except PublicRequestRateLimitError as error:
        raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error
    except PublicAppointmentCredentialError as error:
        try:
            protection.record_invalid_credential()
        except PublicRequestRateLimitError as block_error:
            raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from block_error
        raise HTTPException(status_code=404, detail=_CREDENTIAL_DETAIL) from error
    except CancellationReasonValidationError as error:
        raise HTTPException(status_code=422, detail=_REASON_DETAIL) from error
    except PublicAppointmentCancellationPersistenceError as error:
        raise HTTPException(status_code=409, detail=_VALIDATION_DETAIL) from error
    except PublicAppointmentCancellationNotPermittedError as error:
        raise HTTPException(status_code=422, detail=_VALIDATION_DETAIL) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=_VALIDATION_DETAIL) from error

    protection.record_valid_credential()
    return PublicAppointmentCancellationResponse(
        appointment=_to_response(cancelled),
        notifications=[
            PublicNotificationStatusResponse(
                channel=delivery.channel,
                status=delivery.status,
            )
            for delivery in cancelled.deliveries
        ],
    )


def _digest_private_code(value: object, digester: SecretDigester) -> bytes:
    """Reject malformed credentials without retaining their plaintext value."""

    if not isinstance(value, str) or not value:
        raise PublicAppointmentCredentialError()
    try:
        return digester.digest(value)
    except (TypeError, ValueError, PrivateCodeProtectionError) as error:
        raise PublicAppointmentCredentialError() from error


def _to_response(appointment: CancelledAppointment) -> PublicAppointmentCancellationSummaryResponse:
    return PublicAppointmentCancellationSummaryResponse(
        service_name=appointment.service_name,
        branch=appointment.branch,
        scheduled_start=appointment.scheduled_start,
        duration_minutes=appointment.duration_minutes,
        price=_format_price(appointment.price),
        status=appointment.status,
    )


def _format_price(price: Decimal) -> str:
    return f"{price:.2f}"

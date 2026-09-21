"""Public HTTP contract for one authorized appointment reprogramming."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import Engine

from backend.app.application.clock import SystemClock
from backend.app.application.change_appointment_with_notifications import (
    ReschedulePublicAppointmentWithNotifications,
)
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.booking_confirmation_reference import SecretDigester
from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
)
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.application.reschedule_public_appointment import (
    PublicAppointmentRescheduleCommand,
    PublicAppointmentRescheduleConflictError,
    PublicAppointmentReschedulePersistenceError,
    ReschedulePublicAppointment,
)
from backend.app.domain.service import AppointmentServiceSelectionError
from backend.app.domain.service_configuration import ServiceConfigurationValidationError
from backend.app.domain.service_text import ServiceTextValidationError
from backend.app.domain.time import InstantValidationError
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator
from backend.app.infrastructure.persistence.notification_delivery_result_writer import (
    PostgresNotificationDeliveryResultWriter,
)
from backend.app.infrastructure.persistence.public_appointment_reschedule_repository import (
    PostgresPublicAppointmentRescheduleUnitOfWork,
)
from backend.app.infrastructure.security.private_code_protection import (
    PrivateCodeProtector,
    PrivateCodeProtectionError,
)
from backend.app.infrastructure.settings import (
    load_private_code_master_key,
    load_settings,
)
from backend.app.web.public_appointment_confirmations import (
    PublicAppointmentConflictSuggester,
    PublicNotificationStatusResponse,
    get_public_appointment_conflict_suggester,
)
from backend.app.web.public_request_protection import (
    get_public_appointment_modification_protection,
)
from backend.app.application.public_access_restrictions import (
    ProtectPublicAppointmentLookup,
)


router = APIRouter(prefix="/api/public/appointments")
_CREDENTIAL_DETAIL = "No fue posible validar las credenciales de la cita."
_VALIDATION_DETAIL = "No fue posible modificar la cita."
_CONFLICT_DETAIL = "El horario seleccionado ya no está disponible."
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class PublicAppointmentRescheduleRequest(BaseModel):
    """Accept only the approved public credentials and mutable appointment fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    private_code: object | None = Field(default=None, validation_alias="privateCode")
    phone: object | None = None
    service_name: StrictStr = Field(validation_alias="serviceName")
    branch: StrictStr
    scheduled_start: datetime = Field(validation_alias="scheduledStart")


class PublicAppointmentRescheduleSummaryResponse(BaseModel):
    """Safe public summary of a successful modification."""

    model_config = ConfigDict(populate_by_name=False)

    service_name: str = Field(serialization_alias="serviceName")
    branch: str
    scheduled_start: datetime = Field(serialization_alias="scheduledStart")
    duration_minutes: int = Field(serialization_alias="durationMinutes")
    price: str
    status: str


class PublicAppointmentRescheduleResponse(BaseModel):
    """Return the changed appointment without re-exposing its private code."""

    appointment: PublicAppointmentRescheduleSummaryResponse
    notifications: list[PublicNotificationStatusResponse]


def get_public_appointment_rescheduler() -> Iterator[object]:
    """Compose the approved atomic PostgreSQL modification use case."""

    engine: Engine = create_postgres_engine(load_settings().database_url)
    try:
        clock = SystemClock()
        yield ReschedulePublicAppointmentWithNotifications(
            rescheduler=ReschedulePublicAppointment(
                unit_of_work=PostgresPublicAppointmentRescheduleUnitOfWork(engine),
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


@router.post("/reschedule", response_model=PublicAppointmentRescheduleResponse)
def reschedule_public_appointment(
    request: PublicAppointmentRescheduleRequest,
    protection: Annotated[
        ProtectPublicAppointmentLookup,
        Depends(get_public_appointment_modification_protection),
    ],
    rescheduler: Annotated[
        ReschedulePublicAppointment,
        Depends(get_public_appointment_rescheduler),
    ],
    secret_digester: Annotated[SecretDigester, Depends(get_private_code_digester)],
    conflict_suggester: Annotated[
        PublicAppointmentConflictSuggester,
        Depends(get_public_appointment_conflict_suggester),
    ],
) -> PublicAppointmentRescheduleResponse | JSONResponse:
    """Apply one public modification and expose only its allowed result."""

    try:
        protection.ensure_allowed()
        private_code_digest = _digest_private_code(
            request.private_code,
            secret_digester,
        )
        modified = rescheduler.execute(
            PublicAppointmentRescheduleCommand(
                private_code_digest=private_code_digest,
                phone=request.phone,  # type: ignore[arg-type]
                service_name=request.service_name,
                branch=request.branch,
                scheduled_start=request.scheduled_start,
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
    except PublicAppointmentRescheduleConflictError as error:
        alternatives, requires_different_date = conflict_suggester.suggest(
            branch=request.branch,
            service_name=request.service_name,
            scheduled_start=request.scheduled_start,
        )
        return JSONResponse(
            status_code=409,
            content={
                "detail": _CONFLICT_DETAIL,
                "alternatives": [start.isoformat() for start in alternatives],
                "requiresDifferentDate": requires_different_date,
            },
        )
    except PublicAppointmentReschedulePersistenceError as error:
        raise HTTPException(status_code=409, detail=_CONFLICT_DETAIL) from error
    except InstantValidationError as error:
        raise HTTPException(status_code=422, detail=_time_validation_detail(error)) from error
    except (
        AppointmentServiceSelectionError,
        ServiceConfigurationValidationError,
        ServiceTextValidationError,
        TypeError,
        ValueError,
    ) as error:
        raise HTTPException(status_code=422, detail=_VALIDATION_DETAIL) from error

    protection.record_valid_credential()
    return PublicAppointmentRescheduleResponse(
        appointment=PublicAppointmentRescheduleSummaryResponse(
            service_name=modified.service_snapshot.name,
            branch=modified.branch,
            scheduled_start=modified.scheduled_start,
            duration_minutes=modified.service_snapshot.duration_minutes,
            price=_format_price(modified.service_snapshot.price),
            status=modified.status,
        ),
        notifications=[
            PublicNotificationStatusResponse(
                channel=delivery.channel,
                status=delivery.status,
            )
            for delivery in modified.deliveries
        ],
    )


def _digest_private_code(value: object, digester: SecretDigester) -> bytes:
    """Reject malformed public credentials without retaining their plaintext value."""

    if not isinstance(value, str) or not value:
        raise PublicAppointmentCredentialError()
    try:
        return digester.digest(value)
    except (TypeError, ValueError, PrivateCodeProtectionError) as error:
        raise PublicAppointmentCredentialError() from error


def _format_price(price: Decimal) -> str:
    return f"{price:.2f}"


def _time_validation_detail(error: InstantValidationError) -> str:
    messages = {
        "public appointment requires at least 60 minutes notice": (
            "La cita debe solicitarse con al menos 60 minutos de anticipación."
        ),
        "public appointment exceeds the 90-day horizon": (
            "La cita debe iniciar dentro de los próximos 90 días."
        ),
        "public appointment must start during business hours": (
            "El horario debe iniciar entre las 09:00 y las 19:00."
        ),
        "public appointment must start on the approved daily grid": (
            "El horario debe coincidir con un intervalo de 15 minutos."
        ),
        "instant must include a time zone.": (
            "Indica una fecha y hora válida con zona horaria."
        ),
    }
    return messages.get(str(error), _VALIDATION_DETAIL)

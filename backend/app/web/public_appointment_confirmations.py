"""Public HTTP contract for confirming one appointment exactly once."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from sqlalchemy import Connection

from backend.app.application.clock import Clock, SystemClock
from backend.app.application.confirm_appointment import (
    AppointmentConfirmationReferenceError,
    AppointmentServiceNotFoundError,
    AppointmentScheduleConflictError,
    ConfirmAppointment,
)
from backend.app.application.confirm_appointment_with_notifications import (
    ConfirmAppointmentWithNotifications,
)
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.list_public_availability import (
    ListPublicAvailability,
    PublicAvailabilityReader,
)
from backend.app.application.confirm_public_appointment import (
    ConfirmPublicAppointment,
    ConfirmPublicAppointmentCommand,
    PublicAppointmentConfirmationValidationError,
)
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.public_request_limit import (
    PublicRequestLimiter,
    PublicRequestRateLimitError,
)
from backend.app.domain.appointment import AppointmentValidationError
from backend.app.domain.customer_name import CustomerNameValidationError
from backend.app.domain.email_address import EmailAddressValidationError
from backend.app.domain.mexican_phone import MexicanPhoneValidationError
from backend.app.domain.privacy_consent import PrivacyConsentValidationError
from backend.app.domain.service import AppointmentServiceSelectionError
from backend.app.domain.service_configuration import ServiceConfigurationValidationError
from backend.app.domain.service_text import ServiceTextValidationError
from backend.app.domain.time import InstantValidationError
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.appointment_confirmation_repository import (
    PostgresAppointmentConfirmationUnitOfWork,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.notification_delivery_result_writer import (
    PostgresNotificationDeliveryResultWriter,
)
from backend.app.infrastructure.persistence.public_appointment_selection_repository import (
    PostgresPublicAppointmentSelectionReader,
)
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresPublicAvailabilityReader,
)
from backend.app.infrastructure.security.private_code_protection import PrivateCodeProtector
from backend.app.infrastructure.settings import (
    load_private_code_master_key,
    load_settings,
)
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator
from backend.app.web.public_request_protection import (
    get_public_appointment_operation_limiter,
)


router = APIRouter(prefix="/api/public/appointments")
_VALIDATION_DETAIL = "No fue posible validar la solicitud de cita."
_CONFLICT_DETAIL = "El horario seleccionado ya no está disponible."
_REFERENCE_DETAIL = "No fue posible confirmar la solicitud."
_RATE_LIMIT_DETAIL = "Intenta nuevamente más tarde."


class PublicPrivacyConsentRequest(BaseModel):
    """The three explicit public confirmations and visible notice version."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    notice_version: StrictStr = Field(validation_alias="noticeVersion")
    privacy_notice_accepted: StrictBool = Field(
        validation_alias="privacyNoticeAccepted"
    )
    contact_processing_authorized: StrictBool = Field(
        validation_alias="contactProcessingAuthorized"
    )
    adult_responsibility_declared: StrictBool = Field(
        validation_alias="adultResponsibilityDeclared"
    )


class PublicAppointmentConfirmationRequest(BaseModel):
    """Exactly the fields approved to create a public BeautyHub appointment."""

    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    confirmation_reference: StrictStr = Field(validation_alias="confirmationReference")
    first_name: StrictStr = Field(validation_alias="firstName")
    last_name: StrictStr = Field(validation_alias="lastName")
    phone: StrictStr
    email: StrictStr
    service_name: StrictStr = Field(validation_alias="serviceName")
    branch: StrictStr
    scheduled_start: datetime = Field(validation_alias="scheduledStart")
    privacy_consent: PublicPrivacyConsentRequest = Field(
        validation_alias="privacyConsent"
    )


class PublicAppointmentSummaryResponse(BaseModel):
    """Public confirmation summary excluding internal IDs and contact details."""

    model_config = ConfigDict(populate_by_name=False)

    service_name: str = Field(serialization_alias="serviceName")
    branch: str
    scheduled_start: datetime = Field(serialization_alias="scheduledStart")
    duration_minutes: int = Field(serialization_alias="durationMinutes")
    price: str
    status: str


class PublicNotificationStatusResponse(BaseModel):
    """One channel status without provider diagnostics or delivery identifiers."""

    channel: Literal["email", "whatsapp"]
    status: Literal["pending", "accepted", "delivered", "failed"]


class PublicAppointmentConfirmationResponse(BaseModel):
    """The only public response that reveals a newly confirmed private code."""

    model_config = ConfigDict(populate_by_name=False)

    private_code: str = Field(serialization_alias="privateCode")
    appointment: PublicAppointmentSummaryResponse
    notifications: list[PublicNotificationStatusResponse]


class PublicAppointmentConflictSuggester:
    """Calculate approved same-day alternatives only after a schedule conflict."""

    def __init__(self, reader: PublicAvailabilityReader, clock: Clock) -> None:
        self._reader = reader
        self._clock = clock

    def suggest(
        self,
        *,
        branch: str,
        service_name: str,
        scheduled_start: datetime,
    ) -> tuple[tuple[datetime, ...], bool]:
        """Return at most three valid same-day starts or a different-date signal."""

        starts = ListPublicAvailability(self._reader, self._clock).execute(
            branch=branch,
            service_name=service_name,
            appointment_date=scheduled_start.date(),
        )
        from backend.app.domain.schedule import public_same_day_alternative_suggestion

        suggestion = public_same_day_alternative_suggestion(
            requested_start=scheduled_start,
            current_time=self._clock.now(),
            available_starts=starts,
        )
        return suggestion.starts, suggestion.requires_different_date


class PostgresPublicAppointmentConflictSuggester:
    """Open PostgreSQL only if a conflict needs approved alternatives."""

    def suggest(
        self,
        *,
        branch: str,
        service_name: str,
        scheduled_start: datetime,
    ) -> tuple[tuple[datetime, ...], bool]:
        """Read current availability after the failed confirmation transaction."""

        engine = create_postgres_engine(load_settings().database_url)
        connection: Connection | None = None
        try:
            connection = engine.connect()
            return PublicAppointmentConflictSuggester(
                PostgresPublicAvailabilityReader(connection),
                SystemClock(),
            ).suggest(
                branch=branch,
                service_name=service_name,
                scheduled_start=scheduled_start,
            )
        finally:
            if connection is not None:
                connection.close()
            engine.dispose()


def get_public_appointment_conflict_suggester() -> (
    PostgresPublicAppointmentConflictSuggester
):
    """Delay any availability read until a conflict actually occurs."""

    return PostgresPublicAppointmentConflictSuggester()


def get_public_appointment_confirmer() -> Iterator[ConfirmPublicAppointment]:
    """Compose public confirmation with synchronous PostgreSQL adapters."""

    engine = create_postgres_engine(load_settings().database_url)
    connection: Connection | None = None
    try:
        connection = engine.connect()
        clock = SystemClock()
        secret_generator = SystemSecretGenerator()
        protector = PrivateCodeProtector(
            master_key=load_private_code_master_key(),
            secret_generator=secret_generator,
        )
        confirmation = ConfirmAppointment(
            unit_of_work=PostgresAppointmentConfirmationUnitOfWork(engine),
            clock=clock,
            secret_generator=secret_generator,
            private_code_protection=protector,
        )
        yield ConfirmPublicAppointment(
            confirmation=ConfirmAppointmentWithNotifications(
                confirmation=confirmation,
                dispatcher=NotificationDispatcher(
                    email_port=EmailSimulator(outcome="accepted"),
                    whatsapp_port=WhatsAppSimulator(outcome="accepted"),
                    result_writer=PostgresNotificationDeliveryResultWriter(engine),
                ),
                clock=clock,
            ),
            selection_reader=PostgresPublicAppointmentSelectionReader(connection),
            clock=clock,
            secret_digester=protector,
        )
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


@router.post("", response_model=PublicAppointmentConfirmationResponse, status_code=status.HTTP_201_CREATED)
def confirm_public_appointment(
    request: PublicAppointmentConfirmationRequest,
    limiter: Annotated[
        PublicRequestLimiter,
        Depends(get_public_appointment_operation_limiter),
    ],
    confirmer: Annotated[
        ConfirmPublicAppointment, Depends(get_public_appointment_confirmer)
    ],
    conflict_suggester: Annotated[
        PublicAppointmentConflictSuggester,
        Depends(get_public_appointment_conflict_suggester),
    ],
) -> PublicAppointmentConfirmationResponse | JSONResponse:
    """Create or replay a public appointment without exposing internal state."""

    try:
        limiter.ensure_allowed("appointment_confirmation")
        confirmed = confirmer.execute(
            ConfirmPublicAppointmentCommand(
                confirmation_reference=request.confirmation_reference,
                first_name=request.first_name,
                last_name=request.last_name,
                phone=request.phone,
                email=request.email,
                service_name=request.service_name,
                branch=request.branch,
                scheduled_start=request.scheduled_start,
                privacy_notice_version=request.privacy_consent.notice_version,
                privacy_notice_accepted=(
                    request.privacy_consent.privacy_notice_accepted
                ),
                contact_processing_authorized=(
                    request.privacy_consent.contact_processing_authorized
                ),
                adult_responsibility_declared=(
                    request.privacy_consent.adult_responsibility_declared
                ),
            )
        )
    except PublicRequestRateLimitError as error:
        raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error
    except AppointmentConfirmationReferenceError as error:
        raise HTTPException(status_code=404, detail=_REFERENCE_DETAIL) from error
    except AppointmentScheduleConflictError as error:
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
    except InstantValidationError as error:
        raise HTTPException(
            status_code=422,
            detail=_time_validation_detail(error),
        ) from error
    except _VALIDATION_ERRORS as error:
        raise HTTPException(status_code=422, detail=_VALIDATION_DETAIL) from error

    appointment = confirmed.appointment
    return PublicAppointmentConfirmationResponse(
        private_code=confirmed.private_code.value,
        appointment=PublicAppointmentSummaryResponse(
            service_name=appointment.service_snapshot.name,
            branch=appointment.branch,
            scheduled_start=appointment.scheduled_start,
            duration_minutes=appointment.service_snapshot.duration_minutes,
            price=_format_price(appointment.service_snapshot.price),
            status=appointment.status,
        ),
        notifications=[
            PublicNotificationStatusResponse(
                channel=delivery.channel,
                status=delivery.status,
            )
            for delivery in confirmed.deliveries
        ],
    )


_VALIDATION_ERRORS = (
    PublicAppointmentConfirmationValidationError,
    AppointmentValidationError,
    AppointmentServiceNotFoundError,
    AppointmentServiceSelectionError,
    CustomerNameValidationError,
    EmailAddressValidationError,
    MexicanPhoneValidationError,
    PrivacyConsentValidationError,
    ServiceConfigurationValidationError,
    ServiceTextValidationError,
)


def _format_price(price: Decimal) -> str:
    """Render the agreed MXN amount with the approved two decimal places."""

    return f"{price:.2f}"


def _time_validation_detail(error: InstantValidationError) -> str:
    """State the correctable time rule without exposing technical exception text."""

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

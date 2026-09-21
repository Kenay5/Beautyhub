"""T055 and T055A contract tests for public appointment confirmation routes."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.application.booking_confirmation_reference import (
    IssuedBookingConfirmationReference,
)
from backend.app.application.clock import FixedClock
from backend.app.application.confirm_appointment import (
    AppointmentConfirmationReferenceError,
    AppointmentScheduleConflictError,
    ConfirmationDeliveryResult,
    ConfirmedAppointment,
)
from backend.app.application.confirm_public_appointment import (
    PublicAppointmentConfirmationValidationError,
)
from backend.app.application.private_code import PrivateCode
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.appointment import AppointmentServiceSnapshot, ScheduledAppointment
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.web.app import create_app
from backend.app.web.public_appointment_confirmations import (
    get_public_appointment_confirmer,
    get_public_appointment_conflict_suggester,
)
from backend.app.web.public_booking_references import (
    get_booking_confirmation_reference_issuer,
)
from backend.app.web.public_request_protection import (
    get_public_appointment_operation_limiter,
    get_public_request_limiter,
)


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
START = NOW + timedelta(days=1, hours=1)


class FakeReferenceIssuer:
    """Controlled issuer that exposes only a synthetic public value."""

    def execute(self) -> IssuedBookingConfirmationReference:
        return IssuedBookingConfirmationReference(
            value="synthetic-confirmation-reference",
            reference_digest=b"digest-not-public",
            generated_at=NOW,
            expires_at=NOW + timedelta(hours=24),
        )


class AllowRequests:
    """Public guard double that leaves business execution untouched."""

    def ensure_allowed(self, category: str) -> None:
        assert category in {"booking_confirmation_reference", "appointment_confirmation"}


class DenyRequests:
    """Public guard double that proves the sanitized rate-limit category."""

    def ensure_allowed(self, category: str) -> None:
        raise PublicRequestRateLimitError("synthetic internal limit detail")


class AllowAppointmentOperations:
    """Public appointment guard double that leaves confirmation untouched."""

    def ensure_allowed(self, category: str) -> None:
        assert category == "appointment_confirmation"


class DenyAppointmentOperations:
    """Deny before the confirmation use case can inspect a request."""

    def ensure_allowed(self, category: str) -> None:
        assert category == "appointment_confirmation"
        raise PublicRequestRateLimitError("synthetic internal limit detail")


class FakePublicAppointmentConfirmer:
    """Controlled public use case that records exactly the accepted contract fields."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.commands: list[object] = []

    def execute(self, command: object) -> ConfirmedAppointment:
        self.commands.append(command)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]


class FakeConflictSuggester:
    """Controlled alternatives without opening PostgreSQL during a contract test."""

    def suggest(
        self,
        *,
        branch: str,
        service_name: str,
        scheduled_start: datetime,
    ) -> tuple[tuple[datetime, ...], bool]:
        assert branch == "chiconcuac"
        assert service_name == "Manicure"
        assert scheduled_start == START
        return (START - timedelta(minutes=15), START + timedelta(minutes=15)), False


def test_t055_issues_only_a_reference_and_expiry_without_internal_fields() -> None:
    app = create_app()
    app.dependency_overrides[get_booking_confirmation_reference_issuer] = FakeReferenceIssuer
    app.dependency_overrides[get_public_request_limiter] = AllowRequests

    with TestClient(app) as client:
        response = client.post("/api/public/booking-confirmation-references")

    assert response.status_code == 201
    assert response.json() == {
        "confirmationReference": "synthetic-confirmation-reference",
        "expiresAt": "2030-06-02T10:00:00-06:00",
    }


def test_t055_returns_only_the_sanitized_rate_limit_category() -> None:
    app = create_app()
    app.dependency_overrides[get_booking_confirmation_reference_issuer] = FakeReferenceIssuer
    app.dependency_overrides[get_public_request_limiter] = DenyRequests

    with TestClient(app) as client:
        response = client.post("/api/public/booking-confirmation-references")

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}


def test_t055a_confirms_only_approved_public_fields_and_filters_internal_data() -> None:
    confirmer = FakePublicAppointmentConfirmer(_confirmed_appointment())
    app = create_app()
    app.dependency_overrides[get_public_appointment_confirmer] = lambda: confirmer
    app.dependency_overrides[get_public_appointment_operation_limiter] = (
        AllowAppointmentOperations
    )

    with TestClient(app) as client:
        response = client.post("/api/public/appointments", json=_valid_request())

    assert response.status_code == 201
    assert response.json() == {
        "privateCode": "synthetic-private-code",
        "appointment": {
            "serviceName": "Manicure",
            "branch": "chiconcuac",
            "scheduledStart": "2030-06-02T11:00:00-06:00",
            "durationMinutes": 60,
            "price": "350.00",
            "status": "scheduled",
        },
        "notifications": [
            {"channel": "email", "status": "pending"},
            {"channel": "whatsapp", "status": "pending"},
        ],
    }
    assert len(confirmer.commands) == 1
    response_text = response.text
    for prohibited_value in (
        "appointment_id",
        "delivery_id",
        "5510000000",
        "clienta@example.test",
        "ciphertext",
        "digest",
    ):
        assert prohibited_value not in response_text


def test_t055a_rejects_additional_or_malformed_fields_without_echoing_input() -> None:
    app = create_app()
    app.dependency_overrides[get_public_appointment_confirmer] = lambda: (
        FakePublicAppointmentConfirmer(_confirmed_appointment())
    )
    app.dependency_overrides[get_public_appointment_operation_limiter] = (
        AllowAppointmentOperations
    )
    payload = _valid_request()
    payload["internalId"] = "must-not-be-accepted"

    with TestClient(app) as client:
        response = client.post("/api/public/appointments", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "No fue posible validar la solicitud."}
    assert "internalId" not in response.text


def test_t055a_distinguishes_validation_conflict_reference_and_limit_categories() -> None:
    scenarios = (
        (
            PublicAppointmentConfirmationValidationError("synthetic validation"),
            AllowAppointmentOperations,
            422,
            "No fue posible validar la solicitud de cita.",
        ),
        (
            AppointmentConfirmationReferenceError("synthetic reference"),
            AllowAppointmentOperations,
            404,
            "No fue posible confirmar la solicitud.",
        ),
        (
            _confirmed_appointment(),
            DenyAppointmentOperations,
            429,
            "Intenta nuevamente más tarde.",
        ),
    )

    for result, limiter, expected_status, expected_detail in scenarios:
        app = create_app()
        app.dependency_overrides[get_public_appointment_confirmer] = (
            lambda result=result: FakePublicAppointmentConfirmer(result)
        )
        app.dependency_overrides[get_public_appointment_operation_limiter] = limiter

        with TestClient(app) as client:
            response = client.post("/api/public/appointments", json=_valid_request())

        assert response.status_code == expected_status
        assert response.json() == {"detail": expected_detail}
        assert "synthetic" not in response.text


def test_t055a_returns_only_same_day_alternatives_for_a_schedule_conflict() -> None:
    app = create_app()
    app.dependency_overrides[get_public_appointment_confirmer] = lambda: (
        FakePublicAppointmentConfirmer(AppointmentScheduleConflictError("synthetic"))
    )
    app.dependency_overrides[get_public_appointment_operation_limiter] = (
        AllowAppointmentOperations
    )
    app.dependency_overrides[get_public_appointment_conflict_suggester] = (
        FakeConflictSuggester
    )

    with TestClient(app) as client:
        response = client.post("/api/public/appointments", json=_valid_request())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "El horario seleccionado ya no está disponible.",
        "alternatives": [
            "2030-06-02T10:45:00-06:00",
            "2030-06-02T11:15:00-06:00",
        ],
        "requiresDifferentDate": False,
    }
    assert "synthetic" not in response.text


def test_t068_rejects_before_the_public_confirmation_use_case_runs() -> None:
    confirmer = FakePublicAppointmentConfirmer(_confirmed_appointment())
    app = create_app()
    app.dependency_overrides[get_public_appointment_confirmer] = lambda: confirmer
    app.dependency_overrides[get_public_appointment_operation_limiter] = (
        DenyAppointmentOperations
    )

    with TestClient(app) as client:
        response = client.post("/api/public/appointments", json=_valid_request())

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert "synthetic" not in response.text
    assert confirmer.commands == []


def _valid_request() -> dict[str, object]:
    return {
        "confirmationReference": "synthetic-confirmation-reference",
        "firstName": "Clienta",
        "lastName": "Ejemplo",
        "phone": "5510000000",
        "email": "clienta@example.test",
        "serviceName": "Manicure",
        "branch": "chiconcuac",
        "scheduledStart": "2030-06-02T11:00:00-06:00",
        "privacyConsent": {
            "noticeVersion": "privacy-example-v1",
            "privacyNoticeAccepted": True,
            "contactProcessingAuthorized": True,
            "adultResponsibilityDeclared": True,
        },
    }


def _confirmed_appointment() -> ConfirmedAppointment:
    consent = create_privacy_consent_evidence(
        privacy_notice_version_id=7,
        accepted_at=NOW,
        origin=PUBLIC_APPOINTMENT_ORIGIN,
        contact_processing_authorized=True,
        adult_responsibility_declared=True,
        confirmed_by_account_id=None,
    )
    appointment = ScheduledAppointment(
        private_code_ciphertext=b"synthetic-ciphertext",
        private_code_digest=b"synthetic-digest",
        first_name="Clienta",
        last_name="Ejemplo",
        phone="5510000000",
        email="clienta@example.test",
        service_snapshot=AppointmentServiceSnapshot(
            service_id=13,
            name="Manicure",
            duration_minutes=60,
            price=Decimal("350.00"),
        ),
        branch="chiconcuac",
        scheduled_start=START,
        scheduled_end=START + timedelta(hours=1),
        status="scheduled",
        privacy_consent=consent,
    )
    return ConfirmedAppointment(
        appointment_id=29,
        appointment=appointment,
        private_code=PrivateCode("synthetic-private-code"),
        deliveries=(
            ConfirmationDeliveryResult(31, "email", "pending"),
            ConfirmationDeliveryResult(32, "whatsapp", "pending"),
        ),
    )

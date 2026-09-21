"""T081 contract evidence for public appointment cancellation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.application.cancel_public_appointment import (
    CancelledAppointment,
    PublicAppointmentCancellationCommand,
    PublicAppointmentCancellationNotPermittedError,
)
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.domain.notification_delivery import ACCEPTED_DELIVERY_STATUS, FAILED_DELIVERY_STATUS
from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
)
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.web.app import create_app
from backend.app.web.public_appointment_cancellation import (
    get_private_code_digester,
    get_public_appointment_canceller,
)
from backend.app.web.public_request_protection import (
    get_public_appointment_cancellation_protection,
)


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
START = NOW + timedelta(hours=1)
PRIVATE_CODE = "synthetic-private-code-not-for-production"
REASON = "Motivo privado no debe aparecer"


class FakeCanceller:
    """Controlled application boundary for the public HTTP contract."""

    def __init__(self, result: CancelledAppointment | Exception) -> None:
        self._result = result
        self.commands: list[PublicAppointmentCancellationCommand] = []

    def execute(self, command: PublicAppointmentCancellationCommand) -> CancelledAppointment:
        self.commands.append(command)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class MappingDigester:
    """Return a deterministic fixture digest without exposing a production key."""

    def digest(self, secret: str) -> bytes:
        if not isinstance(secret, str) or not secret:
            raise ValueError("synthetic malformed private code")
        return f"digest:{secret}".encode("ascii")


class AllowCancellationProtection:
    def __init__(self) -> None:
        self.allowed = 0
        self.invalid = 0
        self.valid = 0

    def ensure_allowed(self) -> None:
        self.allowed += 1

    def record_invalid_credential(self) -> None:
        self.invalid += 1

    def record_valid_credential(self) -> None:
        self.valid += 1


class DenyCancellationProtection(AllowCancellationProtection):
    def ensure_allowed(self) -> None:
        super().ensure_allowed()
        raise PublicRequestRateLimitError("synthetic internal rate detail")


def test_t081_returns_cancelled_summary_without_reason_or_private_code(caplog) -> None:
    canceller = FakeCanceller(_cancelled_appointment())
    protection = AllowCancellationProtection()
    app = _app(canceller=canceller, protection=protection)

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        response = client.post("/api/public/appointments/cancel", json=_request())

    assert response.status_code == 200
    assert response.json() == {
        "appointment": {
            "serviceName": "Servicio sintético",
            "branch": "chiconcuac",
            "scheduledStart": "2030-06-01T11:00:00-06:00",
            "durationMinutes": 90,
            "price": "450.00",
            "status": "cancelled",
        },
        "notifications": [],
    }
    assert canceller.commands == [
        PublicAppointmentCancellationCommand(
            private_code_digest=b"digest:synthetic-private-code-not-for-production",
            phone="55 1000 0000",
            reason=REASON,
        )
    ]
    assert protection.allowed == 1
    assert protection.valid == 1
    assert protection.invalid == 0
    for prohibited_value in (
        PRIVATE_CODE,
        "digest:synthetic-private-code-not-for-production",
        REASON,
        "5510000000",
        "clienta@example.test",
        "appointment_id",
        "privateCode",
    ):
        assert prohibited_value not in response.text
        assert prohibited_value not in caplog.text


def test_t081_accepts_a_request_already_revalidated_at_the_exact_one_hour_boundary() -> None:
    canceller = FakeCanceller(_cancelled_appointment())
    app = _app(canceller=canceller, protection=AllowCancellationProtection())

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/cancel", json=_request())

    assert response.status_code == 200
    assert canceller.commands[0].reason == REASON
    assert canceller.commands[0].private_code_digest.startswith(b"digest:")


def test_t081_maps_a_request_one_second_after_the_boundary_to_a_safe_error() -> None:
    canceller = FakeCanceller(PublicAppointmentCancellationNotPermittedError())
    app = _app(canceller=canceller, protection=AllowCancellationProtection())

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/cancel", json=_request())

    assert response.status_code == 422
    assert response.json() == {"detail": "No fue posible cancelar la cita."}
    assert PRIVATE_CODE not in response.text
    assert REASON not in response.text


def test_t081_returns_generic_credentials_error_without_echoing_credentials() -> None:
    protection = AllowCancellationProtection()
    app = _app(
        canceller=FakeCanceller(PublicAppointmentCredentialError()),
        protection=protection,
    )

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/cancel", json=_request())

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No fue posible validar las credenciales de la cita."
    }
    assert protection.invalid == 1
    assert PRIVATE_CODE not in response.text
    assert REASON not in response.text


def test_t081_rejects_a_rate_limited_request_before_cancellation() -> None:
    canceller = FakeCanceller(_cancelled_appointment())
    protection = DenyCancellationProtection()
    app = _app(canceller=canceller, protection=protection)

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/cancel", json=_request())

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert canceller.commands == []
    assert PRIVATE_CODE not in response.text


def test_t093_exposes_failed_whatsapp_without_internal_diagnostics() -> None:
    result = _cancelled_appointment()
    result = CancelledAppointment(
        **{**result.__dict__, "deliveries": (
            ChangeNotificationDelivery(1, "email", ACCEPTED_DELIVERY_STATUS),
            ChangeNotificationDelivery(2, "whatsapp", FAILED_DELIVERY_STATUS),
        )}
    )
    response = _request_response(FakeCanceller(result))
    assert response.status_code == 200
    assert response.json()["notifications"] == [
        {"channel": "email", "status": "accepted"},
        {"channel": "whatsapp", "status": "failed"},
    ]
    assert "provider" not in response.text.lower()
    assert "exception" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def test_t081_forbids_fields_outside_the_public_cancellation_contract() -> None:
    app = _app(
        canceller=FakeCanceller(_cancelled_appointment()),
        protection=AllowCancellationProtection(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/public/appointments/cancel",
            json={**_request(), "status": "cancelled"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "No fue posible validar la solicitud."}


def _app(*, canceller: FakeCanceller, protection: AllowCancellationProtection):
    app = create_app()
    app.dependency_overrides[get_public_appointment_canceller] = lambda: canceller
    app.dependency_overrides[get_public_appointment_cancellation_protection] = (
        lambda: protection
    )
    app.dependency_overrides[get_private_code_digester] = MappingDigester
    return app


def _request_response(canceller: FakeCanceller):
    with TestClient(_app(canceller=canceller, protection=AllowCancellationProtection())) as client:
        return client.post("/api/public/appointments/cancel", json=_request())


def _request() -> dict[str, object]:
    return {
        "privateCode": PRIVATE_CODE,
        "phone": "55 1000 0000",
        "reason": REASON,
    }


def _cancelled_appointment() -> CancelledAppointment:
    return CancelledAppointment(
        appointment_id=29,
        service_name="Servicio sintético",
        duration_minutes=90,
        price=Decimal("450.00"),
        branch="chiconcuac",
        scheduled_start=START,
        scheduled_end=START + timedelta(minutes=90),
        status="cancelled",
        email="clienta@example.test",
        phone="5510000000",
        deliveries=(),
    )

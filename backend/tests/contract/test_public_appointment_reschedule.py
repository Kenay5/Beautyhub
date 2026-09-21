"""T077 contract evidence for public appointment reprogramming."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
)
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.domain.notification_delivery import ACCEPTED_DELIVERY_STATUS, FAILED_DELIVERY_STATUS
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.application.reschedule_public_appointment import (
    PublicAppointmentRescheduleConflictError,
    PublicAppointmentRescheduleCommand,
    RescheduledAppointment,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.web.app import create_app
from backend.app.web.public_appointment_confirmations import (
    get_public_appointment_conflict_suggester,
)
from backend.app.web.public_appointment_reschedule import (
    get_private_code_digester,
    get_public_appointment_rescheduler,
)
from backend.app.web.public_request_protection import (
    get_public_appointment_modification_protection,
)


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
START = NOW + timedelta(days=1, hours=1)
PRIVATE_CODE = "synthetic-private-code-not-for-production"


class FakeRescheduler:
    """Controlled application boundary without opening PostgreSQL in a contract test."""

    def __init__(self, result: RescheduledAppointment | Exception) -> None:
        self._result = result
        self.commands: list[PublicAppointmentRescheduleCommand] = []

    def execute(
        self,
        command: PublicAppointmentRescheduleCommand,
    ) -> RescheduledAppointment:
        self.commands.append(command)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class MappingDigester:
    """Return a deterministic non-secret fixture digest."""

    def digest(self, secret: str) -> bytes:
        if not isinstance(secret, str) or not secret:
            raise ValueError("synthetic malformed private code")
        return f"digest:{secret}".encode("ascii")


class AllowModificationProtection:
    """Capture credential accounting without persisting a request event."""

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


class DenyModificationProtection(AllowModificationProtection):
    """Deny before any credential or appointment data is inspected."""

    def ensure_allowed(self) -> None:
        super().ensure_allowed()
        raise PublicRequestRateLimitError("synthetic internal rate detail")


class FakeConflictSuggester:
    """Return controlled same-day alternatives from the approved adapter seam."""

    def suggest(
        self,
        *,
        branch: str,
        service_name: str,
        scheduled_start: datetime,
    ) -> tuple[tuple[datetime, ...], bool]:
        assert branch == "chiconcuac"
        assert service_name == "Servicio sintético"
        assert scheduled_start == START
        return (START - timedelta(minutes=15), START + timedelta(minutes=15)), False


def test_t077_returns_only_the_modified_public_summary_without_the_private_code(
    caplog,
) -> None:
    rescheduler = FakeRescheduler(_modified_appointment())
    protection = AllowModificationProtection()
    app = _app(rescheduler=rescheduler, protection=protection)

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        response = client.post("/api/public/appointments/reschedule", json=_request())

    assert response.status_code == 200
    assert response.json() == {
        "appointment": {
            "serviceName": "Servicio sintético",
            "branch": "chiconcuac",
            "scheduledStart": "2030-06-02T11:00:00-06:00",
            "durationMinutes": 90,
            "price": "450.00",
            "status": "scheduled",
        },
        "notifications": [],
    }
    assert rescheduler.commands == [
        PublicAppointmentRescheduleCommand(
            private_code_digest=b"digest:synthetic-private-code-not-for-production",
            phone="55 1000 0000",
            service_name="Servicio sintético",
            branch="chiconcuac",
            scheduled_start=START,
        )
    ]
    assert protection.allowed == 1
    assert protection.valid == 1
    assert protection.invalid == 0
    for prohibited_value in (
        PRIVATE_CODE,
        "digest:synthetic-private-code-not-for-production",
        "5510000000",
        "clienta@example.test",
        "appointment_id",
        "privateCode",
        "ciphertext",
    ):
        assert prohibited_value not in response.text
        assert prohibited_value not in caplog.text


def test_t077_returns_one_generic_credential_error_without_echoing_credentials() -> None:
    rescheduler = FakeRescheduler(PublicAppointmentCredentialError())
    protection = AllowModificationProtection()
    app = _app(rescheduler=rescheduler, protection=protection)

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/reschedule", json=_request())

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No fue posible validar las credenciales de la cita."
    }
    assert PRIVATE_CODE not in response.text
    assert protection.allowed == 1
    assert protection.invalid == 1
    assert protection.valid == 0


def test_t077_returns_same_day_alternatives_for_a_schedule_conflict() -> None:
    rescheduler = FakeRescheduler(
        PublicAppointmentRescheduleConflictError("synthetic conflict")
    )
    protection = AllowModificationProtection()
    app = _app(rescheduler=rescheduler, protection=protection)
    app.dependency_overrides[get_public_appointment_conflict_suggester] = (
        FakeConflictSuggester
    )

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/reschedule", json=_request())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "El horario seleccionado ya no está disponible.",
        "alternatives": [
            "2030-06-02T10:45:00-06:00",
            "2030-06-02T11:15:00-06:00",
        ],
        "requiresDifferentDate": False,
    }
    assert PRIVATE_CODE not in response.text
    assert "synthetic conflict" not in response.text
    assert protection.allowed == 1
    assert protection.invalid == protection.valid == 0


def test_t077_rejects_a_limited_request_before_rescheduling() -> None:
    rescheduler = FakeRescheduler(_modified_appointment())
    protection = DenyModificationProtection()
    app = _app(rescheduler=rescheduler, protection=protection)

    with TestClient(app) as client:
        response = client.post("/api/public/appointments/reschedule", json=_request())

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert rescheduler.commands == []
    assert protection.allowed == 1
    assert protection.invalid == protection.valid == 0
    assert PRIVATE_CODE not in response.text


def test_t093_exposes_only_the_failed_channel_and_keeps_success() -> None:
    result = _modified_appointment()
    result = RescheduledAppointment(
        **{**result.__dict__, "deliveries": (
            ChangeNotificationDelivery(1, "email", FAILED_DELIVERY_STATUS),
            ChangeNotificationDelivery(2, "whatsapp", ACCEPTED_DELIVERY_STATUS),
        )}
    )
    response = _request_response(FakeRescheduler(result))
    assert response.status_code == 200
    assert response.json()["notifications"] == [
        {"channel": "email", "status": "failed"},
        {"channel": "whatsapp", "status": "accepted"},
    ]
    assert "provider" not in response.text.lower()
    assert "exception" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def _app(
    *,
    rescheduler: FakeRescheduler,
    protection: AllowModificationProtection,
):
    app = create_app()
    app.dependency_overrides[get_public_appointment_rescheduler] = lambda: rescheduler
    app.dependency_overrides[get_public_appointment_modification_protection] = (
        lambda: protection
    )
    app.dependency_overrides[get_private_code_digester] = MappingDigester
    return app


def _request_response(rescheduler: FakeRescheduler):
    with TestClient(_app(rescheduler=rescheduler, protection=AllowModificationProtection())) as client:
        return client.post("/api/public/appointments/reschedule", json=_request())


def _request() -> dict[str, object]:
    return {
        "privateCode": PRIVATE_CODE,
        "phone": "55 1000 0000",
        "serviceName": "Servicio sintético",
        "branch": "chiconcuac",
        "scheduledStart": "2030-06-02T11:00:00-06:00",
    }


def _modified_appointment() -> RescheduledAppointment:
    return RescheduledAppointment(
        appointment_id=29,
        service_snapshot=AppointmentServiceSnapshot(
            service_id=17,
            name="Servicio sintético",
            duration_minutes=90,
            price=Decimal("450.00"),
        ),
        branch="chiconcuac",
        scheduled_start=START,
        scheduled_end=START + timedelta(minutes=90),
        status="scheduled",
        email="clienta@example.test",
        phone="5510000000",
        deliveries=(),
    )

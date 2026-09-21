"""T070 contract evidence for body-only public appointment lookup."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.application.lookup_public_appointment import (
    LookupPublicAppointment,
    PublicAppointmentCredentialError,
    PublicAppointmentRecord,
)
from backend.app.application.clock import FixedClock
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.time import BUSINESS_TIME_ZONE
from backend.app.web.app import create_app
from backend.app.web.public_appointment_lookup import get_public_appointment_lookup
from backend.app.web.public_request_protection import (
    get_public_appointment_lookup_protection,
)


PRIVATE_CODE = "synthetic-private-code-not-for-production"
NOW = datetime(2030, 6, 2, 11, tzinfo=BUSINESS_TIME_ZONE)


class FakeLookup:
    """Controlled lookup double that retains only the submitted synthetic code."""

    def __init__(self, result: PublicAppointmentRecord | Exception) -> None:
        self._result = result
        self.codes: list[object] = []

    def execute(self, private_code: object) -> PublicAppointmentRecord:
        self.codes.append(private_code)
        if not isinstance(private_code, str) or not private_code:
            raise PublicAppointmentCredentialError()
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class AllowLookupProtection:
    """Controlled guard that proves lookup runs through the dedicated category."""

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


class DenyLookupProtection(AllowLookupProtection):
    """Prove rate restriction occurs before the private-code lookup."""

    def ensure_allowed(self) -> None:
        super().ensure_allowed()
        raise PublicRequestRateLimitError("synthetic internal rate detail")


class MappingDigester:
    """Controlled private-code boundary that gives each fixture a distinct digest."""

    def digest(self, secret: str) -> bytes:
        return f"digest:{secret}".encode("utf-8")


class DigestMappedReader:
    """In-memory exact-digest reader for the public contract boundary."""

    def __init__(self, records: dict[bytes, PublicAppointmentRecord]) -> None:
        self._records = records
        self.digests: list[bytes] = []

    def find_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> PublicAppointmentRecord | None:
        self.digests.append(private_code_digest)
        return self._records.get(private_code_digest)


def test_t070_accepts_the_private_code_only_in_the_body_and_filters_response(
    caplog,
) -> None:
    lookup = FakeLookup(_record())
    protection = AllowLookupProtection()
    app = create_app()
    app.dependency_overrides[get_public_appointment_lookup] = lambda: lookup
    app.dependency_overrides[get_public_appointment_lookup_protection] = lambda: protection

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": PRIVATE_CODE},
        )

    assert response.status_code == 200
    assert response.json() == {
        "serviceName": "Servicio sintético",
        "branch": "chiconcuac",
        "scheduledStart": "2030-06-02T11:00:00-06:00",
        "durationMinutes": 60,
        "price": "350.00",
        "status": "scheduled",
        "contact": {"phone": "******0000", "email": "c***@e***.test"},
    }
    assert lookup.codes == [PRIVATE_CODE]
    assert protection.allowed == 1
    assert protection.valid == 1
    assert protection.invalid == 0
    for prohibited_value in (
        PRIVATE_CODE,
        "5510000000",
        "clienta@example.test",
        "private_code_digest",
        "private_code_ciphertext",
        "appointment_id",
    ):
        assert prohibited_value not in response.text
        assert prohibited_value not in caplog.text


def test_t070_does_not_accept_a_private_code_from_the_url() -> None:
    lookup = FakeLookup(_record())
    protection = AllowLookupProtection()
    app = create_app()
    app.dependency_overrides[get_public_appointment_lookup] = lambda: lookup
    app.dependency_overrides[get_public_appointment_lookup_protection] = lambda: protection

    with TestClient(app) as client:
        response = client.post(
            "/api/public/appointments/lookup",
            params={"privateCode": PRIVATE_CODE},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "No fue posible validar la solicitud."}
    assert lookup.codes == []
    assert protection.allowed == 0
    assert protection.invalid == 0
    assert PRIVATE_CODE not in response.text


def test_t070_records_a_malformed_body_code_as_an_invalid_credential() -> None:
    lookup = FakeLookup(_record())
    protection = AllowLookupProtection()
    app = create_app()
    app.dependency_overrides[get_public_appointment_lookup] = lambda: lookup
    app.dependency_overrides[get_public_appointment_lookup_protection] = lambda: protection

    with TestClient(app) as client:
        response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": ["not", "a", "code"]},
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No fue posible validar las credenciales de la cita."
    }
    assert lookup.codes == [["not", "a", "code"]]
    assert protection.invalid == 1


def test_t070_returns_a_generic_credential_error_without_echoing_the_code() -> None:
    lookup = FakeLookup(PublicAppointmentCredentialError())
    protection = AllowLookupProtection()
    app = create_app()
    app.dependency_overrides[get_public_appointment_lookup] = lambda: lookup
    app.dependency_overrides[get_public_appointment_lookup_protection] = lambda: protection

    with TestClient(app) as client:
        response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": PRIVATE_CODE},
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "No fue posible validar las credenciales de la cita."
    }
    assert protection.invalid == 1
    assert protection.valid == 0
    assert PRIVATE_CODE not in response.text


def test_t070_rejects_rate_limited_lookup_before_reading_the_code() -> None:
    lookup = FakeLookup(_record())
    protection = DenyLookupProtection()
    app = create_app()
    app.dependency_overrides[get_public_appointment_lookup] = lambda: lookup
    app.dependency_overrides[get_public_appointment_lookup_protection] = lambda: protection

    with TestClient(app) as client:
        response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": PRIVATE_CODE},
        )

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert lookup.codes == []
    assert protection.invalid == 0
    assert PRIVATE_CODE not in response.text


def test_t072_public_lookup_isolates_appointments_and_sanitizes_rejections(
    caplog,
) -> None:
    first_code = "synthetic-first-appointment-code"
    second_code = "synthetic-second-appointment-code"
    expired_code = "synthetic-expired-appointment-code"
    unknown_code = "synthetic-unknown-appointment-code"
    first = _isolated_record(
        service_name="Servicio sintético uno",
        branch="texcoco",
        phone="5511111111",
        email="one@example.test",
    )
    second = _isolated_record(
        service_name="Servicio sintético dos",
        branch="chiconcuac",
        phone="5522222222",
        email="two@example.test",
    )
    expired = _isolated_record(
        service_name="Servicio sintético vencido",
        branch="texcoco",
        phone="5533333333",
        email="expired@example.test",
        scheduled_start=datetime(2030, 5, 1, 11, tzinfo=BUSINESS_TIME_ZONE),
    )
    digester = MappingDigester()
    reader = DigestMappedReader({
        digester.digest(first_code): first,
        digester.digest(second_code): second,
        digester.digest(expired_code): expired,
    })
    lookup = LookupPublicAppointment(
        reader=reader,
        secret_digester=digester,
        clock=FixedClock(NOW),
    )
    protection = AllowLookupProtection()
    app = create_app()
    app.dependency_overrides[get_public_appointment_lookup] = lambda: lookup
    app.dependency_overrides[get_public_appointment_lookup_protection] = lambda: protection

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        first_response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": first_code},
        )
        second_response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": second_code},
        )
        unknown_response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": unknown_code},
        )
        expired_response = client.post(
            "/api/public/appointments/lookup",
            json={"privateCode": expired_code},
        )

    assert first_response.status_code == 200
    assert first_response.json() == {
        "serviceName": "Servicio sintético uno",
        "branch": "texcoco",
        "scheduledStart": "2030-06-02T11:00:00-06:00",
        "durationMinutes": 60,
        "price": "350.00",
        "status": "scheduled",
        "contact": {"phone": "******1111", "email": "o***@e***.test"},
    }
    assert second_response.status_code == 200
    assert second_response.json() == {
        "serviceName": "Servicio sintético dos",
        "branch": "chiconcuac",
        "scheduledStart": "2030-06-02T11:00:00-06:00",
        "durationMinutes": 60,
        "price": "350.00",
        "status": "scheduled",
        "contact": {"phone": "******2222", "email": "t***@e***.test"},
    }
    assert unknown_response.status_code == expired_response.status_code == 404
    assert unknown_response.json() == expired_response.json() == {
        "detail": "No fue posible validar las credenciales de la cita."
    }
    assert reader.digests == [
        b"digest:synthetic-first-appointment-code",
        b"digest:synthetic-second-appointment-code",
        b"digest:synthetic-unknown-appointment-code",
        b"digest:synthetic-expired-appointment-code",
    ]
    assert protection.allowed == 4
    assert protection.valid == 2
    assert protection.invalid == 2

    for response, prohibited_values in (
        (first_response, (second_code, "Servicio sintético dos", "5522222222", "two@example.test", "digest:synthetic-second-appointment-code")),
        (second_response, (first_code, "Servicio sintético uno", "5511111111", "one@example.test", "digest:synthetic-first-appointment-code")),
        (unknown_response, (first_code, second_code, expired_code, unknown_code, "Servicio sintético uno", "Servicio sintético dos", "Servicio sintético vencido", "5511111111", "5522222222", "5533333333", "one@example.test", "two@example.test", "expired@example.test")),
    ):
        for value in prohibited_values:
            assert value not in response.text
            assert value not in caplog.text


def _record() -> PublicAppointmentRecord:
    return PublicAppointmentRecord(
        service_name="Servicio sintético",
        duration_minutes=60,
        price=Decimal("350.00"),
        branch="chiconcuac",
        scheduled_start=NOW,
        status="scheduled",
        phone="5510000000",
        email="clienta@example.test",
    )


def _isolated_record(
    *,
    service_name: str,
    branch: str,
    phone: str,
    email: str,
    scheduled_start: datetime = NOW,
) -> PublicAppointmentRecord:
    return PublicAppointmentRecord(
        service_name=service_name,
        duration_minutes=60,
        price=Decimal("350.00"),
        branch=branch,
        scheduled_start=scheduled_start,
        status="scheduled",
        phone=phone,
        email=email,
    )

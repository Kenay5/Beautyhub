"""T091 contracts keep shared public 429 responses generic and side-effect free."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.login_session import (
    AdministrativeLoginSessionOutcome,
)
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.web.admin_auth.login import get_administrative_login, router as login_router
from backend.app.web.admin_auth.password_recovery_request import (
    get_password_recovery_operations,
    router as recovery_router,
)
from backend.app.web.public_availability import (
    get_public_availability_reader,
    router as availability_router,
)
from backend.app.web.public_request_protection import (
    get_public_authentication_request_limiter,
    get_public_read_request_limiter,
)


RATE_LIMIT_DETAIL = "Demasiadas solicitudes. Inténtalo más tarde."


class DeniedPublicAuthenticationRequests:
    def __init__(self) -> None:
        self.categories: list[str] = []

    def ensure_allowed(self, category: str) -> None:
        self.categories.append(category)
        raise PublicRequestRateLimitError("private limiter diagnostics")


class AllowPublicReads:
    def ensure_allowed(self, category: str) -> None:
        assert category == "availability"


class LoginOperation:
    def __init__(self) -> None:
        self.calls = 0

    def login(self, **_credentials) -> AdministrativeLoginSessionOutcome:
        self.calls += 1
        return AdministrativeLoginSessionOutcome(rejection="invalid_credentials")


class RecoveryOperation:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, **_values) -> None:
        self.calls += 1


class RateLimitedRecoveryOperation:
    def __init__(self) -> None:
        self.checked_emails: list[str] = []
        self.recovery_started = 0

    def request(self, *, email: str) -> None:
        self.checked_emails.append(email)
        raise PublicRequestRateLimitError("private limiter diagnostics")


class AvailabilityReader:
    def __init__(self) -> None:
        self.calls = 0

    def get_active_service_duration(self, *_args):
        self.calls += 1
        return 60

    def list_scheduled_intervals(self):
        self.calls += 1
        return ()

    def list_applicable_blocks(self, *_args):
        self.calls += 1
        return ()


def test_t091_limited_login_does_not_validate_credentials_or_create_session() -> None:
    app = FastAPI()
    app.include_router(login_router)
    limiter = DeniedPublicAuthenticationRequests()
    login = LoginOperation()
    app.dependency_overrides[get_public_authentication_request_limiter] = lambda: limiter
    app.dependency_overrides[get_administrative_login] = lambda: login

    with TestClient(app) as client:
        response = client.post(
            "/api/admin/sessions",
            json={
                "email": "synthetic.owner@example.test",
                "password": "synthetic password",
                "totpCode": "123456",
            },
        )

    _assert_sanitized_rate_limit(response)
    assert limiter.categories == ["login"]
    assert login.calls == 0
    assert "set-cookie" not in response.headers


def test_t091_limited_recovery_does_not_start_recovery_or_reveal_account_state() -> None:
    app = FastAPI()
    app.include_router(recovery_router)
    operation = RateLimitedRecoveryOperation()
    app.dependency_overrides[get_password_recovery_operations] = lambda: operation

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/admin/password-recovery",
                json={"email": email},
            )
            for email in (
                "synthetic.existing@example.test",
                "synthetic.absent@example.test",
            )
        ]

    for response in responses:
        _assert_sanitized_rate_limit(response)
    assert responses[0].status_code == responses[1].status_code
    assert responses[0].json() == responses[1].json()
    assert operation.checked_emails == [
        "synthetic.existing@example.test",
        "synthetic.absent@example.test",
    ]
    assert operation.recovery_started == 0


def test_t091_limited_availability_does_not_read_schedule() -> None:
    app = FastAPI()
    app.include_router(availability_router)
    limiter = DeniedPublicAuthenticationRequests()
    reader = AvailabilityReader()
    app.dependency_overrides[get_public_authentication_request_limiter] = lambda: limiter
    app.dependency_overrides[get_public_read_request_limiter] = AllowPublicReads
    app.dependency_overrides[get_public_availability_reader] = lambda: reader

    with TestClient(app) as client:
        response = client.get(
            "/api/public/availability",
            params={
                "branch": "chiconcuac",
                "service": "Servicio ficticio",
                "date": "2030-06-15",
            },
        )

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert "private limiter diagnostics" not in response.text
    assert limiter.categories == ["availability"]
    assert reader.calls == 0


def _assert_sanitized_rate_limit(response) -> None:
    assert response.status_code == 429
    assert response.json() == {"detail": RATE_LIMIT_DETAIL}
    assert "private limiter diagnostics" not in response.text
    assert "synthetic" not in response.text

"""T057 contract evidence for the authenticated password-change boundary."""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.mutation_protection import ValidateAdministrativeMutationProtection
from backend.app.application.clock import FixedClock
from backend.app.web.admin_auth.change_password import (
    get_password_change_operation,
    router,
)
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import get_administrative_mutation_validator
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.tests.contract.admin_access.test_admin_mutation_protection_http import (
    CSRF_TOKEN,
    NOW,
    ORIGIN,
    SESSION_TOKEN,
    SessionStore,
    _protector,
)


class PasswordChangeOperation:
    def __init__(self, result: str) -> None:
        self.result = result
        self.calls = []

    def change(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.result


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(operation: PasswordChangeOperation) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: AdministrativeActor(
        account_id=7, role="staff"
    )
    app.dependency_overrides[get_password_change_operation] = lambda: operation
    app.dependency_overrides[get_administrative_mutation_validator] = lambda: (
        ValidateAdministrativeMutationProtection(
            store=SessionStore(), protector=_protector(), clock=FixedClock(NOW)
        )
    )
    return TestClient(app, base_url=ORIGIN)


def _request(client: TestClient, *, csrf: bytes | None = CSRF_TOKEN):
    headers = {
        "origin": ORIGIN,
        "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}",
    }
    if csrf is not None:
        headers["x-csrf-token"] = _encoded(csrf)
    return client.post(
        "/api/admin/password",
        headers=headers,
        json={
            "currentPassword": "synthetic current phrase",
            "totpCode": "123456",
            "newPassword": "synthetic new phrase",
        },
    )


def test_t057_success_is_cookie_free_and_accepts_staff_session() -> None:
    operation = PasswordChangeOperation("changed")
    response = _request(_client(operation))

    assert response.status_code == 204
    assert response.content == b""
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "__Host-beautyhub-session" in response.headers["set-cookie"]
    assert operation.calls == [
        {
            "account_id": 7,
            "current_password": "synthetic current phrase",
            "totp_code": "123456",
            "new_password": "synthetic new phrase",
        }
    ]


def test_t057_invalid_credentials_are_generic_and_keep_the_session() -> None:
    operation = PasswordChangeOperation("invalid_credentials")
    response = _request(_client(operation))

    assert response.status_code == 400
    assert response.json() == {"detail": "No fue posible comprobar las credenciales."}
    assert "set-cookie" not in response.headers


def test_t057_missing_csrf_is_rejected_before_credential_verification() -> None:
    operation = PasswordChangeOperation("changed")
    response = _request(_client(operation), csrf=None)

    assert response.status_code == 403
    assert operation.calls == []

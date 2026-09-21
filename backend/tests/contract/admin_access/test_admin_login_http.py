"""T048 HTTP evidence for protected administrative cookie and CSRF emission."""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.login_session import (
    AdministrativeLoginSessionOutcome,
)
from backend.app.web.admin_auth.login import (
    ADMINISTRATIVE_SESSION_COOKIE,
    get_administrative_login,
    router,
)


SESSION_TOKEN = b"\x61" * 32
CSRF_TOKEN = b"\x62" * 32


class LoginOperation:
    def __init__(self, outcome: AdministrativeLoginSessionOutcome) -> None:
        self.outcome = outcome
        self.calls = []

    def login(self, **values):
        self.calls.append(values)
        return self.outcome


def _client(login: LoginOperation) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_administrative_login] = lambda: login
    return TestClient(app)


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_t048_success_emits_host_cookie_and_separate_csrf_response() -> None:
    login = LoginOperation(
        AdministrativeLoginSessionOutcome(
            account_id=7,
            role="staff",
            session_id=19,
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
        )
    )

    with _client(login) as client:
        response = client.post(
            "/api/admin/sessions",
            json={
                "email": "synthetic.staff@example.test",
                "password": "synthetic staff password",
                "totpCode": "123456",
            },
        )

    cookie_value = _encoded(SESSION_TOKEN)
    csrf_value = _encoded(CSRF_TOKEN)
    set_cookie = response.headers["set-cookie"]
    assert response.status_code == 200
    assert response.json() == {"role": "staff", "csrfToken": csrf_value}
    assert response.cookies[ADMINISTRATIVE_SESSION_COOKIE] == cookie_value
    assert set_cookie.startswith(f"{ADMINISTRATIVE_SESSION_COOKIE}={cookie_value};")
    assert "secure" in set_cookie.lower()
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()
    assert "domain=" not in set_cookie.lower()
    assert cookie_value != csrf_value
    assert cookie_value not in response.text
    assert "account" not in response.text
    assert "sessionId" not in response.text
    assert login.calls == [
        {
            "email": "synthetic.staff@example.test",
            "password": "synthetic staff password",
            "totp_code": "123456",
            "recovery_code": None,
        }
    ]


def test_t048_rejected_login_emits_neither_cookie_nor_csrf() -> None:
    login = LoginOperation(
        AdministrativeLoginSessionOutcome(rejection="invalid_credentials")
    )

    with _client(login) as client:
        response = client.post(
            "/api/admin/sessions",
            json={
                "email": "synthetic.owner@example.test",
                "password": "incorrect synthetic password",
                "recoveryCode": "ABCD-EFGH-JKLM-NPQR",
            },
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Las credenciales no son válidas."}
    assert "set-cookie" not in response.headers
    assert "csrf" not in response.text.lower()

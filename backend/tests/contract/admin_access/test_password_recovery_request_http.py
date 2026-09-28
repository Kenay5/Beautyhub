"""T058: public recovery responses cannot distinguish account existence."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.password_recovery_request import PasswordRecoveryIntent
from backend.app.application.public_request_limit import AllowPublicRequests
from backend.app.web.admin_auth.password_recovery_request import (
    get_password_recovery_operations,
    router,
)
from backend.app.web.admin_security_headers import register_administrative_security_headers
from backend.app.web.public_request_protection import (
    get_public_authentication_request_limiter,
)


class Requester:
    def __init__(self, intent: PasswordRecoveryIntent | None) -> None:
        self.intent = intent
        self.emails: list[str] = []

    def request(self, *, email: str) -> PasswordRecoveryIntent | None:
        self.emails.append(email)
        return self.intent


def _request(email: str, intent: PasswordRecoveryIntent | None):
    app = FastAPI()
    app.include_router(router)
    register_administrative_security_headers(app)
    requester = Requester(intent)
    app.dependency_overrides[get_password_recovery_operations] = lambda: requester
    app.dependency_overrides[get_public_authentication_request_limiter] = (
        AllowPublicRequests
    )
    with TestClient(app) as client:
        response = client.post("/api/admin/password-recovery", json={"email": email})
    assert requester.emails == [email]
    return response


def test_t058_active_missing_and_inactive_emails_have_identical_external_response() -> None:
    active = _request("synthetic.active@example.test", PasswordRecoveryIntent(7))
    missing = _request("synthetic.missing@example.test", None)
    inactive = _request("synthetic.inactive@example.test", None)

    for response in (active, missing, inactive):
        assert response.status_code == 202
        assert response.json() == {
            "message": "Si existe una cuenta activa con ese correo, recibirás instrucciones para recuperar tu contraseña."
        }
        assert "set-cookie" not in response.headers
        assert "7" not in response.text
    assert (active.content, dict(active.headers)) == (missing.content, dict(missing.headers))
    assert (active.content, dict(active.headers)) == (inactive.content, dict(inactive.headers))

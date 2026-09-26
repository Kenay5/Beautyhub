"""T068 HTTP security contract for one-time replacement confirmation."""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.confirm_totp_replacement import TotpReplacementConfirmationOutcome
from backend.app.application.admin_access.mutation_protection import ValidateAdministrativeMutationProtection
from backend.app.application.clock import FixedClock
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import get_administrative_mutation_validator
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.totp_replacement_confirmation import (
    get_totp_replacement_confirmation_operation,
    router,
)
from backend.tests.contract.admin_access.test_admin_mutation_protection_http import (
    CSRF_TOKEN,
    NOW,
    ORIGIN,
    SESSION_TOKEN,
    SessionStore,
    _protector,
)


class Operation:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def confirm(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcome


def _client(operation):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: AdministrativeActor(
        account_id=7, role="staff"
    )
    app.dependency_overrides[get_totp_replacement_confirmation_operation] = lambda: operation
    app.dependency_overrides[get_administrative_mutation_validator] = lambda: ValidateAdministrativeMutationProtection(
        store=SessionStore(), protector=_protector(), clock=FixedClock(NOW)
    )
    return TestClient(app, base_url=ORIGIN)


def _request(client, *, csrf=CSRF_TOKEN, body=None):
    headers = {
        "origin": ORIGIN,
        "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={base64.urlsafe_b64encode(SESSION_TOKEN).rstrip(b'=').decode()}",
    }
    if csrf is not None:
        headers["x-csrf-token"] = base64.urlsafe_b64encode(csrf).rstrip(b"=").decode()
    return client.post(
        "/api/admin/totp-replacement/confirm",
        headers=headers,
        json=body or {"totpCode": "123456"},
    )


def test_t068_success_shows_exact_batch_once_and_expires_session_cookie():
    codes = tuple(f"ABCD-EFGH-IJKL-MNP{index}" for index in range(10))
    operation = Operation(TotpReplacementConfirmationOutcome("replaced", recovery_codes=codes))

    response = _request(_client(operation))

    assert response.status_code == 200
    assert response.json() == {"recoveryCodes": list(codes)}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert operation.calls == [{"account_id": 7, "totp_code": "123456"}]


def test_t068_invalid_confirmation_is_generic_and_keeps_session_cookie():
    operation = Operation(TotpReplacementConfirmationOutcome("invalid_credentials"))

    response = _request(_client(operation))

    assert response.status_code == 400
    assert response.json() == {"detail": "No fue posible comprobar las credenciales."}
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_t068_missing_csrf_is_denied_before_confirming():
    operation = Operation(TotpReplacementConfirmationOutcome("replaced"))

    response = _request(_client(operation), csrf=None)

    assert response.status_code == 403
    assert operation.calls == []

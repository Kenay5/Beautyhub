"""T066 HTTP evidence for authenticated recovery-code regeneration."""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.mutation_protection import (
    ValidateAdministrativeMutationProtection,
)
from backend.app.application.admin_access.regenerate_recovery_codes import (
    RecoveryCodeRegenerationOutcome,
)
from backend.app.application.clock import FixedClock
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import (
    get_administrative_mutation_validator,
)
from backend.app.web.admin_auth.recovery_code_regeneration import (
    get_recovery_code_regeneration_operation,
    router,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.tests.contract.admin_access.test_admin_mutation_protection_http import (
    CSRF_TOKEN,
    NOW,
    ORIGIN,
    SESSION_TOKEN,
    SessionStore,
    _protector,
)


RECOVERY_CODES = tuple(
    f"ABCD-EFGH-JKLM-NPQ{digit}" for digit in "23456789AB"
)


class RegenerationOperation:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls = []

    def regenerate(self, **kwargs) -> RecoveryCodeRegenerationOutcome:
        self.calls.append(kwargs)
        return RecoveryCodeRegenerationOutcome(
            status=self.status,
            recovery_codes=RECOVERY_CODES if self.status == "regenerated" else (),
        )


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(operation: RegenerationOperation) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: AdministrativeActor(
        account_id=7, role="staff"
    )
    app.dependency_overrides[get_recovery_code_regeneration_operation] = lambda: operation
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
        "/api/admin/recovery-codes/regenerate",
        headers=headers,
        json={"currentPassword": "synthetic current phrase", "totpCode": "123456"},
    )


def test_t066_success_returns_one_batch_and_clears_the_session_cookie() -> None:
    operation = RegenerationOperation("regenerated")

    response = _request(_client(operation))

    assert response.status_code == 200
    assert response.json() == {"recoveryCodes": list(RECOVERY_CODES)}
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert ADMINISTRATIVE_SESSION_COOKIE in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert operation.calls == [
        {
            "account_id": 7,
            "current_password": "synthetic current phrase",
            "totp_code": "123456",
        }
    ]


def test_t066_invalid_credentials_are_generic_and_do_not_clear_session() -> None:
    operation = RegenerationOperation("invalid_credentials")

    response = _request(_client(operation))

    assert response.status_code == 400
    assert response.json() == {
        "detail": "No fue posible comprobar las credenciales."
    }
    assert "set-cookie" not in response.headers
    assert "recoveryCodes" not in response.json()


def test_t066_missing_csrf_is_rejected_before_credential_verification() -> None:
    operation = RegenerationOperation("regenerated")

    response = _request(_client(operation), csrf=None)

    assert response.status_code == 403
    assert operation.calls == []

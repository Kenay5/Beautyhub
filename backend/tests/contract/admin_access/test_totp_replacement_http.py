"""T067 HTTP contract for authorized setup and generic credential rejection."""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.mutation_protection import ValidateAdministrativeMutationProtection
from backend.app.application.admin_access.prepare_totp_replacement import PreparedTotpReplacement
from backend.app.application.clock import FixedClock
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import get_administrative_mutation_validator
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.totp_replacement import get_totp_replacement_operation, router
from backend.tests.contract.admin_access.test_admin_mutation_protection_http import (
    CSRF_TOKEN, NOW, ORIGIN, SESSION_TOKEN, SessionStore, _protector,
)


class Operation:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def prepare(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(operation):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_admin_actor] = lambda: AdministrativeActor(
        account_id=7, role="staff"
    )
    app.dependency_overrides[get_totp_replacement_operation] = lambda: operation
    app.dependency_overrides[get_administrative_mutation_validator] = lambda: ValidateAdministrativeMutationProtection(
        store=SessionStore(), protector=_protector(), clock=FixedClock(NOW)
    )
    return TestClient(app, base_url=ORIGIN)


def _request(client, *, proof="totp", csrf=CSRF_TOKEN):
    headers = {
        "origin": ORIGIN,
        "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}",
    }
    if csrf is not None:
        headers["x-csrf-token"] = _encoded(csrf)
    body = {"currentPassword": "synthetic current phrase"}
    body["totpCode" if proof == "totp" else "recoveryCode"] = (
        "123456" if proof == "totp" else "ABCD-EFGH-JKLM-NPQ2"
    )
    return client.post("/api/admin/totp-replacement/prepare", headers=headers, json=body)


def test_t067_totp_setup_is_visible_only_in_uncached_authorized_response():
    operation = Operation(PreparedTotpReplacement(
        provisioning_uri="otpauth://totp/BeautyHub:test", manual_key="A" * 32
    ))

    response = _request(_client(operation))

    assert response.status_code == 200
    assert response.json() == {
        "provisioningUri": "otpauth://totp/BeautyHub:test",
        "manualKey": "A" * 32,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "set-cookie" not in response.headers
    assert operation.calls == [{
        "account_id": 7,
        "current_password": "synthetic current phrase",
        "totp_code": "123456",
        "recovery_code": None,
    }]


def test_t067_recovery_proof_is_forwarded_without_changing_session():
    operation = Operation(PreparedTotpReplacement(
        provisioning_uri="otpauth://totp/BeautyHub:test", manual_key="B" * 32
    ))

    response = _request(_client(operation), proof="recovery")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert operation.calls[0]["totp_code"] is None
    assert operation.calls[0]["recovery_code"] == "ABCD-EFGH-JKLM-NPQ2"


def test_t067_missing_csrf_is_denied_before_preparation():
    operation = Operation("should not be reached")

    response = _request(_client(operation), csrf=None)

    assert response.status_code == 403
    assert operation.calls == []


def test_t071_admin_factor_replacement_requires_password_and_exactly_one_factor_proof():
    operation = Operation("should not be reached")
    client = _client(operation)
    headers = {
        "origin": ORIGIN,
        "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}",
        "x-csrf-token": _encoded(CSRF_TOKEN),
    }
    invalid_bodies = (
        {"totpCode": "123456"},
        {"currentPassword": "synthetic current phrase"},
        {
            "currentPassword": "synthetic current phrase",
            "totpCode": "123456",
            "recoveryCode": "ABCD-EFGH-JKLM-NPQ2",
        },
    )

    for body in invalid_bodies:
        response = client.post(
            "/api/admin/totp-replacement/prepare",
            headers=headers,
            json=body,
        )
        assert response.status_code == 422

    assert operation.calls == []

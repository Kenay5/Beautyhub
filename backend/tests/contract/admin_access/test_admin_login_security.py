"""T055 security evidence for generic, non-reflective login failures."""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.login_session import (
    AdministrativeLoginSessionOutcome,
)
from backend.app.application.public_request_limit import AllowPublicRequests
from backend.app.web.admin_auth.login import get_administrative_login, router
from backend.app.web.public_request_protection import (
    get_public_authentication_request_limiter,
)


class RejectingLoginOperation:
    def login(self, **values) -> AdministrativeLoginSessionOutcome:
        del values
        return AdministrativeLoginSessionOutcome(rejection="invalid_credentials")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_administrative_login] = RejectingLoginOperation
    app.dependency_overrides[get_public_authentication_request_limiter] = (
        AllowPublicRequests
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "payload",
    (
        {
            "email": "synthetic.unknown@example.test",
            "password": "synthetic unknown password",
            "totpCode": "100001",
        },
        {
            "email": "synthetic.owner@example.test",
            "password": "synthetic wrong password",
            "totpCode": "100002",
        },
        {
            "email": "synthetic.owner@example.test",
            "password": "synthetic owner password",
            "totpCode": "100003",
        },
        {
            "email": "synthetic.owner@example.test",
            "password": "synthetic owner password",
            "recoveryCode": "ABCD-EFGH-JKLM-NPQR",
        },
    ),
    ids=("unknown-account", "wrong-password", "wrong-totp", "wrong-recovery"),
)
def test_t055_rejected_credentials_have_one_non_reflective_http_result(
    payload: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG), _client() as client:
        response = client.post("/api/admin/sessions", json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Las credenciales no son válidas."}
    assert "set-cookie" not in response.headers
    observable = " ".join((response.text, str(response.headers), caplog.text))
    assert all(secret not in observable for secret in payload.values())

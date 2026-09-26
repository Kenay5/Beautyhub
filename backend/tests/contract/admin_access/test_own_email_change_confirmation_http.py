"""T075 public confirmation contract does not expose account or link state."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.web.admin_auth.own_email_change_confirmation import (
    get_own_email_change_confirmation_operation,
    router,
)
from backend.app.web.admin_auth.security_link_transport import encode_security_link_token


class ConfirmationOperation:
    def __init__(self, result: str) -> None:
        self.result = result
        self.tokens: list[bytes] = []

    def confirm(self, *, token: bytes) -> str:
        self.tokens.append(token)
        return self.result


def _post(result: str):
    app = FastAPI()
    app.include_router(router)
    operation = ConfirmationOperation(result)
    app.dependency_overrides[get_own_email_change_confirmation_operation] = lambda: operation
    token = b"\x75" * 32
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/account/email-change/complete",
            json={"token": encode_security_link_token(token), "accountId": 999},
        )
    return response, operation, token


def test_t075_confirmation_returns_no_content_and_creates_no_session() -> None:
    response, operation, token = _post("completed")
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "set-cookie" not in response.headers
    assert operation.tokens == [token]


def test_t075_invalid_link_and_lost_uniqueness_have_same_safe_response() -> None:
    first, _, _ = _post("unavailable")
    second, _, _ = _post("conflict")
    assert first.status_code == second.status_code == 404
    assert first.json() == second.json()
    assert "set-cookie" not in first.headers
    assert "set-cookie" not in second.headers

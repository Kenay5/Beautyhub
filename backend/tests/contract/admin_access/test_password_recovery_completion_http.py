"""T060 contract: successful recovery never establishes a session."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.web.admin_auth.password_recovery_completion import (
    get_password_recovery_completion_operations,
    router,
)
from backend.app.web.admin_security_headers import register_administrative_security_headers
from backend.app.web.admin_auth.security_link_transport import encode_security_link_token


class CompletionOperation:
    def __init__(self, result: str = "completed") -> None:
        self.result = result
        self.calls: list[tuple[bytes, str]] = []

    def complete(self, *, token: bytes, new_password: str) -> str:
        self.calls.append((token, new_password))
        return self.result


def _post(result: str = "completed"):
    app = FastAPI()
    app.include_router(router)
    register_administrative_security_headers(app)
    operation = CompletionOperation(result)
    app.dependency_overrides[get_password_recovery_completion_operations] = lambda: operation
    token = b"\x78" * 32
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/password-recovery/complete",
            json={"token": encode_security_link_token(token), "newPassword": "A synthetic password phrase"},
        )
    return response, operation


def test_t060_success_is_no_content_and_does_not_set_a_session_cookie() -> None:
    response, operation = _post()
    assert response.status_code == 204
    assert response.content == b""
    assert "set-cookie" not in response.headers
    assert operation.calls == [(b"\x78" * 32, "A synthetic password phrase")]


def test_t060_invalid_link_response_is_sanitized_and_does_not_set_cookie() -> None:
    response, _ = _post("invalid_link")
    assert response.status_code == 400
    assert "set-cookie" not in response.headers
    assert "account" not in response.text.lower()

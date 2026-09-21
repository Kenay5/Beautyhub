"""T051 HTTP evidence for removing the administrative browser session cookie."""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.logout import (
    get_administrative_session_closer,
    router,
)
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)


SESSION_TOKEN = b"\x91" * 32


class CloseOperation:
    def __init__(self, results: list[bool]) -> None:
        self._results = results
        self.calls = []

    def close(self, *, session_token: bytes) -> bool:
        self.calls.append(session_token)
        return self._results.pop(0)


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(operation: CloseOperation) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_administrative_mutation_protection] = lambda: None
    app.dependency_overrides[get_administrative_session_closer] = lambda: operation
    return TestClient(app, base_url="https://beautyhub.example.test")


def test_t051_logout_removes_the_host_cookie_without_exposing_its_value() -> None:
    operation = CloseOperation([True])

    with _client(operation) as client:
        response = client.delete(
            "/api/admin/sessions/current",
            cookies={ADMINISTRATIVE_SESSION_COOKIE: _encoded(SESSION_TOKEN)},
        )

    deleted_cookie = response.headers["set-cookie"].lower()
    assert response.status_code == 204
    assert response.content == b""
    assert operation.calls == [SESSION_TOKEN]
    assert "max-age=0" in deleted_cookie
    assert "secure" in deleted_cookie
    assert "httponly" in deleted_cookie
    assert "samesite=strict" in deleted_cookie
    assert "path=/" in deleted_cookie
    assert "domain=" not in deleted_cookie
    assert _encoded(SESSION_TOKEN) not in response.headers["set-cookie"]


def test_t051_logout_is_safe_when_the_session_was_already_invalidated() -> None:
    operation = CloseOperation([False])

    with _client(operation) as client:
        response = client.delete(
            "/api/admin/sessions/current",
            cookies={ADMINISTRATIVE_SESSION_COOKIE: _encoded(SESSION_TOKEN)},
        )

    assert response.status_code == 204
    assert operation.calls == [SESSION_TOKEN]

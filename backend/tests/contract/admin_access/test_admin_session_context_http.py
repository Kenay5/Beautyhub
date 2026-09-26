"""T053 HTTP evidence for the sanitized administrative session context."""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
)
from backend.app.application.admin_access.session_context import (
    AdministrativeSessionContext,
)
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.session_context import (
    get_administrative_session_context_loader,
    router,
)


SESSION_TOKEN = b"\xa1" * 32
CSRF_TOKEN = b"\xa2" * 32


class ContextLoader:
    def __init__(self, *, available: bool) -> None:
        self.available = available
        self.calls = []

    def refresh(self, *, session_token):
        self.calls.append(session_token)
        if not self.available:
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )
        return AdministrativeSessionContext(
            actor=AdministrativeActor(account_id=7, role="owner"),
            csrf_token=CSRF_TOKEN,
        )


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(loader: ContextLoader) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_administrative_session_context_loader] = lambda: loader
    return TestClient(app)


def test_t053_valid_cookie_returns_only_revalidated_browser_context() -> None:
    loader = ContextLoader(available=True)
    with _client(loader) as client:
        response = client.get(
            "/api/admin/sessions/current",
            headers={
                "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}"
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "accountId": 7,
        "role": "owner",
        "csrfToken": _encoded(CSRF_TOKEN),
    }
    assert loader.calls == [SESSION_TOKEN]
    assert _encoded(SESSION_TOKEN) not in response.text


@pytest.mark.parametrize(
    "cookie",
    [
        None,
        "not-base64",
        _encoded(SESSION_TOKEN),
    ],
    ids=["missing", "malformed", "unavailable"],
)
def test_t053_unusable_session_states_share_the_same_401(cookie) -> None:
    loader = ContextLoader(available=False)
    headers = {}
    if cookie is not None:
        headers["cookie"] = f"{ADMINISTRATIVE_SESSION_COOKIE}={cookie}"

    with _client(loader) as client:
        response = client.get("/api/admin/sessions/current", headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Autenticación administrativa requerida."
    }
    assert set(response.json()) == {"detail"}

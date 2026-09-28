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
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.request_rate_limit import (
    get_authenticated_administrative_request_limiter,
)
from backend.app.web.admin_auth.session_context import (
    get_administrative_session_context_loader,
    router,
)
from backend.app.web.admin_auth.staff_deactivation import (
    get_staff_deactivation_operations,
    router as staff_router,
)


SESSION_TOKEN = b"\xa1" * 32
CSRF_TOKEN = b"\xa2" * 32


class ContextLoader:
    def __init__(self, *, available: bool) -> None:
        self.available = available
        self.authentication_calls = []
        self.refresh_calls = []
        self.csrf_token = CSRF_TOKEN

    def authenticate(self, *, session_token):
        self.authentication_calls.append(session_token)
        if not self.available:
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )
        return AdministrativeActor(account_id=7, role="owner")

    def refresh(self, *, session_token):
        self.refresh_calls.append(session_token)
        if not self.available:
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )
        self.csrf_token = b"d" * 32
        return AdministrativeSessionContext(
            actor=AdministrativeActor(account_id=7, role="owner"),
            csrf_token=self.csrf_token,
        )


class AllowLimiter:
    def ensure_allowed(self, *, actor):
        assert actor == AdministrativeActor(account_id=7, role="owner")


class DenyLimiter:
    def __init__(self) -> None:
        self.actors = []

    def ensure_allowed(self, *, actor):
        self.actors.append(actor)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes. Inténtalo más tarde.",
        )


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _client(loader: ContextLoader) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_administrative_session_context_loader] = lambda: loader
    app.dependency_overrides[get_authenticated_administrative_request_limiter] = (
        AllowLimiter
    )
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
        "csrfToken": _encoded(b"d" * 32),
    }
    assert loader.authentication_calls == [SESSION_TOKEN]
    assert loader.refresh_calls == [SESSION_TOKEN]
    assert _encoded(SESSION_TOKEN) not in response.text


def test_t082_client_cannot_choose_the_authenticated_identity_or_role() -> None:
    loader = ContextLoader(available=True)
    with _client(loader) as client:
        response = client.get(
            "/api/admin/sessions/current",
            params={"accountId": 99, "role": "staff"},
            headers={
                "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}",
                "x-admin-account-id": "99",
                "x-admin-role": "staff",
            },
        )

    assert response.status_code == 200
    assert response.json()["accountId"] == 7
    assert response.json()["role"] == "owner"
    assert "99" not in response.text


def test_t092_rate_limited_context_does_not_rotate_csrf_or_touch_session() -> None:
    loader = ContextLoader(available=True)
    limiter = DenyLimiter()
    client = _client(loader)
    app = client.app
    app.dependency_overrides[get_authenticated_administrative_request_limiter] = (
        lambda: limiter
    )
    original_csrf = loader.csrf_token
    with client:
        response = client.get(
            "/api/admin/sessions/current",
            params={"accountId": 99, "role": "staff"},
            headers={
                "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}",
                "x-admin-account-id": "99",
                "x-admin-role": "staff",
            },
        )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "Demasiadas solicitudes. Inténtalo más tarde."
    }
    assert set(response.json()) == {"detail"}
    assert "set-cookie" not in response.headers
    assert loader.authentication_calls == [SESSION_TOKEN]
    assert loader.refresh_calls == []
    assert loader.csrf_token == original_csrf
    assert limiter.actors == [AdministrativeActor(account_id=7, role="owner")]


def test_t092_rate_limit_precedes_csrf_activity_and_business_operation() -> None:
    loader = ContextLoader(available=True)
    limiter = DenyLimiter()
    calls = {"protection": 0, "deactivate": 0}

    class Operations:
        def status(self, *, actor):
            raise AssertionError("status should not run on the mutation route")

        def deactivate(self, *, actor):
            calls["deactivate"] += 1

    def protect():
        calls["protection"] += 1

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(staff_router)
    app.dependency_overrides[get_administrative_session_context_loader] = lambda: loader
    app.dependency_overrides[get_authenticated_administrative_request_limiter] = (
        lambda: limiter
    )
    app.dependency_overrides[require_administrative_mutation_protection] = protect
    app.dependency_overrides[get_staff_deactivation_operations] = Operations

    with TestClient(app) as client:
        response = client.post(
            "/api/admin/staff/deactivate",
            headers={
                "cookie": f"{ADMINISTRATIVE_SESSION_COOKIE}={_encoded(SESSION_TOKEN)}",
                "x-admin-account-id": "99",
                "x-admin-role": "staff",
            },
        )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "Demasiadas solicitudes. Inténtalo más tarde."
    }
    assert calls == {"protection": 0, "deactivate": 0}
    assert loader.authentication_calls == [SESSION_TOKEN]
    assert limiter.actors == [AdministrativeActor(account_id=7, role="owner")]


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

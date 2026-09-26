"""T054 HTTP evidence for administrative security headers."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.web.admin_security_headers import (
    ADMINISTRATIVE_CONTENT_SECURITY_POLICY,
    register_administrative_security_headers,
)


def _client() -> TestClient:
    app = FastAPI()
    register_administrative_security_headers(app)

    @app.get("/api/admin/example")
    def administrative_response() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/public/example")
    def public_response() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_t054_administrative_responses_apply_the_approved_headers() -> None:
    with _client() as client:
        response = client.get("/api/admin/example")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"] == (
        ADMINISTRATIVE_CONTENT_SECURITY_POLICY
    )
    assert response.headers["x-frame-options"] == "DENY"


def test_t054_public_responses_are_not_given_admin_only_cache_policy() -> None:
    with _client() as client:
        response = client.get("/api/public/example")

    assert "cache-control" not in response.headers
    assert "content-security-policy" not in response.headers

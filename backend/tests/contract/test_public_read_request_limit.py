"""T067 contract evidence for catalog and availability rate-limit rejection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.web.app import create_app
from backend.app.web.public_availability import get_public_availability_reader
from backend.app.web.public_request_protection import get_public_read_request_limiter
from backend.app.web.public_services import get_active_service_catalog


class DenyReadRequests:
    def ensure_allowed(self, category: str) -> None:
        assert category in {"service_catalog", "availability"}
        raise PublicRequestRateLimitError("synthetic internal limit detail")


class UnusedCatalog:
    calls = 0

    def list_active_services(self, branch: str):
        self.calls += 1
        return ()


class UnusedAvailabilityReader:
    calls = 0

    def get_active_service_duration(self, branch: str, service_name: str):
        self.calls += 1
        return None

    def list_scheduled_intervals(self):
        self.calls += 1
        return ()

    def list_applicable_blocks(self, branch: str):
        self.calls += 1
        return ()


def test_t067_catalog_limit_rejects_before_reading_and_sanitizes_response() -> None:
    catalog = UnusedCatalog()
    app = create_app()
    app.dependency_overrides[get_active_service_catalog] = lambda: catalog
    app.dependency_overrides[get_public_read_request_limiter] = DenyReadRequests

    with TestClient(app) as client:
        response = client.get("/api/public/services", params={"branch": "texcoco"})

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert "synthetic" not in response.text
    assert catalog.calls == 0


def test_t067_availability_limit_rejects_before_reading_and_sanitizes_response() -> None:
    reader = UnusedAvailabilityReader()
    app = create_app()
    app.dependency_overrides[get_public_availability_reader] = lambda: reader
    app.dependency_overrides[get_public_read_request_limiter] = DenyReadRequests

    with TestClient(app) as client:
        response = client.get(
            "/api/public/availability",
            params={
                "branch": "texcoco",
                "service": "Servicio ficticio",
                "date": "2030-06-15",
            },
        )

    assert response.status_code == 429
    assert response.json() == {"detail": "Intenta nuevamente más tarde."}
    assert "synthetic" not in response.text
    assert reader.calls == 0

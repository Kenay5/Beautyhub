"""Contract tests for the public active-service catalog."""

from collections.abc import Iterable
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.application.list_active_services import PublicService
from backend.app.web.app import create_app
from backend.app.web.public_services import get_active_service_catalog
from backend.app.web.public_request_protection import get_public_read_request_limiter


class FakeActiveServiceCatalog:
    """Controlled public catalog used at the HTTP boundary."""

    def list_active_services(self, branch: str) -> Iterable[PublicService]:
        if branch == "chiconcuac":
            return (PublicService("Manicure", 60, Decimal("350.00")),)
        return ()


class AllowReadRequests:
    def ensure_allowed(self, category: str) -> None:
        assert category == "service_catalog"


def test_public_service_catalog_returns_only_safe_active_service_fields() -> None:
    app = create_app()
    app.dependency_overrides[get_active_service_catalog] = FakeActiveServiceCatalog
    app.dependency_overrides[get_public_read_request_limiter] = AllowReadRequests

    with TestClient(app) as client:
        response = client.get("/api/public/services", params={"branch": "chiconcuac"})

    assert response.status_code == 200
    assert response.json() == [
        {"name": "Manicure", "duration_minutes": 60, "price": "350.00"}
    ]


def test_public_service_catalog_rejects_an_unknown_or_missing_branch() -> None:
    app = create_app()
    app.dependency_overrides[get_active_service_catalog] = FakeActiveServiceCatalog
    app.dependency_overrides[get_public_read_request_limiter] = AllowReadRequests

    with TestClient(app) as client:
        unknown_branch = client.get(
            "/api/public/services", params={"branch": "otra"}
        )
        missing_branch = client.get("/api/public/services")

    assert unknown_branch.status_code == 422
    assert missing_branch.status_code == 422
    assert unknown_branch.json() == {"detail": "Selecciona una sucursal válida."}
    assert missing_branch.json() == {"detail": "Selecciona una sucursal válida."}

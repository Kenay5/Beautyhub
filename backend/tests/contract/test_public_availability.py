"""Contract tests for the public availability endpoint."""

from datetime import date, time

from fastapi.testclient import TestClient

from backend.app.application.clock import FixedClock
from backend.app.web.app import create_app
from backend.app.web.public_availability import (
    get_clock,
    get_public_availability_reader,
)
from backend.app.web.public_request_protection import get_public_read_request_limiter


class FakePublicAvailabilityReader:
    """No-conflict public schedule used to prove the response contract."""

    def get_active_service_duration(self, branch: str, service_name: str) -> int | None:
        return 60 if branch == "chiconcuac" and service_name == "Manicure" else None

    def list_scheduled_intervals(self) -> tuple[object, ...]:
        return ()

    def list_applicable_blocks(self, branch: str) -> tuple[object, ...]:
        return ()


class AllowReadRequests:
    def ensure_allowed(self, category: str) -> None:
        assert category == "availability"


def test_public_availability_returns_only_safe_bookable_start_fields() -> None:
    app = create_app()
    app.dependency_overrides[get_public_availability_reader] = FakePublicAvailabilityReader
    app.dependency_overrides[get_public_read_request_limiter] = AllowReadRequests
    app.dependency_overrides[get_clock] = lambda: FixedClock(
        _business_datetime(date(2030, 6, 15), time(10))
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/public/availability",
            params={
                "branch": "chiconcuac",
                "service": "Manicure",
                "date": "2030-06-15",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "starts": [
            "2030-06-15T11:00:00-06:00",
            "2030-06-15T11:15:00-06:00",
            "2030-06-15T11:30:00-06:00",
            "2030-06-15T11:45:00-06:00",
            "2030-06-15T12:00:00-06:00",
            "2030-06-15T12:15:00-06:00",
            "2030-06-15T12:30:00-06:00",
            "2030-06-15T12:45:00-06:00",
            "2030-06-15T13:00:00-06:00",
            "2030-06-15T13:15:00-06:00",
            "2030-06-15T13:30:00-06:00",
            "2030-06-15T13:45:00-06:00",
            "2030-06-15T14:00:00-06:00",
            "2030-06-15T14:15:00-06:00",
            "2030-06-15T14:30:00-06:00",
            "2030-06-15T14:45:00-06:00",
            "2030-06-15T15:00:00-06:00",
            "2030-06-15T15:15:00-06:00",
            "2030-06-15T15:30:00-06:00",
            "2030-06-15T15:45:00-06:00",
            "2030-06-15T16:00:00-06:00",
            "2030-06-15T16:15:00-06:00",
            "2030-06-15T16:30:00-06:00",
            "2030-06-15T16:45:00-06:00",
            "2030-06-15T17:00:00-06:00",
            "2030-06-15T17:15:00-06:00",
            "2030-06-15T17:30:00-06:00",
            "2030-06-15T17:45:00-06:00",
            "2030-06-15T18:00:00-06:00",
            "2030-06-15T18:15:00-06:00",
            "2030-06-15T18:30:00-06:00",
            "2030-06-15T18:45:00-06:00",
            "2030-06-15T19:00:00-06:00",
        ]
    }


def test_public_availability_returns_one_sanitized_error_for_invalid_input() -> None:
    app = create_app()
    app.dependency_overrides[get_public_availability_reader] = FakePublicAvailabilityReader
    app.dependency_overrides[get_public_read_request_limiter] = AllowReadRequests
    app.dependency_overrides[get_clock] = lambda: FixedClock(
        _business_datetime(date(2030, 6, 15), time(10))
    )

    with TestClient(app) as client:
        responses = (
            client.get(
                "/api/public/availability",
                params={
                    "branch": "otra",
                    "service": "Manicure",
                    "date": "2030-06-15",
                },
            ),
            client.get(
                "/api/public/availability",
                params={
                    "branch": "chiconcuac",
                    "service": "No existe",
                    "date": "2030-06-15",
                },
            ),
            client.get(
                "/api/public/availability",
                params={
                    "branch": "chiconcuac",
                    "service": "Manicure",
                    "date": "invalida",
                },
            ),
        )

    assert all(response.status_code == 422 for response in responses)
    assert {response.json()["detail"] for response in responses} == {
        "No fue posible consultar la disponibilidad solicitada."
    }


def _business_datetime(local_date: date, local_time: time):
    from backend.app.domain.time import business_datetime

    return business_datetime(local_date, local_time)

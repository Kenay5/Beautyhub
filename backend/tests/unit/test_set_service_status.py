"""Unit tests for the internal service status use case."""

from dataclasses import replace
from decimal import Decimal

import pytest

from backend.app.application.set_service_status import (
    ServiceStatusNotFoundError,
    SetServiceStatus,
    SetServiceStatusCommand,
)
from backend.app.domain.service import ServiceDraft, ServiceStateValidationError


class FakeServiceStatusRepository:
    """Small test double for the service status persistence boundary."""

    def __init__(self, services: dict[int, ServiceDraft]) -> None:
        self.services = services

    def set_service_active(self, service_id: int, is_active: bool) -> bool:
        service = self.services.get(service_id)
        if service is None:
            return False
        self.services[service_id] = replace(service, is_active=is_active)
        return True


def stored_service() -> ServiceDraft:
    return ServiceDraft(
        name="Manicure clásico",
        description="Esmalte y cuidado.",
        duration_minutes=60,
        price=Decimal("350.00"),
        is_active=True,
        available_chiconcuac=True,
        available_texcoco=False,
    )


def test_service_status_changes_between_active_and_inactive() -> None:
    repository = FakeServiceStatusRepository({1: stored_service()})
    use_case = SetServiceStatus(repository)

    deactivated = use_case.execute(SetServiceStatusCommand(1, False))
    activated = use_case.execute(SetServiceStatusCommand(1, True))

    assert deactivated.is_active is False
    assert activated.is_active is True
    assert repository.services[1] == stored_service()


def test_service_status_rejects_a_missing_service() -> None:
    with pytest.raises(ServiceStatusNotFoundError, match="not found"):
        SetServiceStatus(FakeServiceStatusRepository({})).execute(
            SetServiceStatusCommand(1, False)
        )


def test_service_status_rejects_a_non_boolean_value() -> None:
    with pytest.raises(ServiceStateValidationError):
        SetServiceStatus(FakeServiceStatusRepository({1: stored_service()})).execute(
            SetServiceStatusCommand(1, "inactive")  # type: ignore[arg-type]
        )

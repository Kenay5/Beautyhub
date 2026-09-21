"""Unit tests for the internal service creation use case."""

from collections.abc import Iterable
from decimal import Decimal

import pytest

from backend.app.application.create_service import (
    CreateService,
    CreateServiceCommand,
)
from backend.app.domain.service import ServiceDraft, ServiceStateValidationError
from backend.app.domain.service_text import ServiceNameUniquenessError


class FakeServiceCreationRepository:
    """Small in-memory test double for the application persistence boundary."""

    def __init__(self, existing_names: Iterable[str] = ()) -> None:
        self.existing_names = list(existing_names)
        self.created_services: list[ServiceDraft] = []

    def list_service_names(self) -> Iterable[str]:
        return self.existing_names

    def create_service(self, service: ServiceDraft) -> int:
        self.created_services.append(service)
        return len(self.created_services)


def valid_command(**overrides: object) -> CreateServiceCommand:
    values: dict[str, object] = {
        "name": "  Manicure clásico  ",
        "description": "  Esmalte y cuidado de uñas.  ",
        "duration_minutes": 60,
        "price": Decimal("350.00"),
        "is_active": True,
        "branches": ["chiconcuac", "texcoco"],
        **overrides,
    }
    return CreateServiceCommand(**values)  # type: ignore[arg-type]


def test_create_service_persists_a_valid_normalized_service() -> None:
    repository = FakeServiceCreationRepository()

    result = CreateService(repository).execute(valid_command())

    assert result.service_id == 1
    assert result.service == ServiceDraft(
        name="Manicure clásico",
        description="Esmalte y cuidado de uñas.",
        duration_minutes=60,
        price=Decimal("350.00"),
        is_active=True,
        available_chiconcuac=True,
        available_texcoco=True,
    )
    assert repository.created_services == [result.service]


def test_create_service_rejects_a_duplicate_before_persisting() -> None:
    repository = FakeServiceCreationRepository(existing_names=["Manicure clásico"])

    with pytest.raises(ServiceNameUniquenessError):
        CreateService(repository).execute(valid_command(name="MANICURE CLÁSICO"))

    assert repository.created_services == []


def test_create_service_rejects_a_non_boolean_state_before_persisting() -> None:
    repository = FakeServiceCreationRepository()

    with pytest.raises(ServiceStateValidationError):
        CreateService(repository).execute(valid_command(is_active="active"))

    assert repository.created_services == []

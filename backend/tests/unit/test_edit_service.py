"""Unit tests for the internal service editing use case."""

from collections.abc import Iterable
from decimal import Decimal

import pytest

from backend.app.application.edit_service import (
    EditService,
    EditServiceCommand,
    ServiceNotFoundError,
)
from backend.app.domain.service import ServiceDraft
from backend.app.domain.service_text import ServiceNameUniquenessError


class FakeServiceEditingRepository:
    """Small test double for the service editing persistence boundary."""

    def __init__(self, services: dict[int, ServiceDraft]) -> None:
        self.services = services
        self.updated_services: list[tuple[int, ServiceDraft]] = []

    def get_service(self, service_id: int) -> ServiceDraft | None:
        return self.services.get(service_id)

    def list_service_names(self, excluding_service_id: int) -> Iterable[str]:
        return tuple(
            service.name
            for service_id, service in self.services.items()
            if service_id != excluding_service_id
        )

    def update_service(self, service_id: int, service: ServiceDraft) -> bool:
        if service_id not in self.services:
            return False
        self.services[service_id] = service
        self.updated_services.append((service_id, service))
        return True


def stored_service(*, is_active: bool = False) -> ServiceDraft:
    return ServiceDraft(
        name="Manicure clásico",
        description="Esmalte y cuidado.",
        duration_minutes=60,
        price=Decimal("350.00"),
        is_active=is_active,
        available_chiconcuac=True,
        available_texcoco=False,
    )


def valid_command(**overrides: object) -> EditServiceCommand:
    values: dict[str, object] = {
        "service_id": 1,
        "name": "  Manicure premium  ",
        "description": "  Esmalte, cuidado y diseño.  ",
        "duration_minutes": 90,
        "price": Decimal("500.00"),
        "branches": ["texcoco"],
        **overrides,
    }
    return EditServiceCommand(**values)  # type: ignore[arg-type]


def test_edit_service_updates_only_approved_fields_and_preserves_state() -> None:
    repository = FakeServiceEditingRepository({1: stored_service(is_active=False)})

    result = EditService(repository).execute(valid_command())

    assert result.service == ServiceDraft(
        name="Manicure premium",
        description="Esmalte, cuidado y diseño.",
        duration_minutes=90,
        price=Decimal("500.00"),
        is_active=False,
        available_chiconcuac=False,
        available_texcoco=True,
    )
    assert repository.updated_services == [(1, result.service)]


def test_edit_service_rejects_a_duplicate_name_before_persisting() -> None:
    repository = FakeServiceEditingRepository(
        {1: stored_service(), 2: ServiceDraft(
            name="Pedicure", description=None, duration_minutes=60,
            price=Decimal("350.00"), is_active=True,
            available_chiconcuac=True, available_texcoco=False,
        )}
    )

    with pytest.raises(ServiceNameUniquenessError):
        EditService(repository).execute(valid_command(name=" PEDICURE "))

    assert repository.updated_services == []


def test_edit_service_rejects_a_missing_service() -> None:
    repository = FakeServiceEditingRepository({})

    with pytest.raises(ServiceNotFoundError, match="not found"):
        EditService(repository).execute(valid_command())

    assert repository.updated_services == []

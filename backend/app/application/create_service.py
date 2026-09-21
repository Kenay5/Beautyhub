"""Internal use case for creating BeautyHub services."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from backend.app.domain.service import ServiceDraft, create_service_draft


@dataclass(frozen=True)
class CreateServiceCommand:
    """External input accepted by the internal service creation use case."""

    name: str
    description: str | None
    duration_minutes: int
    price: Decimal
    is_active: bool
    branches: Iterable[str]


@dataclass(frozen=True)
class CreatedService:
    """Service creation result without a web or database representation."""

    service_id: int
    service: ServiceDraft


class ServiceCreationRepository(Protocol):
    """Persistence boundary required to create a service."""

    def list_service_names(self) -> Iterable[str]:
        """Return persisted service names for canonical duplicate validation."""

    def create_service(self, service: ServiceDraft) -> int:
        """Persist a validated service and return its internal identifier."""


class CreateService:
    """Create a valid service without exposing an administrative web operation."""

    def __init__(self, repository: ServiceCreationRepository) -> None:
        self._repository = repository

    def execute(self, command: CreateServiceCommand) -> CreatedService:
        """Validate and persist one service through the configured repository."""

        service = create_service_draft(
            name=command.name,
            description=command.description,
            duration_minutes=command.duration_minutes,
            price=command.price,
            is_active=command.is_active,
            branches=command.branches,
            existing_names=self._repository.list_service_names(),
        )
        return CreatedService(
            service_id=self._repository.create_service(service),
            service=service,
        )

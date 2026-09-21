"""Internal use case for editing BeautyHub services."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from backend.app.domain.service import ServiceDraft, edit_service_draft


class ServiceNotFoundError(ValueError):
    """Raised when an internal service edit targets no existing service."""


@dataclass(frozen=True)
class EditServiceCommand:
    """Editable fields accepted by the internal service editing use case."""

    service_id: int
    name: str
    description: str | None
    duration_minutes: int
    price: Decimal
    branches: Iterable[str]


@dataclass(frozen=True)
class EditedService:
    """Result of editing a persisted service."""

    service_id: int
    service: ServiceDraft


class ServiceEditingRepository(Protocol):
    """Persistence boundary required to edit one service."""

    def get_service(self, service_id: int) -> ServiceDraft | None:
        """Return the current service state when the service exists."""

    def list_service_names(self, excluding_service_id: int) -> Iterable[str]:
        """Return other service names for canonical duplicate validation."""

    def update_service(self, service_id: int, service: ServiceDraft) -> bool:
        """Persist editable service fields and report whether a row changed."""


class EditService:
    """Edit approved service fields without exposing a web operation."""

    def __init__(self, repository: ServiceEditingRepository) -> None:
        self._repository = repository

    def execute(self, command: EditServiceCommand) -> EditedService:
        """Validate and persist an edit while preserving the active state."""

        current_service = self._repository.get_service(command.service_id)
        if current_service is None:
            raise ServiceNotFoundError("service was not found.")

        updated_service = edit_service_draft(
            name=command.name,
            description=command.description,
            duration_minutes=command.duration_minutes,
            price=command.price,
            branches=command.branches,
            existing_names=self._repository.list_service_names(command.service_id),
            is_active=current_service.is_active,
        )
        if not self._repository.update_service(command.service_id, updated_service):
            raise ServiceNotFoundError("service was not found.")

        return EditedService(service_id=command.service_id, service=updated_service)

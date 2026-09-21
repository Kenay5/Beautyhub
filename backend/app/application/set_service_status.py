"""Internal use case for activating or deactivating BeautyHub services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.app.domain.service import validate_service_state


class ServiceStatusNotFoundError(ValueError):
    """Raised when a status change targets no existing service."""


@dataclass(frozen=True)
class SetServiceStatusCommand:
    """Service state change accepted by the internal use case."""

    service_id: int
    is_active: bool


@dataclass(frozen=True)
class ServiceStatusChanged:
    """Result of a persisted service status change."""

    service_id: int
    is_active: bool


class ServiceStatusRepository(Protocol):
    """Persistence boundary required to change a service status."""

    def set_service_active(self, service_id: int, is_active: bool) -> bool:
        """Persist the requested state and report whether the service exists."""


class SetServiceStatus:
    """Activate or deactivate a service without deleting its history."""

    def __init__(self, repository: ServiceStatusRepository) -> None:
        self._repository = repository

    def execute(self, command: SetServiceStatusCommand) -> ServiceStatusChanged:
        """Persist a valid service state change."""

        is_active = validate_service_state(command.is_active)
        if not self._repository.set_service_active(command.service_id, is_active):
            raise ServiceStatusNotFoundError("service was not found.")
        return ServiceStatusChanged(
            service_id=command.service_id,
            is_active=is_active,
        )

"""Public use case for listing active BeautyHub services by branch."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from backend.app.domain.service_configuration import validate_service_branch


@dataclass(frozen=True)
class PublicService:
    """Service fields approved for the public catalog."""

    name: str
    duration_minutes: int
    price: Decimal


class ActiveServiceCatalog(Protocol):
    """Persistence boundary for the public active-service catalog."""

    def list_active_services(self, branch: str) -> Iterable[PublicService]:
        """Return active services available at the requested branch."""


class ListActiveServices:
    """Return public services eligible for selection at one branch."""

    def __init__(self, catalog: ActiveServiceCatalog) -> None:
        self._catalog = catalog

    def execute(self, branch: str) -> tuple[PublicService, ...]:
        """Validate the branch and return only its active services."""

        return tuple(self._catalog.list_active_services(validate_service_branch(branch)))

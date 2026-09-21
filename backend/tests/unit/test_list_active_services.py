"""Unit tests for listing active services by branch."""

from collections.abc import Iterable
from decimal import Decimal

import pytest

from backend.app.application.list_active_services import ListActiveServices, PublicService
from backend.app.domain.service_configuration import ServiceConfigurationValidationError


class FakeActiveServiceCatalog:
    """Small test double for the public service catalog boundary."""

    def __init__(self) -> None:
        self.requested_branch: str | None = None

    def list_active_services(self, branch: str) -> Iterable[PublicService]:
        self.requested_branch = branch
        return (PublicService("Manicure", 60, Decimal("350.00")),)


def test_active_service_list_validates_branch_before_reading_catalog() -> None:
    catalog = FakeActiveServiceCatalog()

    with pytest.raises(ServiceConfigurationValidationError):
        ListActiveServices(catalog).execute("otra")

    assert catalog.requested_branch is None


def test_active_service_list_returns_only_the_requested_branch_catalog() -> None:
    catalog = FakeActiveServiceCatalog()

    result = ListActiveServices(catalog).execute("texcoco")

    assert catalog.requested_branch == "texcoco"
    assert result == (PublicService("Manicure", 60, Decimal("350.00")),)

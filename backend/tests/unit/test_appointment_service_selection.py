"""Unit tests for service selection during appointment creation or changes."""

from decimal import Decimal

import pytest

from backend.app.domain.service import (
    AppointmentServiceSelectionError,
    ServiceDraft,
    validate_service_for_appointment,
)
from backend.app.domain.service_configuration import ServiceConfigurationValidationError


def appointment_service(
    *,
    is_active: bool = True,
    available_chiconcuac: bool = True,
    available_texcoco: bool = False,
) -> ServiceDraft:
    return ServiceDraft(
        name="Servicio ficticio",
        description=None,
        duration_minutes=60,
        price=Decimal("350.00"),
        is_active=is_active,
        available_chiconcuac=available_chiconcuac,
        available_texcoco=available_texcoco,
    )


def test_active_service_available_in_selected_branch_can_be_selected() -> None:
    service = appointment_service()

    assert validate_service_for_appointment(service, "chiconcuac") is service


@pytest.mark.parametrize(
    ("service", "branch", "error_message"),
    [
        (
            appointment_service(is_active=False),
            "chiconcuac",
            "must be active",
        ),
        (
            appointment_service(available_chiconcuac=False, available_texcoco=True),
            "chiconcuac",
            "not available",
        ),
    ],
)
def test_service_that_cannot_be_selected_is_rejected(
    service: ServiceDraft,
    branch: str,
    error_message: str,
) -> None:
    with pytest.raises(AppointmentServiceSelectionError, match=error_message):
        validate_service_for_appointment(service, branch)


def test_service_selection_rejects_an_unknown_branch() -> None:
    with pytest.raises(ServiceConfigurationValidationError, match="approved BeautyHub branch"):
        validate_service_for_appointment(appointment_service(), "unknown")

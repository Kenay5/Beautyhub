"""Service creation rules independent from infrastructure adapters."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from backend.app.domain.service_configuration import (
    validate_service_branch,
    validate_service_branches,
    validate_service_price,
)
from backend.app.domain.service_duration import validate_service_duration
from backend.app.domain.service_text import (
    ensure_service_name_is_unique,
    validate_service_text,
)


class ServiceStateValidationError(ValueError):
    """Raised when a service state is not represented as a Boolean value."""


class AppointmentServiceSelectionError(ValueError):
    """Raised when a service cannot be selected for an appointment."""


@dataclass(frozen=True)
class ServiceDraft:
    """Validated data required to persist a BeautyHub service."""

    name: str
    description: str | None
    duration_minutes: int
    price: Decimal
    is_active: bool
    available_chiconcuac: bool
    available_texcoco: bool


def create_service_draft(
    *,
    name: str,
    description: str | None,
    duration_minutes: int,
    price: Decimal,
    is_active: bool,
    branches: Iterable[str],
    existing_names: Iterable[str],
) -> ServiceDraft:
    """Validate the data required to create a service under RF-01."""

    normalized_name, normalized_description = validate_service_text(name, description)
    ensure_service_name_is_unique(normalized_name, existing_names)
    normalized_branches = validate_service_branches(branches)

    validate_service_state(is_active)

    return ServiceDraft(
        name=normalized_name,
        description=normalized_description,
        duration_minutes=validate_service_duration(duration_minutes),
        price=validate_service_price(price),
        is_active=is_active,
        available_chiconcuac="chiconcuac" in normalized_branches,
        available_texcoco="texcoco" in normalized_branches,
    )


def validate_service_state(is_active: bool) -> bool:
    """Validate the active or inactive state required by RF-01."""

    if not isinstance(is_active, bool):
        raise ServiceStateValidationError("service state must be a Boolean value.")
    return is_active


def validate_service_for_appointment(
    service: ServiceDraft,
    branch: str,
) -> ServiceDraft:
    """Require an active service that is available in the selected branch."""

    if not isinstance(service, ServiceDraft):
        raise AppointmentServiceSelectionError("service must be a validated ServiceDraft")

    normalized_branch = validate_service_branch(branch)
    if not service.is_active:
        raise AppointmentServiceSelectionError("service must be active for an appointment")

    is_available = (
        service.available_chiconcuac
        if normalized_branch == "chiconcuac"
        else service.available_texcoco
    )
    if not is_available:
        raise AppointmentServiceSelectionError(
            "service is not available in the selected branch",
        )

    return service


def edit_service_draft(
    *,
    name: str,
    description: str | None,
    duration_minutes: int,
    price: Decimal,
    branches: Iterable[str],
    existing_names: Iterable[str],
    is_active: bool,
) -> ServiceDraft:
    """Validate the editable fields while preserving the current service state."""

    return create_service_draft(
        name=name,
        description=description,
        duration_minutes=duration_minutes,
        price=price,
        is_active=is_active,
        branches=branches,
        existing_names=existing_names,
    )

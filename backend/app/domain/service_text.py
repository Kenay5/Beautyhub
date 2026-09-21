"""Pure validation for BeautyHub service names and descriptions."""

from __future__ import annotations

from collections.abc import Iterable
import unicodedata


MAX_SERVICE_NAME_LENGTH = 100
MAX_SERVICE_DESCRIPTION_LENGTH = 250


class ServiceTextValidationError(ValueError):
    """Raised when service text does not meet the approved domain rules."""


class ServiceNameUniquenessError(ValueError):
    """Raised when a service name duplicates an existing canonical name."""


def validate_service_text(
    name: str, description: str | None
) -> tuple[str, str | None]:
    """Trim and validate the service text required by RF-01-CA-01 and CA-02."""

    normalized_name = _validate_text(
        name,
        field_name="name",
        maximum_length=MAX_SERVICE_NAME_LENGTH,
        required=True,
    )
    normalized_description = (
        None
        if description is None
        else _validate_text(
            description,
            field_name="description",
            maximum_length=MAX_SERVICE_DESCRIPTION_LENGTH,
            required=False,
        )
    )
    return normalized_name, normalized_description


def canonicalize_service_name(name: str) -> str:
    """Return the comparison key required by RF-01-CA-03."""

    normalized_name, _ = validate_service_text(name, None)
    return normalized_name.lower()


def ensure_service_name_is_unique(
    name: str, existing_names: Iterable[str]
) -> str:
    """Reject a name that duplicates an existing service after canonicalization."""

    normalized_name, _ = validate_service_text(name, None)
    canonical_name = normalized_name.lower()
    if any(canonical_name == canonicalize_service_name(existing_name) for existing_name in existing_names):
        raise ServiceNameUniquenessError("service name must be unique.")
    return normalized_name


def _validate_text(
    value: str,
    *,
    field_name: str,
    maximum_length: int,
    required: bool,
) -> str:
    if not isinstance(value, str):
        raise ServiceTextValidationError(f"{field_name} must be a string.")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ServiceTextValidationError(
            f"{field_name} must not contain control characters."
        )

    normalized_value = value.strip()
    if required and not normalized_value:
        raise ServiceTextValidationError(f"{field_name} must not be empty.")
    if len(normalized_value) > maximum_length:
        raise ServiceTextValidationError(
            f"{field_name} must not exceed {maximum_length} characters."
        )
    return normalized_value

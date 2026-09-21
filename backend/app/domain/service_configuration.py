"""Pure validation for BeautyHub service prices and branch availability."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation


MIN_SERVICE_PRICE = Decimal("0.01")
MAX_SERVICE_PRICE = Decimal("20000.00")
MEXICAN_PESO_CENTS = Decimal("0.01")
AVAILABLE_SERVICE_BRANCHES = ("chiconcuac", "texcoco")


class ServiceConfigurationValidationError(ValueError):
    """Raised when a service price or its branches are not approved."""


def validate_service_branch(branch: str) -> str:
    """Validate one approved branch for a service catalog operation."""

    if not isinstance(branch, str) or branch not in AVAILABLE_SERVICE_BRANCHES:
        raise ServiceConfigurationValidationError(
            "branch must be an approved BeautyHub branch."
        )
    return branch


def validate_service_price(price: Decimal) -> Decimal:
    """Validate and normalize the MXN price required by RF-01-CA-01 and CA-05."""

    if not isinstance(price, Decimal) or not price.is_finite():
        raise ServiceConfigurationValidationError("price must be a finite Decimal value.")

    try:
        normalized_price = price.quantize(MEXICAN_PESO_CENTS)
    except InvalidOperation as error:
        raise ServiceConfigurationValidationError(
            "price must have at most two decimal places."
        ) from error

    if price != normalized_price:
        raise ServiceConfigurationValidationError(
            "price must have at most two decimal places."
        )
    if not MIN_SERVICE_PRICE <= normalized_price <= MAX_SERVICE_PRICE:
        raise ServiceConfigurationValidationError(
            "price must be between 0.01 and 20000.00 MXN."
        )

    return normalized_price


def validate_service_branches(branches: Iterable[str]) -> tuple[str, ...]:
    """Validate the at-least-one approved branch rule required by RF-01-CA-01."""

    if isinstance(branches, str):
        raise ServiceConfigurationValidationError("branches must be a collection.")

    try:
        selected_branches = set(branches)
    except TypeError as error:
        raise ServiceConfigurationValidationError("branches must be a collection.") from error

    if not selected_branches:
        raise ServiceConfigurationValidationError("at least one branch is required.")
    if not selected_branches.issubset(AVAILABLE_SERVICE_BRANCHES):
        raise ServiceConfigurationValidationError("branches must be approved BeautyHub branches.")

    return tuple(
        branch for branch in AVAILABLE_SERVICE_BRANCHES if branch in selected_branches
    )

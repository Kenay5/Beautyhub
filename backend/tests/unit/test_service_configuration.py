"""Unit tests for service price and branch validation."""

from decimal import Decimal

import pytest

from backend.app.domain.service_configuration import (
    ServiceConfigurationValidationError,
    validate_service_branches,
    validate_service_price,
)


@pytest.mark.parametrize(
    ("price", "expected_price"),
    [
        (Decimal("0.01"), Decimal("0.01")),
        (Decimal("350"), Decimal("350.00")),
        (Decimal("20000.00"), Decimal("20000.00")),
    ],
)
def test_service_price_accepts_the_approved_mxn_range(
    price: Decimal, expected_price: Decimal
) -> None:
    assert validate_service_price(price) == expected_price


@pytest.mark.parametrize(
    "price", [Decimal("0.00"), Decimal("-0.01"), Decimal("20000.01")]
)
def test_service_price_rejects_values_outside_the_approved_range(
    price: Decimal,
) -> None:
    with pytest.raises(ServiceConfigurationValidationError, match="between 0.01"):
        validate_service_price(price)


def test_service_price_rejects_more_than_two_decimal_places() -> None:
    with pytest.raises(ServiceConfigurationValidationError, match="at most two decimal"):
        validate_service_price(Decimal("10.001"))


@pytest.mark.parametrize("price", [10, 10.0, "10.00", True, Decimal("NaN")])
def test_service_price_rejects_non_decimal_or_non_finite_values(price: object) -> None:
    with pytest.raises(ServiceConfigurationValidationError, match="finite Decimal"):
        validate_service_price(price)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("branches", "expected_branches"),
    [
        (["chiconcuac"], ("chiconcuac",)),
        (["texcoco"], ("texcoco",)),
        (["texcoco", "chiconcuac"], ("chiconcuac", "texcoco")),
    ],
)
def test_service_branches_accept_one_or_both_approved_branches(
    branches: list[str], expected_branches: tuple[str, ...]
) -> None:
    assert validate_service_branches(branches) == expected_branches


@pytest.mark.parametrize("branches", [[], ["other"], "chiconcuac", [1]])
def test_service_branches_reject_empty_or_unsupported_values(branches: object) -> None:
    with pytest.raises(ServiceConfigurationValidationError):
        validate_service_branches(branches)  # type: ignore[arg-type]

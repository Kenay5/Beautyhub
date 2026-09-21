"""Unit tests for responsible-adult name validation (RF-03-CA-01)."""

import pytest

from backend.app.domain.customer_name import (
    CustomerNameValidationError,
    normalize_customer_name,
    normalize_customer_names,
)


@pytest.mark.parametrize("value", ["A", "A" * 100])
def test_customer_name_accepts_exact_length_bounds(value: str) -> None:
    assert normalize_customer_name(value) == value


def test_customer_name_trims_outer_spaces_and_preserves_supported_unicode() -> None:
    assert normalize_customer_name("  María José  ") == "María José"
    assert normalize_customer_name("  O’Connor  ") == "O’Connor"
    assert normalize_customer_name("  Ana-María  ") == "Ana-María"
    assert normalize_customer_name("  Jose\u0301  ") == "Jose\u0301"


@pytest.mark.parametrize("value", ["", "   ", "A" * 101])
def test_customer_name_rejects_empty_or_out_of_range_values(value: str) -> None:
    with pytest.raises(CustomerNameValidationError):
        normalize_customer_name(value)


@pytest.mark.parametrize(
    "value",
    ["Ana2", "Ana!", "Ana\tMaría", "Ana\nMaría", "Ana\u200bMaría", "Ana María🙂"],
)
def test_customer_name_rejects_digits_unsupported_punctuation_and_controls(
    value: str,
) -> None:
    with pytest.raises(CustomerNameValidationError):
        normalize_customer_name(value)


def test_customer_names_validate_first_and_last_names_independently() -> None:
    assert normalize_customer_names(" Ana ", " De la Cruz ") == ("Ana", "De la Cruz")


def test_customer_names_reject_a_missing_last_name() -> None:
    with pytest.raises(CustomerNameValidationError):
        normalize_customer_names("Ana", " ")

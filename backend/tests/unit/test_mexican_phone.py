"""Unit tests for Mexican phone normalization (RF-03-CA-02)."""

import pytest

from backend.app.domain.mexican_phone import (
    MexicanPhoneValidationError,
    normalize_mexican_phone,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5512345678", "5512345678"),
        (" 5512345678 ", "5512345678"),
        ("55 1234 5678", "5512345678"),
        ("55-1234-5678", "5512345678"),
        ("(55) 1234-5678", "5512345678"),
        ("+52 55 1234 5678", "5512345678"),
        ("+525512345678", "5512345678"),
        (" +52 (55) 1234-5678 ", "5512345678"),
    ],
)
def test_mexican_phone_normalizes_every_approved_form(value: str, expected: str) -> None:
    assert normalize_mexican_phone(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "+1 5512345678",
        "+5215512345678",
        "++52 5512345678",
        "55 1234 5678 ext 2",
        "55A2345678",
        "٥٥١٢٣٤٥٦٧٨",
        "551234567",
        "55123456789",
        "55\t12345678",
        "55+12345678",
        "+52",
    ],
)
def test_mexican_phone_rejects_unapproved_prefixes_extensions_characters_or_lengths(
    value: str,
) -> None:
    with pytest.raises(MexicanPhoneValidationError):
        normalize_mexican_phone(value)


def test_mexican_phone_rejects_non_string_input() -> None:
    with pytest.raises(MexicanPhoneValidationError):
        normalize_mexican_phone(5512345678)  # type: ignore[arg-type]

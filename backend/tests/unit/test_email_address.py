"""Unit tests for required email validation (RF-03-CA-03)."""

import pytest

from backend.app.domain.email_address import (
    EmailAddressValidationError,
    normalize_email_address,
)


@pytest.mark.parametrize(
    "value",
    [
        "aA1@example.test",
        "first.last+tag_2%ok@example-domain.test",
        "user@sub.domain.test",
        "user@ex4mpl3.d0m",
        "  User.Name+tag@Example.TEST  ",
    ],
)
def test_email_accepts_approved_ascii_forms_and_trims_outer_spaces(value: str) -> None:
    assert normalize_email_address(value) == value.strip(" ")


def test_email_accepts_the_exact_254_character_limit() -> None:
    email = f"{'a' * (254 - len('@example.test'))}@example.test"

    assert len(email) == 254
    assert normalize_email_address(email) == email


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        f"{'a' * 243}@example.test",
        "missing-at.example.test",
        "user@@example.test",
        "user@localhost",
        ".user@example.test",
        "user.@example.test",
        "first..last@example.test",
        "user@.example.test",
        "user@example..test",
        "user@example.",
        "user@-example.test",
        "user@example-.test",
        "user@example.c",
        "user@example.1a",
        "usér@example.test",
        "user@exámple.test",
        "user name@example.test",
        "user\t@example.test",
    ],
)
def test_email_rejects_invalid_lengths_structure_characters_and_domain_labels(
    value: str,
) -> None:
    with pytest.raises(EmailAddressValidationError):
        normalize_email_address(value)


def test_email_rejects_non_string_input() -> None:
    with pytest.raises(EmailAddressValidationError):
        normalize_email_address(None)  # type: ignore[arg-type]

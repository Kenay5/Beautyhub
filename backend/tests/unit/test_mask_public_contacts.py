"""T062 unit evidence for exact public contact masking rules."""

from __future__ import annotations

import pytest

from backend.app.application.mask_public_contacts import (
    PublicContactMaskingError,
    mask_public_email,
    mask_public_phone,
)


@pytest.mark.parametrize(
    ("phone", "expected"),
    (("5512345678", "******5678"), ("0000000000", "******0000")),
)
def test_t062_masks_phone_to_only_its_last_four_digits(
    phone: str,
    expected: str,
) -> None:
    assert mask_public_phone(phone) == expected


@pytest.mark.parametrize(
    ("email", "expected"),
    (
        ("ana@gmail.com", "a***@g***.com"),
        ("a@b.co", "a***@b***.co"),
        ("maria+turno@correo.beauty", "m***@c***.beauty"),
    ),
)
def test_t062_masks_email_and_preserves_extension_for_short_and_normal_values(
    email: str,
    expected: str,
) -> None:
    assert mask_public_email(email) == expected


@pytest.mark.parametrize("phone", ("551234567", "55123456789", "55123456a8"))
def test_t062_rejects_phone_values_that_are_not_normalized_ten_digits(phone: str) -> None:
    with pytest.raises(PublicContactMaskingError):
        mask_public_phone(phone)


@pytest.mark.parametrize("email", ("", "missing-at.example", "a@@b.co", "a@b"))
def test_t062_rejects_email_values_that_cannot_be_masked_safely(email: str) -> None:
    with pytest.raises(PublicContactMaskingError):
        mask_public_email(email)

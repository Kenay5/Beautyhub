"""T021 unit evidence for administrative email normalization and validation."""

from __future__ import annotations

import pytest

from backend.app.domain.authentication.admin_email_claim import (
    AdministrativeEmailClaimError,
    normalize_administrative_email_address,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (
            "  Owner.Name+ops%1@Accounts.Example.MX  ",
            "owner.name+ops%1@accounts.example.mx",
        ),
        ("staff_2@example-domain.test", "staff_2@example-domain.test"),
        ("person@sub.department.example", "person@sub.department.example"),
        ("person@123.abc", "person@123.abc"),
    ),
    ids=("trim-and-case-fold", "allowed-local-symbols", "multi-label-domain", "numeric-label"),
)
def test_t021_normalizes_outer_spaces_and_compares_without_case(
    value: str, expected: str
) -> None:
    assert normalize_administrative_email_address(value) == expected


def test_t021_accepts_the_exact_254_character_limit_after_trimming() -> None:
    email = f"{'a' * (254 - len('@example.test'))}@example.test"

    assert len(email) == 254
    assert normalize_administrative_email_address(f" {email} ") == email


@pytest.mark.parametrize(
    "value",
    (
        "",
        "   ",
        "a@example.test " * 30,
        "missing-at.example.test",
        "user@@example.test",
        "@example.test",
        "user@",
        ".user@example.test",
        "user.@example.test",
        "first..last@example.test",
        "user name@example.test",
        "user\tname@example.test",
        "usér@example.test",
        "user@localhost",
        "user@.example.test",
        "user@example..test",
        "user@example.",
        "user@-example.test",
        "user@example-.test",
        "user@example.c",
        "user@example.1a",
        "user@example.éx",
    ),
    ids=(
        "empty",
        "only-outer-spaces",
        "over-maximum-length",
        "missing-at",
        "multiple-at-signs",
        "empty-local-part",
        "empty-domain",
        "local-start-dot",
        "local-end-dot",
        "local-consecutive-dots",
        "local-space",
        "local-tab",
        "non-ascii-local",
        "domain-without-dot",
        "domain-empty-label",
        "domain-consecutive-empty-label",
        "domain-trailing-dot",
        "domain-label-start-hyphen",
        "domain-label-end-hyphen",
        "one-letter-tld",
        "numeric-only-tld",
        "non-ascii-tld",
    ),
)
def test_t021_rejects_invalid_lengths_characters_points_and_domain_segments(
    value: str,
) -> None:
    with pytest.raises(AdministrativeEmailClaimError):
        normalize_administrative_email_address(value)


def test_t021_rejects_non_string_values_without_coercion() -> None:
    with pytest.raises(AdministrativeEmailClaimError):
        normalize_administrative_email_address(None)  # type: ignore[arg-type]

"""Validation for the responsible adult's appointment name fields."""

from __future__ import annotations

import unicodedata


MIN_CUSTOMER_NAME_LENGTH = 1
MAX_CUSTOMER_NAME_LENGTH = 100
_ALLOWED_APOSTROPHES = frozenset({"'", "’"})
_ALLOWED_HYPHENS = frozenset({"-"})


class CustomerNameValidationError(ValueError):
    """Raised when a responsible adult's name field is invalid."""


def normalize_customer_name(value: str) -> str:
    """Trim and validate a name according to RF-03-CA-01."""

    if not isinstance(value, str):
        raise CustomerNameValidationError("name must be a string.")

    normalized = value.strip()
    if not MIN_CUSTOMER_NAME_LENGTH <= len(normalized) <= MAX_CUSTOMER_NAME_LENGTH:
        raise CustomerNameValidationError("name length is outside the approved range.")

    for character in normalized:
        if character == " ":
            continue
        if character in _ALLOWED_APOSTROPHES or character in _ALLOWED_HYPHENS:
            continue
        if unicodedata.category(character).startswith("L"):
            continue
        if unicodedata.category(character).startswith("M"):
            continue
        raise CustomerNameValidationError("name contains a character not allowed.")

    return normalized


def normalize_customer_names(first_name: str, last_name: str) -> tuple[str, str]:
    """Validate and normalize both required name fields."""

    return normalize_customer_name(first_name), normalize_customer_name(last_name)

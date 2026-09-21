"""Normalization for Mexican national phone numbers."""

from __future__ import annotations


_ALLOWED_PHONE_CHARACTERS = frozenset("0123456789 -()")
_PHONE_SEPARATORS = frozenset(" -()")
_MEXICO_COUNTRY_PREFIX = "+52"
MEXICAN_NATIONAL_PHONE_LENGTH = 10


class MexicanPhoneValidationError(ValueError):
    """Raised when a phone is not an approved Mexican national number."""


def normalize_mexican_phone(value: str) -> str:
    """Return ten ASCII digits from an approved phone form (RF-03-CA-02)."""

    if not isinstance(value, str):
        raise MexicanPhoneValidationError("phone must be a string.")

    normalized = value.strip(" ")
    if normalized.startswith(_MEXICO_COUNTRY_PREFIX):
        national_part = normalized[len(_MEXICO_COUNTRY_PREFIX) :]
    else:
        national_part = normalized

    if any(character not in _ALLOWED_PHONE_CHARACTERS for character in national_part):
        raise MexicanPhoneValidationError("phone contains a character not allowed.")

    digits = "".join(
        character for character in national_part if character not in _PHONE_SEPARATORS
    )
    if len(digits) != MEXICAN_NATIONAL_PHONE_LENGTH:
        raise MexicanPhoneValidationError("phone must contain exactly ten national digits.")

    return digits

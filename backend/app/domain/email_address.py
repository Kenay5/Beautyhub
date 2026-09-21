"""Validation and normalization for required appointment email addresses."""

from __future__ import annotations

import string


MIN_EMAIL_LENGTH = 1
MAX_EMAIL_LENGTH = 254
_LOCAL_PART_CHARACTERS = frozenset(
    string.ascii_letters + string.digits + "._%+-"
)
_DOMAIN_LABEL_CHARACTERS = frozenset(string.ascii_letters + string.digits + "-")
_ASCII_LETTERS = frozenset(string.ascii_letters)
_ASCII_ALPHANUMERIC = frozenset(string.ascii_letters + string.digits)


class EmailAddressValidationError(ValueError):
    """Raised when an appointment email does not meet RF-03-CA-03."""


def normalize_email_address(value: str) -> str:
    """Trim outer spaces, validate the approved ASCII email form, preserve case."""

    if not isinstance(value, str):
        raise EmailAddressValidationError("email must be a string.")

    normalized = value.strip(" ")
    if not MIN_EMAIL_LENGTH <= len(normalized) <= MAX_EMAIL_LENGTH:
        raise EmailAddressValidationError("email length is outside the approved range.")
    if normalized.count("@") != 1:
        raise EmailAddressValidationError("email must contain exactly one at sign.")

    local_part, domain = normalized.split("@")
    _validate_local_part(local_part)
    _validate_domain(domain)
    return normalized


def _validate_local_part(local_part: str) -> None:
    if not local_part or any(character not in _LOCAL_PART_CHARACTERS for character in local_part):
        raise EmailAddressValidationError("email local part contains a character not allowed.")
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        raise EmailAddressValidationError("email local part has an invalid dot placement.")


def _validate_domain(domain: str) -> None:
    labels = domain.split(".")
    if len(labels) < 2:
        raise EmailAddressValidationError("email domain must contain a dot.")

    for label in labels:
        if (
            not label
            or any(character not in _DOMAIN_LABEL_CHARACTERS for character in label)
            or label[0] not in _ASCII_ALPHANUMERIC
            or label[-1] not in _ASCII_ALPHANUMERIC
        ):
            raise EmailAddressValidationError("email domain contains an invalid label.")

    if sum(character in _ASCII_LETTERS for character in labels[-1]) < 2:
        raise EmailAddressValidationError("email final domain label must contain two letters.")

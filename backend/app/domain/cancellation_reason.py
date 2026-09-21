"""Validation for the optional cancellation reason required by RF-07."""

from __future__ import annotations

import unicodedata


MAX_CANCELLATION_REASON_LENGTH = 250


class CancellationReasonValidationError(ValueError):
    """Raised when an optional cancellation reason is not approved text."""


def normalize_cancellation_reason(value: str | None) -> str | None:
    """Return the approved reason or absence after applying RF-07-CA-05."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise CancellationReasonValidationError(
            "cancellation reason must be a string or absent."
        )
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise CancellationReasonValidationError(
            "cancellation reason must not contain control characters."
        )

    normalized_value = value.strip()
    if not normalized_value:
        return None
    if len(normalized_value) > MAX_CANCELLATION_REASON_LENGTH:
        raise CancellationReasonValidationError(
            "cancellation reason must not exceed 250 characters."
        )
    return normalized_value

"""Approved administrative-password validation without password persistence."""

from __future__ import annotations

from typing import Protocol


MINIMUM_PASSWORD_LENGTH = 12
MAXIMUM_PASSWORD_LENGTH = 128


class AdministrativePasswordValidationError(ValueError):
    """Raised when a proposed administrative password is not approved."""


class BlockedPasswordChecker(Protocol):
    """Check membership without retaining the supplied password."""

    def contains(self, password: str) -> bool:
        """Return whether the exact supplied password is locally blocked."""


def validate_administrative_password(
    password: str,
    *,
    blocked_passwords: BlockedPasswordChecker,
) -> None:
    """Apply only the password rules approved for administrative accounts."""

    if not isinstance(password, str):
        raise AdministrativePasswordValidationError("administrative password is invalid.")
    if not MINIMUM_PASSWORD_LENGTH <= len(password) <= MAXIMUM_PASSWORD_LENGTH:
        raise AdministrativePasswordValidationError("administrative password is invalid.")
    if password.isspace():
        raise AdministrativePasswordValidationError("administrative password is invalid.")
    if blocked_passwords.contains(password):
        raise AdministrativePasswordValidationError("administrative password is invalid.")

"""Argon2id password hashing without retaining clear administrative passwords."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type


ARGON2_MEMORY_COST_KIB = 19 * 1024
ARGON2_TIME_COST = 2
ARGON2_PARALLELISM = 1
_DUMMY_PASSWORD_BYTES = 32


class AdministrativePasswordHashError(ValueError):
    """Raised when a password cannot be safely hashed or verified."""


@dataclass(frozen=True)
class PasswordVerification:
    """The only password-verification result exposed to application code."""

    verified: bool
    upgraded_hash: str | None


class AdministrativePasswordHasher:
    """Hash and verify passwords with the approved Argon2id parameters."""

    def __init__(self, *, password_hasher: PasswordHasher | None = None) -> None:
        self._password_hasher = password_hasher or PasswordHasher(
            time_cost=ARGON2_TIME_COST,
            memory_cost=ARGON2_MEMORY_COST_KIB,
            parallelism=ARGON2_PARALLELISM,
            type=Type.ID,
        )
        self._dummy_hash = self._password_hasher.hash(
            secrets.token_urlsafe(_DUMMY_PASSWORD_BYTES)
        )

    def hash_password(self, password: str) -> str:
        """Return one salted PHC Argon2id hash without retaining the password."""

        _require_password_string(password)
        return self._password_hasher.hash(password)

    def verify_and_upgrade(
        self,
        *,
        stored_hash: str,
        password: str,
    ) -> PasswordVerification:
        """Verify a stored hash and return a strengthened replacement when needed."""

        _require_password_string(password)
        if not isinstance(stored_hash, str) or not stored_hash:
            return PasswordVerification(verified=False, upgraded_hash=None)
        try:
            self._password_hasher.verify(stored_hash, password)
        except (InvalidHashError, VerificationError):
            return PasswordVerification(verified=False, upgraded_hash=None)

        upgraded_hash = (
            self._password_hasher.hash(password)
            if self._password_hasher.check_needs_rehash(stored_hash)
            else None
        )
        return PasswordVerification(verified=True, upgraded_hash=upgraded_hash)

    def verify_unknown_account(self, *, password: str) -> PasswordVerification:
        """Perform equivalent bounded Argon2id work without confirming an account."""

        _require_password_string(password)
        try:
            self._password_hasher.verify(self._dummy_hash, password)
        except (InvalidHashError, VerificationError):
            pass
        return PasswordVerification(verified=False, upgraded_hash=None)


def _require_password_string(password: str) -> None:
    if not isinstance(password, str):
        raise AdministrativePasswordHashError("administrative password is invalid.")

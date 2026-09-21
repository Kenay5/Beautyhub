"""Pure rules for administrative credential failure protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, TypeAlias


AdministrativeCredentialOperation: TypeAlias = Literal[
    "login",
    "password_change",
    "email_change",
    "totp_replacement",
    "recovery_code_regeneration",
]

ADMINISTRATIVE_CREDENTIAL_FAILURE_LIMIT: Final = 5
ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW: Final = timedelta(minutes=15)


class AdministrativeAccountSecurityInvariantError(ValueError):
    """Raised when account-security state is not safely shaped."""


@dataclass(frozen=True)
class AdministrativeCredentialFailureResult:
    """The observable outcome of one rejected credential request."""

    failure_count: int
    lock_until: datetime | None
    blocked: bool
    failure_event_id: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.failure_count, bool) or self.failure_count < 0:
            raise AdministrativeAccountSecurityInvariantError(
                "administrative credential failure count is invalid."
            )
        if self.lock_until is not None and (
            self.lock_until.tzinfo is None or self.lock_until.utcoffset() is None
        ):
            raise AdministrativeAccountSecurityInvariantError(
                "administrative credential block expiry is invalid."
            )
        if self.blocked and self.lock_until is None:
            raise AdministrativeAccountSecurityInvariantError(
                "blocked administrative credential result requires an expiry."
            )
        if self.failure_event_id is not None and (
            isinstance(self.failure_event_id, bool)
            or not isinstance(self.failure_event_id, int)
            or self.failure_event_id <= 0
        ):
            raise AdministrativeAccountSecurityInvariantError(
                "administrative credential failure event identifier is invalid."
            )

    @property
    def started_lock(self) -> bool:
        return (
            not self.blocked
            and self.failure_count == ADMINISTRATIVE_CREDENTIAL_FAILURE_LIMIT
            and self.lock_until is not None
            and self.failure_event_id is not None
        )


def is_administrative_account_locked(*, lock_until: datetime | None, now: datetime) -> bool:
    """Keep the account blocked until, but not including, the exact expiry instant."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise AdministrativeAccountSecurityInvariantError(
            "administrative security clock instant must be aware."
        )
    if lock_until is None:
        return False
    if lock_until.tzinfo is None or lock_until.utcoffset() is None:
        raise AdministrativeAccountSecurityInvariantError(
            "administrative credential block expiry is invalid."
        )
    return now < lock_until

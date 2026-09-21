"""Approved administrative moving-window limit definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal, TypeAlias


AdministrativeRateLimitCategory: TypeAlias = Literal[
    "authentication_recovery_lost_factor",
    "authenticated_administrative_operation",
    "security_message_action",
    "appointment_notification_operation",
]


class AdministrativeRateLimitInvariantError(ValueError):
    """Raised when an administrative rate-limit input is unsafe."""


@dataclass(frozen=True)
class AdministrativeRateLimit:
    """One approved shared moving-window limit."""

    category: AdministrativeRateLimitCategory
    capacity: int
    window: timedelta

    def __post_init__(self) -> None:
        if self.capacity <= 0 or self.window <= timedelta(0):
            raise AdministrativeRateLimitInvariantError(
                "administrative rate limit is invalid."
            )


AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT: Final = AdministrativeRateLimit(
    category="authentication_recovery_lost_factor",
    capacity=20,
    window=timedelta(minutes=15),
)
AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT: Final = AdministrativeRateLimit(
    category="authenticated_administrative_operation",
    capacity=120,
    window=timedelta(minutes=1),
)
SECURITY_MESSAGE_ACTION_LIMIT: Final = AdministrativeRateLimit(
    category="security_message_action",
    capacity=10,
    window=timedelta(minutes=15),
)
APPOINTMENT_NOTIFICATION_OPERATION_LIMIT: Final = AdministrativeRateLimit(
    category="appointment_notification_operation",
    capacity=30,
    window=timedelta(minutes=15),
)

ADMINISTRATIVE_RATE_LIMITS: Final = {
    limit.category: limit
    for limit in (
        AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT,
        SECURITY_MESSAGE_ACTION_LIMIT,
        APPOINTMENT_NOTIFICATION_OPERATION_LIMIT,
    )
}


def require_rate_limit_fingerprint(value: bytes, *, field_name: str) -> None:
    """Require the fixed-size keyed digest shape, never a readable subject."""

    if not isinstance(value, bytes) or len(value) != 32:
        raise AdministrativeRateLimitInvariantError(
            f"administrative rate limit {field_name} fingerprint is invalid."
        )

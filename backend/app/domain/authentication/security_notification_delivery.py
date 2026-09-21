"""Private, idempotent administrative security-delivery invariants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias


SecurityNotificationDeliveryStatus: TypeAlias = Literal[
    "pending", "accepted", "failed", "uncertain"
]

PENDING_SECURITY_NOTIFICATION_DELIVERY_STATUS: Final[SecurityNotificationDeliveryStatus] = (
    "pending"
)
FAILED_SECURITY_NOTIFICATION_DELIVERY_STATUS: Final[SecurityNotificationDeliveryStatus] = (
    "failed"
)
SANITIZED_SECURITY_DELIVERY_FAILURE: Final = "security delivery failed."


class SecurityNotificationDeliveryInvariantError(ValueError):
    """Raised when a security-delivery record could expose private data."""


@dataclass(frozen=True)
class SecurityNotificationDelivery:
    """One storage-safe delivery intent with no readable recipient or secret."""

    event: str
    recipient_ciphertext: bytes | None
    recipient_key_version: str | None
    template: str
    idempotency_key_digest: bytes
    status: SecurityNotificationDeliveryStatus = (
        PENDING_SECURITY_NOTIFICATION_DELIVERY_STATUS
    )
    sanitized_error: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.event, "event")
        _require_identifier(self.template, "template")
        if (self.recipient_ciphertext is None) != (self.recipient_key_version is None):
            raise SecurityNotificationDeliveryInvariantError(
                "security delivery recipient protection is invalid."
            )
        if self.recipient_ciphertext is not None:
            if not isinstance(self.recipient_ciphertext, bytes) or not self.recipient_ciphertext:
                raise SecurityNotificationDeliveryInvariantError(
                    "security delivery recipient ciphertext is invalid."
                )
            if (
                not isinstance(self.recipient_key_version, str)
                or not self.recipient_key_version.strip()
                or self.recipient_key_version != self.recipient_key_version.strip()
            ):
                raise SecurityNotificationDeliveryInvariantError(
                    "security delivery recipient key version is invalid."
                )
        if (
            not isinstance(self.idempotency_key_digest, bytes)
            or len(self.idempotency_key_digest) != 32
        ):
            raise SecurityNotificationDeliveryInvariantError(
                "security delivery idempotency key is invalid."
            )
        if self.status not in {"pending", "accepted", "failed", "uncertain"}:
            raise SecurityNotificationDeliveryInvariantError(
                "security delivery status is invalid."
            )
        if self.status == FAILED_SECURITY_NOTIFICATION_DELIVERY_STATUS:
            if self.sanitized_error != SANITIZED_SECURITY_DELIVERY_FAILURE:
                raise SecurityNotificationDeliveryInvariantError(
                    "security delivery error is invalid."
                )
        elif self.sanitized_error is not None:
            raise SecurityNotificationDeliveryInvariantError(
                "security delivery error is invalid."
            )


def _require_identifier(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 100
        or not value[0].islower()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value)
    ):
        raise SecurityNotificationDeliveryInvariantError(
            f"security delivery {field_name} is invalid."
        )

"""Provider-neutral ports and immediate outcomes for transactional messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeAlias


NotificationChannel: TypeAlias = Literal["email", "whatsapp"]
NotificationSendOutcome: TypeAlias = Literal["accepted", "failed", "uncertain"]

EMAIL_CHANNEL: NotificationChannel = "email"
WHATSAPP_CHANNEL: NotificationChannel = "whatsapp"


@dataclass(frozen=True)
class OutboundNotification:
    """A prepared message for one channel without provider-specific fields."""

    channel: NotificationChannel
    recipient: str = field(repr=False)
    content: str = field(repr=False)
    idempotency_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_channel(self.channel)
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str) or not self.idempotency_key
        ):
            raise ValueError("notification idempotency key is invalid.")


@dataclass(frozen=True)
class NotificationSendResult:
    """Controlled immediate provider outcome; acceptance is not delivery."""

    channel: NotificationChannel
    outcome: NotificationSendOutcome

    def __post_init__(self) -> None:
        _require_channel(self.channel)
        if self.outcome not in {"accepted", "failed", "uncertain"}:
            raise ValueError("notification outcome is invalid.")

    @classmethod
    def accepted(cls, channel: NotificationChannel) -> NotificationSendResult:
        """Represent provider acceptance without claiming final delivery."""

        return cls(channel=channel, outcome="accepted")

    @classmethod
    def failed(cls, channel: NotificationChannel) -> NotificationSendResult:
        """Represent a controlled immediate sending failure."""

        return cls(channel=channel, outcome="failed")

    @classmethod
    def uncertain(cls, channel: NotificationChannel) -> NotificationSendResult:
        """Represent an unresolved provider outcome without assuming delivery."""

        return cls(channel=channel, outcome="uncertain")


class NotificationDeliveryUncertain(RuntimeError):
    """The provider may have accepted a message but cannot confirm its outcome."""


class TransactionalNotificationPort(Protocol):
    """Send one prepared transactional notification through an adapter."""

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        """Return a controlled acceptance or failure without exposing provider data."""


def _require_channel(channel: str) -> None:
    if channel not in {EMAIL_CHANNEL, WHATSAPP_CHANNEL}:
        raise ValueError("notification channel must be email or whatsapp.")

"""T084 unit evidence for provider-neutral transactional notification ports."""

from __future__ import annotations

import pytest

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)


class ControlledNotificationPort:
    """A deterministic stand-in shared by the two channels."""

    def __init__(self, outcome: str) -> None:
        self._outcome = outcome
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        return (
            NotificationSendResult.accepted(notification.channel)
            if self._outcome == "accepted"
            else NotificationSendResult.failed(notification.channel)
        )


@pytest.mark.parametrize("channel", (EMAIL_CHANNEL, WHATSAPP_CHANNEL))
@pytest.mark.parametrize("outcome", ("accepted", "failed"))
def test_t084_both_channels_share_one_controlled_result_contract(
    channel: str,
    outcome: str,
) -> None:
    port: TransactionalNotificationPort = ControlledNotificationPort(outcome)
    notification = OutboundNotification(
        channel=channel,  # type: ignore[arg-type]
        recipient="synthetic-recipient",
        content="Synthetic transactional content.",
    )

    result = port.send(notification)

    assert result.channel == channel
    assert result.outcome == outcome


def test_t084_acceptance_does_not_claim_provider_delivery() -> None:
    result = NotificationSendResult.accepted(EMAIL_CHANNEL)

    assert result.outcome == "accepted"
    assert result.outcome != "delivered"


def test_t084_notification_data_is_not_in_debug_representations() -> None:
    notification = OutboundNotification(
        channel=WHATSAPP_CHANNEL,
        recipient="synthetic-recipient",
        content="Synthetic transactional content.",
    )

    assert "synthetic-recipient" not in repr(notification)
    assert "Synthetic transactional content." not in repr(notification)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: OutboundNotification("unsupported", "recipient", "content"),
        lambda: NotificationSendResult("email", "delivered"),
    ),
)
def test_t084_rejects_uncontrolled_channels_or_outcomes(factory) -> None:
    with pytest.raises(ValueError):
        factory()

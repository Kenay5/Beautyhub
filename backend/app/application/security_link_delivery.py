"""Resolve one security-link email outcome without guessing on uncertainty."""

from __future__ import annotations

from typing import Protocol

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationDeliveryUncertain,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)


class ReconciliableNotificationPort(TransactionalNotificationPort, Protocol):
    """Optional provider capability keyed by the original stable delivery key."""

    def reconcile(self, *, idempotency_key: str) -> NotificationSendResult | None:
        """Return a confirmed outcome, or None while the provider remains uncertain."""


def send_security_link_notification(
    *,
    sender: TransactionalNotificationPort,
    notification: OutboundNotification,
) -> NotificationSendResult:
    """Send once and reconcile uncertainty with the same key when supported.

    An unresolved result stays uncertain: callers must persist that state and
    keep the link unusable until a confirmed result or a distinct retry.
    Ordinary exceptions are treated as immediate failure, as the provider
    contract says they did not report an indeterminate acceptance.
    """

    try:
        result = sender.send(notification)
    except NotificationDeliveryUncertain:
        result = NotificationSendResult.uncertain(EMAIL_CHANNEL)
    except Exception:
        return NotificationSendResult.failed(EMAIL_CHANNEL)

    if result.outcome == "uncertain":
        reconcile = getattr(sender, "reconcile", None)
        if notification.idempotency_key is not None and callable(reconcile):
            try:
                reconciled = reconcile(idempotency_key=notification.idempotency_key)
            except Exception:
                reconciled = None
        else:
            reconciled = None
        if reconciled is None or reconciled.outcome == "uncertain":
            return NotificationSendResult.uncertain(EMAIL_CHANNEL)
        result = reconciled

    if result.channel != EMAIL_CHANNEL:
        return NotificationSendResult.failed(EMAIL_CHANNEL)
    return result

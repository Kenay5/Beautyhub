"""T097 tests for safe provider outcome resolution and stable idempotency."""

from __future__ import annotations

from backend.app.application.security_link_delivery import send_security_link_notification
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationDeliveryUncertain,
    NotificationSendResult,
    OutboundNotification,
)


class _Sender:
    def __init__(self, *, result: NotificationSendResult | None = None) -> None:
        self.result = result
        self.notification: OutboundNotification | None = None
        self.reconciled_key: str | None = None

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notification = notification
        if self.result is None:
            raise NotificationDeliveryUncertain("provider state unavailable")
        return self.result

    def reconcile(self, *, idempotency_key: str) -> NotificationSendResult | None:
        self.reconciled_key = idempotency_key
        return None


def _notification() -> OutboundNotification:
    return OutboundNotification(
        channel=EMAIL_CHANNEL,
        recipient="synthetic@example.test",
        content="A security link is available.",
        idempotency_key="security-link:42",
    )


def test_t097_unknown_result_reconciles_with_same_key_and_stays_uncertain() -> None:
    sender = _Sender()

    result = send_security_link_notification(sender=sender, notification=_notification())

    assert result == NotificationSendResult.uncertain(EMAIL_CHANNEL)
    assert sender.reconciled_key == "security-link:42"


def test_t097_confirmed_acceptance_is_preserved_after_reconciliation() -> None:
    class AcceptedOnReconcile(_Sender):
        def reconcile(self, *, idempotency_key: str) -> NotificationSendResult:
            self.reconciled_key = idempotency_key
            return NotificationSendResult.accepted(EMAIL_CHANNEL)

    sender = AcceptedOnReconcile()

    result = send_security_link_notification(sender=sender, notification=_notification())

    assert result == NotificationSendResult.accepted(EMAIL_CHANNEL)
    assert sender.reconciled_key == "security-link:42"


def test_t097_immediate_exception_is_a_controlled_failure() -> None:
    class FailedImmediately(_Sender):
        def send(self, notification: OutboundNotification) -> NotificationSendResult:
            self.notification = notification
            raise RuntimeError("provider rejected request")

    result = send_security_link_notification(
        sender=FailedImmediately(), notification=_notification()
    )

    assert result == NotificationSendResult.failed(EMAIL_CHANNEL)

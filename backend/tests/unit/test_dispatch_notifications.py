"""T089 unit evidence for independent post-commit channel dispatch."""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.application.dispatch_notifications import (
    SANITIZED_DELIVERY_FAILURE,
    NotificationDispatcher,
    PendingNotificationDelivery,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.domain.notification_delivery import (
    ACCEPTED_DELIVERY_STATUS,
    FAILED_DELIVERY_STATUS,
)
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator


DISPATCHED_AT = datetime(2030, 6, 15, 12, 0)


class RecordingResultWriter:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []

    def record_result(self, **result: object) -> None:
        self.results.append(result)


class RaisingPort(TransactionalNotificationPort):
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.calls = 0

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.calls += 1
        raise RuntimeError("provider secret must not escape")


@pytest.mark.parametrize(
    ("email_outcome", "whatsapp_outcome"),
    (("accepted", "accepted"), ("failed", "accepted"), ("accepted", "failed")),
)
def test_t089_dispatches_each_channel_and_records_independent_results(
    email_outcome: str,
    whatsapp_outcome: str,
) -> None:
    writer = RecordingResultWriter()
    dispatcher = NotificationDispatcher(
        email_port=EmailSimulator(outcome=email_outcome),  # type: ignore[arg-type]
        whatsapp_port=WhatsAppSimulator(outcome=whatsapp_outcome),  # type: ignore[arg-type]
        result_writer=writer,
    )

    results = dispatcher.dispatch(
        deliveries=(
            _pending(31, EMAIL_CHANNEL),
            _pending(32, WHATSAPP_CHANNEL),
        ),
        dispatched_at=DISPATCHED_AT,
    )

    expected_email = (
        ACCEPTED_DELIVERY_STATUS
        if email_outcome == "accepted"
        else FAILED_DELIVERY_STATUS
    )
    expected_whatsapp = (
        ACCEPTED_DELIVERY_STATUS
        if whatsapp_outcome == "accepted"
        else FAILED_DELIVERY_STATUS
    )
    assert tuple(result.status for result in results) == (
        expected_email,
        expected_whatsapp,
    )
    assert [result["delivery_id"] for result in writer.results] == [31, 32]
    assert [result["status"] for result in writer.results] == [
        expected_email,
        expected_whatsapp,
    ]
    assert all(result["status_changed_at"] == DISPATCHED_AT for result in writer.results)
    assert all(
        result["sanitized_error"] is None
        for result, expected in zip(
            writer.results,
            (expected_email, expected_whatsapp),
        )
        if expected == ACCEPTED_DELIVERY_STATUS
    )
    assert all(
        result["sanitized_error"] == SANITIZED_DELIVERY_FAILURE
        for result, expected in zip(
            writer.results,
            (expected_email, expected_whatsapp),
        )
        if expected == FAILED_DELIVERY_STATUS
    )


def test_t089_provider_exception_is_sanitized_and_does_not_stop_other_channel() -> None:
    writer = RecordingResultWriter()
    whatsapp = WhatsAppSimulator(outcome="accepted")
    dispatcher = NotificationDispatcher(
        email_port=RaisingPort(EMAIL_CHANNEL),
        whatsapp_port=whatsapp,
        result_writer=writer,
    )

    results = dispatcher.dispatch(
        deliveries=(_pending(41, EMAIL_CHANNEL), _pending(42, WHATSAPP_CHANNEL)),
        dispatched_at=DISPATCHED_AT,
    )

    assert results[0].status == FAILED_DELIVERY_STATUS
    assert results[0].sanitized_error == SANITIZED_DELIVERY_FAILURE
    assert results[1].status == ACCEPTED_DELIVERY_STATUS
    assert whatsapp.notifications
    assert "provider secret" not in repr(results)
    assert "provider secret" not in repr(writer.results)


def test_t089_acceptance_never_becomes_delivered() -> None:
    writer = RecordingResultWriter()
    dispatcher = NotificationDispatcher(
        email_port=EmailSimulator(outcome="accepted"),
        whatsapp_port=WhatsAppSimulator(outcome="accepted"),
        result_writer=writer,
    )

    results = dispatcher.dispatch(
        deliveries=(_pending(51, EMAIL_CHANNEL), _pending(52, WHATSAPP_CHANNEL)),
        dispatched_at=DISPATCHED_AT,
    )

    assert all(result.status == ACCEPTED_DELIVERY_STATUS for result in results)
    assert all(result["status"] == ACCEPTED_DELIVERY_STATUS for result in writer.results)


def _pending(delivery_id: int, channel: str) -> PendingNotificationDelivery:
    return PendingNotificationDelivery(
        delivery_id=delivery_id,
        notification=OutboundNotification(
            channel=channel,  # type: ignore[arg-type]
            recipient="synthetic-recipient",
            content="Synthetic transactional content.",
        ),
    )

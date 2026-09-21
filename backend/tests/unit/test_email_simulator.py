"""T087 unit evidence for the provider-free email simulator."""

from __future__ import annotations

import pytest

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import (
    EmailSimulator,
    EmailSimulatorUncertainOutcome,
)


@pytest.mark.parametrize("outcome", ("accepted", "failed"))
def test_t087_records_the_controlled_email_result(
    outcome: str,
) -> None:
    simulator: TransactionalNotificationPort = EmailSimulator(outcome=outcome)  # type: ignore[arg-type]
    notification = OutboundNotification(
        channel=EMAIL_CHANNEL,
        recipient="synthetic@example.test",
        content="Synthetic transactional content.",
    )

    result = simulator.send(notification)

    assert result == NotificationSendResult(channel=EMAIL_CHANNEL, outcome=outcome)
    assert simulator.notifications == (notification,)  # type: ignore[attr-defined]
    assert simulator.results == (result,)  # type: ignore[attr-defined]


def test_t087_does_not_accept_whatsapp_or_contact_an_external_provider() -> None:
    simulator = EmailSimulator(outcome="accepted")
    notification = OutboundNotification(
        channel=WHATSAPP_CHANNEL,
        recipient="synthetic-phone",
        content="Synthetic transactional content.",
    )

    with pytest.raises(ValueError):
        simulator.send(notification)

    assert simulator.notifications == ()
    assert simulator.results == ()


def test_t087_rejects_an_uncontrolled_outcome() -> None:
    with pytest.raises(ValueError):
        EmailSimulator(outcome="delivered")  # type: ignore[arg-type]


def test_t007_rejects_a_message_without_contacting_a_provider() -> None:
    simulator = EmailSimulator(outcome="rejected")
    notification = OutboundNotification(
        channel=EMAIL_CHANNEL,
        recipient="synthetic@example.test",
        content="Synthetic transactional content.",
    )

    assert simulator.send(notification) == NotificationSendResult.failed(EMAIL_CHANNEL)


def test_t007_exposes_uncertainty_without_provider_details() -> None:
    simulator = EmailSimulator(outcome="uncertain")
    notification = OutboundNotification(
        channel=EMAIL_CHANNEL,
        recipient="synthetic@example.test",
        content="Synthetic transactional content.",
    )

    with pytest.raises(EmailSimulatorUncertainOutcome) as error:
        simulator.send(notification)

    assert str(error.value) == "email provider outcome is uncertain."
    assert "synthetic@example.test" not in str(error.value)


def test_t007_emits_one_late_failure_after_initial_acceptance() -> None:
    from datetime import datetime, timezone

    simulator = EmailSimulator(outcome="late_failure")
    notification = OutboundNotification(
        channel=EMAIL_CHANNEL,
        recipient="synthetic@example.test",
        content="Synthetic transactional content.",
    )

    assert simulator.send(notification) == NotificationSendResult.accepted(EMAIL_CHANNEL)
    update = simulator.emit_late_failure(
        delivery_id=31,
        occurred_at=datetime(2030, 6, 15, 12, tzinfo=timezone.utc),
    )

    assert update.delivery_id == 31
    assert update.channel == EMAIL_CHANNEL
    with pytest.raises(ValueError, match="no pending late failure"):
        simulator.emit_late_failure(
            delivery_id=31,
            occurred_at=datetime(2030, 6, 15, 12, tzinfo=timezone.utc),
        )

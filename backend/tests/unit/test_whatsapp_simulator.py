"""T088 unit evidence for the provider-free WhatsApp simulator."""

from __future__ import annotations

import pytest

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator


@pytest.mark.parametrize("outcome", ("accepted", "no_whatsapp", "failed"))
def test_t088_records_controlled_success_absence_or_failure(
    outcome: str,
) -> None:
    simulator: TransactionalNotificationPort = WhatsAppSimulator(outcome=outcome)  # type: ignore[arg-type]
    notification = OutboundNotification(
        channel=WHATSAPP_CHANNEL,
        recipient="synthetic-phone",
        content="Synthetic transactional content.",
    )

    result = simulator.send(notification)

    expected_result = (
        NotificationSendResult.accepted(WHATSAPP_CHANNEL)
        if outcome == "accepted"
        else NotificationSendResult.failed(WHATSAPP_CHANNEL)
    )
    assert result == expected_result
    assert simulator.notifications == (notification,)  # type: ignore[attr-defined]
    assert simulator.results == (result,)  # type: ignore[attr-defined]
    assert simulator.simulation_outcomes == (outcome,)  # type: ignore[attr-defined]


def test_t088_does_not_accept_email_or_contact_an_external_provider() -> None:
    simulator = WhatsAppSimulator(outcome="accepted")
    notification = OutboundNotification(
        channel=EMAIL_CHANNEL,
        recipient="synthetic@example.test",
        content="Synthetic transactional content.",
    )

    with pytest.raises(ValueError):
        simulator.send(notification)

    assert simulator.notifications == ()
    assert simulator.results == ()
    assert simulator.simulation_outcomes == ()


def test_t088_rejects_an_uncontrolled_outcome() -> None:
    with pytest.raises(ValueError):
        WhatsAppSimulator(outcome="delivered")  # type: ignore[arg-type]

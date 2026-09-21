"""Deterministic WhatsApp adapter used by local development and tests only."""

from __future__ import annotations

from typing import Literal, TypeAlias

from backend.app.application.transactional_notifications import (
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
    WHATSAPP_CHANNEL,
)


WhatsAppSimulatorOutcome: TypeAlias = Literal["accepted", "no_whatsapp", "failed"]


class WhatsAppSimulator(TransactionalNotificationPort):
    """Record WhatsApp attempts and return a controlled immediate outcome."""

    def __init__(self, *, outcome: WhatsAppSimulatorOutcome) -> None:
        if outcome not in {"accepted", "no_whatsapp", "failed"}:
            raise ValueError(
                "WhatsApp simulator outcome must be accepted, no_whatsapp or failed."
            )
        self._outcome = outcome
        self._notifications: list[OutboundNotification] = []
        self._results: list[NotificationSendResult] = []
        self._simulation_outcomes: list[WhatsAppSimulatorOutcome] = []

    @property
    def notifications(self) -> tuple[OutboundNotification, ...]:
        """Return the recorded attempts without exposing them in repr/logs."""

        return tuple(self._notifications)

    @property
    def results(self) -> tuple[NotificationSendResult, ...]:
        """Return one delivery-model result for each recorded attempt."""

        return tuple(self._results)

    @property
    def simulation_outcomes(self) -> tuple[WhatsAppSimulatorOutcome, ...]:
        """Return the controlled simulator outcome for each attempt."""

        return tuple(self._simulation_outcomes)

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        """Record one WhatsApp attempt; never contact an external provider."""

        if notification.channel != WHATSAPP_CHANNEL:
            raise ValueError("WhatsApp simulator accepts WhatsApp notifications only.")

        self._notifications.append(notification)
        self._simulation_outcomes.append(self._outcome)
        result = (
            NotificationSendResult.accepted(WHATSAPP_CHANNEL)
            if self._outcome == "accepted"
            else NotificationSendResult.failed(WHATSAPP_CHANNEL)
        )
        self._results.append(result)
        return result

"""Deterministic email adapter used by local development and tests only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypeAlias

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)


EmailSimulatorOutcome: TypeAlias = Literal[
    "accepted", "rejected", "failed", "uncertain", "late_failure"
]


class EmailSimulatorUncertainOutcome(RuntimeError):
    """The simulated provider outcome cannot be known immediately."""


@dataclass(frozen=True)
class EmailSimulatorLateFailure:
    """A controlled late provider failure for one committed delivery."""

    delivery_id: int
    occurred_at: datetime
    channel: Literal["email"] = EMAIL_CHANNEL


class EmailSimulator(TransactionalNotificationPort):
    """Record email attempts and return controlled provider outcomes."""

    def __init__(self, *, outcome: EmailSimulatorOutcome) -> None:
        if outcome not in {
            "accepted",
            "rejected",
            "failed",
            "uncertain",
            "late_failure",
        }:
            raise ValueError(
                "email simulator outcome must be accepted, rejected, failed, uncertain or late_failure."
            )
        self._outcome = outcome
        self._notifications: list[OutboundNotification] = []
        self._results: list[NotificationSendResult] = []
        self._simulation_outcomes: list[EmailSimulatorOutcome] = []
        self._late_failure_emitted = False

    @property
    def notifications(self) -> tuple[OutboundNotification, ...]:
        """Return the recorded email attempts without exposing them in repr/logs."""

        return tuple(self._notifications)

    @property
    def results(self) -> tuple[NotificationSendResult, ...]:
        """Return one controlled result for each recorded email attempt."""

        return tuple(self._results)

    @property
    def simulation_outcomes(self) -> tuple[EmailSimulatorOutcome, ...]:
        """Return the configured outcome for each recorded email attempt."""

        return tuple(self._simulation_outcomes)

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        """Record one attempt; never contact an external provider."""

        if notification.channel != EMAIL_CHANNEL:
            raise ValueError("email simulator accepts email notifications only.")
        self._notifications.append(notification)
        self._simulation_outcomes.append(self._outcome)
        if self._outcome == "uncertain":
            raise EmailSimulatorUncertainOutcome(
                "email provider outcome is uncertain."
            )
        result = (
            NotificationSendResult.accepted(EMAIL_CHANNEL)
            if self._outcome in {"accepted", "late_failure"}
            else NotificationSendResult.failed(EMAIL_CHANNEL)
        )
        self._results.append(result)
        return result

    def emit_late_failure(
        self,
        *,
        delivery_id: int,
        occurred_at: datetime,
    ) -> EmailSimulatorLateFailure:
        """Emit one controlled late failure after an initially accepted attempt."""

        if self._outcome != "late_failure" or self._late_failure_emitted:
            raise ValueError("email simulator has no pending late failure.")
        if (
            isinstance(delivery_id, bool)
            or not isinstance(delivery_id, int)
            or delivery_id <= 0
            or occurred_at.tzinfo is None
            or occurred_at.utcoffset() is None
        ):
            raise ValueError("email simulator late failure is invalid.")
        self._late_failure_emitted = True
        return EmailSimulatorLateFailure(
            delivery_id=delivery_id,
            occurred_at=occurred_at,
        )

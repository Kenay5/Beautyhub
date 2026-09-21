"""Dispatch committed notification intents independently by channel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationChannel,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.domain.notification_delivery import (
    ACCEPTED_DELIVERY_STATUS,
    FAILED_DELIVERY_STATUS,
    NotificationDeliveryStatus,
    PENDING_DELIVERY_STATUS,
    transition_notification_delivery_status,
)


SANITIZED_DELIVERY_FAILURE = "notification delivery failed."


@dataclass(frozen=True)
class PendingNotificationDelivery:
    """One pending delivery intent committed with its appointment."""

    delivery_id: int
    notification: OutboundNotification


@dataclass(frozen=True)
class DispatchedNotificationDelivery:
    """The sanitized result persisted for one delivery attempt."""

    delivery_id: int
    channel: NotificationChannel
    status: NotificationDeliveryStatus
    sanitized_error: str | None


class NotificationDeliveryResultWriter(Protocol):
    """Persist a per-channel result in the existing delivery model."""

    def record_result(
        self,
        *,
        delivery_id: int,
        status: NotificationDeliveryStatus,
        status_changed_at: datetime,
        sanitized_error: str | None,
    ) -> None:
        """Update only the delivery row; never mutate the appointment."""


class NotificationDispatcher:
    """Dispatch already-committed notification intents without a provider transaction."""

    def __init__(
        self,
        *,
        email_port: TransactionalNotificationPort,
        whatsapp_port: TransactionalNotificationPort,
        result_writer: NotificationDeliveryResultWriter,
    ) -> None:
        self._ports = {
            EMAIL_CHANNEL: email_port,
            WHATSAPP_CHANNEL: whatsapp_port,
        }
        self._result_writer = result_writer

    def dispatch(
        self,
        *,
        deliveries: tuple[PendingNotificationDelivery, ...],
        dispatched_at: datetime,
    ) -> tuple[DispatchedNotificationDelivery, ...]:
        """Process every channel independently after the appointment commit."""

        dispatched: list[DispatchedNotificationDelivery] = []
        for delivery in deliveries:
            dispatched.append(
                self._dispatch_one(
                    delivery=delivery,
                    dispatched_at=dispatched_at,
                )
            )
        return tuple(dispatched)

    def _dispatch_one(
        self,
        *,
        delivery: PendingNotificationDelivery,
        dispatched_at: datetime,
    ) -> DispatchedNotificationDelivery:
        channel = delivery.notification.channel
        port = self._ports[channel]
        status: NotificationDeliveryStatus
        sanitized_error: str | None
        try:
            result = port.send(delivery.notification)
            status, sanitized_error = _status_from_result(result, channel)
        except Exception:
            status = FAILED_DELIVERY_STATUS
            sanitized_error = SANITIZED_DELIVERY_FAILURE

        status = transition_notification_delivery_status(
            current_status=PENDING_DELIVERY_STATUS,
            next_status=status,
        )
        self._result_writer.record_result(
            delivery_id=delivery.delivery_id,
            status=status,
            status_changed_at=dispatched_at,
            sanitized_error=sanitized_error,
        )
        return DispatchedNotificationDelivery(
            delivery_id=delivery.delivery_id,
            channel=channel,
            status=status,
            sanitized_error=sanitized_error,
        )


def _status_from_result(
    result: NotificationSendResult,
    expected_channel: NotificationChannel,
) -> tuple[NotificationDeliveryStatus, str | None]:
    if result.channel != expected_channel:
        return FAILED_DELIVERY_STATUS, SANITIZED_DELIVERY_FAILURE
    if result.outcome == "accepted":
        return ACCEPTED_DELIVERY_STATUS, None
    return FAILED_DELIVERY_STATUS, SANITIZED_DELIVERY_FAILURE

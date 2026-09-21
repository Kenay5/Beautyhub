"""Connect committed appointment creation to post-commit notification dispatch."""

from __future__ import annotations

from dataclasses import replace

from backend.app.application.clock import Clock
from backend.app.application.confirm_appointment import (
    ConfirmationDeliveryResult,
    ConfirmAppointment,
    ConfirmAppointmentCommand,
    ConfirmedAppointment,
)
from backend.app.application.creation_notification_templates import (
    prepare_creation_notifications,
)
from backend.app.application.dispatch_notifications import (
    NotificationDispatcher,
    PendingNotificationDelivery,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)


class ConfirmAppointmentWithNotifications:
    """Dispatch creation notifications only after a new confirmation commits."""

    def __init__(
        self,
        *,
        confirmation: ConfirmAppointment,
        dispatcher: NotificationDispatcher,
        clock: Clock,
    ) -> None:
        self._confirmation = confirmation
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(self, command: ConfirmAppointmentCommand) -> ConfirmedAppointment:
        """Confirm first, then attempt each newly committed delivery exactly once."""

        confirmed = self._confirmation.execute(command)
        if not confirmed.notification_dispatch_required:
            return confirmed

        deliveries_by_channel = {
            delivery.channel: delivery for delivery in confirmed.deliveries
        }
        if set(deliveries_by_channel) != {EMAIL_CHANNEL, WHATSAPP_CHANNEL}:
            raise RuntimeError("appointment confirmation requires both delivery channels.")

        notifications = prepare_creation_notifications(
            appointment=confirmed.appointment,
            private_code=confirmed.private_code,
        )
        dispatched = self._dispatcher.dispatch(
            deliveries=tuple(
                PendingNotificationDelivery(
                    delivery_id=deliveries_by_channel[notification.channel].delivery_id,
                    notification=notification,
                )
                for notification in notifications
            ),
            dispatched_at=self._clock.now(),
        )
        dispatched_by_channel = {delivery.channel: delivery for delivery in dispatched}
        return replace(
            confirmed,
            deliveries=tuple(
                ConfirmationDeliveryResult(
                    delivery_id=delivery.delivery_id,
                    channel=delivery.channel,
                    status=dispatched_by_channel[delivery.channel].status,
                )
                for delivery in confirmed.deliveries
            ),
            notification_dispatch_required=False,
        )

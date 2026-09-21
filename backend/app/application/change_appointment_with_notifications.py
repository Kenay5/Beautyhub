"""Dispatch modification and cancellation notifications after commit."""

from __future__ import annotations

from datetime import datetime
from dataclasses import replace

from backend.app.application.cancel_public_appointment import (
    CancelPublicAppointment,
    CancelledAppointment,
    PublicAppointmentCancellationCommand,
)
from backend.app.application.change_notification_data import (
    AppointmentChangeNotificationData,
    ChangeNotificationDelivery,
)
from backend.app.application.change_notification_templates import (
    prepare_cancellation_notifications_from_data,
    prepare_modification_notifications_from_data,
)
from backend.app.application.clock import Clock
from backend.app.application.dispatch_notifications import (
    NotificationDispatcher,
    PendingNotificationDelivery,
)
from backend.app.application.reschedule_public_appointment import (
    PublicAppointmentRescheduleCommand,
    ReschedulePublicAppointment,
    RescheduledAppointment,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    OutboundNotification,
)


class ReschedulePublicAppointmentWithNotifications:
    """Dispatch one notification per channel after a reschedule commits."""

    def __init__(
        self,
        *,
        rescheduler: ReschedulePublicAppointment,
        dispatcher: NotificationDispatcher,
        clock: Clock,
    ) -> None:
        self._rescheduler = rescheduler
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(
        self, command: PublicAppointmentRescheduleCommand
    ) -> RescheduledAppointment:
        modified = self._rescheduler.execute(command)
        notifications = prepare_modification_notifications_from_data(
            data=AppointmentChangeNotificationData(
                email=modified.email,
                phone=modified.phone,
                service_name=modified.service_snapshot.name,
                duration_minutes=modified.service_snapshot.duration_minutes,
                price=modified.service_snapshot.price,
                branch=modified.branch,
                scheduled_start=modified.scheduled_start,
                status=modified.status,
            )
        )
        dispatched = _dispatch(
            deliveries=modified.deliveries,
            notifications=notifications,
            dispatcher=self._dispatcher,
            dispatched_at=self._clock.now(),
        )
        return replace(modified, deliveries=dispatched)


class CancelPublicAppointmentWithNotifications:
    """Dispatch one notification per channel after a cancellation commits."""

    def __init__(
        self,
        *,
        canceller: CancelPublicAppointment,
        dispatcher: NotificationDispatcher,
        clock: Clock,
    ) -> None:
        self._canceller = canceller
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(
        self, command: PublicAppointmentCancellationCommand
    ) -> CancelledAppointment:
        cancelled = self._canceller.execute(command)
        notifications = prepare_cancellation_notifications_from_data(
            data=AppointmentChangeNotificationData(
                email=cancelled.email,
                phone=cancelled.phone,
                service_name=cancelled.service_name,
                duration_minutes=cancelled.duration_minutes,
                price=cancelled.price,
                branch=cancelled.branch,
                scheduled_start=cancelled.scheduled_start,
                status=cancelled.status,
            )
        )
        dispatched = _dispatch(
            deliveries=cancelled.deliveries,
            notifications=notifications,
            dispatcher=self._dispatcher,
            dispatched_at=self._clock.now(),
        )
        return replace(cancelled, deliveries=dispatched)


def _dispatch(
    *,
    deliveries: tuple[ChangeNotificationDelivery, ...],
    notifications: tuple[OutboundNotification, OutboundNotification],
    dispatcher: NotificationDispatcher,
    dispatched_at: datetime,
) -> tuple[ChangeNotificationDelivery, ...]:
    deliveries_by_channel = {delivery.channel: delivery for delivery in deliveries}
    if set(deliveries_by_channel) != {EMAIL_CHANNEL, WHATSAPP_CHANNEL}:
        raise RuntimeError("appointment change requires both delivery channels.")
    dispatched = dispatcher.dispatch(
        deliveries=tuple(
            PendingNotificationDelivery(
                delivery_id=deliveries_by_channel[notification.channel].delivery_id,
                notification=notification,
            )
            for notification in notifications
        ),
        dispatched_at=dispatched_at,
    )
    return tuple(
        ChangeNotificationDelivery(
            delivery_id=result.delivery_id,
            channel=result.channel,
            status=result.status,
        )
        for result in dispatched
    )

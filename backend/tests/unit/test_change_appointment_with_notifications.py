"""T091 unit evidence for post-commit modification and cancellation notices."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from backend.app.application.cancel_public_appointment import CancelledAppointment
from backend.app.application.change_appointment_with_notifications import (
    CancelPublicAppointmentWithNotifications,
    ReschedulePublicAppointmentWithNotifications,
)
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.clock import FixedClock
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.reschedule_public_appointment import RescheduledAppointment
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 15, 9, 0, tzinfo=BUSINESS_TIME_ZONE)


class CommittedOperation:
    def __init__(self, result: object, events: list[str]) -> None:
        self.result = result
        self.events = events

    def execute(self, command: object) -> object:
        self.events.append("commit")
        return self.result


class RecordingPort:
    def __init__(self, channel: str, events: list[str], *, fails: bool = False) -> None:
        self.channel = channel
        self.events = events
        self.fails = fails
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.events.append(self.channel)
        self.notifications.append(notification)
        if self.fails:
            raise RuntimeError("synthetic provider failure")
        return NotificationSendResult.accepted(self.channel)  # type: ignore[arg-type]


class RecordingWriter:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []

    def record_result(self, **result: object) -> None:
        self.results.append(result)


@pytest.mark.parametrize(("kind", "failing_channel"), (
    ("modification", EMAIL_CHANNEL),
    ("cancellation", WHATSAPP_CHANNEL),
))
def test_t091_dispatches_exactly_once_per_channel_after_commit_without_reverting(
    kind: str,
    failing_channel: str,
) -> None:
    events: list[str] = []
    email = RecordingPort(EMAIL_CHANNEL, events, fails=failing_channel == EMAIL_CHANNEL)
    whatsapp = RecordingPort(
        WHATSAPP_CHANNEL, events, fails=failing_channel == WHATSAPP_CHANNEL
    )
    writer = RecordingWriter()
    dispatcher = NotificationDispatcher(
        email_port=email,
        whatsapp_port=whatsapp,
        result_writer=writer,
    )

    if kind == "modification":
        committed = _modified()
        operation = ReschedulePublicAppointmentWithNotifications(
            rescheduler=CommittedOperation(committed, events),  # type: ignore[arg-type]
            dispatcher=dispatcher,
            clock=FixedClock(NOW),
        )
    else:
        committed = _cancelled()
        operation = CancelPublicAppointmentWithNotifications(
            canceller=CommittedOperation(committed, events),  # type: ignore[arg-type]
            dispatcher=dispatcher,
            clock=FixedClock(NOW),
        )

    result = operation.execute(object())  # type: ignore[arg-type]

    assert result.appointment_id == committed.appointment_id  # type: ignore[attr-defined]
    assert events == ["commit", EMAIL_CHANNEL, WHATSAPP_CHANNEL]
    assert len(email.notifications) == len(whatsapp.notifications) == 1
    assert {entry["delivery_id"] for entry in writer.results} == {71, 72}
    assert all("código" not in notice.content.lower() for notice in email.notifications)
    assert all(
        "código" not in notice.content.lower() for notice in whatsapp.notifications
    )


def _deliveries() -> tuple[ChangeNotificationDelivery, ChangeNotificationDelivery]:
    return (
        ChangeNotificationDelivery(71, EMAIL_CHANNEL, PENDING_DELIVERY_STATUS),
        ChangeNotificationDelivery(72, WHATSAPP_CHANNEL, PENDING_DELIVERY_STATUS),
    )


def _modified() -> RescheduledAppointment:
    return RescheduledAppointment(
        appointment_id=29,
        service_snapshot=AppointmentServiceSnapshot(
            service_id=17,
            name="Uñas demo",
            duration_minutes=60,
            price=Decimal("350.00"),
        ),
        branch="texcoco",
        scheduled_start=NOW + timedelta(days=1),
        scheduled_end=NOW + timedelta(days=1, hours=1),
        status="scheduled",
        email="clienta@example.test",
        phone="5510000000",
        deliveries=_deliveries(),
    )


def _cancelled() -> CancelledAppointment:
    return CancelledAppointment(
        appointment_id=29,
        service_name="Uñas demo",
        duration_minutes=60,
        price=Decimal("350.00"),
        branch="texcoco",
        scheduled_start=NOW + timedelta(days=1),
        scheduled_end=NOW + timedelta(days=1, hours=1),
        status="cancelled",
        email="clienta@example.test",
        phone="5510000000",
        deliveries=_deliveries(),
    )

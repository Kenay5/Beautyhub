"""T090 unit evidence for post-commit creation notification dispatch."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.confirm_appointment import (
    ConfirmationDeliveryResult,
    ConfirmAppointmentCommand,
    ConfirmedAppointment,
)
from backend.app.application.confirm_appointment_with_notifications import (
    ConfirmAppointmentWithNotifications,
)
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.private_code import PrivateCode
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot, ScheduledAppointment
from backend.app.domain.privacy_consent import (
    PUBLIC_APPOINTMENT_ORIGIN,
    create_privacy_consent_evidence,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 1, 12, tzinfo=BUSINESS_TIME_ZONE)
START = datetime(2030, 6, 15, 17, 30, tzinfo=BUSINESS_TIME_ZONE)


class ControlledConfirmation:
    def __init__(
        self,
        results: tuple[ConfirmedAppointment, ...],
        events: list[str],
    ) -> None:
        self._results = list(results)
        self._events = events

    def execute(self, command: ConfirmAppointmentCommand) -> ConfirmedAppointment:
        self._events.append("commit")
        return self._results.pop(0)


class TrackingPort:
    def __init__(self, channel: str, outcome: str, events: list[str]) -> None:
        self.channel = channel
        self.outcome = outcome
        self.events = events
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.events.append(self.channel)
        self.notifications.append(notification)
        return (
            NotificationSendResult.accepted(notification.channel)
            if self.outcome == "accepted"
            else NotificationSendResult.failed(notification.channel)
        )


class RecordingResultWriter:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []

    def record_result(self, **result: object) -> None:
        self.results.append(result)


def test_t090_dispatches_exactly_one_creation_attempt_per_channel_after_commit() -> None:
    events: list[str] = []
    email = TrackingPort(EMAIL_CHANNEL, "accepted", events)
    whatsapp = TrackingPort(WHATSAPP_CHANNEL, "accepted", events)
    writer = RecordingResultWriter()
    service = _service(
        confirmation=ControlledConfirmation((_confirmed(is_new=True),), events),
        email=email,
        whatsapp=whatsapp,
        writer=writer,
    )

    result = service.execute(_command())

    assert events == ["commit", EMAIL_CHANNEL, WHATSAPP_CHANNEL]
    assert len(email.notifications) == 1
    assert len(whatsapp.notifications) == 1
    assert [delivery.status for delivery in result.deliveries] == [
        "accepted",
        "accepted",
    ]
    assert [entry["delivery_id"] for entry in writer.results] == [31, 32]
    for notification in (*email.notifications, *whatsapp.notifications):
        assert "Código privado: synthetic-private-code" in notification.content


def test_t090_notification_failure_keeps_the_committed_appointment_intact() -> None:
    events: list[str] = []
    confirmed = _confirmed(is_new=True)
    writer = RecordingResultWriter()
    service = _service(
        confirmation=ControlledConfirmation((confirmed,), events),
        email=TrackingPort(EMAIL_CHANNEL, "failed", events),
        whatsapp=TrackingPort(WHATSAPP_CHANNEL, "accepted", events),
        writer=writer,
    )

    result = service.execute(_command())

    assert result.appointment == confirmed.appointment
    assert result.appointment_id == confirmed.appointment_id
    assert [delivery.status for delivery in result.deliveries] == [
        "failed",
        "accepted",
    ]
    assert len(writer.results) == 2


@pytest.mark.parametrize(
    ("email_status", "whatsapp_status"),
    (("accepted", "accepted"), ("failed", "failed"), ("failed", "accepted")),
)
def test_t092_idempotent_replay_preserves_original_results_without_redispatch(
    email_status: str,
    whatsapp_status: str,
) -> None:
    events: list[str] = []
    email = TrackingPort(EMAIL_CHANNEL, "accepted", events)
    whatsapp = TrackingPort(WHATSAPP_CHANNEL, "accepted", events)
    writer = RecordingResultWriter()
    service = _service(
        confirmation=ControlledConfirmation(
            (
                _confirmed(is_new=True),
                _confirmed(
                    is_new=False,
                    email_status=email_status,
                    whatsapp_status=whatsapp_status,
                ),
            ),
            events,
        ),
        email=email,
        whatsapp=whatsapp,
        writer=writer,
    )

    service.execute(_command())
    replay = service.execute(_command())

    assert events == ["commit", EMAIL_CHANNEL, WHATSAPP_CHANNEL, "commit"]
    assert len(email.notifications) == 1
    assert len(whatsapp.notifications) == 1
    assert len(writer.results) == 2
    assert replay.notification_dispatch_required is False
    assert [delivery.status for delivery in replay.deliveries] == [
        email_status,
        whatsapp_status,
    ]


def _service(
    *,
    confirmation: ControlledConfirmation,
    email: TrackingPort,
    whatsapp: TrackingPort,
    writer: RecordingResultWriter,
) -> ConfirmAppointmentWithNotifications:
    return ConfirmAppointmentWithNotifications(
        confirmation=confirmation,  # type: ignore[arg-type]
        dispatcher=NotificationDispatcher(
            email_port=email,
            whatsapp_port=whatsapp,
            result_writer=writer,
        ),
        clock=FixedClock(NOW),
    )


def _confirmed(
    *,
    is_new: bool,
    email_status: str = "pending",
    whatsapp_status: str = "pending",
) -> ConfirmedAppointment:
    return ConfirmedAppointment(
        appointment_id=29,
        appointment=_appointment(),
        private_code=PrivateCode("synthetic-private-code"),
        deliveries=(
            ConfirmationDeliveryResult(31, EMAIL_CHANNEL, email_status),
            ConfirmationDeliveryResult(32, WHATSAPP_CHANNEL, whatsapp_status),
        ),
        notification_dispatch_required=is_new,
    )


def _appointment() -> ScheduledAppointment:
    return ScheduledAppointment(
        private_code_ciphertext=b"synthetic-ciphertext",
        private_code_digest=b"synthetic-digest",
        first_name="Clienta",
        last_name="Sintética",
        phone="5510000000",
        email="clienta@example.test",
        service_snapshot=AppointmentServiceSnapshot(
            service_id=13,
            name="Servicio sintético",
            duration_minutes=90,
            price=Decimal("450.00"),
        ),
        branch="texcoco",
        scheduled_start=START,
        scheduled_end=START,
        status="scheduled",
        privacy_consent=create_privacy_consent_evidence(
            privacy_notice_version_id=7,
            accepted_at=NOW,
            origin=PUBLIC_APPOINTMENT_ORIGIN,
            contact_processing_authorized=True,
            adult_responsibility_declared=True,
            confirmed_by_account_id=None,
        ),
    )


def _command() -> ConfirmAppointmentCommand:
    return ConfirmAppointmentCommand(
        reference_digest=b"synthetic-reference-digest",
        first_name="Clienta",
        last_name="Sintética",
        phone="5510000000",
        email="clienta@example.test",
        service_id=13,
        branch="texcoco",
        scheduled_start=START,
        privacy_consent=_appointment().privacy_consent,
    )

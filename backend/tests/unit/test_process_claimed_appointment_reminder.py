"""T093F unit evidence for registered-start reminder processing."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.dispatch_notifications import NotificationDispatcher
from backend.app.application.process_claimed_appointment_reminder import (
    ClaimedAppointmentReminderRepository,
    LockedClaimedReminder,
    ProcessClaimedAppointmentReminder,
    ProcessClaimedReminderCommand,
    ReminderDeliveryIntent,
)
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    WHATSAPP_CHANNEL,
)
from backend.app.domain.notification_delivery import (
    ACCEPTED_DELIVERY_STATUS,
    FAILED_DELIVERY_STATUS,
    PENDING_DELIVERY_STATUS,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE, normalize_instant
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.whatsapp_simulator import WhatsAppSimulator


NOW = datetime(2030, 6, 15, 10, tzinfo=BUSINESS_TIME_ZONE)
CLAIMED_AT = NOW - timedelta(minutes=1)


class FakeReminderProcessingRepository:
    def __init__(self, locked: LockedClaimedReminder) -> None:
        self.locked = locked
        self.finished: list[dict[str, object]] = []
        self.created_deliveries: list[dict[str, object]] = []

    def lock_reminder_and_appointment(
        self,
        *,
        reminder_id: int,
    ) -> LockedClaimedReminder | None:
        return self.locked if reminder_id == self.locked.reminder_id else None

    def finish_claim(self, **values: object) -> bool:
        self.finished.append(values)
        return True

    def create_delivery_intents(
        self,
        **values: object,
    ) -> tuple[ReminderDeliveryIntent, ReminderDeliveryIntent]:
        self.created_deliveries.append(values)
        return (
            ReminderDeliveryIntent(31, EMAIL_CHANNEL, PENDING_DELIVERY_STATUS),
            ReminderDeliveryIntent(32, WHATSAPP_CHANNEL, PENDING_DELIVERY_STATUS),
        )


class FakeReminderProcessingUnitOfWork:
    def __init__(self, repository: FakeReminderProcessingRepository) -> None:
        self.repository = repository
        self.committed = False
        self.inside_transaction = False

    @contextmanager
    def transaction(self) -> Iterator[ClaimedAppointmentReminderRepository]:
        self.inside_transaction = True
        try:
            yield self.repository
        except Exception:
            raise
        else:
            self.committed = True
        finally:
            self.inside_transaction = False


class CommitCheckingEmailSimulator(EmailSimulator):
    def __init__(self, unit_of_work: FakeReminderProcessingUnitOfWork) -> None:
        super().__init__(outcome="failed")
        self._unit_of_work = unit_of_work

    def send(self, notification):  # type: ignore[no-untyped-def]
        assert self._unit_of_work.committed
        assert not self._unit_of_work.inside_transaction
        return super().send(notification)


class RecordingResultWriter:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []

    def record_result(self, **values: object) -> None:
        self.results.append(values)


def test_t093f_commits_the_registered_start_before_contacting_each_channel() -> None:
    repository = FakeReminderProcessingRepository(_locked())
    unit_of_work = FakeReminderProcessingUnitOfWork(repository)
    email = CommitCheckingEmailSimulator(unit_of_work)
    whatsapp = WhatsAppSimulator(outcome="accepted")
    writer = RecordingResultWriter()

    result = _processor(
        unit_of_work=unit_of_work,
        email=email,
        whatsapp=whatsapp,
        writer=writer,
    ).execute(_command())

    assert result.outcome == "processed"
    assert tuple(delivery.status for delivery in result.deliveries) == (
        FAILED_DELIVERY_STATUS,
        ACCEPTED_DELIVERY_STATUS,
    )
    assert repository.created_deliveries == [
        {
            "appointment_id": 29,
            "reminder_id": 17,
            "status_changed_at": normalize_instant(NOW),
        }
    ]
    assert repository.finished == [
        {
            "reminder_id": 17,
            "claimed_at": normalize_instant(CLAIMED_AT),
            "status": "completed",
            "status_changed_at": normalize_instant(NOW),
        }
    ]
    assert len(email.notifications) == len(whatsapp.notifications) == 1
    assert [entry["status"] for entry in writer.results] == [
        FAILED_DELIVERY_STATUS,
        ACCEPTED_DELIVERY_STATUS,
    ]


@pytest.mark.parametrize(
    ("appointment_status", "appointment_start"),
    (
        pytest.param("cancelled", None, id="cancelled"),
        pytest.param(
            "scheduled",
            NOW + timedelta(hours=3),
            id="rescheduled",
        ),
    ),
)
def test_t093f_a_change_confirmed_before_registered_start_prevents_dispatch(
    appointment_status: str,
    appointment_start: datetime | None,
) -> None:
    repository = FakeReminderProcessingRepository(
        _locked(
            appointment_status=appointment_status,
            appointment_start=appointment_start,
        )
    )
    unit_of_work = FakeReminderProcessingUnitOfWork(repository)
    email = EmailSimulator(outcome="accepted")
    whatsapp = WhatsAppSimulator(outcome="accepted")

    result = _processor(
        unit_of_work=unit_of_work,
        email=email,
        whatsapp=whatsapp,
    ).execute(_command())

    assert result.outcome == "skipped"
    assert result.deliveries == ()
    assert repository.created_deliveries == []
    assert repository.finished[0]["status"] == "invalidated"
    assert email.notifications == whatsapp.notifications == ()


def _processor(
    *,
    unit_of_work: FakeReminderProcessingUnitOfWork,
    email: EmailSimulator,
    whatsapp: WhatsAppSimulator,
    writer: RecordingResultWriter | None = None,
) -> ProcessClaimedAppointmentReminder:
    return ProcessClaimedAppointmentReminder(
        unit_of_work=unit_of_work,
        dispatcher=NotificationDispatcher(
            email_port=email,
            whatsapp_port=whatsapp,
            result_writer=writer or RecordingResultWriter(),
        ),
        clock=FixedClock(NOW),
    )


def _command() -> ProcessClaimedReminderCommand:
    return ProcessClaimedReminderCommand(reminder_id=17, claimed_at=CLAIMED_AT)


def _locked(
    *,
    appointment_status: str = "scheduled",
    appointment_start: datetime | None = None,
) -> LockedClaimedReminder:
    reminder_start = NOW + timedelta(hours=2)
    return LockedClaimedReminder(
        reminder_id=17,
        appointment_id=29,
        reminder_status="claimed",
        reminder_claimed_at=normalize_instant(CLAIMED_AT),
        reminder_scheduled_start=reminder_start,
        appointment_status=appointment_status,
        appointment_scheduled_start=appointment_start or reminder_start,
        email="clienta@example.test",
        phone="5510000000",
        service_name="Servicio sintético",
        duration_minutes=60,
        price=Decimal("350.00"),
        branch="chiconcuac",
    )

"""Focused unit evidence for T080 public cancellation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest

from backend.app.application.cancel_public_appointment import (
    CancelPublicAppointment,
    LockedAppointmentForCancellation,
    PublicAppointmentCancellationCommand,
    PublicAppointmentCancellationNotPermittedError,
    PublicAppointmentCancellationRepository,
)
from backend.app.application.clock import FixedClock
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, WHATSAPP_CHANNEL
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.application.lookup_public_appointment import (
    PublicAppointmentCredentialError,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 15, 9, 0, tzinfo=BUSINESS_TIME_ZONE)


class FakeCancellationRepository:
    def __init__(self) -> None:
        self.schedule_locked = False
        self.appointment = _appointment()
        self.cancellations: list[dict[str, object]] = []
        self.invalidated_reminders: list[dict[str, object]] = []

    def lock_schedule(self) -> None:
        self.schedule_locked = True

    def lock_appointment_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> LockedAppointmentForCancellation | None:
        assert self.schedule_locked
        return self.appointment if private_code_digest == b"synthetic-digest" else None

    def cancel_appointment(self, **values: object) -> bool:
        assert self.schedule_locked
        self.cancellations.append(values)
        return True

    def create_pending_deliveries(
        self, appointment_id: int, status_changed_at: datetime
    ) -> tuple[ChangeNotificationDelivery, ChangeNotificationDelivery]:
        return (
            ChangeNotificationDelivery(1, EMAIL_CHANNEL, PENDING_DELIVERY_STATUS),
            ChangeNotificationDelivery(2, WHATSAPP_CHANNEL, PENDING_DELIVERY_STATUS),
        )

    def invalidate_pending_reminders(self, **values: object) -> None:
        assert self.schedule_locked
        self.invalidated_reminders.append(values)


class FakeCancellationUnitOfWork:
    def __init__(self, repository: FakeCancellationRepository) -> None:
        self.repository = repository
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[PublicAppointmentCancellationRepository]:
        self.transactions += 1
        yield self.repository


def test_t080_cancels_at_exactly_sixty_minutes_and_normalizes_the_reason() -> None:
    repository = FakeCancellationRepository()

    result = _canceller(repository).execute(_command(reason="  Cambio de planes ✨  "))

    assert result.status == "cancelled"
    assert result.appointment_id == 29
    assert repository.cancellations == [{
        "appointment_id": 29,
        "reason": "Cambio de planes ✨",
        "changed_at": NOW,
    }]
    assert repository.invalidated_reminders == [
        {"appointment_id": 29, "status_changed_at": NOW}
    ]


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_t080_treats_an_empty_optional_reason_as_absent(reason: str | None) -> None:
    repository = FakeCancellationRepository()

    _canceller(repository).execute(_command(reason=reason))

    assert repository.cancellations[0]["reason"] is None


def test_t080_rejects_one_second_inside_the_notice_without_writing() -> None:
    repository = FakeCancellationRepository()
    repository.appointment = _appointment(scheduled_start=NOW + timedelta(minutes=59, seconds=59))

    with pytest.raises(PublicAppointmentCancellationNotPermittedError):
        _canceller(repository).execute(_command())

    assert repository.cancellations == []


@pytest.mark.parametrize("status", ["cancelled", "completed", "no_show", "unrecorded_result"])
def test_t080_rejects_a_final_state_without_writing(status: str) -> None:
    repository = FakeCancellationRepository()
    repository.appointment = _appointment(status=status)

    with pytest.raises(PublicAppointmentCancellationNotPermittedError):
        _canceller(repository).execute(_command())

    assert repository.cancellations == []


@pytest.mark.parametrize(
    "command",
    [
        PublicAppointmentCancellationCommand(b"wrong-digest", "5510000000"),
        PublicAppointmentCancellationCommand(b"synthetic-digest", "5599999999"),
    ],
)
def test_t080_rejects_invalid_credentials_without_writing(
    command: PublicAppointmentCancellationCommand,
) -> None:
    repository = FakeCancellationRepository()

    with pytest.raises(PublicAppointmentCredentialError):
        _canceller(repository).execute(command)

    assert repository.cancellations == []


def _canceller(repository: FakeCancellationRepository) -> CancelPublicAppointment:
    return CancelPublicAppointment(
        unit_of_work=FakeCancellationUnitOfWork(repository),
        clock=FixedClock(NOW),
    )


def _command(*, reason: str | None = None) -> PublicAppointmentCancellationCommand:
    return PublicAppointmentCancellationCommand(
        private_code_digest=b"synthetic-digest",
        phone="55 1000 0000",
        reason=reason,
    )


def _appointment(
    *,
    scheduled_start: datetime = NOW + timedelta(hours=1),
    status: str = "scheduled",
) -> LockedAppointmentForCancellation:
    return LockedAppointmentForCancellation(
        appointment_id=29,
        phone="5510000000",
        email="clienta@example.test",
        service_snapshot_name="Servicio sintético",
        service_snapshot_duration_minutes=60,
        service_snapshot_price=Decimal("350.00"),
        branch="chiconcuac",
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_start + timedelta(hours=1),
        status=status,
    )

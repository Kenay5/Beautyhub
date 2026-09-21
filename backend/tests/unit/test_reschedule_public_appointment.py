"""T075 unit evidence for atomic public appointment reprogramming decisions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest

from backend.app.application.authorize_public_appointment_modification import (
    PublicAppointmentModificationNotPermittedError,
)
from backend.app.application.clock import FixedClock
from backend.app.application.change_notification_data import ChangeNotificationDelivery
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, WHATSAPP_CHANNEL
from backend.app.domain.notification_delivery import PENDING_DELIVERY_STATUS
from backend.app.application.reschedule_public_appointment import (
    LockedAppointmentForReschedule,
    LockedServiceForReschedule,
    PublicAppointmentRescheduleCommand,
    PublicAppointmentRescheduleConflictError,
    ReschedulePublicAppointment,
)
from backend.app.domain.appointment import AppointmentServiceSnapshot
from backend.app.domain.schedule import ScheduledInterval, TimeInterval
from backend.app.domain.service import AppointmentServiceSelectionError, ServiceDraft
from backend.app.domain.time import BUSINESS_TIME_ZONE, InstantValidationError


NOW = datetime(2030, 6, 1, 10, tzinfo=BUSINESS_TIME_ZONE)
ORIGINAL_START = datetime(2030, 6, 2, 11, tzinfo=BUSINESS_TIME_ZONE)
NEW_START = datetime(2030, 6, 2, 14, tzinfo=BUSINESS_TIME_ZONE)


class FakeRescheduleRepository:
    """Record each protected step and expose controlled current state."""

    def __init__(self) -> None:
        self.schedule_locked = False
        self.appointment = LockedAppointmentForReschedule(
            appointment_id=29,
            phone="5510000000",
            email="clienta@example.test",
            service_id=13,
            service_snapshot_name="Servicio original",
            service_snapshot_duration_minutes=60,
            service_snapshot_price=Decimal("350.00"),
            scheduled_start=ORIGINAL_START,
            status="scheduled",
        )
        self.service = LockedServiceForReschedule(
            service_id=17,
            service=_service_draft(),
        )
        self.other_intervals: tuple[ScheduledInterval, ...] = ()
        self.blocks: tuple[TimeInterval, ...] = ()
        self.excluded_ids: list[int] = []
        self.updates: list[dict[str, object]] = []
        self.invalidated_reminders: list[dict[str, object]] = []
        self.created_reminders: list[dict[str, object]] = []

    def lock_schedule(self) -> None:
        self.schedule_locked = True

    def lock_appointment_by_private_code_digest(
        self,
        private_code_digest: bytes,
    ) -> LockedAppointmentForReschedule | None:
        assert self.schedule_locked
        return self.appointment if private_code_digest == b"synthetic-digest" else None

    def get_service_for_update(
        self,
        *,
        service_name: str,
    ) -> LockedServiceForReschedule | None:
        assert self.schedule_locked
        return self.service if service_name == "Servicio nuevo" else None

    def list_other_scheduled_intervals_for_update(
        self,
        *,
        excluding_appointment_id: int,
    ) -> tuple[ScheduledInterval, ...]:
        assert self.schedule_locked
        self.excluded_ids.append(excluding_appointment_id)
        return self.other_intervals

    def list_applicable_blocks_for_update(
        self,
        branch: str,
    ) -> tuple[TimeInterval, ...]:
        assert self.schedule_locked
        return self.blocks

    def update_schedule(self, **values: object) -> bool:
        assert self.schedule_locked
        self.updates.append(values)
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

    def create_initial_reminder(self, **values: object) -> None:
        assert self.schedule_locked
        self.created_reminders.append(values)


class FakeRescheduleUnitOfWork:
    def __init__(self, repository: FakeRescheduleRepository) -> None:
        self.repository = repository
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeRescheduleRepository]:
        self.transactions += 1
        yield self.repository


def test_t076_switching_service_replaces_the_snapshot_in_the_atomic_update() -> None:
    repository = FakeRescheduleRepository()

    result = _rescheduler(repository).execute(_command())

    assert repository.excluded_ids == [29]
    assert repository.updates == [
        {
            "appointment_id": 29,
            "service_snapshot": AppointmentServiceSnapshot(
                service_id=17,
                name="Servicio nuevo",
                duration_minutes=90,
                price=Decimal("450.00"),
            ),
            "branch": "texcoco",
            "scheduled_start": NEW_START,
            "scheduled_end": NEW_START + timedelta(minutes=90),
            "changed_at": NOW,
        }
    ]
    assert result.appointment_id == 29
    assert result.scheduled_end == NEW_START + timedelta(minutes=90)
    assert result.service_snapshot.name == "Servicio nuevo"
    assert result.service_snapshot.duration_minutes == 90
    assert result.service_snapshot.price == Decimal("450.00")


def test_t076_moving_schedule_with_the_same_service_preserves_its_snapshot() -> None:
    repository = FakeRescheduleRepository()
    repository.service = LockedServiceForReschedule(
        service_id=13,
        service=_service_draft(name="Servicio nuevo", duration_minutes=120),
    )

    result = _rescheduler(repository).execute(_command(scheduled_start=ORIGINAL_START))

    assert repository.excluded_ids == [29]
    assert repository.updates[0]["service_snapshot"] == AppointmentServiceSnapshot(
        service_id=13,
        name="Servicio original",
        duration_minutes=60,
        price=Decimal("350.00"),
    )
    assert result.scheduled_end == ORIGINAL_START + timedelta(minutes=60)
    assert result.service_snapshot.name == "Servicio original"
    assert result.service_snapshot.duration_minutes == 60
    assert result.service_snapshot.price == Decimal("350.00")
    assert repository.invalidated_reminders == []
    assert repository.created_reminders == []


def test_t093c_replaces_the_previous_reminder_for_an_eligible_new_start() -> None:
    repository = FakeRescheduleRepository()

    _rescheduler(repository).execute(_command())

    assert repository.invalidated_reminders == [
        {"appointment_id": 29, "status_changed_at": NOW}
    ]
    assert repository.created_reminders == [
        {
            "appointment_id": 29,
            "appointment_scheduled_start": NEW_START,
            "send_at": NEW_START - timedelta(hours=24),
            "status_changed_at": NOW,
        }
    ]


def test_t093c_invalidates_without_replacement_at_exactly_24_hours() -> None:
    repository = FakeRescheduleRepository()

    _rescheduler(repository).execute(
        _command(scheduled_start=NOW + timedelta(hours=24))
    )

    assert repository.invalidated_reminders == [
        {"appointment_id": 29, "status_changed_at": NOW}
    ]
    assert repository.created_reminders == []


@pytest.mark.parametrize(
    "scheduled_start",
    (
        NOW + timedelta(minutes=59, seconds=59),
        NOW + timedelta(days=90, seconds=1),
    ),
)
def test_t075_rejects_notice_and_horizon_violations_before_any_transaction(
    scheduled_start: datetime,
) -> None:
    repository = FakeRescheduleRepository()
    unit_of_work = FakeRescheduleUnitOfWork(repository)
    service = ReschedulePublicAppointment(
        unit_of_work=unit_of_work,
        clock=FixedClock(NOW),
    )

    with pytest.raises(InstantValidationError):
        service.execute(_command(scheduled_start=scheduled_start))

    assert unit_of_work.transactions == 0
    assert repository.updates == []


@pytest.mark.parametrize("conflict_kind", ("appointment", "block"))
def test_t075_rejects_current_schedule_conflicts_without_an_update(
    conflict_kind: str,
) -> None:
    repository = FakeRescheduleRepository()
    occupied = TimeInterval(NEW_START, NEW_START + timedelta(hours=2))
    if conflict_kind == "appointment":
        repository.other_intervals = (ScheduledInterval(occupied, "chiconcuac"),)
    else:
        repository.blocks = (occupied,)

    with pytest.raises(PublicAppointmentRescheduleConflictError):
        _rescheduler(repository).execute(_command())

    assert repository.excluded_ids == [29]
    assert repository.updates == []


@pytest.mark.parametrize(
    ("is_active", "available_texcoco"),
    (
        (False, True),
        (True, False),
    ),
)
def test_t075_revalidates_service_state_and_branch_before_updating(
    is_active: bool,
    available_texcoco: bool,
) -> None:
    repository = FakeRescheduleRepository()
    repository.service = LockedServiceForReschedule(
        service_id=17,
        service=_service_draft(
            is_active=is_active,
            available_texcoco=available_texcoco,
        ),
    )

    with pytest.raises(AppointmentServiceSelectionError):
        _rescheduler(repository).execute(_command())

    assert repository.updates == []


def test_t075_rechecks_the_original_appointment_state_inside_the_transaction() -> None:
    repository = FakeRescheduleRepository()
    repository.appointment = LockedAppointmentForReschedule(
        appointment_id=29,
        phone="5510000000",
        email="clienta@example.test",
        service_id=13,
        service_snapshot_name="Servicio original",
        service_snapshot_duration_minutes=60,
        service_snapshot_price=Decimal("350.00"),
        scheduled_start=NOW + timedelta(minutes=59, seconds=59),
        status="scheduled",
    )

    with pytest.raises(PublicAppointmentModificationNotPermittedError):
        _rescheduler(repository).execute(_command())

    assert repository.updates == []


def _rescheduler(repository: FakeRescheduleRepository) -> ReschedulePublicAppointment:
    return ReschedulePublicAppointment(
        unit_of_work=FakeRescheduleUnitOfWork(repository),
        clock=FixedClock(NOW),
    )


def _command(**overrides: object) -> PublicAppointmentRescheduleCommand:
    values = {
        "private_code_digest": b"synthetic-digest",
        "phone": "55 1000 0000",
        "service_name": "Servicio nuevo",
        "branch": "texcoco",
        "scheduled_start": NEW_START,
        **overrides,
    }
    return PublicAppointmentRescheduleCommand(**values)  # type: ignore[arg-type]


def _service_draft(
    *,
    name: str = "Servicio nuevo",
    duration_minutes: int = 90,
    is_active: bool = True,
    available_texcoco: bool = True,
) -> ServiceDraft:
    return ServiceDraft(
        name=name,
        description=None,
        duration_minutes=duration_minutes,
        price=Decimal("450.00"),
        is_active=is_active,
        available_chiconcuac=True,
        available_texcoco=available_texcoco,
    )

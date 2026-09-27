"""T093A unit evidence for auditable failed-delivery retry preparation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import pytest

from backend.app.application.clock import FixedClock
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.prepare_notification_retry import (
    CurrentAppointmentContact,
    LockedFailedNotificationDelivery,
    NotificationRetryNotPermittedError,
    NotificationRetryRepository,
    PrepareNotificationRetry,
)
from backend.app.domain.notification_delivery import (
    ACCEPTED_DELIVERY_STATUS,
    FAILED_DELIVERY_STATUS,
)
from backend.app.domain.time import BUSINESS_TIME_ZONE


NOW = datetime(2030, 6, 15, 12, tzinfo=BUSINESS_TIME_ZONE)


class FakeRetryRepository:
    def __init__(self, *, status: str = FAILED_DELIVERY_STATUS) -> None:
        self.original = LockedFailedNotificationDelivery(
            delivery_id=31,
            appointment_id=29,
            event="appointment_created",
            channel="email",
            status=status,  # type: ignore[arg-type]
            appointment_reminder_id=None,
        )
        self.contact = CurrentAppointmentContact(
            appointment_id=29,
            email="updated-contact@example.test",
            phone="5510000000",
        )
        self.created: list[dict[str, object]] = []
        self.appointment_writes = 0

    def lock_delivery(self, delivery_id: int) -> LockedFailedNotificationDelivery | None:
        return self.original if delivery_id == self.original.delivery_id else None

    def lock_current_appointment_contact(
        self, appointment_id: int
    ) -> CurrentAppointmentContact | None:
        return self.contact if appointment_id == self.contact.appointment_id else None

    def create_pending_retry(self, **values: object) -> int:
        self.created.append(values)
        return 47


class FakeRetryUnitOfWork:
    def __init__(self, repository: FakeRetryRepository) -> None:
        self.repository = repository

    @contextmanager
    def transaction(self) -> Iterator[NotificationRetryRepository]:
        yield self.repository


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, **event: object) -> None:
        self.events.append(event)


@pytest.mark.parametrize("role", ("owner", "staff"))
def test_t093a_owner_and_staff_retry_only_to_current_contact_without_code(
    role: str,
) -> None:
    repository = FakeRetryRepository()

    result = _service(repository).execute(
        actor=AdministrativeActor(account_id=7, role=role),  # type: ignore[arg-type]
        delivery_id=31,
    )

    assert result.delivery_id == 47
    assert result.previous_delivery_id == 31
    assert result.recipient == "updated-contact@example.test"
    assert result.status == "pending"
    assert repository.created == [
        {
            "appointment_id": 29,
            "event": "appointment_created",
            "channel": "email",
            "previous_delivery_id": 31,
            "status_changed_at": NOW,
        }
    ]
    assert repository.appointment_writes == 0
    assert "private" not in repr(result).lower()
    assert not hasattr(result, "private_code")


def test_t082_notification_retry_rejects_untrusted_actor_before_database_access() -> None:
    repository = FakeRetryRepository()

    with pytest.raises(AdministrativeAuthorizationError):
        _service(repository).execute(actor=None, delivery_id=31)  # type: ignore[arg-type]

    assert repository.created == []
    assert repository.appointment_writes == 0


def test_t093a_rejects_a_delivery_that_did_not_fail_without_writes() -> None:
    repository = FakeRetryRepository(status=ACCEPTED_DELIVERY_STATUS)

    with pytest.raises(NotificationRetryNotPermittedError):
        _service(repository).execute(
            actor=AdministrativeActor(account_id=7, role="owner"), delivery_id=31
        )

    assert repository.created == []
    assert repository.appointment_writes == 0


def test_t093g_generic_retry_cannot_bypass_reminder_retry_limits() -> None:
    repository = FakeRetryRepository()
    repository.original = LockedFailedNotificationDelivery(
        delivery_id=31,
        appointment_id=29,
        event="appointment_reminder",
        channel="email",
        status=FAILED_DELIVERY_STATUS,
        appointment_reminder_id=None,
    )

    with pytest.raises(NotificationRetryNotPermittedError):
        _service(repository).execute(
            actor=AdministrativeActor(account_id=7, role="staff"), delivery_id=31
        )

    assert repository.created == []


def _service(repository: FakeRetryRepository) -> PrepareNotificationRetry:
    return PrepareNotificationRetry(
        unit_of_work=FakeRetryUnitOfWork(repository),
        clock=FixedClock(NOW),
        audit=RecordingAudit(),
    )

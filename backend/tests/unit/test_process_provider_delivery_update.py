"""T089A unit evidence for isolated authenticated late delivery updates."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import pytest

from backend.app.application.dispatch_notifications import SANITIZED_DELIVERY_FAILURE
from backend.app.application.process_provider_delivery_update import (
    LockedNotificationDelivery,
    ProcessProviderDeliveryUpdate,
    ProviderDeliveryUpdate,
    ProviderDeliveryUpdateError,
)
from backend.app.domain.notification_delivery import (
    ACCEPTED_DELIVERY_STATUS,
    DELIVERED_DELIVERY_STATUS,
    FAILED_DELIVERY_STATUS,
    NotificationDeliveryTransitionError,
)


OCCURRED_AT = datetime(2030, 6, 15, 12, 30)


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.deliveries = {
            31: LockedNotificationDelivery(31, "email", ACCEPTED_DELIVERY_STATUS),
            32: LockedNotificationDelivery(32, "whatsapp", ACCEPTED_DELIVERY_STATUS),
            33: LockedNotificationDelivery(33, "email", DELIVERED_DELIVERY_STATUS),
        }
        self.updates: list[dict[str, object]] = []
        self.appointment_state = "scheduled"

    def lock_delivery(self, delivery_id: int) -> LockedNotificationDelivery | None:
        return self.deliveries.get(delivery_id)

    def update_delivery(self, **values: object) -> None:
        delivery_id = values["delivery_id"]
        current = self.deliveries[delivery_id]  # type: ignore[index]
        self.deliveries[delivery_id] = LockedNotificationDelivery(
            delivery_id=current.delivery_id,
            channel=current.channel,
            status=values["status"],  # type: ignore[arg-type]
        )
        self.updates.append(values)


class FakeDeliveryUnitOfWork:
    def __init__(self, repository: FakeDeliveryRepository) -> None:
        self.repository = repository

    @contextmanager
    def transaction(self) -> Iterator[FakeDeliveryRepository]:
        yield self.repository


def _update(
    *,
    delivery_id: int,
    channel: str,
    status: str,
    authenticated: bool = True,
) -> ProviderDeliveryUpdate:
    return ProviderDeliveryUpdate(
        delivery_id=delivery_id,
        channel=channel,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        authentication_verified=authenticated,
        occurred_at=OCCURRED_AT,
    )


@pytest.mark.parametrize(
    ("delivery_id", "channel", "status", "expected_error"),
    (
        (31, "email", "delivered", None),
        (32, "whatsapp", "failed", SANITIZED_DELIVERY_FAILURE),
    ),
)
def test_t089a_updates_only_the_authenticated_matching_delivery(
    delivery_id: int,
    channel: str,
    status: str,
    expected_error: str | None,
) -> None:
    repository = FakeDeliveryRepository()
    original_other_deliveries = {
        key: value for key, value in repository.deliveries.items() if key != delivery_id
    }
    service = ProcessProviderDeliveryUpdate(
        unit_of_work=FakeDeliveryUnitOfWork(repository)
    )

    result = service.execute(
        _update(delivery_id=delivery_id, channel=channel, status=status)
    )

    assert result == LockedNotificationDelivery(delivery_id, channel, status)
    assert repository.updates == [
        {
            "delivery_id": delivery_id,
            "status": status,
            "status_changed_at": OCCURRED_AT,
            "sanitized_error": expected_error,
        }
    ]
    assert {
        key: value for key, value in repository.deliveries.items() if key != delivery_id
    } == original_other_deliveries
    assert repository.appointment_state == "scheduled"


@pytest.mark.parametrize(
    "update",
    (
        _update(delivery_id=31, channel="email", status="delivered", authenticated=False),
        _update(delivery_id=999, channel="email", status="delivered"),
        _update(delivery_id=31, channel="whatsapp", status="delivered"),
        _update(delivery_id=0, channel="email", status="delivered"),
    ),
)
def test_t089a_rejects_unauthenticated_missing_mismatched_or_invalid_updates(
    update: ProviderDeliveryUpdate,
) -> None:
    repository = FakeDeliveryRepository()
    original_deliveries = dict(repository.deliveries)
    service = ProcessProviderDeliveryUpdate(
        unit_of_work=FakeDeliveryUnitOfWork(repository)
    )

    with pytest.raises(ProviderDeliveryUpdateError):
        service.execute(update)

    assert repository.deliveries == original_deliveries
    assert repository.updates == []
    assert repository.appointment_state == "scheduled"


def test_t089a_rejects_a_transition_from_a_terminal_delivery() -> None:
    repository = FakeDeliveryRepository()
    original_deliveries = dict(repository.deliveries)
    service = ProcessProviderDeliveryUpdate(
        unit_of_work=FakeDeliveryUnitOfWork(repository)
    )

    with pytest.raises(NotificationDeliveryTransitionError):
        service.execute(_update(delivery_id=33, channel="email", status="failed"))

    assert repository.deliveries == original_deliveries
    assert repository.updates == []
    assert repository.appointment_state == "scheduled"

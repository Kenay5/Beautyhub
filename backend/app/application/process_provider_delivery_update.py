"""Apply authenticated late provider updates to one notification delivery."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypeAlias

from backend.app.application.dispatch_notifications import SANITIZED_DELIVERY_FAILURE
from backend.app.application.transactional_notifications import NotificationChannel
from backend.app.domain.notification_delivery import (
    FAILED_DELIVERY_STATUS,
    NotificationDeliveryStatus,
    transition_notification_delivery_status,
)


ProviderDeliveryUpdateStatus: TypeAlias = Literal["delivered", "failed"]


class ProviderDeliveryUpdateError(ValueError):
    """Raised when a provider update cannot safely target one delivery."""


@dataclass(frozen=True)
class ProviderDeliveryUpdate:
    """A provider status update after its adapter verifies authenticity."""

    delivery_id: int
    channel: NotificationChannel
    status: ProviderDeliveryUpdateStatus
    authentication_verified: bool
    occurred_at: datetime


@dataclass(frozen=True)
class LockedNotificationDelivery:
    """Current state of the exact delivery locked for an update."""

    delivery_id: int
    channel: NotificationChannel
    status: NotificationDeliveryStatus


class ProviderDeliveryUpdateRepository(Protocol):
    """Persistence operations limited to one notification delivery row."""

    def lock_delivery(
        self,
        delivery_id: int,
    ) -> LockedNotificationDelivery | None:
        """Lock and reload only the requested delivery."""

    def update_delivery(
        self,
        *,
        delivery_id: int,
        status: NotificationDeliveryStatus,
        status_changed_at: datetime,
        sanitized_error: str | None,
    ) -> None:
        """Update only the previously locked delivery."""


class ProviderDeliveryUpdateUnitOfWork(Protocol):
    """Provide a short transaction around one delivery transition."""

    def transaction(
        self,
    ) -> AbstractContextManager[ProviderDeliveryUpdateRepository]:
        """Commit one valid delivery update and roll back a rejected update."""


class ProcessProviderDeliveryUpdate:
    """Process an authenticated late update without touching its appointment."""

    def __init__(self, *, unit_of_work: ProviderDeliveryUpdateUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def execute(self, update: ProviderDeliveryUpdate) -> LockedNotificationDelivery:
        """Apply one valid provider transition to the matching delivery only."""

        _validate_update(update)
        with self._unit_of_work.transaction() as repository:
            delivery = repository.lock_delivery(update.delivery_id)
            if delivery is None or delivery.channel != update.channel:
                raise ProviderDeliveryUpdateError("provider delivery update is invalid.")

            next_status = transition_notification_delivery_status(
                current_status=delivery.status,
                next_status=update.status,
            )
            repository.update_delivery(
                delivery_id=delivery.delivery_id,
                status=next_status,
                status_changed_at=update.occurred_at,
                sanitized_error=(
                    SANITIZED_DELIVERY_FAILURE
                    if next_status == FAILED_DELIVERY_STATUS
                    else None
                ),
            )

        return LockedNotificationDelivery(
            delivery_id=delivery.delivery_id,
            channel=delivery.channel,
            status=next_status,
        )


def _validate_update(update: ProviderDeliveryUpdate) -> None:
    if update.authentication_verified is not True:
        raise ProviderDeliveryUpdateError("provider delivery update is invalid.")
    if (
        isinstance(update.delivery_id, bool)
        or not isinstance(update.delivery_id, int)
        or update.delivery_id <= 0
    ):
        raise ProviderDeliveryUpdateError("provider delivery update is invalid.")
    if update.status not in {"delivered", "failed"}:
        raise ProviderDeliveryUpdateError("provider delivery update is invalid.")

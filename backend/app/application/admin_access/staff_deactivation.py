"""Owner-only deactivation of the one active or pending staff account."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
    require_owner,
)
from backend.app.domain.time import normalize_instant
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)


class StaffDeactivationError(ValueError):
    """Raised when there is no deactivatable staff account."""


StaffStatus = Literal["none", "pending", "active"]


@dataclass(frozen=True)
class DeactivatedStaff:
    account_id: int
    owner_email: str
    notification_delivery_id: int = 0


class StaffDeactivationStore(Protocol):
    def load_current_status(self, *, owner_account_id: int) -> StaffStatus: ...

    def deactivate_current_staff(
        self, *, owner_account_id: int, current_time: datetime
    ) -> DeactivatedStaff: ...


class DeactivateStaff:
    """Revoke every credential and retain only the deactivated account identity."""

    def __init__(
        self,
        *,
        store: StaffDeactivationStore,
        audit: RecordAdministrativeAuditEvent,
        notifications: RecordSecurityNotificationDelivery,
        clock,
    ) -> None:
        self._store = store
        self._audit = audit
        self._notifications = notifications
        self._clock = clock

    def status(self, *, actor: AdministrativeActor) -> StaffStatus:
        self._require_owner(actor=actor)
        return self._store.load_current_status(owner_account_id=actor.account_id)

    def deactivate(self, *, actor: AdministrativeActor) -> DeactivatedStaff:
        self._require_owner(actor=actor)
        staff = self._store.deactivate_current_staff(
            owner_account_id=actor.account_id,
            current_time=normalize_instant(self._clock.now()),
        )
        self._audit.record(
            actor_account_id=actor.account_id,
            action="staff_deactivation",
            result="succeeded",
            target_reference=f"admin_account:{staff.account_id}",
        )
        delivery = self._notifications.record(
            event="staff_deactivated",
            template="staff_deactivation_notice",
            recipient=staff.owner_email,
            idempotency_reference=f"staff_deactivation:{staff.account_id}",
        )
        return DeactivatedStaff(
            account_id=staff.account_id,
            owner_email=staff.owner_email,
            notification_delivery_id=delivery.delivery_id,
        )

    def _require_owner(self, *, actor: AdministrativeActor) -> None:
        try:
            require_owner(actor=actor)
        except AdministrativeAuthorizationError:
            self._audit.record(
                actor_account_id=actor.account_id,
                action="authorization_denied",
                result="denied",
            )
            raise

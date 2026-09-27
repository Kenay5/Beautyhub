from datetime import datetime, timezone

import pytest

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.admin_access.staff_deactivation import (
    DeactivateStaff,
    DeactivatedStaff,
)


class Store:
    def __init__(self):
        self.deactivations = 0

    def deactivate_current_staff(self, **kwargs):
        self.deactivations += 1
        return DeactivatedStaff(account_id=8, owner_email="owner@example.test")

    def load_current_status(self, **kwargs):
        return "active"


class Audit:
    def __init__(self):
        self.events = []

    def record(self, **event):
        self.events.append(event)


class Notifications:
    def record(self, **kwargs):
        class Delivery:
            delivery_id = 12
        return Delivery()


class Clock:
    def now(self):
        return datetime(2035, 1, 1, tzinfo=timezone.utc)


def _operation(store, audit):
    return DeactivateStaff(
        store=store,
        audit=audit,
        notifications=Notifications(),
        clock=Clock(),
    )


def test_t080_owner_deactivates_staff_and_records_notification_intent():
    store = Store()
    audit = Audit()

    result = _operation(store, audit).deactivate(
        actor=AdministrativeActor(account_id=1, role="owner")
    )

    assert result.account_id == 8
    assert result.notification_delivery_id == 12
    assert store.deactivations == 1
    assert audit.events == [{
        "actor_account_id": 1,
        "action": "staff_deactivation",
        "result": "succeeded",
        "target_reference": "admin_account:8",
    }]


def test_t084_ordinary_owner_status_read_does_not_create_an_audit_event():
    store = Store()
    audit = Audit()

    status = _operation(store, audit).status(
        actor=AdministrativeActor(account_id=1, role="owner")
    )

    assert status == "active"
    assert store.deactivations == 0
    assert audit.events == []


@pytest.mark.parametrize("action", ["status", "deactivate"])
def test_t080_staff_cannot_manage_accounts_or_self(action):
    store = Store()
    audit = Audit()
    operation = _operation(store, audit)

    with pytest.raises(AdministrativeAuthorizationError):
        getattr(operation, action)(actor=AdministrativeActor(account_id=8, role="staff"))

    assert store.deactivations == 0
    assert audit.events == [{
        "actor_account_id": 8,
        "action": "authorization_denied",
        "result": "denied",
    }]

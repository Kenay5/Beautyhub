"""PostgreSQL lifecycle tests for T081 identity retention and history references."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.deactivated_staff_retention import (
    PurgeExpiredDeactivatedStaffIdentities,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.audit.retention import administrative_retention_deadline
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.deactivated_staff_retention_repository import (
    PostgresDeactivatedStaffRetentionStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAuditEvent,
    DeactivatedStaffIdentity,
)
from backend.tests.integration.admin_access.test_admin_login_session import (
    NOW,
    _seed_account,
    migrated_engine,
)
from backend.tests.integration.admin_access.test_staff_deactivation import (
    _operation,
    _seed_active_staff,
)


def _deactivate_staff(engine) -> tuple[int, int]:
    _seed_account(engine)
    staff_id = _seed_active_staff(engine, owner_id=1)
    with engine.begin() as connection:
        _operation(connection).deactivate(
            actor=AdministrativeActor(account_id=1, role="owner")
        )
    return 1, staff_id


def _purge_batch(engine, current_time) -> int:
    with engine.begin() as connection:
        return PurgeExpiredDeactivatedStaffIdentities(
            store=PostgresDeactivatedStaffRetentionStore(connection)
        ).purge_batch(current_time=current_time)


def _archive_deadline(engine, account_id: int):
    with engine.connect() as connection:
        return connection.execute(
            select(DeactivatedStaffIdentity.identifiable_until).where(
                DeactivatedStaffIdentity.admin_account_id == account_id
            )
        ).scalar_one()


@pytest.mark.integration
def test_t081_identity_archive_is_kept_before_and_removed_exactly_at_anniversary(
    migrated_engine,
):
    owner_id, staff_id = _deactivate_staff(migrated_engine)
    deadline = _archive_deadline(migrated_engine, staff_id)
    assert deadline == administrative_retention_deadline(NOW)

    assert _purge_batch(migrated_engine, deadline - timedelta(microseconds=1)) == 0
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(DeactivatedStaffIdentity.email_ciphertext).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).scalar_one()

    assert _purge_batch(migrated_engine, deadline) == 1
    assert _purge_batch(migrated_engine, deadline + timedelta(microseconds=1)) == 0
    assert _purge_batch(migrated_engine, deadline) == 0

    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).first() is None
        assert connection.execute(
            select(AdminAccount.status).where(
                AdminAccount.admin_account_id == staff_id
            )
        ).scalar_one() == "deactivated"
        assert connection.execute(
            select(
                AdminAuditEvent.action,
                AdminAuditEvent.target_reference,
                AdminAuditEvent.actor_account_id,
            ).where(
                AdminAuditEvent.action == "staff_deactivation",
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}",
            )
        ).one() == (
            "staff_deactivation",
            f"admin_account:{staff_id}",
            owner_id,
        )


@pytest.mark.integration
def test_t081_later_associated_events_extend_retention_without_losing_internal_refs(
    migrated_engine,
):
    owner_id, staff_id = _deactivate_staff(migrated_engine)
    earlier_deadline = _archive_deadline(migrated_engine, staff_id)
    later_event_time = NOW + timedelta(days=30)
    later_deadline = administrative_retention_deadline(later_event_time)
    assert later_deadline > earlier_deadline

    with migrated_engine.begin() as connection:
        RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=FixedClock(later_event_time),
        ).record(
            actor_account_id=owner_id,
            action="password_recovery",
            result="succeeded",
            target_reference=f"admin_account:{staff_id}",
        )

    assert _archive_deadline(migrated_engine, staff_id) == later_deadline
    assert _purge_batch(migrated_engine, earlier_deadline) == 0
    assert _purge_batch(migrated_engine, later_deadline - timedelta(microseconds=1)) == 0
    assert _purge_batch(migrated_engine, later_deadline) == 1

    with migrated_engine.connect() as connection:
        events = connection.execute(
            select(AdminAuditEvent.action, AdminAuditEvent.target_reference).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            ).order_by(AdminAuditEvent.admin_audit_event_id)
        ).all()
        assert events == [
            ("staff_invitation", f"admin_account:{staff_id}"),
            ("staff_deactivation", f"admin_account:{staff_id}"),
            ("password_recovery", f"admin_account:{staff_id}"),
        ]
        assert "synthetic.staff@example.test" not in repr(events)
        assert connection.execute(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == staff_id
            )
        ).scalar_one() == staff_id
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).first() is None

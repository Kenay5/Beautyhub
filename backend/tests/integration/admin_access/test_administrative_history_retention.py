"""PostgreSQL evidence for T087 bounded and exact administrative retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import DBAPIError

from backend.app.application.admin_access.administrative_history_retention import (
    PurgeExpiredAdministrativeHistory,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.clock import FixedClock
from backend.app.domain.audit.retention import administrative_retention_deadline
from backend.app.infrastructure.persistence.administrative_history_retention_repository import (
    AUDIT_EVENT_PURGE_BATCH_SIZE,
    PostgresAdministrativeHistoryRetentionStore,
)
from backend.app.infrastructure.persistence.administrative_history_repository import (
    administrative_event_expiration_time,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAuditEvent,
    DeactivatedStaffIdentity,
)
from backend.tests.integration.admin_access.test_admin_login_session import (
    _seed_account,
    migrated_engine,
)
def _purge_batch(engine, current_time: datetime) -> int:
    with engine.begin() as connection:
        return PurgeExpiredAdministrativeHistory(
            store=PostgresAdministrativeHistoryRetentionStore(connection)
        ).purge_batch(current_time=current_time)


def _event_expiration(engine, event_id: int) -> datetime:
    with engine.connect() as connection:
        occurred_at = connection.execute(
            select(AdminAuditEvent.occurred_at).where(
                AdminAuditEvent.admin_audit_event_id == event_id
            )
        ).scalar_one()
    return administrative_retention_deadline(occurred_at)


def _event_time_for_deadline(deadline: datetime) -> datetime:
    local_deadline = deadline.astimezone(ZoneInfo("America/Mexico_City"))
    return local_deadline.replace(year=local_deadline.year - 1).astimezone(timezone.utc)


def _seed_deactivated_history(engine, *, identity_deadline: datetime) -> int:
    _seed_account(engine)
    with engine.begin() as connection:
        staff_id = connection.execute(
            insert(AdminAccount)
            .values(role="staff", status="deactivated")
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(DeactivatedStaffIdentity).values(
                admin_account_id=staff_id,
                email_ciphertext=b"synthetic-encrypted-email",
                key_version="test-v1",
                identifiable_until=identity_deadline,
            )
        )
    return staff_id


def _record_staff_event(
    engine, *, staff_id: int, action: str, event_time: datetime
) -> int:
    with engine.begin() as connection:
        RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=FixedClock(event_time),
        ).record(
            actor_account_id=1,
            action=action,
            result="succeeded",
            target_reference=f"admin_account:{staff_id}",
        )
        event_id = connection.execute(
            select(AdminAuditEvent.admin_audit_event_id)
            .where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}",
                AdminAuditEvent.action == action,
            )
            .order_by(AdminAuditEvent.admin_audit_event_id.desc())
            .limit(1)
        ).scalar_one()
    return event_id


@pytest.mark.integration
def test_t087_event_and_staff_identity_are_kept_before_then_purged_at_anniversary(
    migrated_engine,
) -> None:
    with migrated_engine.connect() as connection:
        db_now = connection.execute(select(func.clock_timestamp())).scalar_one()
    deadline = db_now - timedelta(days=20)
    staff_id = _seed_deactivated_history(migrated_engine, identity_deadline=deadline)
    event_time = _event_time_for_deadline(deadline)
    _record_staff_event(
        migrated_engine,
        staff_id=staff_id,
        action="staff_invitation",
        event_time=event_time,
    )
    _record_staff_event(
        migrated_engine,
        staff_id=staff_id,
        action="staff_deactivation",
        event_time=event_time,
    )
    with migrated_engine.connect() as connection:
        event_ids = connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            )
        ).scalars().all()
    event_deadlines = {
        event_id: _event_expiration(migrated_engine, event_id)
        for event_id in event_ids
    }
    just_before = deadline - timedelta(microseconds=1)
    expired_before = {
        event_id for event_id, event_deadline in event_deadlines.items()
        if event_deadline <= just_before
    }
    expected_before = len(expired_before)

    assert _purge_batch(migrated_engine, just_before) == expected_before
    with migrated_engine.connect() as connection:
        remaining_event_ids = set(connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            )
        ).scalars().all())
        assert remaining_event_ids == set(event_ids) - expired_before
        identity_remains = connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).scalar_one_or_none()
        assert identity_remains == staff_id

    remaining_due_events = set(event_ids) - expired_before
    expected_at_deadline = len(remaining_due_events) + 1
    assert _purge_batch(migrated_engine, deadline) == expected_at_deadline
    assert _purge_batch(migrated_engine, deadline + timedelta(microseconds=1)) == 0
    assert _purge_batch(migrated_engine, deadline) == 0
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == staff_id
            )
        ).scalar_one() == staff_id
        assert connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            )
        ).first() is None
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).first() is None


@pytest.mark.integration
def test_t087_later_event_extends_identity_retention_and_only_due_events_are_removed(
    migrated_engine,
) -> None:
    with migrated_engine.connect() as connection:
        db_now = connection.execute(select(func.clock_timestamp())).scalar_one()
    old_deadline = db_now - timedelta(days=60)
    later_deadline = old_deadline + timedelta(days=30)
    staff_id = _seed_deactivated_history(migrated_engine, identity_deadline=old_deadline)
    old_event_time = _event_time_for_deadline(old_deadline)
    _record_staff_event(
        migrated_engine,
        staff_id=staff_id,
        action="staff_deactivation",
        event_time=old_event_time,
    )
    with migrated_engine.connect() as connection:
        old_event_ids = connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            )
        ).scalars().all()
    first_deadline = min(
        [old_deadline]
        + [_event_expiration(migrated_engine, event_id) for event_id in old_event_ids]
    )
    later_event_time = _event_time_for_deadline(later_deadline)
    with migrated_engine.begin() as connection:
        RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=FixedClock(later_event_time),
        ).record(
            actor_account_id=1,
            action="password_recovery",
            result="succeeded",
            target_reference=f"admin_account:{staff_id}",
        )
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(DeactivatedStaffIdentity.identifiable_until).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).scalar_one() == later_deadline
    with migrated_engine.connect() as connection:
        next_deadline = PurgeExpiredAdministrativeHistory(
            store=PostgresAdministrativeHistoryRetentionStore(connection)
        ).next_expiration(
            current_time=old_deadline - timedelta(days=30)
        )
    assert next_deadline == first_deadline

    # At the earlier deadline only the older deactivation-associated events expire.
    assert _purge_batch(migrated_engine, old_deadline) == 1
    with migrated_engine.connect() as connection:
        next_deadline = PurgeExpiredAdministrativeHistory(
            store=PostgresAdministrativeHistoryRetentionStore(connection)
        ).next_expiration(current_time=old_deadline)
    assert next_deadline == later_deadline
    with migrated_engine.connect() as connection:
        retained = connection.execute(
            select(
                AdminAuditEvent.action,
                AdminAuditEvent.target_reference,
                AdminAuditEvent.actor_account_id,
            ).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            )
        ).one()
        assert retained == (
            "password_recovery",
            f"admin_account:{staff_id}",
            1,
        )
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).scalar_one() == staff_id

    assert _purge_batch(migrated_engine, later_deadline - timedelta(microseconds=1)) == 0
    assert _purge_batch(migrated_engine, later_deadline) == 2
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.target_reference == f"admin_account:{staff_id}"
            )
        ).first() is None
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).first() is None


@pytest.mark.integration
def test_t087_timezone_year_boundary_and_t085_trigger_allow_only_retention_delete(
    migrated_engine,
) -> None:
    _seed_account(migrated_engine)
    owner_id = 1
    event_time = datetime(2024, 1, 1, 5, 59, 59, 999999, tzinfo=timezone.utc)
    deadline = administrative_retention_deadline(event_time)
    with migrated_engine.begin() as connection:
        event_id = connection.execute(
            insert(AdminAuditEvent)
            .values(
                actor_account_id=owner_id,
                action="login",
                result="succeeded",
                occurred_at=event_time,
                target_reference=None,
            )
            .returning(AdminAuditEvent.admin_audit_event_id)
        ).scalar_one()
        with pytest.raises(DBAPIError):
            connection.execute(
                select(
                    func.set_config(
                        "beautyhub.administrative_history_retention_delete",
                        "authorized",
                        True,
                    )
                )
            )
            with connection.begin_nested():
                connection.execute(
                    delete(AdminAuditEvent).where(
                        AdminAuditEvent.admin_audit_event_id == event_id
                    )
                )

    assert _purge_batch(migrated_engine, deadline - timedelta(microseconds=1)) == 0
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.admin_audit_event_id == event_id
            )
        ).scalar_one() == event_id
        expiration = connection.execute(
            select(administrative_event_expiration_time()).where(
                AdminAuditEvent.admin_audit_event_id == event_id
            )
        ).scalar_one()
        assert expiration == deadline

    assert _purge_batch(migrated_engine, deadline) == 1
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.admin_audit_event_id == event_id
            )
        ).first() is None


@pytest.mark.integration
def test_t087_event_purge_is_bounded_and_resumes_until_idempotent(
    migrated_engine,
) -> None:
    _seed_account(migrated_engine)
    owner_id = 1
    event_time = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    deadline = administrative_retention_deadline(event_time)
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(AdminAuditEvent),
            [
                {
                    "actor_account_id": owner_id,
                    "action": "login",
                    "result": "succeeded",
                    "occurred_at": event_time,
                    "target_reference": None,
                }
                for _ in range(AUDIT_EVENT_PURGE_BATCH_SIZE + 1)
            ],
        )

    assert _purge_batch(migrated_engine, deadline) == AUDIT_EVENT_PURGE_BATCH_SIZE
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(AdminAuditEvent)
        ).scalar_one() == 1

    assert _purge_batch(migrated_engine, deadline) == 1
    assert _purge_batch(migrated_engine, deadline) == 0


@pytest.mark.integration
def test_t087_future_cutoff_cannot_remove_unexpired_history(migrated_engine) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.connect() as connection:
        db_now = connection.execute(select(func.clock_timestamp())).scalar_one()
    with migrated_engine.begin() as connection:
        RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=FixedClock(db_now),
        ).record(
            actor_account_id=1,
            action="login",
            result="succeeded",
        )
        staff_id = connection.execute(
            insert(AdminAccount)
            .values(role="staff", status="deactivated")
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(DeactivatedStaffIdentity).values(
                admin_account_id=staff_id,
                email_ciphertext=b"synthetic-encrypted-email",
                key_version="test-v1",
                identifiable_until=db_now + timedelta(days=1),
            )
        )
        event_id = connection.execute(
            select(AdminAuditEvent.admin_audit_event_id)
            .where(
                AdminAuditEvent.actor_account_id == 1,
                AdminAuditEvent.action == "login",
                AdminAuditEvent.occurred_at == db_now,
            )
            .order_by(AdminAuditEvent.admin_audit_event_id.desc())
            .limit(1)
        ).scalar_one()

    assert _purge_batch(
        migrated_engine,
        datetime(9999, 1, 1, tzinfo=timezone.utc),
    ) == 0
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.admin_audit_event_id == event_id
            )
        ).scalar_one() == event_id
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).scalar_one() == staff_id


@pytest.mark.integration
def test_t087_event_and_identity_purge_roll_back_together(migrated_engine) -> None:
    with migrated_engine.connect() as connection:
        db_now = connection.execute(select(func.clock_timestamp())).scalar_one()
    deadline = db_now - timedelta(days=10)
    staff_id = _seed_deactivated_history(
        migrated_engine, identity_deadline=deadline
    )
    event_id = _record_staff_event(
        migrated_engine,
        staff_id=staff_id,
        action="staff_deactivation",
        event_time=_event_time_for_deadline(deadline),
    )

    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert PostgresAdministrativeHistoryRetentionStore(
                connection
            ).purge_expired_batch(current_time=db_now) >= 2
            assert connection.execute(
                select(AdminAuditEvent.admin_audit_event_id).where(
                    AdminAuditEvent.admin_audit_event_id == event_id
                )
            ).scalar_one_or_none() is None
            assert connection.execute(
                select(DeactivatedStaffIdentity.admin_account_id).where(
                    DeactivatedStaffIdentity.admin_account_id == staff_id
                )
            ).scalar_one_or_none() is None
        finally:
            transaction.rollback()

    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminAuditEvent.admin_audit_event_id).where(
                AdminAuditEvent.admin_audit_event_id == event_id
            )
        ).scalar_one() == event_id
        assert connection.execute(
            select(DeactivatedStaffIdentity.admin_account_id).where(
                DeactivatedStaffIdentity.admin_account_id == staff_id
            )
        ).scalar_one() == staff_id

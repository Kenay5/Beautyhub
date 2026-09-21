"""T046 PostgreSQL evidence for preserving and expiring administrative locks."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, select, text

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
)
from backend.app.application.clock import FixedClock
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminCredentialFailureEvent,
    AdminSession,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.settings import load_test_database_url


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE admin_accounts, owner_bootstrap_state "
                    "RESTART IDENTITY CASCADE"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO owner_bootstrap_state "
                    "(bootstrap_state_id, status) VALUES (1, 'open')"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _seed_account_with_existing_session(engine: Engine) -> int:
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password(
                    "synthetic administrative phrase"
                ),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminSession).values(
                admin_account_id=account_id,
                session_digest=b"\x31" * 32,
                csrf_digest=b"\x32" * 32,
                key_version="v1",
                created_at=NOW - timedelta(minutes=1),
                last_human_activity_at=NOW,
                absolute_expires_at=NOW + timedelta(hours=7, minutes=59),
                status="active",
            )
        )
    return account_id


def _record_failures(connection, *, account_id: int, current_time: datetime) -> None:
    recorder = RecordAdministrativeCredentialFailure(
        store=PostgresAdministrativeAccountSecurityStore(connection),
        clock=FixedClock(current_time),
    )
    for _ in range(5):
        recorder.record(account_id=account_id, operation="login")


@pytest.mark.integration
def test_t046_active_lock_rejects_without_extending_counting_or_closing_session(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_account_with_existing_session(migrated_engine)
    with migrated_engine.begin() as connection:
        _record_failures(connection, account_id=account_id, current_time=NOW)

    during_lock = NOW + timedelta(seconds=1)
    with migrated_engine.begin() as connection:
        allowed = EnsureAdministrativeCredentialCheck(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(during_lock),
        ).ensure_allowed(account_id=account_id)

    with migrated_engine.connect() as connection:
        state = connection.execute(
            select(
                AdminAccountSecurityState.lock_until,
                AdminAccountSecurityState.fifth_failure_event_id,
            ).where(AdminAccountSecurityState.admin_account_id == account_id)
        ).one()
        failure_count = connection.execute(
            select(text("count(*)"))
            .select_from(AdminCredentialFailureEvent)
            .where(AdminCredentialFailureEvent.admin_account_id == account_id)
        ).scalar_one()
        session_status = connection.execute(
            select(AdminSession.status).where(AdminSession.admin_account_id == account_id)
        ).scalar_one()

    assert not allowed
    assert state.lock_until == NOW + timedelta(minutes=15)
    assert state.fifth_failure_event_id is not None
    assert failure_count == 5
    assert session_status == "active"


@pytest.mark.integration
def test_t046_exact_lock_expiry_clears_the_guard_and_starts_a_new_failure_window(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_account_with_existing_session(migrated_engine)
    with migrated_engine.begin() as connection:
        _record_failures(connection, account_id=account_id, current_time=NOW)

    expiry = NOW + timedelta(minutes=15)
    with migrated_engine.begin() as connection:
        guard = EnsureAdministrativeCredentialCheck(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(expiry),
        )
        allowed = guard.ensure_allowed(account_id=account_id)
        next_failure = RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(expiry),
        ).record(account_id=account_id, operation="login")

    with migrated_engine.connect() as connection:
        state = connection.execute(
            select(
                AdminAccountSecurityState.lock_until,
                AdminAccountSecurityState.fifth_failure_event_id,
            ).where(AdminAccountSecurityState.admin_account_id == account_id)
        ).one()
        session_status = connection.execute(
            select(AdminSession.status).where(AdminSession.admin_account_id == account_id)
        ).scalar_one()

    assert allowed
    assert next_failure.failure_count == 1
    assert next_failure.lock_until is None
    assert state.lock_until is None
    assert state.fifth_failure_event_id is None
    assert session_status == "active"

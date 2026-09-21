"""T014 PostgreSQL evidence for row-locked administrative account failures."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, delete, func, inspect, select, text

from backend.app.application.admin_access.account_security import (
    RecordAdministrativeCredentialFailure,
    RestrictPostRecoveryFactorReplacement,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.authentication.account_security import (
    ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW,
)
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccountSecurityState,
    AdminCredentialFailureEvent,
)
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            alembic_config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
        yield engine
    finally:
        engine.dispose()


def _insert_account(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES ('staff', 'deactivated') RETURNING admin_account_id"
        )
    ).scalar_one()


def _record_failure(
    connection: Connection, *, account_id: int, current_time: datetime
):
    return RecordAdministrativeCredentialFailure(
        store=PostgresAdministrativeAccountSecurityStore(connection),
        clock=FixedClock(current_time),
    ).record(account_id=account_id, operation="login")


@pytest.mark.integration
def test_t014_persists_minimum_events_and_an_exact_nonextending_lock(
    migrated_engine: Engine,
) -> None:
    inspector = inspect(migrated_engine)
    assert {
        "admin_credential_failure_events",
        "admin_account_security_states",
    }.issubset(inspector.get_table_names())
    event_columns = {
        column["name"]
        for column in inspector.get_columns("admin_credential_failure_events")
    }
    state_columns = {
        column["name"]
        for column in inspector.get_columns("admin_account_security_states")
    }
    prohibited = {"password", "code", "token", "credential", "secret"}
    assert not (event_columns | state_columns) & prohibited

    account_id: int | None = None
    try:
        with migrated_engine.begin() as connection:
            account_id = _insert_account(connection)
            results = tuple(
                _record_failure(
                    connection,
                    account_id=account_id,
                    current_time=NOW,
                )
                for _ in range(5)
            )
            blocked = _record_failure(
                connection,
                account_id=account_id,
                current_time=NOW + timedelta(minutes=1),
            )
            RestrictPostRecoveryFactorReplacement(
                store=PostgresAdministrativeAccountSecurityStore(connection)
            ).apply(account_id=account_id)

        with migrated_engine.connect() as connection:
            event_count = connection.execute(
                select(func.count())
                .select_from(AdminCredentialFailureEvent)
                .where(AdminCredentialFailureEvent.admin_account_id == account_id)
            ).scalar_one()
            state = connection.execute(
                select(
                    AdminAccountSecurityState.lock_until,
                    AdminAccountSecurityState.fifth_failure_event_id,
                    AdminAccountSecurityState.post_recovery_second_factor_restricted,
                ).where(
                    AdminAccountSecurityState.admin_account_id == account_id
                )
            ).mappings().one()

        assert results[-1].failure_count == 5
        assert results[-1].lock_until == NOW + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW
        assert not results[-1].blocked
        assert blocked.blocked
        assert blocked.lock_until == NOW + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW
        assert event_count == 5
        assert state["lock_until"] == NOW + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW
        assert state["fifth_failure_event_id"] is not None
        assert state["post_recovery_second_factor_restricted"]

        with migrated_engine.begin() as connection:
            after_expiry = _record_failure(
                connection,
                account_id=account_id,
                current_time=NOW + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW,
            )
        assert after_expiry.failure_count == 1
        assert after_expiry.lock_until is None
    finally:
        if account_id is not None:
            with migrated_engine.begin() as connection:
                connection.execute(
                    delete(AdminAccountSecurityState).where(
                        AdminAccountSecurityState.admin_account_id == account_id
                    )
                )
                connection.execute(
                    delete(AdminCredentialFailureEvent).where(
                        AdminCredentialFailureEvent.admin_account_id == account_id
                    )
                )
                connection.execute(
                    text(
                        "DELETE FROM admin_accounts WHERE admin_account_id = :account_id"
                    ),
                    {"account_id": account_id},
                )


@pytest.mark.integration
def test_t014_serializes_the_contested_fifth_failure_with_a_row_lock(
    migrated_engine: Engine,
) -> None:
    account_id: int | None = None
    try:
        with migrated_engine.begin() as connection:
            account_id = _insert_account(connection)
            for _ in range(4):
                _record_failure(connection, account_id=account_id, current_time=NOW)

        outcomes = _run_concurrently(
            (
                lambda: _attempt_fifth_failure(migrated_engine, account_id),
                lambda: _attempt_fifth_failure(migrated_engine, account_id),
            )
        )

        with migrated_engine.connect() as connection:
            event_count = connection.execute(
                select(func.count())
                .select_from(AdminCredentialFailureEvent)
                .where(AdminCredentialFailureEvent.admin_account_id == account_id)
            ).scalar_one()
            lock_until = connection.execute(
                select(AdminAccountSecurityState.lock_until).where(
                    AdminAccountSecurityState.admin_account_id == account_id
                )
            ).scalar_one()

        assert sorted(outcomes) == ["blocked", "created"]
        assert event_count == 5
        assert lock_until == NOW + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW
    finally:
        if account_id is not None:
            with migrated_engine.begin() as connection:
                connection.execute(
                    delete(AdminAccountSecurityState).where(
                        AdminAccountSecurityState.admin_account_id == account_id
                    )
                )
                connection.execute(
                    delete(AdminCredentialFailureEvent).where(
                        AdminCredentialFailureEvent.admin_account_id == account_id
                    )
                )
                connection.execute(
                    text(
                        "DELETE FROM admin_accounts WHERE admin_account_id = :account_id"
                    ),
                    {"account_id": account_id},
                )


def _run_concurrently(workers: tuple[Callable[[], str], ...]) -> list[str]:
    barrier = Barrier(len(workers))

    def synchronized(worker: Callable[[], str]) -> str:
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(synchronized, workers))


def _attempt_fifth_failure(engine: Engine, account_id: int) -> str:
    with engine.begin() as connection:
        result = _record_failure(connection, account_id=account_id, current_time=NOW)
    return "blocked" if result.blocked else "created"

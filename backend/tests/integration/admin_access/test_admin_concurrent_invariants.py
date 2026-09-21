"""T020 PostgreSQL evidence for concurrent administrative invariants."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from typing import TypeVar

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2032, 2, 20, 16, tzinfo=timezone.utc)
T = TypeVar("T")


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        _reset_admin_fixture_state(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("role", "status", "count_predicate"),
    (
        ("owner", "inactive", "role = 'owner'"),
        (
            "staff",
            "pending",
            "role = 'staff' AND status IN ('pending', 'active')",
        ),
    ),
    ids=("single-owner", "single-current-staff"),
)
def test_t020_concurrent_account_creation_allows_one_current_account(
    migrated_engine: Engine,
    role: str,
    status: str,
    count_predicate: str,
) -> None:
    outcomes = _run_concurrently(
        migrated_engine,
        (
            lambda connection: _insert_account(connection, role, status),
            lambda connection: _insert_account(connection, role, status),
        ),
        rejected_result=("rejected", None),
    )
    accepted_ids = [
        account_id
        for outcome, account_id in outcomes
        if outcome == "accepted" and account_id is not None
    ]

    try:
        assert len(accepted_ids) == 1
        with migrated_engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM admin_accounts WHERE " + count_predicate
                )
            ).scalar_one()
        assert count == 1
    finally:
        # The owner trigger intentionally rejects DELETE; reset only this test DB.
        _reset_admin_fixture_state(migrated_engine)


@pytest.mark.integration
def test_t020_concurrent_email_claims_allow_one_global_owner(
    migrated_engine: Engine,
) -> None:
    account_ids = _create_deactivated_staff_accounts(migrated_engine, 2)
    digest = b"\x20" * 32
    try:
        outcomes = _run_concurrently(
            migrated_engine,
            tuple(
                lambda connection, account_id=account_id: _insert_email_claim(
                    connection, account_id, digest, "current"
                )
                for account_id in account_ids
            ),
            rejected_result="rejected",
        )
        assert sorted(outcomes) == ["accepted", "rejected"]
        with migrated_engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM admin_email_claims "
                    "WHERE lookup_digest = :digest"
                ),
                {"digest": digest},
            ).scalar_one()
        assert count == 1
    finally:
        _delete_accounts(migrated_engine, list(account_ids))


@pytest.mark.integration
def test_t020_concurrent_activation_changes_one_pending_account_once(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine, "staff", "pending")
    try:
        outcomes = _run_concurrently(
            migrated_engine,
            (
                lambda connection: _activate_pending_account(connection, account_id),
                lambda connection: _activate_pending_account(connection, account_id),
            ),
            rejected_result="rejected",
        )
        assert sorted(outcomes) == ["activated", "unchanged"]
        assert _account_status(migrated_engine, account_id) == "active"
    finally:
        _delete_accounts(migrated_engine, [account_id])


@pytest.mark.integration
def test_t020_concurrent_session_replacement_leaves_one_active_session(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine, "staff", "deactivated")
    _insert_active_session(migrated_engine, account_id, b"\x31" * 32, b"\x41" * 32)
    try:
        outcomes = _run_concurrently(
            migrated_engine,
            (
                lambda connection: _replace_session(
                    connection, account_id, b"\x32" * 32, b"\x42" * 32
                ),
                lambda connection: _replace_session(
                    connection, account_id, b"\x33" * 32, b"\x43" * 32
                ),
            ),
            rejected_result="rejected",
        )
        assert sorted(outcomes) == ["accepted", "rejected"]
        with migrated_engine.connect() as connection:
            active_count = connection.execute(
                text(
                    "SELECT count(*) FROM admin_sessions "
                    "WHERE admin_account_id = :account_id AND status = 'active'"
                ),
                {"account_id": account_id},
            ).scalar_one()
        assert active_count == 1
    finally:
        _delete_accounts(migrated_engine, [account_id])


@pytest.mark.integration
def test_t020_concurrent_totp_and_recovery_consumption_allow_one_success(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine, "staff", "deactivated")
    factor_id = _insert_totp_factor(migrated_engine, account_id)
    recovery_code_id = _insert_recovery_code(
        migrated_engine, account_id, b"\x51" * 32, position=1
    )
    untouched_code_id = _insert_recovery_code(
        migrated_engine, account_id, b"\x52" * 32, position=2
    )
    try:
        period_outcomes = _run_concurrently(
            migrated_engine,
            (
                lambda connection: _consume_totp_period(
                    connection, account_id, factor_id, 123456
                ),
                lambda connection: _consume_totp_period(
                    connection, account_id, factor_id, 123456
                ),
            ),
            rejected_result="rejected",
        )
        recovery_outcomes = _run_concurrently(
            migrated_engine,
            (
                lambda connection: _consume_recovery_code(
                    connection, recovery_code_id, b"\x51" * 32
                ),
                lambda connection: _consume_recovery_code(
                    connection, recovery_code_id, b"\x51" * 32
                ),
            ),
            rejected_result="rejected",
        )

        assert sorted(period_outcomes) == ["accepted", "rejected"]
        assert sorted(recovery_outcomes) == ["consumed", "unchanged"]
        assert (
            _consume_recovery_code_by_digest(
                migrated_engine, account_id, b"\xff" * 32
            )
            == "unchanged"
        )
        assert _recovery_code_status(migrated_engine, untouched_code_id) == "active"
    finally:
        _delete_accounts(migrated_engine, [account_id])


@pytest.mark.integration
def test_t020_concurrent_email_changes_leave_one_reservation_and_link(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine, "staff", "deactivated")
    current_digest = b"\x61" * 32
    _insert_claim_committed(migrated_engine, account_id, current_digest, "current")
    try:
        outcomes = _run_concurrently(
            migrated_engine,
            (
                lambda connection: _request_email_change(
                    connection, account_id, b"\x62" * 32, b"\x72" * 32
                ),
                lambda connection: _request_email_change(
                    connection, account_id, b"\x63" * 32, b"\x73" * 32
                ),
            ),
            rejected_result="rejected",
        )
        assert sorted(outcomes) == ["accepted", "rejected"]
        with migrated_engine.connect() as connection:
            current_count = connection.execute(
                text(
                    "SELECT count(*) FROM admin_email_claims "
                    "WHERE admin_account_id = :account_id "
                    "AND claim_kind = 'current' AND lookup_digest = :digest"
                ),
                {"account_id": account_id, "digest": current_digest},
            ).scalar_one()
            reserved_count = connection.execute(
                text(
                    "SELECT count(*) FROM admin_email_claims "
                    "WHERE admin_account_id = :account_id AND claim_kind = 'reserved'"
                ),
                {"account_id": account_id},
            ).scalar_one()
            active_link_count = connection.execute(
                text(
                    "SELECT count(*) FROM security_links "
                    "WHERE admin_account_id = :account_id "
                    "AND purpose = 'email_change' AND status = 'active'"
                ),
                {"account_id": account_id},
            ).scalar_one()
        assert (current_count, reserved_count, active_link_count) == (1, 1, 1)
    finally:
        _delete_accounts(migrated_engine, [account_id])


def _run_concurrently(
    engine: Engine,
    workers: tuple[Callable[[Connection], T], ...],
    *,
    rejected_result: T,
) -> list[T]:
    barrier = Barrier(len(workers))

    def run(worker: Callable[[Connection], T]) -> T:
        barrier.wait(timeout=10)
        try:
            with engine.begin() as connection:
                return worker(connection)
        except DBAPIError:
            return rejected_result

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(run, workers))


def _insert_account(
    connection: Connection, role: str, status: str
) -> tuple[str, int | None]:
    account_id = connection.execute(
        text(
            "INSERT INTO admin_accounts (role, status) "
            "VALUES (:role, :status) RETURNING admin_account_id"
        ),
        {"role": role, "status": status},
    ).scalar_one()
    return "accepted", account_id


def _insert_email_claim(
    connection: Connection, account_id: int, digest: bytes, claim_kind: str
) -> str:
    connection.execute(
        text(
            "INSERT INTO admin_email_claims ("
            "admin_account_id, claim_kind, lookup_digest, email_ciphertext, key_version"
            ") VALUES ("
            ":account_id, :claim_kind, :digest, :ciphertext, 'v1'"
            ")"
        ),
        {
            "account_id": account_id,
            "claim_kind": claim_kind,
            "digest": digest,
            "ciphertext": b"protected-fixture",
        },
    )
    return "accepted"


def _activate_pending_account(connection: Connection, account_id: int) -> str:
    activated_id = connection.execute(
        text(
            "UPDATE admin_accounts SET status = 'active' "
            "WHERE admin_account_id = :account_id AND status = 'pending' "
            "RETURNING admin_account_id"
        ),
        {"account_id": account_id},
    ).scalar_one_or_none()
    return "activated" if activated_id is not None else "unchanged"


def _replace_session(
    connection: Connection,
    account_id: int,
    session_digest: bytes,
    csrf_digest: bytes,
) -> str:
    connection.execute(
        text(
            "UPDATE admin_sessions SET status = 'invalidated', "
            "invalidated_at = :now WHERE admin_account_id = :account_id "
            "AND status = 'active'"
        ),
        {"now": NOW, "account_id": account_id},
    )
    connection.execute(
        text(
            "INSERT INTO admin_sessions ("
            "admin_account_id, session_digest, csrf_digest, key_version, created_at, "
            "last_human_activity_at, absolute_expires_at, status, invalidated_at"
            ") VALUES ("
            ":account_id, :session_digest, :csrf_digest, 'v1', :now, :now, "
            ":expires_at, 'active', NULL)"
        ),
        {
            "account_id": account_id,
            "session_digest": session_digest,
            "csrf_digest": csrf_digest,
            "now": NOW,
            "expires_at": NOW + timedelta(hours=8),
        },
    )
    return "accepted"


def _consume_totp_period(
    connection: Connection, account_id: int, factor_id: int, counter: int
) -> str:
    connection.execute(
        text(
            "INSERT INTO totp_period_uses ("
            "admin_account_id, totp_factor_id, period_counter, consumed_at"
            ") VALUES (:account_id, :factor_id, :counter, :now)"
        ),
        {
            "account_id": account_id,
            "factor_id": factor_id,
            "counter": counter,
            "now": NOW,
        },
    )
    return "accepted"


def _consume_recovery_code(
    connection: Connection, recovery_code_id: int, digest: bytes
) -> str:
    consumed_id = connection.execute(
        text(
            "UPDATE recovery_codes SET status = 'used', used_at = :now "
            "WHERE recovery_code_id = :recovery_code_id "
            "AND lookup_digest = :digest AND status = 'active' "
            "RETURNING recovery_code_id"
        ),
        {"now": NOW, "recovery_code_id": recovery_code_id, "digest": digest},
    ).scalar_one_or_none()
    return "consumed" if consumed_id is not None else "unchanged"


def _request_email_change(
    connection: Connection,
    account_id: int,
    email_digest: bytes,
    token_digest: bytes,
) -> str:
    _insert_email_claim(connection, account_id, email_digest, "reserved")
    connection.execute(
        text(
            "INSERT INTO security_links ("
            "admin_account_id, purpose, token_digest, key_version, issued_at, "
            "expires_at, status, delivery_status, consumed_at, invalidated_at"
            ") VALUES ("
            ":account_id, 'email_change', :token_digest, 'v1', :now, :expires_at, "
            "'active', 'pending', NULL, NULL)"
        ),
        {
            "account_id": account_id,
            "token_digest": token_digest,
            "now": NOW,
            "expires_at": NOW + timedelta(minutes=30),
        },
    )
    return "accepted"


def _create_account(engine: Engine, role: str, status: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO admin_accounts (role, status) "
                "VALUES (:role, :status) RETURNING admin_account_id"
            ),
            {"role": role, "status": status},
        ).scalar_one()


def _create_deactivated_staff_accounts(engine: Engine, count: int) -> tuple[int, ...]:
    return tuple(
        _create_account(engine, "staff", "deactivated") for _ in range(count)
    )


def _account_status(engine: Engine, account_id: int) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT status FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).scalar_one()


def _insert_claim_committed(
    engine: Engine, account_id: int, digest: bytes, claim_kind: str
) -> None:
    with engine.begin() as connection:
        result = _insert_email_claim(connection, account_id, digest, claim_kind)
        assert result == "accepted"


def _insert_active_session(
    engine: Engine, account_id: int, session_digest: bytes, csrf_digest: bytes
) -> None:
    with engine.begin() as connection:
        assert _replace_session(
            connection, account_id, session_digest, csrf_digest
        ) == "accepted"


def _insert_totp_factor(engine: Engine, account_id: int) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO totp_factors ("
                "admin_account_id, totp_secret_ciphertext, key_version, algorithm, "
                "digits, period_seconds, status, confirmed_at, invalidated_at"
                ") VALUES ("
                ":account_id, :ciphertext, 'v1', 'SHA1', 6, 30, 'active', :now, NULL"
                ") RETURNING totp_factor_id"
            ),
            {
                "account_id": account_id,
                "ciphertext": b"protected-totp-fixture",
                "now": NOW,
            },
        ).scalar_one()


def _insert_recovery_code(
    engine: Engine, account_id: int, digest: bytes, position: int
) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO recovery_codes ("
                "admin_account_id, lookup_digest, key_version, position, status, "
                "used_at, invalidated_at"
                ") VALUES ("
                ":account_id, :digest, 'v1', :position, 'active', NULL, NULL"
                ") RETURNING recovery_code_id"
            ),
            {"account_id": account_id, "digest": digest, "position": position},
        ).scalar_one()


def _consume_recovery_code_by_digest(
    engine: Engine, account_id: int, digest: bytes
) -> str:
    with engine.begin() as connection:
        consumed_id = connection.execute(
            text(
                "UPDATE recovery_codes SET status = 'used', used_at = :now "
                "WHERE admin_account_id = :account_id "
                "AND lookup_digest = :digest AND status = 'active' "
                "RETURNING recovery_code_id"
            ),
            {"now": NOW, "account_id": account_id, "digest": digest},
        ).scalar_one_or_none()
    return "consumed" if consumed_id is not None else "unchanged"


def _recovery_code_status(engine: Engine, recovery_code_id: int) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT status FROM recovery_codes "
                "WHERE recovery_code_id = :recovery_code_id"
            ),
            {"recovery_code_id": recovery_code_id},
        ).scalar_one()


def _delete_accounts(engine: Engine, account_ids: list[int]) -> None:
    if not account_ids:
        return
    with engine.begin() as connection:
        for account_id in account_ids:
            connection.execute(
                text(
                    "DELETE FROM admin_accounts "
                    "WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            )


def _reset_admin_fixture_state(engine: Engine) -> None:
    """Reset only the dedicated test database's administrative fixture state."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE admin_accounts, owner_bootstrap_state "
                "RESTART IDENTITY CASCADE"
            )
        )
        connection.execute(
            text(
                "INSERT INTO owner_bootstrap_state (bootstrap_state_id, status) "
                "VALUES (1, 'open')"
            )
        )

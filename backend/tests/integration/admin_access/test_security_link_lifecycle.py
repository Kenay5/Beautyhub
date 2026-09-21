"""T027 PostgreSQL evidence for replacement, expiry and atomic link consumption."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2032, 4, 5, 16, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


def _protector() -> SecurityLinkProtector:
    return SecurityLinkProtector(
        key_ring=CryptographyKeyRing(
            CryptographyKeyConfiguration(
                root_key=SecretValue(
                    base64.urlsafe_b64encode(b"\x79" * 32).decode("ascii")
                ),
                key_version="v1",
            )
        )
    )


def _create_account(engine: Engine) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO admin_accounts (role, status) "
                "VALUES ('staff', 'deactivated') RETURNING admin_account_id"
            )
        ).scalar_one()


def _delete_account(engine: Engine, account_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM admin_accounts WHERE admin_account_id = :account_id"),
            {"account_id": account_id},
        )


def _delete_test_links(engine: Engine, *tokens: bytes) -> None:
    protector = _protector()
    with engine.begin() as connection:
        for token in tokens:
            connection.execute(
                text("DELETE FROM security_links WHERE token_digest = :digest"),
                {"digest": protector.digest(token)},
            )


@pytest.mark.integration
def test_t027_postgres_replaces_and_expires_links_without_plain_tokens(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    first_token = b"\x7a" * 32
    second_token = b"\x7b" * 32
    _delete_test_links(migrated_engine, first_token, second_token)
    try:
        with migrated_engine.begin() as connection:
            first = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((first_token,)),
                protector=_protector(),
            ).issue(account_id=account_id, purpose="email_change")

        replacement_time = NOW + timedelta(minutes=5)
        with migrated_engine.begin() as connection:
            lifecycle = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(replacement_time),
                secret_generator=SequenceSecretGenerator((second_token,)),
                protector=_protector(),
            )
            second = lifecycle.issue(account_id=account_id, purpose="email_change")
            assert lifecycle.inspect(
                token=first.token, purpose="email_change"
            ) is None

        with migrated_engine.begin() as connection:
            at_expiry = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(second.stored_link.expires_at),
                secret_generator=SequenceSecretGenerator(()),
                protector=_protector(),
            )
            assert at_expiry.consume(
                token=second.token, purpose="email_change"
            ) is None

        with migrated_engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT token_digest, status FROM security_links "
                    "WHERE admin_account_id = :account_id ORDER BY security_link_id"
                ),
                {"account_id": account_id},
            ).all()
        assert [row.status for row in rows] == ["invalidated", "expired"]
        assert all(row.token_digest not in {first_token, second_token} for row in rows)
    finally:
        _delete_test_links(migrated_engine, first_token, second_token)
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t027_postgres_allows_only_one_concurrent_consumption(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    token = b"\x7c" * 32
    _delete_test_links(migrated_engine, token)
    try:
        with migrated_engine.begin() as connection:
            issued = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((token,)),
                protector=_protector(),
            ).issue(account_id=account_id, purpose="password_recovery")

        barrier = Barrier(2)

        def consume() -> bool:
            with migrated_engine.begin() as connection:
                lifecycle = SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=FixedClock(NOW + timedelta(minutes=1)),
                    secret_generator=SequenceSecretGenerator(()),
                    protector=_protector(),
                )
                barrier.wait()
                return lifecycle.consume(
                    token=issued.token, purpose="password_recovery"
                ) is not None

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(lambda _: consume(), range(2)))

        assert sorted(outcomes) == [False, True]
        with migrated_engine.connect() as connection:
            status = connection.execute(
                text(
                    "SELECT status FROM security_links "
                    "WHERE security_link_id = :link_id"
                ),
                {"link_id": issued.stored_link.link_id},
            ).scalar_one()
        assert status == "consumed"
    finally:
        _delete_test_links(migrated_engine, token)
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t027_failed_replacement_rolls_back_without_partial_invalidation(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    token = b"\x7d" * 32
    _delete_test_links(migrated_engine, token)
    try:
        with migrated_engine.begin() as connection:
            issued = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((token,)),
                protector=_protector(),
            ).issue(account_id=account_id, purpose="initial_activation")

        with pytest.raises(DBAPIError):
            with migrated_engine.begin() as connection:
                SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=FixedClock(NOW + timedelta(minutes=1)),
                    secret_generator=SequenceSecretGenerator((token,)),
                    protector=_protector(),
                ).issue(account_id=account_id, purpose="initial_activation")

        with migrated_engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT security_link_id, status FROM security_links "
                    "WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).all()
        assert rows == [(issued.stored_link.link_id, "active")]
    finally:
        _delete_test_links(migrated_engine, token)
        _delete_account(migrated_engine, account_id)

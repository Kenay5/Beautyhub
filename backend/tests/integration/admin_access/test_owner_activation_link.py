"""T032 PostgreSQL evidence for initial owner-activation link delivery states."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from backend.app.application.admin_access.owner_activation_link import (
    DeliverOwnerActivationLink,
    PrepareOwnerActivationLink,
)
from backend.app.application.admin_access.owner_bootstrap import RegisterOwnerBootstrap
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.owner_activation_link_repository import (
    PostgresOwnerActivationRecipientStore,
)
from backend.app.infrastructure.persistence.owner_bootstrap_repository import (
    PostgresOwnerBootstrapRegistrationStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
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
NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)


@pytest.fixture()
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
        _reset_admin_fixture_state(engine)
        engine.dispose()


def _reset_admin_fixture_state(engine: Engine) -> None:
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


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x61" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _email_protector(nonce: bytes) -> AdministrativeEmailProtector:
    return AdministrativeEmailProtector(
        key_ring=_key_ring(),
        secret_generator=SequenceSecretGenerator([nonce]),
    )


def _register_owner(engine: Engine) -> None:
    with engine.begin() as connection:
        RegisterOwnerBootstrap(
            store=PostgresOwnerBootstrapRegistrationStore(connection),
            email_protector=_email_protector(b"\x62" * 12),
        ).register(email="synthetic.owner@example.test")


def _prepare(engine: Engine, token: bytes):
    with engine.begin() as connection:
        key_ring = _key_ring()
        return PrepareOwnerActivationLink(
            recipient_store=PostgresOwnerActivationRecipientStore(
                connection,
                email_protector=_email_protector(b"\x63" * 12),
            ),
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator([token]),
                protector=SecurityLinkProtector(key_ring=key_ring),
            ),
        ).prepare()


def _deliver(engine: Engine, prepared, outcome: str) -> bool:
    with engine.begin() as connection:
        return DeliverOwnerActivationLink(
            delivery_state_store=PostgresSecurityLinkStore(connection),
            email_sender=EmailSimulator(outcome=outcome),  # type: ignore[arg-type]
            clock=FixedClock(NOW),
        ).deliver(
            prepared_link=prepared,
            content="/admin/security-link#token=opaque-test-token",
        )


@pytest.mark.integration
def test_t032_keeps_only_one_accepted_initial_link_for_the_inactive_owner(
    migrated_engine: Engine,
) -> None:
    _register_owner(migrated_engine)
    first = _prepare(migrated_engine, b"\x64" * 32)
    _deliver(migrated_engine, first, "accepted")
    replacement = _prepare(migrated_engine, b"\x65" * 32)
    _deliver(migrated_engine, replacement, "accepted")

    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT status, delivery_status, expires_at - issued_at "
                "FROM security_links ORDER BY security_link_id"
            )
        ).all()

    assert [(row.status, row.delivery_status) for row in rows] == [
        ("invalidated", "accepted"),
        ("active", "accepted"),
    ]
    assert all(row[2] == timedelta(minutes=30) for row in rows)
    assert first.issued_link.token != replacement.issued_link.token


@pytest.mark.integration
def test_t032_invalidates_failed_link_keeps_owner_inactive_and_allows_reissue(
    migrated_engine: Engine,
) -> None:
    _register_owner(migrated_engine)
    failed = _prepare(migrated_engine, b"\x66" * 32)

    assert not _deliver(migrated_engine, failed, "failed")

    replacement = _prepare(migrated_engine, b"\x67" * 32)

    with migrated_engine.connect() as connection:
        account_status = connection.execute(
            text("SELECT status FROM admin_accounts WHERE role = 'owner'")
        ).scalar_one()
        rows = connection.execute(
            text(
                "SELECT status, delivery_status FROM security_links "
                "ORDER BY security_link_id"
            )
        ).all()

    assert account_status == "inactive"
    assert [(row.status, row.delivery_status) for row in rows] == [
        ("invalidated", "failed"),
        ("active", "pending"),
    ]
    assert failed.issued_link.token != replacement.issued_link.token


@pytest.mark.integration
def test_t097_uncertain_link_is_not_inspectable_or_consumable(migrated_engine: Engine) -> None:
    _register_owner(migrated_engine)
    prepared = _prepare(migrated_engine, b"\x68" * 32)
    assert not _deliver(migrated_engine, prepared, "uncertain")

    with migrated_engine.begin() as connection:
        lifecycle = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator([b"\x69" * 32]),
            protector=SecurityLinkProtector(key_ring=_key_ring()),
        )
        assert lifecycle.inspect(
            token=prepared.issued_link.token, purpose="initial_activation"
        ) is None
        assert lifecycle.consume(
            token=prepared.issued_link.token, purpose="initial_activation"
        ) is None
    with migrated_engine.connect() as connection:
        assert connection.execute(
            text("SELECT status, delivery_status FROM security_links")
        ).one() == ("active", "uncertain")
        assert connection.execute(
            text("SELECT status FROM admin_accounts WHERE role = 'owner'")
        ).scalar_one() == "inactive"


@pytest.mark.integration
def test_t097_late_failure_invalidates_accepted_link_idempotently(
    migrated_engine: Engine,
) -> None:
    _register_owner(migrated_engine)
    prepared = _prepare(migrated_engine, b"\x6a" * 32)
    assert _deliver(migrated_engine, prepared, "accepted")
    with migrated_engine.begin() as connection:
        PostgresSecurityLinkStore(connection).invalidate_failed_delivery(
            link_id=prepared.issued_link.stored_link.link_id,
            current_time=NOW + timedelta(seconds=20),
        )
    with migrated_engine.begin() as connection:
        PostgresSecurityLinkStore(connection).invalidate_failed_delivery(
            link_id=prepared.issued_link.stored_link.link_id,
            current_time=NOW + timedelta(seconds=30),
        )
    with migrated_engine.connect() as connection:
        assert connection.execute(
            text("SELECT status, delivery_status, invalidated_at FROM security_links")
        ).one() == ("invalidated", "failed", NOW + timedelta(seconds=20))


@pytest.mark.integration
def test_t097_late_provider_results_cannot_change_a_replacement(
    migrated_engine: Engine,
) -> None:
    _register_owner(migrated_engine)
    first = _prepare(migrated_engine, b"\x6b" * 32)
    assert _deliver(migrated_engine, first, "accepted")
    second = _prepare(migrated_engine, b"\x6c" * 32)
    assert _deliver(migrated_engine, second, "accepted")

    with migrated_engine.begin() as connection:
        links = PostgresSecurityLinkStore(connection)
        links.invalidate_failed_delivery(
            link_id=first.issued_link.stored_link.link_id,
            current_time=NOW + timedelta(seconds=40),
        )
        links.mark_delivery_accepted(
            link_id=first.issued_link.stored_link.link_id,
            current_time=NOW + timedelta(seconds=41),
        )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT status, delivery_status FROM security_links ORDER BY security_link_id")
        ).all()
    assert rows == [("invalidated", "accepted"), ("active", "accepted")]

"""T031 PostgreSQL evidence for atomic owner bootstrap registration."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from backend.app.application.admin_access.owner_bootstrap import RegisterOwnerBootstrap
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.owner_bootstrap_repository import (
    OwnerBootstrapRegistrationError,
    PostgresOwnerBootstrapRegistrationStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


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
    """Restore the shared test database to its migrated bootstrap baseline."""

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


def _register(engine: Engine, email: str, entropy_marker: int) -> None:
    key_configuration = CryptographyKeyConfiguration(
        root_key=SecretValue(
            base64.urlsafe_b64encode(b"\x41" * 32).decode("ascii")
        ),
        key_version="v1",
    )
    with engine.begin() as connection:
        RegisterOwnerBootstrap(
            store=PostgresOwnerBootstrapRegistrationStore(connection),
            email_protector=AdministrativeEmailProtector(
                key_ring=CryptographyKeyRing(key_configuration),
                secret_generator=SequenceSecretGenerator([bytes([entropy_marker]) * 12]),
            ),
        ).register(email=email)


@pytest.mark.integration
def test_t031_creates_one_inactive_owner_and_protected_current_email_claim(
    migrated_engine: Engine,
) -> None:
    _register(migrated_engine, "  Synthetic.Owner@Example.TEST ", 0x42)

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text("SELECT role, status FROM admin_accounts")
        ).one()._tuple()
        claim = connection.execute(
            text(
                "SELECT lookup_digest, email_ciphertext, key_version "
                "FROM admin_email_claims"
            )
        ).one()._tuple()
        bootstrap = connection.execute(
            text(
                "SELECT status, owner_account_id FROM owner_bootstrap_state "
                "WHERE bootstrap_state_id = 1"
            )
        ).one()._tuple()

    assert account == ("owner", "inactive")
    assert len(claim[0]) == 32
    assert b"synthetic.owner@example.test" not in claim[1]
    assert claim[2] == "v1"
    assert bootstrap == ("open", None)


@pytest.mark.integration
def test_t031_rejects_a_second_registration_without_a_partial_account(
    migrated_engine: Engine,
) -> None:
    _register(migrated_engine, "synthetic.owner@example.test", 0x43)

    with pytest.raises(OwnerBootstrapRegistrationError):
        _register(migrated_engine, "other.owner@example.test", 0x44)

    with migrated_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM admin_accounts")).scalar_one() == 1
        assert connection.execute(
            text("SELECT count(*) FROM admin_email_claims")
        ).scalar_one() == 1

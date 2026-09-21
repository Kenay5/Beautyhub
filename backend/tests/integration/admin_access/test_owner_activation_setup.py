"""T033 PostgreSQL evidence for reversible owner activation preparation."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, text

from backend.app.application.admin_access.owner_activation_setup import (
    AbandonOwnerActivationSetup,
    PrepareOwnerActivationSetup,
)
from backend.app.application.admin_access.pending_security_state import (
    DiscardPendingSecurityState,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import AdminAccount
from backend.app.infrastructure.persistence.pending_security_state_repository import (
    PostgresPendingSecurityStateStore,
)
from backend.app.infrastructure.persistence.pending_totp_setup_repository import (
    PostgresPendingTotpSetupStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)
TOKEN = b"\x81" * 32


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
            root_key=SecretValue(base64.urlsafe_b64encode(b"\x82" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _lifecycle(connection) -> SecurityLinkLifecycle:
    return SecurityLinkLifecycle(
        store=PostgresSecurityLinkStore(connection),
        clock=FixedClock(NOW),
        secret_generator=SequenceSecretGenerator((TOKEN,)),
        protector=SecurityLinkProtector(key_ring=_key_ring()),
    )


def _seed_inactive_owner_link(engine: Engine) -> int:
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(role="owner", status="inactive")
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        issued = _lifecycle(connection).issue(
            account_id=account_id,
            purpose="initial_activation",
        )
        PostgresSecurityLinkStore(connection).mark_delivery_accepted(
            link_id=issued.stored_link.link_id,
            current_time=NOW,
        )
    return account_id


def _prepare(engine: Engine, *, secret_entropy: bytes, nonce: bytes):
    with engine.begin() as connection:
        return PrepareOwnerActivationSetup(
            link_lifecycle=_lifecycle(connection),
            setup_store=PostgresPendingTotpSetupStore(connection),
            totp=TotpAuthenticator(
                secret_generator=SequenceSecretGenerator((secret_entropy,))
            ),
            protector=PendingTotpProtector(
                key_ring=_key_ring(),
                secret_generator=SequenceSecretGenerator((nonce,)),
            ),
            clock=FixedClock(NOW),
        ).prepare(token=TOKEN)


@pytest.mark.integration
def test_t033_preparation_keeps_owner_and_link_inactive_and_unconsumed(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_inactive_owner_link(migrated_engine)

    first = _prepare(
        migrated_engine,
        secret_entropy=b"\x83" * 20,
        nonce=b"\x84" * 12,
    )
    second = _prepare(
        migrated_engine,
        secret_entropy=b"\x85" * 20,
        nonce=b"\x86" * 12,
    )

    with migrated_engine.connect() as connection:
        account_status = connection.execute(
            text("SELECT status FROM admin_accounts WHERE admin_account_id = :account_id"),
            {"account_id": account_id},
        ).scalar_one()
        link_state = connection.execute(
            text(
                "SELECT status, consumed_at FROM security_links "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        setup = connection.execute(
            text(
                "SELECT status, totp_secret_ciphertext, key_version "
                "FROM pending_security_setups WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        totp_factor_count = connection.execute(
            text("SELECT count(*) FROM totp_factors WHERE admin_account_id = :account_id"),
            {"account_id": account_id},
        ).scalar_one()
        recovery_code_count = connection.execute(
            text("SELECT count(*) FROM recovery_codes WHERE admin_account_id = :account_id"),
            {"account_id": account_id},
        ).scalar_one()

    assert first.manual_key == second.manual_key
    assert account_status == "inactive"
    assert (link_state.status, link_state.consumed_at) == ("active", None)
    assert setup.status == "pending"
    assert setup.key_version == "v1"
    assert first.manual_key.encode("ascii") not in setup.totp_secret_ciphertext
    assert totp_factor_count == 0
    assert recovery_code_count == 0


@pytest.mark.integration
def test_t033_abandon_erases_pending_secret_without_consuming_the_valid_link(
    migrated_engine: Engine,
) -> None:
    account_id = _seed_inactive_owner_link(migrated_engine)
    _prepare(
        migrated_engine,
        secret_entropy=b"\x87" * 20,
        nonce=b"\x88" * 12,
    )

    with migrated_engine.begin() as connection:
        AbandonOwnerActivationSetup(
            link_lifecycle=_lifecycle(connection),
            pending_state=DiscardPendingSecurityState(
                store=PostgresPendingSecurityStateStore(connection),
                clock=FixedClock(NOW),
            ),
        ).abandon(token=TOKEN)

    with migrated_engine.connect() as connection:
        account_status = connection.execute(
            text("SELECT status FROM admin_accounts WHERE admin_account_id = :account_id"),
            {"account_id": account_id},
        ).scalar_one()
        link_status = connection.execute(
            text(
                "SELECT status FROM security_links "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).scalar_one()
        setup = connection.execute(
            text(
                "SELECT status, totp_secret_ciphertext, key_version "
                "FROM pending_security_setups WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()

    assert account_status == "inactive"
    assert link_status == "active"
    assert (setup.status, setup.totp_secret_ciphertext, setup.key_version) == (
        "invalidated",
        None,
        None,
    )

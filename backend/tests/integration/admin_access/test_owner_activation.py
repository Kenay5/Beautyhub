"""T034 PostgreSQL and concurrency evidence for atomic owner activation."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, text

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.owner_activation import CompleteOwnerActivation
from backend.app.application.admin_access.owner_activation_setup import PrepareOwnerActivationSetup
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import AdminAccount
from backend.app.infrastructure.persistence.owner_activation_repository import (
    PostgresOwnerActivationStore,
)
from backend.app.infrastructure.persistence.pending_totp_setup_repository import (
    PostgresPendingTotpSetupStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2033, 4, 5, 14, tzinfo=timezone.utc)
TOKEN = b"\xa1" * 32
PASSWORD = "synthetic owner phrase 2033"


class AllowedPasswords:
    def contains(self, password: str) -> bool:
        assert password == PASSWORD
        return False


class FailingAuditStore:
    def append(self, *, event) -> None:
        del event
        raise RuntimeError("synthetic audit failure")


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
            root_key=SecretValue(base64.urlsafe_b64encode(b"\xa2" * 32).decode("ascii")),
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


def _seed_prepared_activation(engine: Engine) -> tuple[int, str]:
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
    with engine.begin() as connection:
        prepared = PrepareOwnerActivationSetup(
            link_lifecycle=_lifecycle(connection),
            setup_store=PostgresPendingTotpSetupStore(connection),
            totp=TotpAuthenticator(
                secret_generator=SequenceSecretGenerator((b"\xa3" * 20,))
            ),
            protector=PendingTotpProtector(
                key_ring=_key_ring(),
                secret_generator=SequenceSecretGenerator((b"\xa4" * 12,)),
            ),
            clock=FixedClock(NOW),
        ).prepare(token=TOKEN)
    return account_id, prepared.manual_key


def _completer(connection, *, audit_store=None) -> CompleteOwnerActivation:
    key_ring = _key_ring()
    return CompleteOwnerActivation(
        link_lifecycle=_lifecycle(connection),
        store=PostgresOwnerActivationStore(connection),
        blocked_passwords=AllowedPasswords(),
        password_hasher=AdministrativePasswordHasher(),
        pending_totp_protector=PendingTotpProtector(
            key_ring=key_ring,
            secret_generator=SystemSecretGenerator(),
        ),
        factor_protector=TotpFactorProtector(
            key_ring=key_ring,
            secret_generator=SystemSecretGenerator(),
        ),
        totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),
        recovery_codes=RecoveryCodeService(
            secret_generator=SystemSecretGenerator(),
            protector=RecoveryCodeProtector(key_ring=key_ring),
        ),
        audit=RecordAdministrativeAuditEvent(
            store=audit_store or PostgresAdministrativeAuditStore(connection),
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


def _totp_code(manual_key: str) -> str:
    return pyotp.TOTP(manual_key, digits=6, interval=30).at(NOW)


@pytest.mark.integration
def test_t034_commits_credentials_factor_codes_link_bootstrap_and_audit_together(
    migrated_engine: Engine,
) -> None:
    account_id, manual_key = _seed_prepared_activation(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _completer(connection).complete(
            token=TOKEN,
            password=PASSWORD,
            totp_code=_totp_code(manual_key),
        )

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        link = connection.execute(
            text("SELECT status, consumed_at FROM security_links")
        ).one()
        setup = connection.execute(
            text(
                "SELECT status, totp_secret_ciphertext, key_version "
                "FROM pending_security_setups"
            )
        ).one()
        bootstrap = connection.execute(
            text("SELECT status, owner_account_id, closed_at FROM owner_bootstrap_state")
        ).one()
        counts = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in (
                "totp_factors",
                "totp_period_uses",
                "recovery_codes",
                "admin_audit_events",
                "admin_sessions",
            )
        }
        stored_digests = connection.execute(
            text("SELECT lookup_digest FROM recovery_codes ORDER BY position")
        ).scalars().all()

    assert outcome.activated
    assert len(outcome.recovery_codes) == 10
    assert account.status == "active"
    assert account.password_hash != PASSWORD
    assert AdministrativePasswordHasher().verify_and_upgrade(
        stored_hash=account.password_hash,
        password=PASSWORD,
    ).verified
    assert link.status == "consumed" and link.consumed_at == NOW
    assert (setup.status, setup.totp_secret_ciphertext, setup.key_version) == (
        "confirmed",
        None,
        None,
    )
    assert (bootstrap.status, bootstrap.owner_account_id, bootstrap.closed_at) == (
        "closed",
        account_id,
        NOW,
    )
    assert counts == {
        "totp_factors": 1,
        "totp_period_uses": 1,
        "recovery_codes": 10,
        "admin_audit_events": 1,
        "admin_sessions": 0,
    }
    protector = RecoveryCodeProtector(key_ring=_key_ring())
    assert [protector.digest(code.replace("-", "")) for code in outcome.recovery_codes] == stored_digests


@pytest.mark.integration
def test_t034_bad_totp_discards_setup_and_leaves_no_partial_activation(
    migrated_engine: Engine,
) -> None:
    account_id, manual_key = _seed_prepared_activation(migrated_engine)
    valid_code = _totp_code(manual_key)
    invalid_code = ("1" if valid_code[0] != "1" else "2") + valid_code[1:]
    with migrated_engine.begin() as connection:
        outcome = _completer(connection).complete(
            token=TOKEN,
            password=PASSWORD,
            totp_code=invalid_code,
        )

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        setup = connection.execute(
            text(
                "SELECT status, totp_secret_ciphertext, key_version "
                "FROM pending_security_setups"
            )
        ).one()
        link_status = connection.execute(text("SELECT status FROM security_links")).scalar_one()
        bootstrap_status = connection.execute(
            text("SELECT status FROM owner_bootstrap_state")
        ).scalar_one()
        side_effect_count = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM totp_factors) + "
                "(SELECT count(*) FROM recovery_codes) + "
                "(SELECT count(*) FROM admin_audit_events) + "
                "(SELECT count(*) FROM admin_sessions)"
            )
        ).scalar_one()

    assert outcome.rejection == "unavailable"
    assert (account.status, account.password_hash) == ("inactive", None)
    assert (setup.status, setup.totp_secret_ciphertext, setup.key_version) == (
        "invalidated",
        None,
        None,
    )
    assert link_status == "active"
    assert bootstrap_status == "open"
    assert side_effect_count == 0


@pytest.mark.integration
def test_t034_audit_failure_rolls_back_every_activation_write(
    migrated_engine: Engine,
) -> None:
    account_id, manual_key = _seed_prepared_activation(migrated_engine)

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        with migrated_engine.begin() as connection:
            _completer(connection, audit_store=FailingAuditStore()).complete(
                token=TOKEN,
                password=PASSWORD,
                totp_code=_totp_code(manual_key),
            )

    with migrated_engine.connect() as connection:
        account = connection.execute(
            text(
                "SELECT status, password_hash FROM admin_accounts "
                "WHERE admin_account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        states = connection.execute(
            text(
                "SELECT "
                "(SELECT status FROM security_links), "
                "(SELECT status FROM pending_security_setups), "
                "(SELECT status FROM owner_bootstrap_state), "
                "(SELECT count(*) FROM totp_factors), "
                "(SELECT count(*) FROM recovery_codes)"
            )
        ).one()

    assert (account.status, account.password_hash) == ("inactive", None)
    assert tuple(states) == ("active", "pending", "open", 0, 0)


@pytest.mark.integration
def test_t034_two_concurrent_activations_allow_exactly_one_complete_winner(
    migrated_engine: Engine,
) -> None:
    account_id, manual_key = _seed_prepared_activation(migrated_engine)
    code = _totp_code(manual_key)
    barrier = Barrier(2)

    def activate():
        barrier.wait(timeout=10)
        with migrated_engine.begin() as connection:
            return _completer(connection).complete(
                token=TOKEN,
                password=PASSWORD,
                totp_code=code,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: activate(), range(2)))

    with migrated_engine.connect() as connection:
        final_state = connection.execute(
            text(
                "SELECT "
                "(SELECT status FROM admin_accounts WHERE admin_account_id = :account_id), "
                "(SELECT status FROM security_links), "
                "(SELECT status FROM owner_bootstrap_state), "
                "(SELECT count(*) FROM totp_factors), "
                "(SELECT count(*) FROM recovery_codes), "
                "(SELECT count(*) FROM admin_audit_events), "
                "(SELECT count(*) FROM admin_sessions)"
            ),
            {"account_id": account_id},
        ).one()

    assert sum(outcome.activated for outcome in outcomes) == 1
    assert sum(outcome.rejection == "unavailable" for outcome in outcomes) == 1
    assert tuple(final_state) == ("active", "consumed", "closed", 1, 10, 1, 0)

"""T029 PostgreSQL evidence for discarding only incomplete security artifacts."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from backend.app.application.admin_access.pending_security_state import (
    DiscardPendingSecurityState,
)
from backend.app.application.admin_access.security_change_invalidation import (
    InvalidateAfterSecurityChange,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.pending_security_state_repository import (
    PostgresPendingSecurityStateStore,
)
from backend.app.infrastructure.persistence.security_change_invalidation_repository import (
    PostgresSecurityChangeInvalidationStore,
)
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
NOW = datetime(2032, 5, 6, 12, tzinfo=timezone.utc)


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
                    base64.urlsafe_b64encode(b"\x83" * 32).decode("ascii")
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


def _insert_pending_setup(connection, *, account_id: int, flow: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO pending_security_setups (
                admin_account_id, flow, status, totp_secret_ciphertext,
                key_version, created_at, expires_at
            ) VALUES (
                :account_id, :flow, 'pending', :ciphertext,
                'v1', :created_at, :expires_at
            )
            """
        ),
        {
            "account_id": account_id,
            "flow": flow,
            "ciphertext": b"synthetic-encrypted-pending-secret",
            "created_at": NOW,
            "expires_at": NOW + timedelta(minutes=30),
        },
    )


def _insert_active_credentials(connection, *, account_id: int) -> None:
    recovery_digest = _test_digest(account_id, marker=1)
    session_digest = _test_digest(account_id, marker=2)
    csrf_digest = _test_digest(account_id, marker=3)
    connection.execute(
        text(
            """
            INSERT INTO totp_factors (
                admin_account_id, totp_secret_ciphertext, key_version, algorithm,
                digits, period_seconds, status, confirmed_at, invalidated_at
            ) VALUES (
                :account_id, :ciphertext, 'v1', 'SHA1', 6, 30,
                'active', :confirmed_at, NULL
            )
            """
        ),
        {
            "account_id": account_id,
            "ciphertext": b"synthetic-encrypted-active-factor",
            "confirmed_at": NOW - timedelta(days=1),
        },
    )
    connection.execute(
        text(
            """
            INSERT INTO recovery_codes (
                admin_account_id, lookup_digest, key_version, position,
                status, used_at, invalidated_at
            ) VALUES (:account_id, :digest, 'v1', 1, 'active', NULL, NULL)
            """
        ),
        {"account_id": account_id, "digest": recovery_digest},
    )
    connection.execute(
        text(
            """
            INSERT INTO admin_sessions (
                admin_account_id, session_digest, csrf_digest, key_version,
                created_at, last_human_activity_at, absolute_expires_at,
                status, invalidated_at
            ) VALUES (
                :account_id, :session_digest, :csrf_digest, 'v1',
                :created_at, :created_at, :absolute_expires_at, 'active', NULL
            )
            """
        ),
        {
            "account_id": account_id,
            "session_digest": session_digest,
            "csrf_digest": csrf_digest,
            "created_at": NOW - timedelta(minutes=1),
            "absolute_expires_at": NOW + timedelta(hours=7, minutes=59),
        },
    )


def _insert_email_claim(connection, *, account_id: int, kind: str, marker: int) -> None:
    connection.execute(
        text(
            """
            INSERT INTO admin_email_claims (
                admin_account_id, claim_kind, lookup_digest, email_ciphertext, key_version
            ) VALUES (:account_id, :kind, :digest, :ciphertext, 'v1')
            """
        ),
        {
            "account_id": account_id,
            "kind": kind,
            "digest": _test_digest(account_id, marker=marker),
            "ciphertext": f"synthetic-email-{marker}".encode(),
        },
    )


def _test_digest(account_id: int, *, marker: int) -> bytes:
    return bytes((marker,)) + account_id.to_bytes(31, byteorder="big")


@pytest.mark.integration
def test_t029_expiry_and_replacement_discard_only_the_matching_pending_totp_setup(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    first_token = _test_digest(account_id, marker=132)
    second_token = _test_digest(account_id, marker=133)
    third_token = _test_digest(account_id, marker=134)
    try:
        with migrated_engine.begin() as connection:
            lifecycle = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((first_token,)),
                protector=_protector(),
            )
            first = lifecycle.issue(account_id=account_id, purpose="totp_replacement")
            _insert_pending_setup(
                connection, account_id=account_id, flow="totp_replacement"
            )
            _insert_active_credentials(connection, account_id=account_id)

        with migrated_engine.begin() as connection:
            at_expiry = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(first.stored_link.expires_at),
                secret_generator=SequenceSecretGenerator(()),
                protector=_protector(),
            )
            assert at_expiry.inspect(
                token=first_token, purpose="totp_replacement"
            ) is None

        with migrated_engine.connect() as connection:
            expired_setup = connection.execute(
                text(
                    "SELECT status, totp_secret_ciphertext, key_version "
                    "FROM pending_security_setups WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).one()
            credential_states = connection.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM totp_factors WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM recovery_codes WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM admin_sessions WHERE admin_account_id = :account_id)"
                ),
                {"account_id": account_id},
            ).one()
        assert expired_setup == ("expired", None, None)
        assert credential_states == ("active", "active", "active")

        with migrated_engine.begin() as connection:
            lifecycle = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=31)),
                secret_generator=SequenceSecretGenerator((second_token,)),
                protector=_protector(),
            )
            lifecycle.issue(account_id=account_id, purpose="totp_replacement")
            _insert_pending_setup(
                connection, account_id=account_id, flow="totp_replacement"
            )
            SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=32)),
                secret_generator=SequenceSecretGenerator((third_token,)),
                protector=_protector(),
            ).issue(account_id=account_id, purpose="totp_replacement")

        with migrated_engine.connect() as connection:
            replaced_setup = connection.execute(
                text(
                    "SELECT status, totp_secret_ciphertext, key_version "
                    "FROM pending_security_setups WHERE admin_account_id = :account_id "
                    "ORDER BY pending_security_setup_id DESC LIMIT 1"
                ),
                {"account_id": account_id},
            ).one()
        assert replaced_setup == ("invalidated", None, None)
    finally:
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t029_general_invalidation_preserves_current_identity_and_active_credentials(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    try:
        with migrated_engine.begin() as connection:
            _insert_active_credentials(connection, account_id=account_id)
            _insert_pending_setup(
                connection, account_id=account_id, flow="owner_activation"
            )
            _insert_pending_setup(
                connection, account_id=account_id, flow="staff_activation"
            )
            _insert_pending_setup(
                connection, account_id=account_id, flow="totp_replacement"
            )
            _insert_email_claim(connection, account_id=account_id, kind="current", marker=94)
            _insert_email_claim(connection, account_id=account_id, kind="reserved", marker=95)
            for purpose, marker in (("password_recovery", 96), ("email_change", 97)):
                connection.execute(
                    text(
                        """
                        INSERT INTO security_links (
                            admin_account_id, purpose, token_digest, key_version,
                            issued_at, expires_at, status, delivery_status,
                            consumed_at, invalidated_at
                        ) VALUES (
                            :account_id, :purpose, :digest, 'v1',
                            :issued_at, :expires_at, 'active', 'accepted', NULL, NULL
                        )
                        """
                    ),
                    {
                        "account_id": account_id,
                        "purpose": purpose,
                        "digest": _test_digest(account_id, marker=marker),
                        "issued_at": NOW,
                        "expires_at": NOW + timedelta(minutes=30),
                    },
                )

            DiscardPendingSecurityState(
                store=PostgresPendingSecurityStateStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=1)),
            ).completed_security_change(account_id=account_id)

        with migrated_engine.connect() as connection:
            link_states = connection.execute(
                text(
                    "SELECT status FROM security_links WHERE admin_account_id = :account_id "
                    "ORDER BY security_link_id"
                ),
                {"account_id": account_id},
            ).scalars().all()
            setup_states = connection.execute(
                text(
                    "SELECT status, totp_secret_ciphertext, key_version "
                    "FROM pending_security_setups WHERE admin_account_id = :account_id "
                    "ORDER BY flow"
                ),
                {"account_id": account_id},
            ).all()
            claim_kinds = connection.execute(
                text(
                    "SELECT claim_kind FROM admin_email_claims "
                    "WHERE admin_account_id = :account_id ORDER BY claim_kind"
                ),
                {"account_id": account_id},
            ).scalars().all()
            credential_states = connection.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM totp_factors WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM recovery_codes WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM admin_sessions WHERE admin_account_id = :account_id)"
                ),
                {"account_id": account_id},
            ).one()
        assert link_states == ["invalidated", "invalidated"]
        assert setup_states == [
            ("invalidated", None, None),
            ("invalidated", None, None),
            ("invalidated", None, None),
        ]
        assert claim_kinds == ["current"]
        assert credential_states == ("active", "active", "active")
    finally:
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t029_email_link_cleanup_releases_only_the_pending_reservation(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    try:
        with migrated_engine.begin() as connection:
            _insert_active_credentials(connection, account_id=account_id)
            _insert_email_claim(connection, account_id=account_id, kind="current", marker=98)
            _insert_email_claim(connection, account_id=account_id, kind="reserved", marker=99)
            cleanup = DiscardPendingSecurityState(
                store=PostgresPendingSecurityStateStore(connection),
                clock=FixedClock(NOW),
            )
            cleanup.replaced_link(account_id=account_id, purpose="email_change")

        with migrated_engine.connect() as connection:
            claim_kinds = connection.execute(
                text(
                    "SELECT claim_kind FROM admin_email_claims "
                    "WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).scalars().all()
            credential_states = connection.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM totp_factors WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM recovery_codes WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM admin_sessions WHERE admin_account_id = :account_id)"
                ),
                {"account_id": account_id},
            ).one()
        assert claim_kinds == ["current"]
        assert credential_states == ("active", "active", "active")

        with migrated_engine.begin() as connection:
            _insert_email_claim(connection, account_id=account_id, kind="reserved", marker=100)
            DiscardPendingSecurityState(
                store=PostgresPendingSecurityStateStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=30)),
            ).expired_link(account_id=account_id, purpose="email_change")

        with migrated_engine.connect() as connection:
            claim_kinds_after_expiry = connection.execute(
                text(
                    "SELECT claim_kind FROM admin_email_claims "
                    "WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).scalars().all()
        assert claim_kinds_after_expiry == ["current"]
    finally:
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t029_abandoning_setup_discards_only_its_unconfirmed_secret(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    try:
        with migrated_engine.begin() as connection:
            _insert_active_credentials(connection, account_id=account_id)
            _insert_pending_setup(
                connection, account_id=account_id, flow="totp_replacement"
            )
            DiscardPendingSecurityState(
                store=PostgresPendingSecurityStateStore(connection),
                clock=FixedClock(NOW),
            ).abandoned_setup(account_id=account_id, flow="totp_replacement")

        with migrated_engine.connect() as connection:
            setup = connection.execute(
                text(
                    "SELECT status, totp_secret_ciphertext, key_version "
                    "FROM pending_security_setups WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).one()
            credential_states = connection.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM totp_factors WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM recovery_codes WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM admin_sessions WHERE admin_account_id = :account_id)"
                ),
                {"account_id": account_id},
            ).one()
        assert setup == ("invalidated", None, None)
        assert credential_states == ("active", "active", "active")
    finally:
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t029_expired_initial_activation_discards_owner_setup_without_activating_account(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    token = _test_digest(account_id, marker=135)
    try:
        with migrated_engine.begin() as connection:
            issued = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SequenceSecretGenerator((token,)),
                protector=_protector(),
            ).issue(account_id=account_id, purpose="initial_activation")
            _insert_pending_setup(connection, account_id=account_id, flow="owner_activation")

        with migrated_engine.begin() as connection:
            assert SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(issued.stored_link.expires_at),
                secret_generator=SequenceSecretGenerator(()),
                protector=_protector(),
            ).inspect(token=token, purpose="initial_activation") is None

        with migrated_engine.connect() as connection:
            account_status = connection.execute(
                text("SELECT status FROM admin_accounts WHERE admin_account_id = :account_id"),
                {"account_id": account_id},
            ).scalar_one()
            setup = connection.execute(
                text(
                    "SELECT status, totp_secret_ciphertext, key_version "
                    "FROM pending_security_setups WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).one()
        assert account_status == "deactivated"
        assert setup == ("expired", None, None)
    finally:
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t052_security_change_closes_sessions_and_discards_temporary_state(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    invalidated_at = NOW + timedelta(minutes=1)
    try:
        with migrated_engine.begin() as connection:
            _insert_active_credentials(connection, account_id=account_id)
            _insert_pending_setup(
                connection, account_id=account_id, flow="totp_replacement"
            )
            _insert_email_claim(
                connection, account_id=account_id, kind="current", marker=136
            )
            _insert_email_claim(
                connection, account_id=account_id, kind="reserved", marker=137
            )
            connection.execute(
                text(
                    """
                    INSERT INTO security_links (
                        admin_account_id, purpose, token_digest, key_version,
                        issued_at, expires_at, status, delivery_status,
                        consumed_at, invalidated_at
                    ) VALUES (
                        :account_id, 'password_recovery', :digest, 'v1',
                        :issued_at, :expires_at, 'active', 'accepted', NULL, NULL
                    )
                    """
                ),
                {
                    "account_id": account_id,
                    "digest": _test_digest(account_id, marker=138),
                    "issued_at": NOW,
                    "expires_at": NOW + timedelta(minutes=30),
                },
            )

            InvalidateAfterSecurityChange(
                store=PostgresSecurityChangeInvalidationStore(connection),
                clock=FixedClock(invalidated_at),
            ).execute(account_id=account_id)

        with migrated_engine.connect() as connection:
            session = connection.execute(
                text(
                    "SELECT status, invalidated_at FROM admin_sessions "
                    "WHERE admin_account_id = :account_id"
                ),
                {"account_id": account_id},
            ).one()
            link = connection.execute(
                text(
                    "SELECT status, invalidated_at FROM security_links "
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
            claim_kinds = connection.execute(
                text(
                    "SELECT claim_kind FROM admin_email_claims "
                    "WHERE admin_account_id = :account_id ORDER BY claim_kind"
                ),
                {"account_id": account_id},
            ).scalars().all()
            active_credentials = connection.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM totp_factors WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM recovery_codes WHERE admin_account_id = :account_id)"
                ),
                {"account_id": account_id},
            ).one()

        assert session == ("invalidated", invalidated_at)
        assert link == ("invalidated", invalidated_at)
        assert setup == ("invalidated", None, None)
        assert claim_kinds == ["current"]
        assert active_credentials == ("active", "active")
    finally:
        _delete_account(migrated_engine, account_id)


@pytest.mark.integration
def test_t052_invalidation_rolls_back_with_the_security_change_transaction(
    migrated_engine: Engine,
) -> None:
    account_id = _create_account(migrated_engine)
    try:
        with migrated_engine.begin() as connection:
            _insert_active_credentials(connection, account_id=account_id)
            _insert_pending_setup(
                connection, account_id=account_id, flow="totp_replacement"
            )
            _insert_email_claim(
                connection, account_id=account_id, kind="reserved", marker=139
            )

        connection = migrated_engine.connect()
        transaction = connection.begin()
        try:
            InvalidateAfterSecurityChange(
                store=PostgresSecurityChangeInvalidationStore(connection),
                clock=FixedClock(NOW + timedelta(minutes=1)),
            ).execute(account_id=account_id)
        finally:
            transaction.rollback()
            connection.close()

        with migrated_engine.connect() as connection:
            states = connection.execute(
                text(
                    "SELECT "
                    "(SELECT status FROM admin_sessions WHERE admin_account_id = :account_id), "
                    "(SELECT status FROM pending_security_setups "
                    " WHERE admin_account_id = :account_id), "
                    "(SELECT claim_kind FROM admin_email_claims "
                    " WHERE admin_account_id = :account_id)"
                ),
                {"account_id": account_id},
            ).one()

        assert states == ("active", "pending", "reserved")
    finally:
        _delete_account(migrated_engine, account_id)

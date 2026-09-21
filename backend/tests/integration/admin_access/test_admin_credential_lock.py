"""T045 PostgreSQL evidence for exact, auditable credential lock creation."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, insert, select, text

from backend.app.application.admin_access.account_security import (
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import (
    PostgresAdministrativeLockRecipientDirectory,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminEmailClaim,
    SecurityNotificationDelivery,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
OWNER_EMAIL = "synthetic.owner@example.test"
STAFF_EMAIL = "synthetic.staff@example.test"


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
                    "TRUNCATE TABLE security_notification_deliveries, "
                    "admin_audit_events, admin_accounts, owner_bootstrap_state "
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


def _ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(
                base64.urlsafe_b64encode(b"\xf1" * 32).decode("ascii")
            ),
            key_version="v1",
        )
    )


def _seed_accounts(engine: Engine, *, include_staff: bool) -> tuple[int, int | None]:
    ring = _ring()
    owner_email = AdministrativeEmailProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xf2" * 12,)),
    ).protect(OWNER_EMAIL)
    staff_email = AdministrativeEmailProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xf3" * 12,)),
    ).protect(STAFF_EMAIL)
    password_hash = AdministrativePasswordHasher().hash_password(
        "synthetic administrative phrase"
    )
    with engine.begin() as connection:
        owner_id = connection.execute(
            insert(AdminAccount)
            .values(role="owner", status="active", password_hash=password_hash)
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=owner_id,
                claim_kind="current",
                lookup_digest=owner_email.lookup_digest,
                email_ciphertext=owner_email.email_ciphertext,
                key_version=owner_email.key_version,
            )
        )
        staff_id = None
        if include_staff:
            staff_id = connection.execute(
                insert(AdminAccount)
                .values(role="staff", status="active", password_hash=password_hash)
                .returning(AdminAccount.admin_account_id)
            ).scalar_one()
            connection.execute(
                insert(AdminEmailClaim).values(
                    admin_account_id=staff_id,
                    claim_kind="current",
                    lookup_digest=staff_email.lookup_digest,
                    email_ciphertext=staff_email.email_ciphertext,
                    key_version=staff_email.key_version,
                )
            )
    return owner_id, staff_id


def _protected_recorder(connection, *, now: datetime = NOW):
    ring = _ring()
    email_protector = AdministrativeEmailProtector(
        key_ring=ring,
        secret_generator=SystemSecretGenerator(),
    )
    return RecordProtectedAdministrativeCredentialFailure(
        failure_recorder=RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(now),
        ),
        audit=RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=FixedClock(now),
        ),
        notifications=RecordSecurityNotificationDelivery(
            store=PostgresSecurityNotificationDeliveryStore(connection),
            protector=SecurityNotificationDeliveryProtector(
                key_ring=ring,
                secret_generator=SystemSecretGenerator(),
            ),
        ),
        recipients=PostgresAdministrativeLockRecipientDirectory(
            connection=connection,
            email_protector=email_protector,
        ),
    )


@pytest.mark.integration
def test_t045_fifth_staff_failure_sets_exact_lock_and_prepares_required_evidence(
    migrated_engine: Engine,
) -> None:
    _, staff_id = _seed_accounts(migrated_engine, include_staff=True)
    assert staff_id is not None

    with migrated_engine.begin() as connection:
        recorder = _protected_recorder(connection)
        outcomes = tuple(
            recorder.record(account_id=staff_id, operation="login")
            for _ in range(5)
        )

    with migrated_engine.connect() as connection:
        state = connection.execute(
            select(
                AdminAccountSecurityState.lock_until,
                AdminAccountSecurityState.fifth_failure_event_id,
            ).where(AdminAccountSecurityState.admin_account_id == staff_id)
        ).one()
        audits = tuple(
            connection.execute(
                select(
                    AdminAuditEvent.actor_account_id,
                    AdminAuditEvent.action,
                    AdminAuditEvent.result,
                    AdminAuditEvent.target_reference,
                )
            )
        )
        deliveries = tuple(
            connection.execute(
                select(
                    SecurityNotificationDelivery.event,
                    SecurityNotificationDelivery.template,
                    SecurityNotificationDelivery.recipient_ciphertext,
                    SecurityNotificationDelivery.status,
                )
            )
        )

    assert [outcome.failure_count for outcome in outcomes] == [1, 2, 3, 4, 5]
    assert outcomes[-1].started_lock
    assert state.lock_until == NOW + timedelta(minutes=15)
    assert state.fifth_failure_event_id == outcomes[-1].failure_event_id
    assert audits == (
        (staff_id, "account_locked", "succeeded", f"admin_account:{staff_id}"),
    )
    assert len(deliveries) == 2
    assert {(row.event, row.template, row.status) for row in deliveries} == {
        ("account_locked", "account_locked_notice", "pending")
    }
    assert all(OWNER_EMAIL.encode("ascii") not in row.recipient_ciphertext for row in deliveries)
    assert all(STAFF_EMAIL.encode("ascii") not in row.recipient_ciphertext for row in deliveries)


@pytest.mark.integration
def test_t045_exact_window_boundary_does_not_create_a_lock(
    migrated_engine: Engine,
) -> None:
    owner_id, _ = _seed_accounts(migrated_engine, include_staff=False)
    boundary = NOW - timedelta(minutes=15)
    with migrated_engine.begin() as connection:
        old_recorder = RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(boundary),
        )
        for _ in range(4):
            old_recorder.record(account_id=owner_id, operation="login")
        outcome = _protected_recorder(connection).record(
            account_id=owner_id,
            operation="login",
        )

    with migrated_engine.connect() as connection:
        lock_until = connection.execute(
            select(AdminAccountSecurityState.lock_until).where(
                AdminAccountSecurityState.admin_account_id == owner_id
            )
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count()).select_from(AdminAuditEvent)
        ).scalar_one()
        delivery_count = connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one()

    assert outcome.failure_count == 1
    assert lock_until is None
    assert audit_count == 0
    assert delivery_count == 0


@pytest.mark.integration
def test_t045_concurrent_fifth_failure_creates_one_lock_audit_and_notice(
    migrated_engine: Engine,
) -> None:
    owner_id, _ = _seed_accounts(migrated_engine, include_staff=False)
    with migrated_engine.begin() as connection:
        recorder = RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW),
        )
        for _ in range(4):
            recorder.record(account_id=owner_id, operation="login")

    outcomes = _run_concurrently(
        (
            lambda: _record_in_transaction(migrated_engine, owner_id),
            lambda: _record_in_transaction(migrated_engine, owner_id),
        )
    )

    with migrated_engine.connect() as connection:
        failure_count = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()
        state = connection.execute(
            select(AdminAccountSecurityState.lock_until).where(
                AdminAccountSecurityState.admin_account_id == owner_id
            )
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count()).select_from(AdminAuditEvent)
        ).scalar_one()
        delivery_count = connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one()

    assert sorted(outcomes) == ["created", "existing"]
    assert failure_count == 5
    assert state == NOW + timedelta(minutes=15)
    assert audit_count == 1
    assert delivery_count == 1


def _run_concurrently(workers: tuple[Callable[[], str], ...]) -> list[str]:
    barrier = Barrier(len(workers))

    def synchronized(worker: Callable[[], str]) -> str:
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(synchronized, workers))


def _record_in_transaction(engine: Engine, account_id: int) -> str:
    with engine.begin() as connection:
        outcome = _protected_recorder(connection).record(
            account_id=account_id,
            operation="login",
        )
    return "created" if outcome.started_lock else "existing"

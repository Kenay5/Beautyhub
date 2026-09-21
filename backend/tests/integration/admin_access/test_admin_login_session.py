"""T047 PostgreSQL evidence for atomic administrative session replacement."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, insert, select, text, update

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.login_completion import (
    CompleteAdministrativeLoginCredentials,
)
from backend.app.application.admin_access.login_session import (
    CreateAdministrativeLoginSession,
)
from backend.app.application.admin_access.logout import CloseAdministrativeSession
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
    ValidateAdministrativeMutationProtection,
)
from backend.app.application.admin_access.login_validation import (
    ValidateAdministrativeLogin,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_login_completion_repository import (
    PostgresAdministrativeLoginFactorStore,
)
from backend.app.infrastructure.persistence.admin_login_repository import (
    PostgresAdministrativeLoginStore,
)
from backend.app.infrastructure.persistence.admin_session_repository import (
    PostgresAdministrativeCsrfSessionStore,
    PostgresAdministrativeLoginSessionStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminEmailClaim,
    AdminSession,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
EMAIL = "synthetic.owner@example.test"
PASSWORD = "synthetic owner password"
SECRET = b"JBSWY3DPEHPK3PXP"
SESSION_TOKEN = b"\x51" * 32
CSRF_TOKEN = b"\x52" * 32


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


def _ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(
                base64.urlsafe_b64encode(b"\xf1" * 32).decode("ascii")
            ),
            key_version="v1",
        )
    )


def _seed_account(engine: Engine, *, with_previous_session: bool = False) -> None:
    ring = _ring()
    email = AdministrativeEmailProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xf2" * 12,)),
    ).protect(EMAIL)
    factor_ciphertext = TotpFactorProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xf3" * 12,)),
    ).encrypt(account_id=1, secret=SECRET)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password(PASSWORD),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        assert account_id == 1
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=email.lookup_digest,
                email_ciphertext=email.email_ciphertext,
                key_version=email.key_version,
            )
        )
        connection.execute(
            insert(TotpFactor).values(
                admin_account_id=account_id,
                totp_secret_ciphertext=factor_ciphertext,
                key_version="v1",
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                status="active",
                confirmed_at=NOW,
            )
        )
        if with_previous_session:
            connection.execute(
                insert(AdminSession).values(
                    admin_account_id=account_id,
                    session_digest=b"\x41" * 32,
                    csrf_digest=b"\x42" * 32,
                    key_version="v1",
                    created_at=NOW - timedelta(hours=1),
                    last_human_activity_at=NOW - timedelta(minutes=1),
                    absolute_expires_at=NOW + timedelta(hours=7),
                    status="active",
                )
            )


def _validator(connection) -> ValidateAdministrativeLogin:
    ring = _ring()
    entropy = SystemSecretGenerator()
    return ValidateAdministrativeLogin(
        store=PostgresAdministrativeLoginStore(connection),
        email_lookup=AdministrativeEmailProtector(
            key_ring=ring,
            secret_generator=entropy,
        ),
        password_verifier=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=ring,
            secret_generator=entropy,
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=ring),
        ),
        credential_check_guard=EnsureAdministrativeCredentialCheck(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


def _login(connection, *, code: str, tokens=None):
    clock = FixedClock(NOW)
    validation = _validator(connection).validate(
        email=EMAIL,
        password=PASSWORD,
        totp_code=code,
    )
    credentials = CompleteAdministrativeLoginCredentials(
        factor_store=PostgresAdministrativeLoginFactorStore(connection),
        failure_recorder=RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=clock,
        ),
        clock=clock,
    )
    return CreateAdministrativeLoginSession(
        credentials=credentials,
        store=PostgresAdministrativeLoginSessionStore(connection),
        protector=AdminSessionProtector(key_ring=_ring()),
        secret_generator=tokens or SystemSecretGenerator(),
        audit=RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection),
            clock=clock,
        ),
        clock=clock,
    ).create(validation=validation)


@pytest.mark.integration
def test_t047_success_clears_failures_and_atomically_replaces_the_session(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine, with_previous_session=True)
    with migrated_engine.begin() as connection:
        failures = RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW - timedelta(minutes=1)),
        )
        failures.record(account_id=1, operation="login")
        failures.record(account_id=1, operation="login")

    with migrated_engine.begin() as connection:
        outcome = _login(
            connection,
            code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
        )

    protector = AdminSessionProtector(key_ring=_ring())
    with migrated_engine.connect() as connection:
        sessions = tuple(
            connection.execute(
                select(
                    AdminSession.session_digest,
                    AdminSession.csrf_digest,
                    AdminSession.created_at,
                    AdminSession.absolute_expires_at,
                    AdminSession.status,
                    AdminSession.invalidated_at,
                ).order_by(AdminSession.admin_session_id)
            )
        )
        failure_count = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()
        security_state = connection.execute(
            select(
                AdminAccountSecurityState.lock_until,
                AdminAccountSecurityState.fifth_failure_event_id,
            ).where(AdminAccountSecurityState.admin_account_id == 1)
        ).one()
        audit = connection.execute(
            select(
                AdminAuditEvent.actor_account_id,
                AdminAuditEvent.action,
                AdminAuditEvent.result,
            )
        ).one()

    assert outcome.accepted
    assert outcome.role == "owner"
    assert (outcome.session_token, outcome.csrf_token) == (SESSION_TOKEN, CSRF_TOKEN)
    assert failure_count == 0
    assert security_state == (None, None)
    assert sessions[0].status == "invalidated"
    assert sessions[0].invalidated_at == NOW
    assert sessions[1].status == "active"
    assert sessions[1].session_digest == protector.digest_session_token(SESSION_TOKEN)
    assert sessions[1].csrf_digest == protector.digest_csrf_token(CSRF_TOKEN)
    assert sessions[1].created_at == NOW
    assert sessions[1].absolute_expires_at == NOW + timedelta(hours=8)
    assert SESSION_TOKEN not in sessions[1]
    assert CSRF_TOKEN not in sessions[1]
    assert audit == (1, "login", "succeeded")


@pytest.mark.integration
def test_t047_two_concurrent_logins_leave_exactly_one_active_session(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    totp = pyotp.TOTP(SECRET.decode("ascii"))
    outcomes = _run_concurrently(
        migrated_engine,
        (totp.at(NOW), totp.at(NOW + timedelta(seconds=30))),
    )

    with migrated_engine.connect() as connection:
        session_states = tuple(
            connection.execute(
                select(AdminSession.status).order_by(AdminSession.admin_session_id)
            ).scalars()
        )
        active_count = connection.execute(
            select(func.count())
            .select_from(AdminSession)
            .where(AdminSession.status == "active")
        ).scalar_one()
        factor_use_count = connection.execute(
            select(func.count()).select_from(TotpPeriodUse)
        ).scalar_one()
        audit_count = connection.execute(
            select(func.count())
            .select_from(AdminAuditEvent)
            .where(
                AdminAuditEvent.action == "login",
                AdminAuditEvent.result == "succeeded",
            )
        ).scalar_one()

    assert outcomes == [True, True]
    assert session_states == ("invalidated", "active")
    assert active_count == 1
    assert factor_use_count == 2
    assert audit_count == 2


@pytest.mark.integration
def test_t049_csrf_validation_uses_the_digest_of_the_active_postgres_session(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _login(
            connection,
            code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
        )
    assert outcome.accepted

    with migrated_engine.connect() as connection:
        validator = ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(NOW),
        )
        validator.validate(
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            approved_origin="https://beautyhub.example.test",
            origin="https://beautyhub.example.test",
            referer=None,
            human_initiated=False,
        )

    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE admin_sessions SET status = 'invalidated', "
                "invalidated_at = :now WHERE status = 'active'"
            ),
            {"now": NOW},
        )

    with migrated_engine.connect() as connection:
        validator = ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(NOW),
        )
        with pytest.raises(AdministrativeSessionAuthenticationError):
            validator.validate(
                session_token=SESSION_TOKEN,
                csrf_token=CSRF_TOKEN,
                approved_origin="https://beautyhub.example.test",
                origin="https://beautyhub.example.test",
                referer=None,
                human_initiated=False,
            )


@pytest.mark.integration
def test_t051_logout_invalidates_once_and_prevents_session_reuse(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _login(
            connection,
            code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
        )
    assert outcome.accepted
    logout_time = NOW + timedelta(minutes=1)

    with migrated_engine.begin() as connection:
        logout = CloseAdministrativeSession(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(logout_time),
            ),
            clock=FixedClock(logout_time),
        )
        assert logout.close(session_token=SESSION_TOKEN) is True
        assert logout.close(session_token=SESSION_TOKEN) is False

    with migrated_engine.connect() as connection:
        session_state = connection.execute(
            select(AdminSession.status, AdminSession.invalidated_at)
        ).one()
        logout_events = tuple(
            connection.execute(
                select(
                    AdminAuditEvent.actor_account_id,
                    AdminAuditEvent.action,
                    AdminAuditEvent.result,
                ).where(AdminAuditEvent.action == "logout")
            )
        )
        validator = ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(logout_time),
        )
        with pytest.raises(AdministrativeSessionAuthenticationError):
            validator.validate(
                session_token=SESSION_TOKEN,
                csrf_token=CSRF_TOKEN,
                approved_origin="https://beautyhub.example.test",
                origin="https://beautyhub.example.test",
                referer=None,
                human_initiated=False,
            )

    assert session_state == ("invalidated", logout_time)
    assert logout_events == ((1, "logout", "succeeded"),)


@pytest.mark.integration
def test_t050_human_activity_renews_the_postgres_inactivity_window(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _login(
            connection,
            code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
        )
    assert outcome.accepted
    activity_time = NOW + timedelta(minutes=29, seconds=59)

    with migrated_engine.begin() as connection:
        ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(activity_time),
        ).validate(
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            approved_origin="https://beautyhub.example.test",
            origin="https://beautyhub.example.test",
            referer=None,
            human_initiated=True,
        )

    with migrated_engine.connect() as connection:
        state = connection.execute(
            select(
                AdminSession.last_human_activity_at,
                AdminSession.status,
                AdminSession.invalidated_at,
            )
        ).one()

    assert state == (activity_time, "active", None)


@pytest.mark.integration
def test_t050_background_activity_and_absolute_expiry_do_not_extend_a_session(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _login(
            connection,
            code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
        )
    assert outcome.accepted

    with migrated_engine.begin() as connection:
        ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(NOW + timedelta(minutes=29, seconds=59)),
        ).validate(
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            approved_origin="https://beautyhub.example.test",
            origin="https://beautyhub.example.test",
            referer=None,
            human_initiated=False,
        )

    with migrated_engine.begin() as connection:
        validator = ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(NOW + timedelta(minutes=30)),
        )
        with pytest.raises(AdministrativeSessionAuthenticationError):
            validator.validate(
                session_token=SESSION_TOKEN,
                csrf_token=CSRF_TOKEN,
                approved_origin="https://beautyhub.example.test",
                origin="https://beautyhub.example.test",
                referer=None,
                human_initiated=False,
            )

    with migrated_engine.connect() as connection:
        inactivity_state = connection.execute(
            select(
                AdminSession.last_human_activity_at,
                AdminSession.status,
                AdminSession.invalidated_at,
            )
        ).one()

    assert inactivity_state == (NOW, "invalidated", NOW + timedelta(minutes=30))



@pytest.mark.integration
def test_t050_absolute_expiry_invalidates_even_after_recent_activity(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _login(
            connection,
            code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
        )
        assert outcome.accepted
        connection.execute(
            update(AdminSession)
            .where(AdminSession.status == "active")
            .values(last_human_activity_at=NOW + timedelta(hours=7, minutes=59))
        )

    with migrated_engine.begin() as connection:
        validator = ValidateAdministrativeMutationProtection(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            clock=FixedClock(NOW + timedelta(hours=8)),
        )
        with pytest.raises(AdministrativeSessionAuthenticationError):
            validator.validate(
                session_token=SESSION_TOKEN,
                csrf_token=CSRF_TOKEN,
                approved_origin="https://beautyhub.example.test",
                origin="https://beautyhub.example.test",
                referer=None,
                human_initiated=True,
            )

    with migrated_engine.connect() as connection:
        absolute_state = connection.execute(
            select(AdminSession.status, AdminSession.invalidated_at)
        ).one()

    assert absolute_state == ("invalidated", NOW + timedelta(hours=8))


def _run_concurrently(engine: Engine, codes: tuple[str, str]) -> list[bool]:
    barrier = Barrier(len(codes))

    def worker(code: str) -> bool:
        barrier.wait(timeout=10)
        with engine.begin() as connection:
            return _login(connection, code=code).accepted

    with ThreadPoolExecutor(max_workers=len(codes)) as executor:
        return list(executor.map(worker, codes))

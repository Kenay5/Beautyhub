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
    CheckPostRecoveryFactorReplacement,
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.login_completion import (
    CompleteAdministrativeLoginCredentials,
)
from backend.app.application.admin_access.login_session import (
    CreateAdministrativeLoginSession,
    AdministrativeLoginSessionValueError,
)
from backend.app.application.admin_access.login_validation import (
    ValidateAdministrativeLogin,
)
from backend.app.application.admin_access.logout import CloseAdministrativeSession
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
    ValidateAdministrativeMutationProtection,
)
from backend.app.application.admin_access.session_context import (
    LoadAdministrativeSessionContext,
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
    RecoveryCode,
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
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
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
REFRESHED_CSRF_TOKEN = b"\x53" * 32
STAFF_SESSION_TOKEN = b"\x54" * 32
STAFF_CSRF_TOKEN = b"\x55" * 32


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
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE TABLE admin_accounts RESTART IDENTITY CASCADE")
            )
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


def _login(
    connection,
    *,
    email: str = EMAIL,
    password: str = PASSWORD,
    code: str | None = None,
    recovery_code: str | None = None,
    tokens=None,
):
    clock = FixedClock(NOW)
    validation = _validator(connection).validate(
        email=email,
        password=password,
        totp_code=code,
        recovery_code=recovery_code,
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
def test_t084_failed_known_and_unknown_logins_record_one_minimum_event_each(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        known = _login(
            connection,
            password="incorrect synthetic password",
            code="123456",
        )
        unknown = _login(
            connection,
            email="missing.synthetic@example.test",
            password="incorrect synthetic password",
            code="123456",
        )

    with migrated_engine.connect() as connection:
        events = tuple(
            connection.execute(
                select(
                    AdminAuditEvent.actor_account_id,
                    AdminAuditEvent.action,
                    AdminAuditEvent.result,
                    AdminAuditEvent.target_reference,
                ).order_by(AdminAuditEvent.admin_audit_event_id)
            )
        )
        sessions = connection.execute(
            select(func.count()).select_from(AdminSession)
        ).scalar_one()
        failures = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()

    assert not known.accepted and not unknown.accepted
    assert events == (
        (1, "login", "failed", None),
        (None, "login", "failed", None),
    )
    assert sessions == 0
    assert failures == 1


@pytest.mark.integration
def test_t084_login_audit_and_session_share_the_caller_transaction(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with pytest.raises(RuntimeError, match="rollback synthetic login"):
        with migrated_engine.begin() as connection:
            outcome = _login(
                connection,
                code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
                tokens=SequenceSecretGenerator((SESSION_TOKEN, CSRF_TOKEN)),
            )
            assert outcome.accepted
            raise RuntimeError("rollback synthetic login")

    with migrated_engine.connect() as connection:
        sessions = connection.execute(
            select(func.count()).select_from(AdminSession)
        ).scalar_one()
        events = connection.execute(
            select(func.count()).select_from(AdminAuditEvent)
        ).scalar_one()
        factor_uses = connection.execute(
            select(func.count()).select_from(TotpPeriodUse)
        ).scalar_one()

    assert (sessions, events, factor_uses) == (0, 0, 0)


@pytest.mark.integration
def test_t064_failed_factor_authentication_keeps_post_recovery_restriction(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == 1)
            .values(post_recovery_second_factor_restricted=True)
        )
        outcome = _login(connection, code="000000")

    with migrated_engine.connect() as connection:
        restricted = connection.execute(
            select(AdminAccountSecurityState.post_recovery_second_factor_restricted)
            .where(AdminAccountSecurityState.admin_account_id == 1)
        ).scalar_one()
        active_sessions = connection.execute(
            select(func.count()).select_from(AdminSession).where(AdminSession.status == "active")
        ).scalar_one()
    assert not outcome.accepted
    assert restricted
    assert active_sessions == 0


@pytest.mark.integration
def test_t064_only_successful_totp_login_clears_post_recovery_restriction(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == 1)
            .values(post_recovery_second_factor_restricted=True)
        )
        outcome = _login(connection, code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW))

    with migrated_engine.connect() as connection:
        restricted = connection.execute(
            select(AdminAccountSecurityState.post_recovery_second_factor_restricted)
            .where(AdminAccountSecurityState.admin_account_id == 1)
        ).scalar_one()
        session_count = connection.execute(
            select(func.count()).select_from(AdminSession).where(AdminSession.status == "active")
        ).scalar_one()
        factor_replacement_allowed = CheckPostRecoveryFactorReplacement(
            store=PostgresAdministrativeAccountSecurityStore(connection)
        ).is_allowed(account_id=1)
    assert outcome.accepted
    assert not restricted
    assert factor_replacement_allowed
    assert session_count == 1


@pytest.mark.integration
def test_t064_successful_recovery_code_login_clears_post_recovery_restriction(
    migrated_engine: Engine,
) -> None:
    recovery_code = "ABCD-EFGH-JKLM-NPQR"
    _seed_account(migrated_engine)
    protector = RecoveryCodeProtector(key_ring=_ring())
    with migrated_engine.begin() as connection:
        connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == 1)
            .values(post_recovery_second_factor_restricted=True)
        )
        connection.execute(
            insert(RecoveryCode).values(
                admin_account_id=1,
                lookup_digest=protector.digest(recovery_code.replace("-", "")),
                key_version="v1",
                position=1,
                status="active",
            )
        )
        outcome = _login(connection, recovery_code=recovery_code.lower())

    with migrated_engine.connect() as connection:
        restricted = connection.execute(
            select(AdminAccountSecurityState.post_recovery_second_factor_restricted)
            .where(AdminAccountSecurityState.admin_account_id == 1)
        ).scalar_one()
        code_status = connection.execute(select(RecoveryCode.status)).scalar_one()
    assert outcome.accepted
    assert not restricted
    assert code_status == "used"


@pytest.mark.integration
def test_t065_correct_recovery_code_is_consumed_only_with_a_completed_login(
    migrated_engine: Engine,
) -> None:
    recovery_code = "ABCD-EFGH-JKLM-NPQR"
    _seed_account(migrated_engine)
    protector = RecoveryCodeProtector(key_ring=_ring())
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode).values(
                admin_account_id=1,
                lookup_digest=protector.digest(recovery_code.replace("-", "")),
                key_version="v1",
                position=1,
                status="active",
            )
        )
        outcome = _login(connection, recovery_code=recovery_code.lower())

    with migrated_engine.connect() as connection:
        code_status = connection.execute(select(RecoveryCode.status)).scalar_one()
        active_sessions = connection.execute(
            select(func.count()).select_from(AdminSession).where(AdminSession.status == "active")
        ).scalar_one()
        failures = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()
    assert outcome.accepted
    assert code_status == "used"
    assert active_sessions == 1
    assert failures == 0


@pytest.mark.integration
def test_t065_incorrect_recovery_code_preserves_the_entire_lot_and_records_one_failure(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    protector = RecoveryCodeProtector(key_ring=_ring())
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode),
            tuple(
                {
                    "admin_account_id": 1,
                    "lookup_digest": protector.digest(code.replace("-", "")),
                    "key_version": "v1",
                    "position": position,
                    "status": "active",
                }
                for position, code in enumerate(("ABCD-EFGH-JKLM-NPQR", "2345-6789-ABCD-EFGH"), 1)
            ),
        )
        outcome = _login(connection, recovery_code="ZZZZ-ZZZZ-ZZZZ-ZZZZ")

    with migrated_engine.connect() as connection:
        statuses = tuple(connection.execute(select(RecoveryCode.status).order_by(RecoveryCode.position)).scalars())
        failures = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()
        sessions = connection.execute(
            select(func.count()).select_from(AdminSession).where(AdminSession.status == "active")
        ).scalar_one()
    assert not outcome.accepted
    assert statuses == ("active", "active")
    assert failures == 1
    assert sessions == 0


@pytest.mark.integration
def test_t065_reused_recovery_code_is_rejected_without_consuming_remaining_codes(
    migrated_engine: Engine,
) -> None:
    recovery_code = "ABCD-EFGH-JKLM-NPQR"
    _seed_account(migrated_engine)
    protector = RecoveryCodeProtector(key_ring=_ring())
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode),
            tuple(
                {
                    "admin_account_id": 1,
                    "lookup_digest": protector.digest(code.replace("-", "")),
                    "key_version": "v1",
                    "position": position,
                    "status": "active",
                }
                for position, code in enumerate((recovery_code, "2345-6789-ABCD-EFGH"), 1)
            ),
        )
        first = _login(connection, recovery_code=recovery_code)
    with migrated_engine.begin() as connection:
        reused = _login(connection, recovery_code=recovery_code)

    with migrated_engine.connect() as connection:
        statuses = tuple(connection.execute(select(RecoveryCode.status).order_by(RecoveryCode.position)).scalars())
        failures = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()
        sessions = connection.execute(
            select(func.count()).select_from(AdminSession).where(AdminSession.status == "active")
        ).scalar_one()
    assert first.accepted
    assert not reused.accepted
    assert statuses == ("used", "active")
    assert failures == 1
    assert sessions == 1


@pytest.mark.integration
def test_t065_valid_code_is_restored_if_session_creation_fails(
    migrated_engine: Engine,
) -> None:
    recovery_code = "ABCD-EFGH-JKLM-NPQR"
    _seed_account(migrated_engine)
    protector = RecoveryCodeProtector(key_ring=_ring())
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode).values(
                admin_account_id=1,
                lookup_digest=protector.digest(recovery_code.replace("-", "")),
                key_version="v1",
                position=1,
                status="active",
            )
        )
    with pytest.raises(AdministrativeLoginSessionValueError):
        with migrated_engine.begin() as connection:
            _login(
                connection,
                recovery_code=recovery_code,
                tokens=SequenceSecretGenerator((SESSION_TOKEN, SESSION_TOKEN)),
            )

    with migrated_engine.connect() as connection:
        code_status = connection.execute(select(RecoveryCode.status)).scalar_one()
        active_sessions = connection.execute(
            select(func.count()).select_from(AdminSession).where(AdminSession.status == "active")
        ).scalar_one()
    assert code_status == "active"
    assert active_sessions == 0


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


@pytest.mark.integration
def test_t053_context_revalidates_account_and_rotates_csrf_without_activity(
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
    context_time = NOW + timedelta(minutes=1)

    with migrated_engine.begin() as connection:
        context = LoadAdministrativeSessionContext(
            store=PostgresAdministrativeCsrfSessionStore(connection),
            protector=AdminSessionProtector(key_ring=_ring()),
            secret_generator=SequenceSecretGenerator((REFRESHED_CSRF_TOKEN,)),
            clock=FixedClock(context_time),
        ).refresh(session_token=SESSION_TOKEN)

    with migrated_engine.connect() as connection:
        stored_session = connection.execute(
            select(
                AdminSession.csrf_digest,
                AdminSession.last_human_activity_at,
                AdminSession.status,
            )
        ).one()

    assert (context.actor.account_id, context.actor.role) == (1, "owner")
    assert context.csrf_token == REFRESHED_CSRF_TOKEN
    assert stored_session == (
        AdminSessionProtector(key_ring=_ring()).digest_csrf_token(
            REFRESHED_CSRF_TOKEN
        ),
        NOW,
        "active",
    )

    protector = AdminSessionProtector(key_ring=_ring())
    with migrated_engine.begin() as connection:
        staff_account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="staff",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password(PASSWORD),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminSession).values(
                admin_account_id=staff_account_id,
                session_digest=protector.digest_session_token(STAFF_SESSION_TOKEN),
                csrf_digest=protector.digest_csrf_token(STAFF_CSRF_TOKEN),
                key_version="v1",
                created_at=NOW,
                last_human_activity_at=NOW,
                absolute_expires_at=NOW + timedelta(hours=8),
                status="active",
            )
        )
        connection.execute(
            update(AdminAccount)
            .where(AdminAccount.admin_account_id == staff_account_id)
            .values(status="deactivated", updated_at=context_time)
        )

    with migrated_engine.connect() as connection:
        with pytest.raises(
            AdministrativeSessionAuthenticationError,
            match="administrative session is unavailable",
        ):
            LoadAdministrativeSessionContext(
                store=PostgresAdministrativeCsrfSessionStore(connection),
                protector=AdminSessionProtector(key_ring=_ring()),
                secret_generator=SequenceSecretGenerator(()),
                clock=FixedClock(context_time),
            ).authenticate(session_token=STAFF_SESSION_TOKEN)
        with pytest.raises(AdministrativeSessionAuthenticationError):
            ValidateAdministrativeMutationProtection(
                store=PostgresAdministrativeCsrfSessionStore(connection),
                protector=protector,
                clock=FixedClock(context_time),
            ).validate(
                session_token=STAFF_SESSION_TOKEN,
                csrf_token=STAFF_CSRF_TOKEN,
                approved_origin="https://beautyhub.example.test",
                origin="https://beautyhub.example.test",
                referer=None,
                human_initiated=True,
            )


def _run_concurrently(engine: Engine, codes: tuple[str, str]) -> list[bool]:
    barrier = Barrier(len(codes))

    def worker(code: str) -> bool:
        barrier.wait(timeout=10)
        with engine.begin() as connection:
            return _login(connection, code=code).accepted

    with ThreadPoolExecutor(max_workers=len(codes)) as executor:
        return list(executor.map(worker, codes))

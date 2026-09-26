"""T068 PostgreSQL evidence for atomic TOTP and recovery-code replacement."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from sqlalchemy import Engine, func, insert, select, text, update

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.confirm_totp_replacement import ConfirmAdministrativeTotpReplacement
from backend.app.application.admin_access.prepare_totp_replacement import PrepareAdministrativeTotpReplacement
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_account_security_repository import PostgresAdministrativeAccountSecurityStore
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import PostgresAdministrativeLockRecipientDirectory
from backend.app.infrastructure.persistence.models import (
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminSession,
    PendingSecuritySetup,
    RecoveryCode,
    SecurityNotificationDelivery,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.persistence.totp_replacement_confirmation_repository import PostgresTotpReplacementConfirmationStore
from backend.app.infrastructure.persistence.totp_replacement_repository import PostgresTotpReplacementStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.tests.integration.admin_access.test_admin_login_session import (
    NOW,
    PASSWORD,
    SECRET,
    _ring,
    _seed_account,
    migrated_engine,
)


OLD_RECOVERY = "ABCDEFGHJKLMNPQ2"


class _FailingAuditStore:
    def append(self, *, event) -> None:
        raise RuntimeError("synthetic audit persistence failure")


def _old_code_digest(value=OLD_RECOVERY):
    return RecoveryCodeProtector(key_ring=_ring()).digest(value)


def _protected_snapshot(connection):
    return (
        connection.execute(
            select(
                TotpFactor.totp_factor_id,
                TotpFactor.status,
                TotpFactor.totp_secret_ciphertext,
                TotpFactor.key_version,
                TotpFactor.invalidated_at,
            ).order_by(TotpFactor.totp_factor_id)
        ).all(),
        connection.execute(
            select(
                RecoveryCode.recovery_code_id,
                RecoveryCode.lookup_digest,
                RecoveryCode.status,
                RecoveryCode.used_at,
                RecoveryCode.invalidated_at,
            ).order_by(RecoveryCode.recovery_code_id)
        ).all(),
        connection.execute(
            select(AdminSession.admin_session_id, AdminSession.status, AdminSession.invalidated_at)
            .order_by(AdminSession.admin_session_id)
        ).all(),
        connection.execute(
            select(TotpPeriodUse.totp_factor_id, TotpPeriodUse.period_counter)
            .order_by(TotpPeriodUse.totp_factor_id, TotpPeriodUse.period_counter)
        ).all(),
    )


def _seed_recovery_codes(engine: Engine):
    protector = RecoveryCodeProtector(key_ring=_ring())
    values = ["ABCDEFGHJKLMNPQ" + suffix for suffix in "23456789AB"]
    with engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode),
            [
                {
                    "admin_account_id": 1,
                    "lookup_digest": protector.digest(value),
                    "key_version": "v1",
                    "position": position,
                    "status": "active",
                    "used_at": None,
                    "invalidated_at": None,
                }
                for position, value in enumerate(values, start=1)
            ],
        )


def _recording(connection, *, failing_audit=False):
    clock, entropy, ring = FixedClock(NOW), SystemSecretGenerator(), _ring()
    security = PostgresAdministrativeAccountSecurityStore(connection)
    email = AdministrativeEmailProtector(key_ring=ring, secret_generator=entropy)
    audit = RecordAdministrativeAuditEvent(
        store=_FailingAuditStore() if failing_audit else PostgresAdministrativeAuditStore(connection),
        clock=clock,
    )
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(key_ring=ring, secret_generator=entropy),
    )
    failures = RecordProtectedAdministrativeCredentialFailure(
        failure_recorder=RecordAdministrativeCredentialFailure(store=security, clock=clock),
        audit=audit,
        notifications=notifications,
        recipients=PostgresAdministrativeLockRecipientDirectory(
            connection=connection, email_protector=email
        ),
    )
    return clock, entropy, ring, email, audit, notifications, failures


def _prepare(connection, *, proof="totp"):
    clock, entropy, ring, email, audit, notifications, failures = _recording(connection)
    security = PostgresAdministrativeAccountSecurityStore(connection)
    operation = PrepareAdministrativeTotpReplacement(
        store=PostgresTotpReplacementStore(connection),
        credential_guard=EnsureAdministrativeCredentialCheck(store=security, clock=clock),
        failure_recorder=failures,
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(key_ring=ring, secret_generator=entropy),
        pending_factor_protector=PendingTotpProtector(key_ring=ring, secret_generator=entropy),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=ring),
        ),
        audit=audit,
        clock=clock,
    )
    result = operation.prepare(
        account_id=1,
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode()).at(NOW) if proof == "totp" else None,
        recovery_code=OLD_RECOVERY if proof == "recovery" else None,
    )
    assert result != "invalid_credentials"
    return result.manual_key


def _confirmation(connection, *, failing_audit=False):
    clock, entropy, ring, email, audit, notifications, failures = _recording(
        connection, failing_audit=failing_audit
    )
    security = PostgresAdministrativeAccountSecurityStore(connection)
    return ConfirmAdministrativeTotpReplacement(
        store=PostgresTotpReplacementConfirmationStore(connection, email),
        credential_guard=EnsureAdministrativeCredentialCheck(store=security, clock=clock),
        failure_recorder=failures,
        pending_factor_protector=PendingTotpProtector(key_ring=ring, secret_generator=entropy),
        factor_protector=TotpFactorProtector(key_ring=ring, secret_generator=entropy),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=ring),
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection), clock=clock
        ),
        audit=audit,
        notifications=notifications,
        clock=clock,
    )


@pytest.fixture()
def replacement_engine(migrated_engine: Engine) -> Engine:
    with migrated_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE security_notification_deliveries RESTART IDENTITY"))
    return migrated_engine


@pytest.mark.integration
@pytest.mark.parametrize("proof", ["totp", "recovery"])
def test_t068_success_atomically_replaces_factor_codes_consumes_proof_and_closes_sessions(
    replacement_engine: Engine, proof: str
):
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_codes(replacement_engine)
    old_proof_counter = int(NOW.timestamp()) // 30
    with replacement_engine.begin() as connection:
        new_secret = _prepare(connection, proof=proof)
    new_counter = int(NOW.timestamp()) // 30
    new_code = pyotp.TOTP(new_secret).at(NOW)

    with replacement_engine.begin() as connection:
        result = _confirmation(connection).confirm(account_id=1, totp_code=new_code)

    assert result.status == "replaced"
    assert len(result.recovery_codes) == 10 and len(set(result.recovery_codes)) == 10
    with replacement_engine.connect() as connection:
        factors = connection.execute(
            select(TotpFactor.status, TotpFactor.totp_secret_ciphertext).order_by(TotpFactor.totp_factor_id)
        ).all()
        assert factors[0].status == "invalidated" and factors[0].totp_secret_ciphertext is None
        assert factors[1].status == "active" and factors[1].totp_secret_ciphertext
        old_codes = connection.execute(
            select(RecoveryCode.status).order_by(RecoveryCode.recovery_code_id)
        ).scalars().all()
        assert old_codes[:10] == ["invalidated"] * 10
        assert old_codes[10:] == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["invalidated"]
        assert connection.execute(select(PendingSecuritySetup.status)).scalars().all() == ["confirmed"]
        uses = connection.execute(
            select(TotpPeriodUse.totp_factor_id, TotpPeriodUse.period_counter)
            .order_by(TotpPeriodUse.totp_factor_id)
        ).all()
        if proof == "totp":
            assert uses == [(1, old_proof_counter), (2, new_counter)]
        else:
            assert uses == [(2, new_counter)]
            assert connection.execute(
                select(RecoveryCode.status).where(RecoveryCode.lookup_digest == _old_code_digest())
            ).scalar_one() == "invalidated"
        assert connection.execute(
            select(AdminAuditEvent.action, AdminAuditEvent.result)
        ).all() == [("totp_replacement", "succeeded")]
        assert connection.execute(
            select(SecurityNotificationDelivery.event, SecurityNotificationDelivery.template)
        ).all() == [("totp_replaced", "totp_replaced_notice")]


@pytest.mark.integration
def test_t068_audit_failure_rolls_back_factor_batch_proof_pending_and_sessions(replacement_engine: Engine):
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_codes(replacement_engine)
    with replacement_engine.begin() as connection:
        new_secret = _prepare(connection)
    with replacement_engine.connect() as connection:
        previous_state = _protected_snapshot(connection)
    with pytest.raises(RuntimeError, match="synthetic audit"):
        with replacement_engine.begin() as connection:
            _confirmation(connection, failing_audit=True).confirm(
                account_id=1, totp_code=pyotp.TOTP(new_secret).at(NOW)
            )
    with replacement_engine.connect() as connection:
        assert _protected_snapshot(connection) == previous_state
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        setup = connection.execute(
            select(PendingSecuritySetup.status, PendingSecuritySetup.verified_totp_period_counter)
        ).one()
        assert setup == ("pending", int(NOW.timestamp()) // 30)
        assert connection.execute(select(TotpPeriodUse)).scalars().all() == []
        assert connection.execute(select(AdminAuditEvent)).scalars().all() == []


@pytest.mark.integration
def test_t068_wrong_new_factor_code_discards_setup_once_but_preserves_existing_credentials(
    replacement_engine: Engine,
):
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_codes(replacement_engine)
    with replacement_engine.begin() as connection:
        _prepare(connection)
        previous_state = _protected_snapshot(connection)
        outcome = _confirmation(connection).confirm(account_id=1, totp_code="not-a-valid-code")
    assert outcome.status == "invalid_credentials"
    with replacement_engine.connect() as connection:
        assert _protected_snapshot(connection) == previous_state
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"] * 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(PendingSecuritySetup.status)).scalars().all() == ["invalidated"]
        assert connection.execute(select(TotpPeriodUse)).scalars().all() == []
        assert connection.execute(
            select(AdminCredentialFailureEvent.operation)
        ).scalars().all() == ["totp_replacement"]


@pytest.mark.integration
@pytest.mark.parametrize("proof", ["totp", "recovery"])
def test_t068_reused_t067_proof_preserves_old_credentials_and_counts_once(
    replacement_engine: Engine, proof: str
):
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_codes(replacement_engine)
    with replacement_engine.begin() as connection:
        new_secret = _prepare(connection, proof=proof)
    with replacement_engine.begin() as connection:
        if proof == "totp":
            connection.execute(
                insert(TotpPeriodUse).values(
                    admin_account_id=1,
                    totp_factor_id=1,
                    period_counter=int(NOW.timestamp()) // 30,
                    consumed_at=NOW,
                )
            )
        else:
            connection.execute(
                update(RecoveryCode)
                .where(RecoveryCode.lookup_digest == _old_code_digest())
                .values(status="used", used_at=NOW)
            )
        previous_state = _protected_snapshot(connection)
        outcome = _confirmation(connection).confirm(
            account_id=1, totp_code=pyotp.TOTP(new_secret).at(NOW)
        )
    assert outcome.status == "invalid_credentials"
    with replacement_engine.connect() as connection:
        assert _protected_snapshot(connection) == previous_state
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        active_codes = connection.execute(
            select(func.count()).select_from(RecoveryCode).where(RecoveryCode.status == "active")
        ).scalar_one()
        assert active_codes == (9 if proof == "recovery" else 10)
        assert connection.execute(select(PendingSecuritySetup.status)).scalars().all() == ["invalidated"]
        assert connection.execute(select(AdminCredentialFailureEvent.operation)).scalars().all() == ["totp_replacement"]


@pytest.mark.integration
def test_t068_concurrent_confirmations_allow_exactly_one_transition(replacement_engine: Engine):
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_codes(replacement_engine)
    with replacement_engine.begin() as connection:
        new_secret = _prepare(connection)
    code = pyotp.TOTP(new_secret).at(NOW)
    barrier = Barrier(2)

    def confirm_once():
        barrier.wait(timeout=10)
        with replacement_engine.begin() as connection:
            return _confirmation(connection).confirm(account_id=1, totp_code=code).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: confirm_once(), range(2)))
    assert sorted(outcomes) == ["replaced", "unavailable"]
    with replacement_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(TotpFactor).where(TotpFactor.status == "active")).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.status == "active")).scalar_one() == 10
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["invalidated"]
        assert connection.execute(select(AdminAuditEvent.result)).scalars().all().count("succeeded") == 1

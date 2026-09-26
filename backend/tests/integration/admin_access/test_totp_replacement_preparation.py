"""T067 PostgreSQL evidence: pending setup only, existing credentials untouched."""

import pyotp
import pytest
from datetime import timedelta
from sqlalchemy import Engine, insert, select, text

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.prepare_totp_replacement import (
    PrepareAdministrativeTotpReplacement,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import (
    PostgresAdministrativeLockRecipientDirectory,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminSession,
    PendingSecuritySetup,
    RecoveryCode,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.persistence.totp_replacement_repository import (
    PostgresTotpReplacementStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
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


RECOVERY_CODE = "ABCDEFGHJKLMNPQ2"


def _operation(connection):
    clock = FixedClock(NOW)
    entropy = SystemSecretGenerator()
    ring = _ring()
    security = PostgresAdministrativeAccountSecurityStore(connection)
    audit = RecordAdministrativeAuditEvent(
        store=PostgresAdministrativeAuditStore(connection), clock=clock
    )
    email_protector = AdministrativeEmailProtector(key_ring=ring, secret_generator=entropy)
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(key_ring=ring, secret_generator=entropy),
    )
    return PrepareAdministrativeTotpReplacement(
        store=PostgresTotpReplacementStore(connection),
        credential_guard=EnsureAdministrativeCredentialCheck(store=security, clock=clock),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(store=security, clock=clock),
            audit=audit,
            notifications=notifications,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection, email_protector=email_protector
            ),
        ),
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


def _seed_recovery_code(engine: Engine) -> bytes:
    digest = RecoveryCodeProtector(key_ring=_ring()).digest(RECOVERY_CODE)
    with engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode).values(
                admin_account_id=1,
                lookup_digest=digest,
                key_version="v1",
                position=1,
                status="active",
                used_at=None,
                invalidated_at=None,
            )
        )
    return digest


@pytest.fixture()
def replacement_engine(migrated_engine: Engine) -> Engine:
    with migrated_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE security_notification_deliveries RESTART IDENTITY"))
    return migrated_engine


@pytest.mark.integration
@pytest.mark.parametrize("proof_kind", ["totp", "recovery"])
def test_t067_success_persists_only_pending_setup_and_preserves_existing_state(
    replacement_engine: Engine, proof_kind: str
) -> None:
    _seed_account(replacement_engine, with_previous_session=True)
    recovery_digest = _seed_recovery_code(replacement_engine)
    with replacement_engine.begin() as connection:
        outcome = _operation(connection).prepare(
            account_id=1,
            current_password=PASSWORD,
            totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW) if proof_kind == "totp" else None,
            recovery_code=RECOVERY_CODE if proof_kind == "recovery" else None,
        )

    assert outcome.manual_key
    assert outcome.provisioning_uri.startswith("otpauth://totp/")
    with replacement_engine.connect() as connection:
        assert connection.execute(select(AdminAccount.password_hash)).scalar_one()
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"]
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(TotpPeriodUse.totp_period_use_id)).scalars().all() == []
        setup = connection.execute(
            select(
                PendingSecuritySetup.status,
                PendingSecuritySetup.totp_secret_ciphertext,
                PendingSecuritySetup.verified_totp_period_counter,
                PendingSecuritySetup.verified_totp_factor_id,
                PendingSecuritySetup.verified_recovery_code_digest,
            )
        ).one()
        assert setup.status == "pending"
        assert setup.totp_secret_ciphertext is not None
        assert setup.totp_secret_ciphertext != outcome.manual_key.encode()
        if proof_kind == "totp":
            assert setup.verified_totp_period_counter == int(NOW.timestamp()) // 30
            assert setup.verified_totp_factor_id == 1
            assert setup.verified_recovery_code_digest is None
        else:
            assert setup.verified_totp_period_counter is None
            assert setup.verified_recovery_code_digest == recovery_digest
        assert connection.execute(select(AdminCredentialFailureEvent)).scalars().all() == []


@pytest.mark.integration
def test_t067_invalid_proof_counts_once_without_creating_or_changing_credentials(
    replacement_engine: Engine,
) -> None:
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_code(replacement_engine)
    with replacement_engine.begin() as connection:
        outcome = _operation(connection).prepare(
            account_id=1,
            current_password=PASSWORD,
            totp_code="not-a-code",
        )

    assert outcome == "invalid_credentials"
    with replacement_engine.connect() as connection:
        assert connection.execute(select(TotpFactor.status)).scalars().all() == ["active"]
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"]
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(PendingSecuritySetup)).scalars().all() == []
        assert connection.execute(select(TotpPeriodUse.totp_period_use_id)).scalars().all() == []
        assert connection.execute(select(AdminCredentialFailureEvent.operation)).scalars().all() == ["totp_replacement"]
        assert connection.execute(select(AdminAuditEvent.action, AdminAuditEvent.result)).all() == [
            ("totp_replacement", "failed")
        ]


@pytest.mark.integration
def test_t067_invalid_credentials_preserve_existing_pending_setup_byte_for_byte(
    replacement_engine: Engine,
) -> None:
    _seed_account(replacement_engine, with_previous_session=True)
    original_ciphertext = b"previous encrypted pending secret"
    original_digest = b"d" * 32
    with replacement_engine.begin() as connection:
        connection.execute(
            insert(PendingSecuritySetup).values(
                admin_account_id=1,
                flow="totp_replacement",
                status="pending",
                totp_secret_ciphertext=original_ciphertext,
                key_version="v1",
                verified_totp_period_counter=None,
                verified_recovery_code_digest=original_digest,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
        )
        outcome = _operation(connection).prepare(
            account_id=1,
            current_password="incorrect password",
            totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
        )

    assert outcome == "invalid_credentials"
    with replacement_engine.connect() as connection:
        pending = connection.execute(
            select(
                PendingSecuritySetup.status,
                PendingSecuritySetup.totp_secret_ciphertext,
                PendingSecuritySetup.key_version,
                PendingSecuritySetup.verified_recovery_code_digest,
            )
        ).one()
        assert pending == ("pending", original_ciphertext, "v1", original_digest)


@pytest.mark.integration
def test_t067_invalid_recovery_code_is_not_consumed_and_preserves_account_state(
    replacement_engine: Engine,
) -> None:
    _seed_account(replacement_engine, with_previous_session=True)
    _seed_recovery_code(replacement_engine)
    with replacement_engine.begin() as connection:
        outcome = _operation(connection).prepare(
            account_id=1,
            current_password=PASSWORD,
            recovery_code="invalid recovery code",
        )

    assert outcome == "invalid_credentials"
    with replacement_engine.connect() as connection:
        assert connection.execute(select(RecoveryCode.status)).scalars().all() == ["active"]
        assert connection.execute(select(AdminSession.status)).scalars().all() == ["active"]
        assert connection.execute(select(PendingSecuritySetup.pending_security_setup_id)).scalars().all() == []
        assert connection.execute(select(TotpPeriodUse.totp_period_use_id)).scalars().all() == []
        assert connection.execute(select(AdminCredentialFailureEvent.operation)).scalars().all() == [
            "totp_replacement"
        ]

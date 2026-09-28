"""T066 PostgreSQL evidence for recovery-code replacement and rollback."""

import pyotp
import pytest
from sqlalchemy import Engine, func, insert, select, text

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.login_validation import (
    ValidateAdministrativeLogin,
)
from backend.app.application.admin_access.regenerate_recovery_codes import (
    RegenerateAdministrativeRecoveryCodes,
)
from backend.app.application.admin_access.security_change_invalidation import (
    InvalidateAfterSecurityChange,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import (
    PostgresAdministrativeLockRecipientDirectory,
)
from backend.app.infrastructure.persistence.admin_login_repository import (
    PostgresAdministrativeLoginStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminSession,
    RecoveryCode,
    SecurityNotificationDelivery,
    TotpPeriodUse,
)
from backend.app.infrastructure.persistence.recovery_code_regeneration_repository import (
    PostgresRecoveryCodeRegenerationStore,
)
from backend.app.infrastructure.persistence.security_change_invalidation_repository import (
    PostgresSecurityChangeInvalidationStore,
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
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtector,
)
from backend.tests.integration.admin_access.test_admin_login_session import (
    NOW,
    PASSWORD,
    SECRET,
    _ring,
    _seed_account,
    migrated_engine,
)
from backend.app.web.admin_auth import recovery_code_regeneration as recovery_code_web


OLD_CODES = tuple("ABCDEFGHJKLMNPQ" + suffix for suffix in "23456789AB")


class _FailingAuditStore:
    def append(self, *, event) -> None:
        raise RuntimeError("synthetic audit write failure")


def _seed_recovery_codes(engine: Engine) -> None:
    protector = RecoveryCodeProtector(key_ring=_ring())
    with engine.begin() as connection:
        connection.execute(
            insert(RecoveryCode),
            [
                {
                    "admin_account_id": 1,
                    "lookup_digest": protector.digest(code),
                    "key_version": "v1",
                    "position": position,
                    "status": "used" if position == 1 else "active",
                    "used_at": NOW if position == 1 else None,
                    "invalidated_at": None,
                }
                for position, code in enumerate(OLD_CODES, start=1)
            ],
        )


def _operation(connection, *, failing_audit: bool = False):
    clock = FixedClock(NOW)
    entropy = SystemSecretGenerator()
    ring = _ring()
    account_security = PostgresAdministrativeAccountSecurityStore(connection)
    audit = RecordAdministrativeAuditEvent(
        store=_FailingAuditStore()
        if failing_audit
        else PostgresAdministrativeAuditStore(connection),
        clock=clock,
    )
    email_protector = AdministrativeEmailProtector(
        key_ring=ring, secret_generator=entropy
    )
    notices = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(
            key_ring=ring, secret_generator=entropy
        ),
    )
    return RegenerateAdministrativeRecoveryCodes(
        store=PostgresRecoveryCodeRegenerationStore(
            connection=connection, email_protector=email_protector
        ),
        credential_guard=EnsureAdministrativeCredentialCheck(
            store=account_security, clock=clock
        ),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(
                store=account_security, clock=clock
            ),
            audit=audit,
            notifications=notices,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection, email_protector=email_protector
            ),
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=ring, secret_generator=entropy
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=ring),
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection),
            clock=clock,
        ),
        audit=audit,
        notifications=notices,
        clock=clock,
    )


def _login_validator(connection) -> ValidateAdministrativeLogin:
    ring = _ring()
    entropy = SystemSecretGenerator()
    return ValidateAdministrativeLogin(
        store=PostgresAdministrativeLoginStore(connection),
        email_lookup=AdministrativeEmailProtector(
            key_ring=ring, secret_generator=entropy
        ),
        password_verifier=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=ring, secret_generator=entropy
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


@pytest.fixture()
def regeneration_engine(migrated_engine: Engine) -> Engine:
    with migrated_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE TABLE security_notification_deliveries RESTART IDENTITY")
        )
    return migrated_engine


@pytest.mark.integration
def test_t066_success_rotates_the_complete_batch_and_invalidates_old_codes_and_sessions(
    regeneration_engine: Engine,
) -> None:
    _seed_account(regeneration_engine, with_previous_session=True)
    _seed_recovery_codes(regeneration_engine)
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)

    with regeneration_engine.begin() as connection:
        outcome = _operation(connection).regenerate(
            account_id=1, current_password=PASSWORD, totp_code=code
        )

    assert outcome.status == "regenerated"
    assert len(outcome.recovery_codes) == 10
    assert len(set(outcome.recovery_codes)) == 10
    assert all(
        len(value) == 19
        and value[4] == value[9] == value[14] == "-"
        for value in outcome.recovery_codes
    )
    with regeneration_engine.connect() as connection:
        rows = connection.execute(
            select(RecoveryCode.lookup_digest, RecoveryCode.status).order_by(
                RecoveryCode.recovery_code_id
            )
        ).all()
        old_rows, new_rows = rows[:10], rows[10:]
        assert all(row.status == "invalidated" for row in old_rows)
        assert len(new_rows) == 10
        assert all(row.status == "active" for row in new_rows)
        assert connection.execute(select(AdminSession.status)).scalars().all() == [
            "invalidated"
        ]
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 1
        assert connection.execute(
            select(AdminAuditEvent.action, AdminAuditEvent.result)
        ).all() == [("recovery_code_regeneration", "succeeded")]
        assert connection.execute(
            select(SecurityNotificationDelivery.event, SecurityNotificationDelivery.status)
        ).all() == [("recovery_codes_changed", "pending")]

    code_service = RecoveryCodeService(
        secret_generator=SystemSecretGenerator(),
        protector=RecoveryCodeProtector(key_ring=_ring()),
    )
    active_digests = tuple(row.lookup_digest for row in new_rows)
    assert code_service.match(value=OLD_CODES[1], active_lookup_digests=active_digests) is None
    assert code_service.match(
        value=outcome.recovery_codes[0], active_lookup_digests=active_digests
    ) is not None
    with regeneration_engine.connect() as connection:
        validator = _login_validator(connection)
        assert not validator.validate(
            email="synthetic.owner@example.test",
            password=PASSWORD,
            recovery_code=OLD_CODES[1],
        ).accepted
        assert validator.validate(
            email="synthetic.owner@example.test",
            password=PASSWORD,
            recovery_code=outcome.recovery_codes[0],
        ).accepted


@pytest.mark.integration
@pytest.mark.parametrize(
    ("password", "totp_code"),
    [
        ("wrong synthetic password", None),
        (None, "000000"),
        ("wrong synthetic password", "000000"),
    ],
)
def test_t066_rejected_credentials_count_once_and_preserve_all_existing_codes(
    regeneration_engine: Engine, password: str | None, totp_code: str | None
) -> None:
    _seed_account(regeneration_engine, with_previous_session=True)
    _seed_recovery_codes(regeneration_engine)
    request_code = totp_code or pyotp.TOTP(SECRET.decode("ascii")).at(NOW)
    request_password = password or PASSWORD

    with regeneration_engine.begin() as connection:
        outcome = _operation(connection).regenerate(
            account_id=1,
            current_password=request_password,
            totp_code=request_code,
        )

    assert outcome.status == "invalid_credentials"
    with regeneration_engine.connect() as connection:
        assert connection.execute(
            select(RecoveryCode.status).order_by(RecoveryCode.position)
        ).scalars().all() == ["used"] + ["active"] * 9
        assert connection.execute(select(AdminSession.status)).scalar_one() == "active"
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 0
        assert connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one() == 1
        assert connection.execute(
            select(AdminAuditEvent.action, AdminAuditEvent.result)
        ).all() == [("recovery_code_regeneration", "failed")]
        assert connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one() == 0


@pytest.mark.integration
def test_t066_rollback_preserves_entire_old_batch_and_related_security_state(
    regeneration_engine: Engine,
) -> None:
    _seed_account(regeneration_engine, with_previous_session=True)
    _seed_recovery_codes(regeneration_engine)
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)

    with pytest.raises(RuntimeError, match="synthetic audit write failure"):
        with regeneration_engine.begin() as connection:
            _operation(connection, failing_audit=True).regenerate(
                account_id=1, current_password=PASSWORD, totp_code=code
            )

    with regeneration_engine.connect() as connection:
        assert connection.execute(
            select(RecoveryCode.status).order_by(RecoveryCode.position)
        ).scalars().all() == ["used"] + ["active"] * 9
        assert connection.execute(
            select(RecoveryCode.used_at).order_by(RecoveryCode.position)
        ).scalars().all() == [NOW] + [None] * 9
        assert connection.execute(
            select(RecoveryCode.invalidated_at).order_by(RecoveryCode.position)
        ).scalars().all() == [None] * 10
        assert connection.execute(select(AdminSession.status)).scalar_one() == "active"
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 0
        assert connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one() == 0
        assert connection.execute(
            select(func.count()).select_from(AdminAuditEvent)
        ).scalar_one() == 0
        assert connection.execute(
            select(func.count()).select_from(SecurityNotificationDelivery)
        ).scalar_one() == 0


@pytest.mark.integration
def test_t066_consumed_totp_cannot_be_reused_to_replace_the_new_batch(
    regeneration_engine: Engine,
) -> None:
    _seed_account(regeneration_engine)
    _seed_recovery_codes(regeneration_engine)
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)

    with regeneration_engine.begin() as connection:
        first = _operation(connection).regenerate(
            account_id=1, current_password=PASSWORD, totp_code=code
        )
    with regeneration_engine.begin() as connection:
        second = _operation(connection).regenerate(
            account_id=1, current_password=PASSWORD, totp_code=code
        )

    assert first.status == "regenerated"
    assert second.status == "invalid_credentials"
    with regeneration_engine.connect() as connection:
        assert connection.execute(
            select(RecoveryCode.status).order_by(RecoveryCode.recovery_code_id)
        ).scalars().all() == ["invalidated"] * 10 + ["active"] * 10
        assert connection.execute(select(func.count()).select_from(TotpPeriodUse)).scalar_one() == 1
        assert connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one() == 1


@pytest.mark.integration
@pytest.mark.parametrize("delivery_outcome", ["accepted", "failed"])
def test_t066_security_notice_is_attempted_after_commit_without_exposing_codes(
    regeneration_engine: Engine, monkeypatch, delivery_outcome: str
) -> None:
    _seed_account(regeneration_engine)
    _seed_recovery_codes(regeneration_engine)
    monkeypatch.setattr(
        recovery_code_web,
        "_compose_regeneration",
        lambda connection, **_kwargs: _operation(connection),
    )
    sender = EmailSimulator(outcome=delivery_outcome)
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)

    outcome = recovery_code_web._PostgresRecoveryCodeRegenerationOperation(
        regeneration_engine, email_sender=sender
    ).regenerate(account_id=1, current_password=PASSWORD, totp_code=code)

    assert outcome.status == "regenerated"
    assert len(sender.notifications) == 1
    notice = sender.notifications[0]
    assert notice.recipient == "synthetic.owner@example.test"
    assert all(recovery_code not in notice.content for recovery_code in outcome.recovery_codes)
    with regeneration_engine.connect() as connection:
        assert connection.execute(
            select(SecurityNotificationDelivery.status)
        ).scalar_one() == delivery_outcome
        assert connection.execute(
            select(RecoveryCode.status).order_by(RecoveryCode.recovery_code_id)
        ).scalars().all() == ["invalidated"] * 10 + ["active"] * 10

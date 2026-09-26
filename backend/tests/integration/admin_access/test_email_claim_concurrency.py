"""T076 cross-flow email-claim races against PostgreSQL unique constraints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pyotp
import pytest
from sqlalchemy import Engine, insert, select

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.staff_activation import (
    CompleteStaffActivation,
    PrepareStaffActivationSetup,
    StaffActivationOutcome,
)
from backend.app.application.admin_access.staff_invitation import (
    CreateStaffInvitation,
    StaffInvitationError,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    AdminSession,
    PendingSecuritySetup,
    RecoveryCode as RecoveryCodeModel,
    SecurityLink,
    TotpFactor as TotpFactorModel,
    TotpPeriodUse,
)
from backend.app.infrastructure.persistence.pending_totp_setup_repository import PostgresPendingTotpSetupStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.staff_activation_repository import PostgresStaffActivationStore
from backend.app.infrastructure.persistence.staff_invitation_repository import PostgresStaffInvitationStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.tests.integration.admin_access.test_admin_login_session import (
    EMAIL,
    NOW,
    PASSWORD,
    SECRET,
    _ring,
    _seed_account,
    migrated_engine,
)
from backend.tests.integration.admin_access.test_own_email_change_request import (
    _RecordingSender,
    _postgres_operation,
)


TARGET_EMAIL = "synthetic.racing-claim@example.test"
STAFF_PASSWORD = "synthetic staff phrase 2036"


class _AllowedPasswords:
    def contains(self, password: str) -> bool:
        return False


def _email_protector() -> AdministrativeEmailProtector:
    return AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SystemSecretGenerator()
    )


def _invite(engine: Engine, *, email: str, entropy_seed: int):
    with engine.begin() as connection:
        entropy = SequenceSecretGenerator((bytes((entropy_seed,)) * 32,))
        return CreateStaffInvitation(
            store=PostgresStaffInvitationStore(connection),
            email_protector=_email_protector(),
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=entropy,
                protector=SecurityLinkProtector(key_ring=_ring()),
            ),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            ),
        ).invite(actor=AdministrativeActor(account_id=1, role="owner"), email=email)


def _start_pending_staff_activation(engine: Engine) -> tuple[int, bytes, str]:
    email = _email_protector().protect(TARGET_EMAIL)
    invitation_token = b"\xd4" * 32
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(role="staff", status="pending")
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=email.lookup_digest,
                email_ciphertext=email.email_ciphertext,
                key_version=email.key_version,
            )
        )
        lifecycle = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(NOW),
            secret_generator=SequenceSecretGenerator((invitation_token,)),
            protector=SecurityLinkProtector(key_ring=_ring()),
        )
        link = lifecycle.issue(account_id=account_id, purpose="invitation")
        PostgresSecurityLinkStore(connection).mark_delivery_accepted(
            link_id=link.stored_link.link_id, current_time=NOW
        )

    with engine.begin() as connection:
        prepared = PrepareStaffActivationSetup(
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SystemSecretGenerator(),
                protector=SecurityLinkProtector(key_ring=_ring()),
            ),
            setup_store=PostgresPendingTotpSetupStore(connection),
            totp=TotpAuthenticator(
                secret_generator=SequenceSecretGenerator((b"\xd5" * 20,))
            ),
            protector=PendingTotpProtector(
                key_ring=_ring(),
                secret_generator=SequenceSecretGenerator((b"\xd6" * 12,)),
            ),
            clock=FixedClock(NOW),
        ).prepare(token=invitation_token)
    return account_id, invitation_token, pyotp.TOTP(prepared.manual_key).at(NOW)


def _activate(engine: Engine, *, token: bytes, code: str) -> StaffActivationOutcome:
    ring = _ring()
    with engine.begin() as connection:
        return CompleteStaffActivation(
            link_lifecycle=SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=FixedClock(NOW),
                secret_generator=SystemSecretGenerator(),
                protector=SecurityLinkProtector(key_ring=ring),
            ),
            store=PostgresStaffActivationStore(connection),
            blocked_passwords=_AllowedPasswords(),
            password_hasher=AdministrativePasswordHasher(),
            pending_totp_protector=PendingTotpProtector(
                key_ring=ring, secret_generator=SystemSecretGenerator()
            ),
            factor_protector=TotpFactorProtector(
                key_ring=ring, secret_generator=SystemSecretGenerator()
            ),
            totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),
            recovery_codes=RecoveryCodeService(
                secret_generator=SystemSecretGenerator(),
                protector=RecoveryCodeProtector(key_ring=ring),
            ),
            audit=RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=FixedClock(NOW),
            ),
            clock=FixedClock(NOW),
        ).complete(token=token, password=STAFF_PASSWORD, totp_code=code)


def _change_email(engine: Engine, *, sender: _RecordingSender) -> str:
    return _postgres_operation(engine, now=NOW, sender=sender).request(
        account_id=1,
        new_email=TARGET_EMAIL,
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    )


@pytest.mark.integration
def test_t076_invitation_and_email_change_race_leave_one_claim_and_no_loser_artifacts(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    barrier = Barrier(2)
    sender = _RecordingSender()

    def invite() -> str:
        barrier.wait(timeout=10)
        try:
            _invite(migrated_engine, email=TARGET_EMAIL, entropy_seed=0xD1)
            return "invited"
        except StaffInvitationError:
            return "rejected"

    def change() -> str:
        barrier.wait(timeout=10)
        return _change_email(migrated_engine, sender=sender)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda call: call(), (invite, change)))

    assert sum(outcome in {"invited", "reserved"} for outcome in outcomes) == 1
    assert sum(outcome in {"rejected", "unavailable"} for outcome in outcomes) == 1
    with migrated_engine.connect() as connection:
        accounts = connection.execute(
            select(AdminAccount.role, AdminAccount.status).order_by(
                AdminAccount.admin_account_id
            )
        ).all()
        claims = connection.execute(
            select(
                AdminEmailClaim.admin_account_id,
                AdminEmailClaim.claim_kind,
                AdminEmailClaim.lookup_digest,
            ).where(
                AdminEmailClaim.lookup_digest
                == _email_protector().lookup_digest(TARGET_EMAIL)
            )
        ).all()
        links = connection.execute(
            select(SecurityLink.purpose, SecurityLink.status).where(
                SecurityLink.admin_account_id != 1
            )
        ).all()
        expected_accounts = [("owner", "active")]
        if "invited" in outcomes:
            expected_accounts.append(("staff", "pending"))
        assert accounts == expected_accounts
        assert len(claims) == 1
        if "invited" in outcomes:
            assert claims[0][1] == "current"
            assert links == [("invitation", "active")]
            assert connection.execute(
                select(AdminEmailClaim.claim_kind).where(
                    AdminEmailClaim.admin_account_id == 1
                )
            ).scalars().all() == ["current"]
        else:
            assert claims[0][1] == "reserved"
            assert links == []
            assert connection.execute(
                select(AdminAccount.admin_account_id).where(AdminAccount.role == "staff")
            ).scalars().all() == []
        assert connection.execute(
            select(AdminSession.admin_session_id)
        ).scalars().all() == []
        assert connection.execute(
            select(TotpPeriodUse.admin_account_id).where(
                TotpPeriodUse.admin_account_id == 1
            )
        ).scalars().all() == ([1] if "reserved" in outcomes else [])


@pytest.mark.integration
def test_t076_activation_wins_against_simultaneous_invitation_and_email_change_claims(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    staff_id, token, code = _start_pending_staff_activation(migrated_engine)
    barrier = Barrier(3)
    sender = _RecordingSender()

    def activate() -> str:
        barrier.wait(timeout=10)
        outcome = _activate(migrated_engine, token=token, code=code)
        return "activated" if outcome.rejection is None else "rejected"

    def invite() -> str:
        barrier.wait(timeout=10)
        try:
            _invite(migrated_engine, email=TARGET_EMAIL, entropy_seed=0xD2)
            return "invited"
        except StaffInvitationError:
            return "rejected"

    def change() -> str:
        barrier.wait(timeout=10)
        return _change_email(migrated_engine, sender=sender)

    with ThreadPoolExecutor(max_workers=3) as executor:
        outcomes = tuple(executor.map(lambda call: call(), (activate, invite, change)))

    assert outcomes.count("activated") == 1
    assert all(outcome in {"activated", "rejected", "unavailable"} for outcome in outcomes)
    assert sum(outcome in {"rejected", "unavailable"} for outcome in outcomes) == 2
    with migrated_engine.connect() as connection:
        state = connection.execute(
            select(
                AdminAccount.status,
                SecurityLink.status,
                PendingSecuritySetup.status,
                AdminEmailClaim.claim_kind,
            )
            .join(
                SecurityLink,
                SecurityLink.admin_account_id == AdminAccount.admin_account_id,
            )
            .join(
                PendingSecuritySetup,
                PendingSecuritySetup.admin_account_id == AdminAccount.admin_account_id,
            )
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(AdminAccount.admin_account_id == staff_id)
        ).one()
        assert tuple(state) == ("active", "consumed", "confirmed", "current")
        assert connection.execute(
            select(AdminEmailClaim.admin_account_id).where(
                AdminEmailClaim.lookup_digest
                == _email_protector().lookup_digest(TARGET_EMAIL)
            )
        ).scalars().all() == [staff_id]
        assert connection.execute(
            select(AdminEmailClaim.claim_kind).where(AdminEmailClaim.admin_account_id == 1)
        ).scalars().all() == ["current"]
        assert len(
            connection.execute(
                select(TotpFactorModel.totp_factor_id).where(
                    TotpFactorModel.admin_account_id == staff_id,
                    TotpFactorModel.status == "active",
                )
            ).scalars().all()
        ) == 1
        assert len(
            connection.execute(
                select(RecoveryCodeModel.recovery_code_id).where(
                    RecoveryCodeModel.admin_account_id == staff_id,
                    RecoveryCodeModel.status == "active",
                )
            ).scalars().all()
        ) == 10
        assert connection.execute(
            select(AdminAccount.admin_account_id).where(AdminAccount.role == "staff")
        ).scalars().all() == [staff_id]
        assert connection.execute(
            select(AdminSession.admin_session_id).where(
                AdminSession.admin_account_id == staff_id
            )
        ).scalars().all() == []
        assert connection.execute(
            select(TotpPeriodUse.admin_account_id).order_by(
                TotpPeriodUse.admin_account_id
            )
        ).scalars().all() == [staff_id]

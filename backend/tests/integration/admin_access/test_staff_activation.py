"""T038 PostgreSQL evidence for atomic invited-staff activation."""
from __future__ import annotations
import base64
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
import pyotp, pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, text
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.staff_activation import CompleteStaffActivation, PrepareStaffActivationSetup
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim
from backend.app.infrastructure.persistence.pending_totp_setup_repository import PostgresPendingTotpSetupStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.staff_activation_repository import PostgresStaffActivationStore
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue, load_test_database_url
from backend.app.web.admin_auth import staff_activation as staff_activation_web
from backend.app.web.admin_auth.staff_activation import _PostgresStaffActivationCompleter

REPOSITORY_ROOT=Path(__file__).resolve().parents[4]; NOW=datetime(2033,4,5,14,tzinfo=timezone.utc); TOKEN=b"\xc1"*32; PASSWORD="synthetic staff phrase 2033"
class AllowedPasswords:
    def contains(self,password:str)->bool: return False
@pytest.fixture()
def migrated_engine()->Iterator[Engine]:
    engine=create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config=Config(str(REPOSITORY_ROOT/"backend"/"alembic.ini")); config.attributes["connection"]=connection; command.upgrade(config,"head")
        with engine.begin() as c:
            c.execute(text("TRUNCATE TABLE security_notification_deliveries, admin_accounts, owner_bootstrap_state RESTART IDENTITY CASCADE")); c.execute(text("INSERT INTO owner_bootstrap_state (bootstrap_state_id,status) VALUES (1,'open')"))
        yield engine
    finally: engine.dispose()
def _ring(): return CryptographyKeyRing(CryptographyKeyConfiguration(root_key=SecretValue(base64.urlsafe_b64encode(b"\xc2"*32).decode("ascii")),key_version="v1"))
def _lifecycle(c): return SecurityLinkLifecycle(store=PostgresSecurityLinkStore(c),clock=FixedClock(NOW),secret_generator=SequenceSecretGenerator((TOKEN,)),protector=SecurityLinkProtector(key_ring=_ring()))
def _seed(engine):
    with engine.begin() as c:
        account=c.execute(insert(AdminAccount).values(role="staff",status="pending").returning(AdminAccount.admin_account_id)).scalar_one()
        c.execute(insert(AdminEmailClaim).values(admin_account_id=account,claim_kind="current",lookup_digest=b"\xc3"*32,email_ciphertext=b"fixture",key_version="v1"))
        issued=_lifecycle(c).issue(account_id=account,purpose="invitation"); PostgresSecurityLinkStore(c).mark_delivery_accepted(link_id=issued.stored_link.link_id,current_time=NOW)
    return account
def _prepare(engine):
    with engine.begin() as c:
        return PrepareStaffActivationSetup(link_lifecycle=_lifecycle(c),setup_store=PostgresPendingTotpSetupStore(c),totp=TotpAuthenticator(secret_generator=SequenceSecretGenerator((b"\xc4"*20,))),protector=PendingTotpProtector(key_ring=_ring(),secret_generator=SequenceSecretGenerator((b"\xc5"*12,))),clock=FixedClock(NOW)).prepare(token=TOKEN)
def _complete(engine,code):
    with engine.begin() as c:
        ring=_ring(); return CompleteStaffActivation(link_lifecycle=_lifecycle(c),store=PostgresStaffActivationStore(c),blocked_passwords=AllowedPasswords(),password_hasher=AdministrativePasswordHasher(),pending_totp_protector=PendingTotpProtector(key_ring=ring,secret_generator=SystemSecretGenerator()),factor_protector=TotpFactorProtector(key_ring=ring,secret_generator=SystemSecretGenerator()),totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),recovery_codes=RecoveryCodeService(secret_generator=SystemSecretGenerator(),protector=RecoveryCodeProtector(key_ring=ring)),audit=RecordAdministrativeAuditEvent(store=PostgresAdministrativeAuditStore(c),clock=FixedClock(NOW)),clock=FixedClock(NOW)).complete(token=TOKEN,password=PASSWORD,totp_code=code)
@pytest.mark.integration
def test_t038_activates_pending_staff_with_own_password_totp_and_ten_codes_without_session(migrated_engine):
    account=_seed(migrated_engine); prepared=_prepare(migrated_engine); outcome=_complete(migrated_engine,pyotp.TOTP(prepared.manual_key).at(NOW))
    with migrated_engine.connect() as c:
        values=c.execute(text("SELECT status,password_hash FROM admin_accounts WHERE admin_account_id=:id"),{"id":account}).one(); link=c.execute(text("SELECT status FROM security_links")).scalar_one(); setup=c.execute(text("SELECT status,totp_secret_ciphertext FROM pending_security_setups")).one(); counts=c.execute(text("SELECT (SELECT count(*) FROM totp_factors),(SELECT count(*) FROM recovery_codes),(SELECT count(*) FROM admin_sessions)")).one()
    assert outcome.rejection is None and len(outcome.recovery_codes)==10
    assert values.status=="active" and AdministrativePasswordHasher().verify_and_upgrade(stored_hash=values.password_hash,password=PASSWORD).verified
    assert link=="consumed" and tuple(setup)==("confirmed",None) and counts==(1,10,0)


@pytest.mark.integration
def test_t065_activation_returns_recovery_codes_only_on_the_first_successful_completion(
    migrated_engine,
):
    account = _seed(migrated_engine)
    prepared = _prepare(migrated_engine)
    code = pyotp.TOTP(prepared.manual_key).at(NOW)

    first = _complete(migrated_engine, code)
    repeated = _complete(migrated_engine, code)

    with migrated_engine.connect() as connection:
        state = connection.execute(
            text(
                "SELECT "
                "(SELECT status FROM security_links WHERE purpose = 'invitation'), "
                "(SELECT count(*) FROM recovery_codes WHERE admin_account_id = :id), "
                "(SELECT count(*) FROM admin_sessions WHERE admin_account_id = :id)"
            ),
            {"id": account},
        ).one()
    assert first.rejection is None
    assert len(first.recovery_codes) == 10
    assert repeated.rejection == "unavailable"
    assert repeated.recovery_codes == ()
    assert tuple(state) == ("consumed", 10, 0)


class _ActivationNoticeSender:
    def __init__(self) -> None:
        self.notifications: list[OutboundNotification] = []

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        self.notifications.append(notification)
        return NotificationSendResult.accepted(notification.channel)


@pytest.mark.integration
def test_t096_staff_activation_notifies_only_owner_without_credentials(
    migrated_engine, monkeypatch
):
    owner_email = "synthetic.owner@example.test"
    staff_email = "synthetic.staff@example.test"
    protector = AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SystemSecretGenerator()
    )
    owner_claim = protector.protect(owner_email)
    staff_claim = protector.protect(staff_email)
    with migrated_engine.begin() as connection:
        owner_id = connection.execute(
            insert(AdminAccount).values(role="owner", status="active").returning(
                AdminAccount.admin_account_id
            )
        ).scalar_one()
        staff_id = connection.execute(
            insert(AdminAccount).values(role="staff", status="pending").returning(
                AdminAccount.admin_account_id
            )
        ).scalar_one()
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=owner_id,
                claim_kind="current",
                lookup_digest=owner_claim.lookup_digest,
                email_ciphertext=owner_claim.email_ciphertext,
                key_version=owner_claim.key_version,
            )
        )
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=staff_id,
                claim_kind="current",
                lookup_digest=staff_claim.lookup_digest,
                email_ciphertext=staff_claim.email_ciphertext,
                key_version=staff_claim.key_version,
            )
        )
        issued = _lifecycle(connection).issue(
            account_id=staff_id, purpose="invitation"
        )
        PostgresSecurityLinkStore(connection).mark_delivery_accepted(
            link_id=issued.stored_link.link_id, current_time=NOW
        )

    prepared = _prepare(migrated_engine)
    monkeypatch.setattr(staff_activation_web, "_components", lambda: (FixedClock(NOW), _ring()))
    monkeypatch.setattr(
        staff_activation_web.BlockedPasswordList,
        "load",
        classmethod(lambda _cls, *, clock: AllowedPasswords()),
    )
    sender = _ActivationNoticeSender()
    outcome = _PostgresStaffActivationCompleter(
        engine=migrated_engine, email_sender=sender
    ).complete(
        token=TOKEN,
        password="Q7!synthetic-Staff-Activation-2033-zebra",
        totp_code=pyotp.TOTP(prepared.manual_key).at(NOW),
    )

    assert outcome.rejection is None
    assert len(outcome.recovery_codes) == 10
    assert len(sender.notifications) == 1
    notice = sender.notifications[0]
    assert notice.recipient == owner_email
    assert notice.recipient != staff_email
    assert notice.channel == EMAIL_CHANNEL
    assert "token" not in notice.content.lower()
    assert "código" not in notice.content.lower()
    assert "contraseña" not in notice.content.lower()
    assert all(code not in notice.content for code in outcome.recovery_codes)
    with migrated_engine.connect() as connection:
        delivery = connection.execute(
            text(
                "SELECT event, template, status, sanitized_error "
                "FROM security_notification_deliveries"
            )
        ).one()
    assert tuple(delivery) == (
        "staff_activated",
        "staff_activation_notice",
        "accepted",
        None,
    )


@pytest.mark.integration
def test_t040_two_concurrent_staff_activations_allow_exactly_one_complete_winner(
    migrated_engine,
):
    account = _seed(migrated_engine)
    prepared = _prepare(migrated_engine)
    code = pyotp.TOTP(prepared.manual_key).at(NOW)
    barrier = Barrier(2)

    def activate():
        barrier.wait(timeout=10)
        return _complete(migrated_engine, code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: activate(), range(2)))

    with migrated_engine.connect() as connection:
        final_state = connection.execute(
            text(
                "SELECT "
                "(SELECT status FROM admin_accounts WHERE admin_account_id = :id), "
                "(SELECT status FROM security_links), "
                "(SELECT status FROM pending_security_setups), "
                "(SELECT count(*) FROM totp_factors), "
                "(SELECT count(*) FROM recovery_codes), "
                "(SELECT count(*) FROM admin_audit_events), "
                "(SELECT count(*) FROM admin_sessions)"
            ),
            {"id": account},
        ).one()

    assert sum(outcome.rejection is None for outcome in outcomes) == 1
    assert sum(outcome.rejection == "unavailable" for outcome in outcomes) == 1
    assert tuple(final_state) == ("active", "consumed", "confirmed", 1, 10, 1, 0)

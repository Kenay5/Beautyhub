"""T072 PostgreSQL evidence for own-email reservation and transaction boundaries."""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pyotp
import pytest
from sqlalchemy import Engine, insert, select

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.request_own_email_change import (
    RequestOwnAdministrativeEmailChange,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
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
    AdminAuditEvent,
    AdminCredentialFailureEvent,
    AdminEmailClaim,
    SecurityLink,
    TotpPeriodUse,
)
from backend.app.infrastructure.persistence.own_email_change_repository import (
    PostgresOwnEmailChangeStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
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
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
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
from backend.app.web.admin_auth.own_email_change import (
    _PostgresOwnEmailChangeOperation,
)
from backend.app.web.admin_auth.security_link_transport import decode_security_link_token


def _operation(connection) -> RequestOwnAdministrativeEmailChange:
    clock = FixedClock(NOW)
    entropy = SystemSecretGenerator()
    ring = _ring()
    security = PostgresAdministrativeAccountSecurityStore(connection)
    email_protector = AdministrativeEmailProtector(
        key_ring=ring, secret_generator=entropy
    )
    audit = RecordAdministrativeAuditEvent(
        store=PostgresAdministrativeAuditStore(connection), clock=clock
    )
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(
            key_ring=ring, secret_generator=entropy
        ),
    )
    return RequestOwnAdministrativeEmailChange(
        store=PostgresOwnEmailChangeStore(connection),
        email_protector=email_protector,
        credential_guard=EnsureAdministrativeCredentialCheck(
            store=security, clock=clock
        ),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(
                store=security, clock=clock
            ),
            audit=audit,
            notifications=notifications,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection, email_protector=email_protector
            ),
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=ring, secret_generator=entropy
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        audit=audit,
        clock=clock,
    )


def _code() -> str:
    return pyotp.TOTP(SECRET.decode("ascii")).at(NOW)


class _RecordingSender:
    def __init__(self, *, outcome: str = "accepted") -> None:
        self.outcome = outcome
        self.notifications: list[OutboundNotification] = []
        self._lock = threading.Lock()

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        with self._lock:
            self.notifications.append(notification)
        if self.outcome == "accepted":
            return NotificationSendResult.accepted(EMAIL_CHANNEL)
        if self.outcome == "rejected":
            return NotificationSendResult.failed("whatsapp")
        if self.outcome == "exception":
            raise RuntimeError("synthetic delivery failure")
        return NotificationSendResult.failed(EMAIL_CHANNEL)


def _postgres_operation(
    engine: Engine,
    *,
    now,
    sender: _RecordingSender,
    entropy: SequenceSecretGenerator | None = None,
) -> _PostgresOwnEmailChangeOperation:
    return _PostgresOwnEmailChangeOperation(
        engine=engine,
        email_sender=sender,
        clock=FixedClock(now),
        entropy=entropy or SequenceSecretGenerator((b"\xa1" * 12, b"\xa2" * 32)),
        key_ring=_ring(),
    )


def _captured_token(sender: _RecordingSender) -> bytes:
    match = re.search(r"#token=([A-Za-z0-9_-]{43})", sender.notifications[-1].content)
    assert match is not None
    return decode_security_link_token(match.group(1))


def _seed_pending_staff_claim(engine: Engine, email_value: str) -> int:
    email = AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SystemSecretGenerator()
    ).protect(email_value)
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
    return account_id


@pytest.mark.integration
def test_t072_reserves_trimmed_casefolded_email_without_changing_current_or_other_account(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    other_account_id = _seed_pending_staff_claim(
        migrated_engine, "synthetic.pending@example.test"
    )
    requested = "  New.Owner+alias@Example.test  "
    with migrated_engine.begin() as connection:
        outcome = _operation(connection).request(
            account_id=1,
            new_email=requested,
            current_password=PASSWORD,
            totp_code=_code(),
        )

    assert outcome == "reserved"
    with migrated_engine.connect() as connection:
        claims = connection.execute(
            select(
                AdminEmailClaim.admin_account_id,
                AdminEmailClaim.claim_kind,
                AdminEmailClaim.lookup_digest,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            ).order_by(AdminEmailClaim.admin_email_claim_id)
        ).all()
        reserved = [row for row in claims if row.claim_kind == "reserved"]
        assert len(reserved) == 1
        assert reserved[0].admin_account_id == 1
        protector = AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        )
        assert protector.decrypt(
            email_ciphertext=reserved[0].email_ciphertext,
            key_version=reserved[0].key_version,
        ) == "new.owner+alias@example.test"
        assert reserved[0].lookup_digest == protector.lookup_digest(
            "new.owner+alias@example.test"
        )
        current = next(row for row in claims if row.admin_account_id == 1 and row.claim_kind == "current")
        assert current.lookup_digest == protector.lookup_digest(EMAIL)
        other = next(row for row in claims if row.admin_account_id == other_account_id)
        assert other.claim_kind == "current"
        assert connection.execute(select(TotpPeriodUse.admin_account_id)).scalars().all() == [1]


@pytest.mark.integration
def test_t072_rejects_email_owned_by_another_account_without_partial_reservation(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    occupied_email = "synthetic.pending@example.test"
    _seed_pending_staff_claim(migrated_engine, occupied_email)

    with migrated_engine.begin() as connection:
        outcome = _operation(connection).request(
            account_id=1,
            new_email=occupied_email.upper(),
            current_password=PASSWORD,
            totp_code=_code(),
        )

    assert outcome == "unavailable"
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminEmailClaim.admin_account_id).where(
                AdminEmailClaim.claim_kind == "reserved"
            )
        ).scalars().all() == []
        assert connection.execute(select(TotpPeriodUse.totp_period_use_id)).scalars().all() == []
        assert connection.execute(
            select(AdminEmailClaim.lookup_digest).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "current",
            )
        ).scalar_one() == AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        ).lookup_digest(EMAIL)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("password", "code"),
    [("incorrect password", _code()), (PASSWORD, "000000")],
)
def test_t072_invalid_password_or_totp_does_not_reserve_or_consume_factor(
    migrated_engine: Engine, password: str, code: str
) -> None:
    _seed_account(migrated_engine)
    with migrated_engine.begin() as connection:
        outcome = _operation(connection).request(
            account_id=1,
            new_email="synthetic.new@example.test",
            current_password=password,
            totp_code=code,
        )

    assert outcome == "invalid_credentials"
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminEmailClaim.claim_kind).where(
                AdminEmailClaim.admin_account_id == 1
            )
        ).scalars().all() == ["current"]
        assert connection.execute(select(TotpPeriodUse.totp_period_use_id)).scalars().all() == []
        assert connection.execute(
            select(AdminCredentialFailureEvent.operation)
        ).scalars().all() == ["email_change"]


@pytest.mark.integration
def test_t073_replaces_previous_per_account_reservation_without_changing_current_email(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    other_account_id = _seed_pending_staff_claim(
        migrated_engine, "synthetic.pending@example.test"
    )
    reserved = AdministrativeEmailProtector(
        key_ring=_ring(), secret_generator=SystemSecretGenerator()
    ).protect("synthetic.previous@example.test")
    with migrated_engine.begin() as connection:
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=1,
                claim_kind="reserved",
                lookup_digest=reserved.lookup_digest,
                email_ciphertext=reserved.email_ciphertext,
                key_version=reserved.key_version,
            )
        )
        outcome = _operation(connection).request(
            account_id=1,
            new_email="synthetic.new@example.test",
            current_password=PASSWORD,
            totp_code=_code(),
        )

    assert outcome == "reserved"
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(AdminEmailClaim.lookup_digest).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "reserved",
            )
        ).scalar_one() == AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        ).lookup_digest("synthetic.new@example.test")
        assert connection.execute(
            select(AdminEmailClaim.lookup_digest).where(
                AdminEmailClaim.admin_account_id == other_account_id,
                AdminEmailClaim.claim_kind == "current",
            )
        ).scalar_one() == AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        ).lookup_digest("synthetic.pending@example.test")
        assert connection.execute(select(TotpPeriodUse.totp_period_use_id)).scalars().all()
        assert connection.execute(
            select(AdminAuditEvent.result).where(AdminAuditEvent.action == "email_change")
        ).scalars().all() == []


@pytest.mark.integration
def test_t073_emits_one_opaque_30_minute_link_and_replaces_the_previous_claim(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    first_sender = _RecordingSender()
    first_operation = _postgres_operation(
        migrated_engine,
        now=NOW,
        sender=first_sender,
    )
    assert first_operation.request(
        account_id=1,
        new_email="synthetic.first@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    ) == "reserved"
    first_token = _captured_token(first_sender)

    replacement_time = NOW + timedelta(seconds=30)
    second_sender = _RecordingSender()
    second_operation = _postgres_operation(
        migrated_engine,
        now=replacement_time,
        sender=second_sender,
        entropy=SequenceSecretGenerator((b"\xa3" * 12, b"\xa4" * 32)),
    )
    assert second_operation.request(
        account_id=1,
        new_email="synthetic.second@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(replacement_time),
    ) == "reserved"
    second_token = _captured_token(second_sender)

    assert second_token != first_token
    assert "/admin/email-change#token=" in second_sender.notifications[0].content
    assert "30 minutos" in second_sender.notifications[0].content
    assert second_sender.notifications[0].recipient == "synthetic.second@example.test"
    protector = SecurityLinkProtector(key_ring=_ring())
    with migrated_engine.connect() as connection:
        links = connection.execute(
            select(SecurityLink.status, SecurityLink.delivery_status, SecurityLink.expires_at)
            .where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
            )
            .order_by(SecurityLink.security_link_id)
        ).all()
        assert [row.status for row in links] == ["invalidated", "active"]
        assert links[1].delivery_status == "accepted"
        assert links[1].expires_at == replacement_time + timedelta(minutes=30)
        assert len(connection.execute(
            select(SecurityLink.security_link_id).where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
                SecurityLink.status == "active",
            )
        ).scalars().all()) == 1
        stored_digests = connection.execute(
            select(SecurityLink.token_digest).where(
                SecurityLink.purpose == "email_change"
            )
        ).scalars().all()
        assert protector.digest(first_token) in stored_digests
        assert protector.digest(second_token) in stored_digests
        claims = connection.execute(
            select(AdminEmailClaim.claim_kind, AdminEmailClaim.email_ciphertext)
            .where(AdminEmailClaim.admin_account_id == 1)
        ).all()
        assert [claim.claim_kind for claim in claims].count("current") == 1
        assert [claim.claim_kind for claim in claims].count("reserved") == 1
        assert connection.execute(
            select(AdminEmailClaim.lookup_digest).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "current",
            )
        ).scalar_one() == AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        ).lookup_digest(EMAIL)


@pytest.mark.integration
def test_t073_expired_email_change_link_is_reissued_with_a_full_lifetime(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    first_sender = _RecordingSender()
    _postgres_operation(migrated_engine, now=NOW, sender=first_sender).request(
        account_id=1,
        new_email="synthetic.first@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    )
    first_token = _captured_token(first_sender)

    reissue_time = NOW + timedelta(minutes=30)
    second_sender = _RecordingSender()
    _postgres_operation(
        migrated_engine,
        now=reissue_time,
        sender=second_sender,
        entropy=SequenceSecretGenerator((b"\xa5" * 12, b"\xa6" * 32)),
    ).request(
        account_id=1,
        new_email="synthetic.reissued@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(reissue_time),
    )
    second_token = _captured_token(second_sender)

    assert second_token != first_token
    with migrated_engine.connect() as connection:
        links = connection.execute(
            select(SecurityLink.status, SecurityLink.expires_at)
            .where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
            )
            .order_by(SecurityLink.security_link_id)
        ).all()
        assert [link.status for link in links] == ["expired", "active"]
        assert links[1].expires_at == reissue_time + timedelta(minutes=30)
        assert connection.execute(
            select(AdminEmailClaim.lookup_digest).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "reserved",
            )
        ).scalar_one() == AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        ).lookup_digest("synthetic.reissued@example.test")


@pytest.mark.integration
def test_t073_failed_delivery_retires_only_its_link_and_releases_its_reservation(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    sender = _RecordingSender(outcome="failed")

    outcome = _postgres_operation(migrated_engine, now=NOW, sender=sender).request(
        account_id=1,
        new_email="synthetic.delivery-failure@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    )

    assert outcome == "delivery_failed"
    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(SecurityLink.status, SecurityLink.delivery_status).where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
            )
        ).all() == [("invalidated", "failed")]
        assert connection.execute(
            select(AdminEmailClaim.claim_kind).where(
                AdminEmailClaim.admin_account_id == 1
            )
        ).scalars().all() == ["current"]


@pytest.mark.integration
@pytest.mark.parametrize("failure", ("failed", "rejected", "exception"))
def test_t074_delivery_failure_preserves_old_email_and_allows_a_fresh_retry(
    migrated_engine: Engine, failure: str
) -> None:
    _seed_account(migrated_engine)
    failed_sender = _RecordingSender(outcome=failure)
    failed_operation = _postgres_operation(
        migrated_engine, now=NOW, sender=failed_sender
    )

    assert failed_operation.request(
        account_id=1,
        new_email="synthetic.failed-attempt@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    ) == "delivery_failed"
    failed_token = _captured_token(failed_sender)

    retry_time = NOW + timedelta(seconds=30)
    accepted_sender = _RecordingSender()
    accepted_operation = _postgres_operation(
        migrated_engine,
        now=retry_time,
        sender=accepted_sender,
        entropy=SequenceSecretGenerator((b"\xc1" * 12, b"\xc2" * 32)),
    )
    assert accepted_operation.request(
        account_id=1,
        new_email="synthetic.successful-retry@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(retry_time),
    ) == "reserved"
    accepted_token = _captured_token(accepted_sender)
    assert accepted_token != failed_token

    with migrated_engine.begin() as connection:
        lifecycle = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(retry_time),
            secret_generator=SystemSecretGenerator(),
            protector=SecurityLinkProtector(key_ring=_ring()),
        )
        assert lifecycle.inspect(token=failed_token, purpose="email_change") is None
        assert lifecycle.consume(token=failed_token, purpose="email_change") is None
        assert lifecycle.inspect(token=accepted_token, purpose="email_change") is not None

    with migrated_engine.connect() as connection:
        links = connection.execute(
            select(SecurityLink.status, SecurityLink.delivery_status)
            .where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
            )
            .order_by(SecurityLink.security_link_id)
        ).all()
        assert links == [("invalidated", "failed"), ("active", "accepted")]
        claims = connection.execute(
            select(AdminEmailClaim.claim_kind, AdminEmailClaim.lookup_digest)
            .where(AdminEmailClaim.admin_account_id == 1)
            .order_by(AdminEmailClaim.claim_kind)
        ).all()
        email_protector = AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        )
        assert [(kind, digest) for kind, digest in claims] == [
            ("current", email_protector.lookup_digest(EMAIL)),
            ("reserved", email_protector.lookup_digest("synthetic.successful-retry@example.test")),
        ]


@pytest.mark.integration
def test_t074_invalid_and_expired_links_cannot_change_email_and_expiry_releases_claim(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    sender = _RecordingSender()
    assert _postgres_operation(migrated_engine, now=NOW, sender=sender).request(
        account_id=1,
        new_email="synthetic.expiring-email@example.test",
        current_password=PASSWORD,
        totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
    ) == "reserved"
    token = _captured_token(sender)

    with migrated_engine.begin() as connection:
        lifecycle = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(NOW),
            secret_generator=SystemSecretGenerator(),
            protector=SecurityLinkProtector(key_ring=_ring()),
        )
        assert lifecycle.inspect(token=b"not-a-valid-link-token", purpose="email_change") is None
        assert lifecycle.consume(token=b"not-a-valid-link-token", purpose="email_change") is None
        assert lifecycle.inspect(token=token[:-1] + bytes((token[-1] ^ 1,)), purpose="email_change") is None

    expired_time = NOW + timedelta(minutes=30)
    with migrated_engine.begin() as connection:
        lifecycle = SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=FixedClock(expired_time),
            secret_generator=SystemSecretGenerator(),
            protector=SecurityLinkProtector(key_ring=_ring()),
        )
        assert lifecycle.inspect(token=token, purpose="email_change") is None
        assert lifecycle.consume(token=token, purpose="email_change") is None

    with migrated_engine.connect() as connection:
        assert connection.execute(
            select(SecurityLink.status).where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
            )
        ).scalar_one() == "expired"
        claims = connection.execute(
            select(AdminEmailClaim.claim_kind, AdminEmailClaim.lookup_digest).where(
                AdminEmailClaim.admin_account_id == 1
            )
        ).all()
        assert claims == [("current", AdministrativeEmailProtector(
            key_ring=_ring(), secret_generator=SystemSecretGenerator()
        ).lookup_digest(EMAIL))]


@pytest.mark.integration
def test_t073_concurrent_requests_leave_at_most_one_active_link_and_reservation(
    migrated_engine: Engine,
) -> None:
    _seed_account(migrated_engine)
    barrier = Barrier(2)
    code = pyotp.TOTP(SECRET.decode("ascii")).at(NOW)
    operations = (
        _postgres_operation(
            migrated_engine,
            now=NOW,
            sender=_RecordingSender(),
            entropy=SequenceSecretGenerator((b"\xb1" * 12, b"\xb2" * 32)),
        ),
        _postgres_operation(
            migrated_engine,
            now=NOW,
            sender=_RecordingSender(),
            entropy=SequenceSecretGenerator((b"\xb3" * 12, b"\xb4" * 32)),
        ),
    )

    def request(index: int) -> str:
        barrier.wait()
        return operations[index].request(
            account_id=1,
            new_email=f"synthetic.concurrent-{index}@example.test",
            current_password=PASSWORD,
            totp_code=code,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(request, range(2)))

    assert sorted(outcomes) == ["invalid_credentials", "reserved"]
    with migrated_engine.connect() as connection:
        assert len(connection.execute(
            select(SecurityLink.security_link_id).where(
                SecurityLink.admin_account_id == 1,
                SecurityLink.purpose == "email_change",
                SecurityLink.status == "active",
            )
        ).scalars().all()) == 1
        assert len(connection.execute(
            select(AdminEmailClaim.admin_email_claim_id).where(
                AdminEmailClaim.admin_account_id == 1,
                AdminEmailClaim.claim_kind == "reserved",
            )
        ).scalars().all()) == 1
        assert connection.execute(
            select(AdminEmailClaim.claim_kind).where(
                AdminEmailClaim.admin_account_id == 1
            )
        ).scalars().all() == ["current", "reserved"]

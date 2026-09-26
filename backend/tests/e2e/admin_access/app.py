"""Local-only Playwright app using the isolated PostgreSQL test database."""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Engine, func, insert, select, text, update

from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    AdminSession,
    OwnerBootstrapState,
    RecoveryCode,
    SecurityLink,
    TotpFactor,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtector,
)
from backend.app.infrastructure.settings import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.web.admin_auth.staff_invitations import (
    PostgresStaffInvitationOperations,
    get_staff_invitation_operations,
)
from backend.app.web.admin_auth.own_email_change import (
    _PostgresOwnEmailChangeOperation,
    get_own_email_change_operation,
)
from backend.app.web.admin_auth.own_email_change_confirmation import (
    _PostgresOwnEmailChangeConfirmationOperation,
    get_own_email_change_confirmation_operation,
)
from backend.app.web.admin_auth.security_link_transport import SecurityLinkTokenBody


ROOT = Path(__file__).resolve().parents[4]
TEST_OWNER_EMAIL = "synthetic.owner@example.test"
TEST_OWNER_PASSWORD = "synthetic owner phrase for browser tests"
TEST_OWNER_TOTP_BASE32 = "JBSWY3DPEHPK3PXP"
TEST_OWNER_RECOVERY_CODE = "ABCDEFGHJKLMNPQR"

# Every route in this module is mounted only by the test-specific ASGI app.
_test_database_url = load_test_database_url().reveal()
os.environ[DATABASE_URL_ENVIRONMENT_VARIABLE] = _test_database_url
_engine = create_postgres_engine(load_test_database_url())
_key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
_email_protector = AdministrativeEmailProtector(
    key_ring=_key_ring,
    secret_generator=SystemSecretGenerator(),
)


@dataclass(frozen=True)
class _Mail:
    outcome: Literal["accepted", "failed"]
    recipient: str
    content: str


class _InvitationMailbox:
    """In-memory provider double exposed only by this test-only app."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_outcome: Literal["accepted", "failed"] = "accepted"
        self._messages: deque[_Mail] = deque()

    def reset(self) -> None:
        with self._lock:
            self._next_outcome = "accepted"
            self._messages.clear()

    def set_next_outcome(self, outcome: Literal["accepted", "failed"]) -> None:
        with self._lock:
            self._next_outcome = outcome

    def send(self, notification: OutboundNotification) -> NotificationSendResult:
        if notification.channel != EMAIL_CHANNEL:
            raise ValueError("invitation mailbox accepts email only.")
        with self._lock:
            outcome = self._next_outcome
            self._messages.append(
                _Mail(
                    outcome=outcome,
                    recipient=notification.recipient,
                    content=notification.content,
                )
            )
            self._next_outcome = "accepted"
        if outcome == "accepted":
            return NotificationSendResult.accepted(EMAIL_CHANNEL)
        return NotificationSendResult.failed(EMAIL_CHANNEL)

    def peek(self) -> _Mail | None:
        with self._lock:
            return self._messages[0] if self._messages else None

    def consume(self) -> _Mail | None:
        with self._lock:
            return self._messages.popleft() if self._messages else None


_mailbox = _InvitationMailbox()
_link_protector = SecurityLinkProtector(key_ring=_key_ring)


def _migrate_test_database() -> None:
    with _engine.connect() as connection:
        config = Config(str(ROOT / "backend" / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def _seed_owner() -> None:
    """Reset only the guarded beautyhub_test database and seed one synthetic owner."""

    _mailbox.reset()
    now = datetime.now(UTC)
    with _engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE admin_accounts, owner_bootstrap_state, "
                "security_notification_deliveries "
                "RESTART IDENTITY CASCADE"
            )
        )
        connection.execute(
            insert(OwnerBootstrapState).values(
                bootstrap_state_id=1,
                status="open",
            )
        )
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password(
                    TEST_OWNER_PASSWORD
                ),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        protected_email = _email_protector.protect(TEST_OWNER_EMAIL)
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=protected_email.lookup_digest,
                email_ciphertext=protected_email.email_ciphertext,
                key_version=protected_email.key_version,
            )
        )
        ciphertext = TotpFactorProtector(
            key_ring=_key_ring,
            secret_generator=SystemSecretGenerator(),
        ).encrypt(
            account_id=account_id,
            secret=TEST_OWNER_TOTP_BASE32.encode("ascii"),
        )
        connection.execute(
            insert(TotpFactor).values(
                admin_account_id=account_id,
                totp_secret_ciphertext=ciphertext,
                key_version=_key_ring.key_version,
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                status="active",
                confirmed_at=now,
            )
        )
        recovery_protector = RecoveryCodeProtector(key_ring=_key_ring)
        recovery_digest = recovery_protector.digest(TEST_OWNER_RECOVERY_CODE)
        connection.execute(
            insert(RecoveryCode).values(
                admin_account_id=account_id,
                lookup_digest=recovery_digest,
                key_version=recovery_protector.key_version,
                position=1,
                status="active",
            )
        )


_migrate_test_database()
_seed_owner()


def _test_invitation_operations():
    return PostgresStaffInvitationOperations(engine=_engine, email_sender=_mailbox)


def _test_own_email_change_operation():
    return _PostgresOwnEmailChangeOperation(engine=_engine, email_sender=_mailbox)


def _test_own_email_change_confirmation_operation():
    return _PostgresOwnEmailChangeConfirmationOperation(
        engine=_engine, email_sender=_mailbox
    )


app: FastAPI
from backend.app.web.app import create_app

app = create_app()
app.dependency_overrides[get_staff_invitation_operations] = _test_invitation_operations
app.dependency_overrides[get_own_email_change_operation] = _test_own_email_change_operation
app.dependency_overrides[
    get_own_email_change_confirmation_operation
] = _test_own_email_change_confirmation_operation

test_router = APIRouter(prefix="/__test__/staff-invitations", tags=["playwright-test-only"])


class _OutcomeBody(BaseModel):
    outcome: Literal["accepted", "failed"]


@test_router.post("/reset", status_code=204)
def reset_test_database() -> None:
    _seed_owner()


@test_router.put("/mailbox/outcome", status_code=204)
def set_mailbox_outcome(body: _OutcomeBody) -> None:
    _mailbox.set_next_outcome(body.outcome)


@test_router.get("/mailbox/peek")
def peek_mailbox() -> dict[str, str] | None:
    message = _mailbox.peek()
    if message is None:
        return None
    return {"outcome": message.outcome, "recipient": message.recipient}


@test_router.post("/mailbox/consume")
def consume_mailbox() -> dict[str, str]:
    message = _mailbox.consume()
    if message is None:
        raise HTTPException(status_code=404, detail="No test email is available.")
    return {
        "outcome": message.outcome,
        "recipient": message.recipient,
        "content": message.content,
    }


@test_router.get("/accounts/by-email")
def account_by_email(email: str) -> dict[str, int | str]:
    digest = _email_protector.lookup_digest(email)
    with _engine.connect() as connection:
        row = connection.execute(
            select(AdminAccount.admin_account_id, AdminAccount.status)
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminEmailClaim.claim_kind == "current",
                AdminEmailClaim.lookup_digest == digest,
            )
        ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Test account is unavailable.")
    return {"accountId": row.admin_account_id, "status": row.status}


@test_router.get("/accounts/{account_id}")
def account_state(account_id: int) -> dict[str, object]:
    with _engine.connect() as connection:
        account_status = connection.execute(
            select(AdminAccount.status).where(
                AdminAccount.admin_account_id == account_id
            )
        ).scalar_one_or_none()
        if account_status is None:
            raise HTTPException(status_code=404, detail="Test account is unavailable.")
        claim_kinds = list(
            connection.execute(
                select(AdminEmailClaim.claim_kind).where(
                    AdminEmailClaim.admin_account_id == account_id
                )
            ).scalars()
        )
        links = [
            {
                "status": row.status,
                "deliveryStatus": row.delivery_status,
                "issuedAt": row.issued_at.isoformat(),
                "expiresAt": row.expires_at.isoformat(),
            }
            for row in connection.execute(
                select(
                    SecurityLink.status,
                    SecurityLink.delivery_status,
                    SecurityLink.issued_at,
                    SecurityLink.expires_at,
                )
                .where(
                    SecurityLink.admin_account_id == account_id,
                    SecurityLink.purpose == "invitation",
                )
                .order_by(SecurityLink.security_link_id)
            )
        ]
        factor_status = connection.execute(
            select(TotpFactor.status).where(
                TotpFactor.admin_account_id == account_id
            )
        ).scalar_one_or_none()
        recovery_count = connection.execute(
            select(func.count()).select_from(RecoveryCode).where(
                RecoveryCode.admin_account_id == account_id,
                RecoveryCode.status == "active",
            )
        ).scalar_one()
        session_count = connection.execute(
            select(func.count()).select_from(AdminSession).where(
                AdminSession.admin_account_id == account_id,
                AdminSession.status == "active",
            )
        ).scalar_one()
    return {
        "status": account_status,
        "claimKinds": claim_kinds,
        "links": links,
        "factorStatus": factor_status,
        "activeRecoveryCodes": recovery_count,
        "activeSessions": session_count,
    }


@test_router.post("/expire-invitation", status_code=204)
def expire_invitation(body: SecurityLinkTokenBody) -> None:
    now = datetime.now(UTC)
    with _engine.begin() as connection:
        result = connection.execute(
            update(SecurityLink)
            .where(
                SecurityLink.token_digest
                == _link_protector.digest(body.decoded_token()),
                SecurityLink.purpose == "invitation",
                SecurityLink.status == "active",
            )
            .values(
                issued_at=now - timedelta(hours=24, seconds=2),
                expires_at=now - timedelta(seconds=1),
                updated_at=now,
            )
        )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Test invitation is unavailable.")


email_change_test_router = APIRouter(
    prefix="/__test__/email-changes", tags=["playwright-test-only"]
)


@email_change_test_router.post("/reset", status_code=204)
def reset_email_change_test_database() -> None:
    _seed_owner()


@email_change_test_router.put("/mailbox/outcome", status_code=204)
def set_email_change_mailbox_outcome(body: _OutcomeBody) -> None:
    _mailbox.set_next_outcome(body.outcome)


@email_change_test_router.get("/accounts/by-email")
def email_change_account_by_email(email: str) -> dict[str, int | str]:
    digest = _email_protector.lookup_digest(email)
    with _engine.connect() as connection:
        row = connection.execute(
            select(AdminAccount.admin_account_id, AdminAccount.status)
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminEmailClaim.claim_kind == "current",
                AdminEmailClaim.lookup_digest == digest,
            )
        ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Test account is unavailable.")
    return {"accountId": row.admin_account_id, "status": row.status}


@email_change_test_router.get("/accounts/{account_id}")
def email_change_account_state(account_id: int) -> dict[str, object]:
    with _engine.connect() as connection:
        account_status = connection.execute(
            select(AdminAccount.status).where(
                AdminAccount.admin_account_id == account_id
            )
        ).scalar_one_or_none()
        if account_status is None:
            raise HTTPException(status_code=404, detail="Test account is unavailable.")
        claims = [
            {
                "kind": row.claim_kind,
                "email": _email_protector.decrypt(
                    email_ciphertext=row.email_ciphertext,
                    key_version=row.key_version,
                ),
            }
            for row in connection.execute(
                select(
                    AdminEmailClaim.claim_kind,
                    AdminEmailClaim.email_ciphertext,
                    AdminEmailClaim.key_version,
                ).where(AdminEmailClaim.admin_account_id == account_id)
            )
        ]
        links = [
            {
                "status": row.status,
                "deliveryStatus": row.delivery_status,
                "issuedAt": row.issued_at.isoformat(),
                "expiresAt": row.expires_at.isoformat(),
            }
            for row in connection.execute(
                select(
                    SecurityLink.status,
                    SecurityLink.delivery_status,
                    SecurityLink.issued_at,
                    SecurityLink.expires_at,
                )
                .where(
                    SecurityLink.admin_account_id == account_id,
                    SecurityLink.purpose == "email_change",
                )
                .order_by(SecurityLink.security_link_id)
            )
        ]
        session_count = connection.execute(
            select(func.count()).select_from(AdminSession).where(
                AdminSession.admin_account_id == account_id,
                AdminSession.status == "active",
            )
        ).scalar_one()
    return {
        "status": account_status,
        "claims": claims,
        "links": links,
        "activeSessions": session_count,
    }


@email_change_test_router.post("/expire", status_code=204)
def expire_email_change(body: SecurityLinkTokenBody) -> None:
    now = datetime.now(UTC)
    with _engine.begin() as connection:
        result = connection.execute(
            update(SecurityLink)
            .where(
                SecurityLink.token_digest
                == _link_protector.digest(body.decoded_token()),
                SecurityLink.purpose == "email_change",
                SecurityLink.status == "active",
            )
            .values(
                issued_at=now - timedelta(minutes=30, seconds=2),
                expires_at=now - timedelta(seconds=1),
                updated_at=now,
            )
        )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Test email change is unavailable.")


app.include_router(test_router)
app.include_router(email_change_test_router)

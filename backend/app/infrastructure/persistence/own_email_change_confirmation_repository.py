"""Atomic PostgreSQL promotion of a reserved administrative email."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, delete, select, update
from sqlalchemy.exc import IntegrityError

from backend.app.application.admin_access.confirm_own_email_change import (
    EmailChangeConfirmationCandidate,
    EmailChangeConfirmationStore,
)
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim, SecurityLink
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector


class _EmailClaimConflict(Exception):
    """Roll back only the attempted claim promotion."""


class PostgresOwnEmailChangeConfirmationStore(EmailChangeConfirmationStore):
    def __init__(self, connection: Connection, email_protector: AdministrativeEmailProtector) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def lock_active_account(self, *, account_id: int) -> bool:
        return self._connection.execute(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == account_id,
                AdminAccount.status == "active",
            ).with_for_update()
        ).scalar_one_or_none() is not None

    def is_delivery_accepted(self, *, account_id: int, link_id: int) -> bool:
        return self._connection.execute(
            select(SecurityLink.security_link_id).where(
                SecurityLink.security_link_id == link_id,
                SecurityLink.admin_account_id == account_id,
                SecurityLink.purpose == "email_change",
                SecurityLink.status == "active",
                SecurityLink.delivery_status == "accepted",
            )
        ).scalar_one_or_none() is not None

    def load_candidate(self, *, account_id: int) -> EmailChangeConfirmationCandidate | None:
        claims = self._connection.execute(
            select(
                AdminEmailClaim.admin_email_claim_id,
                AdminEmailClaim.claim_kind,
                AdminEmailClaim.lookup_digest,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            ).where(AdminEmailClaim.admin_account_id == account_id).with_for_update()
        ).all()
        current = next((claim for claim in claims if claim.claim_kind == "current"), None)
        reserved = next((claim for claim in claims if claim.claim_kind == "reserved"), None)
        if current is None or reserved is None:
            return None
        if self._connection.execute(
            select(AdminEmailClaim.admin_email_claim_id).where(
                AdminEmailClaim.lookup_digest == reserved.lookup_digest,
                AdminEmailClaim.admin_email_claim_id != reserved.admin_email_claim_id,
            ).limit(1)
        ).scalar_one_or_none() is not None:
            return None
        reserved_email = self._email_protector.decrypt(
            email_ciphertext=reserved.email_ciphertext, key_version=reserved.key_version
        )
        if self._email_protector.lookup_digest(reserved_email) != reserved.lookup_digest:
            return None
        return EmailChangeConfirmationCandidate(
            account_id=account_id,
            current_claim_id=current.admin_email_claim_id,
            reserved_claim_id=reserved.admin_email_claim_id,
            current_email=self._email_protector.decrypt(
                email_ciphertext=current.email_ciphertext, key_version=current.key_version
            ),
            reserved_email=reserved_email,
            reserved_digest=reserved.lookup_digest,
        )

    def promote_reserved(self, *, candidate: EmailChangeConfirmationCandidate) -> bool:
        try:
            with self._connection.begin_nested():
                deleted = self._connection.execute(
                    delete(AdminEmailClaim).where(
                        AdminEmailClaim.admin_email_claim_id == candidate.current_claim_id,
                        AdminEmailClaim.admin_account_id == candidate.account_id,
                        AdminEmailClaim.claim_kind == "current",
                    )
                )
                if deleted.rowcount != 1:
                    raise _EmailClaimConflict
                promoted = self._connection.execute(
                    update(AdminEmailClaim).where(
                        AdminEmailClaim.admin_email_claim_id == candidate.reserved_claim_id,
                        AdminEmailClaim.admin_account_id == candidate.account_id,
                        AdminEmailClaim.claim_kind == "reserved",
                        AdminEmailClaim.lookup_digest == candidate.reserved_digest,
                    ).values(claim_kind="current")
                )
                if promoted.rowcount != 1:
                    raise _EmailClaimConflict
            return True
        except (IntegrityError, _EmailClaimConflict):
            return False

    def invalidate_conflicting_link(self, *, account_id: int, link_id: int, current_time: datetime) -> None:
        retired = self._connection.execute(
            update(SecurityLink).where(
                SecurityLink.security_link_id == link_id,
                SecurityLink.admin_account_id == account_id,
                SecurityLink.purpose == "email_change",
                SecurityLink.status == "active",
            ).values(
                status="invalidated", invalidated_at=current_time, updated_at=current_time
            )
        )
        if retired.rowcount == 1:
            self._connection.execute(
                delete(AdminEmailClaim).where(
                    AdminEmailClaim.admin_account_id == account_id,
                    AdminEmailClaim.claim_kind == "reserved",
                )
            )

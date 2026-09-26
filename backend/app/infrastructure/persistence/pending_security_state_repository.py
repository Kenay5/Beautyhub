"""PostgreSQL cleanup for temporary administrative security artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import Connection, delete, select, update

from backend.app.application.admin_access.pending_security_state import (
    PendingSecurityStateStore,
)
from backend.app.domain.authentication.pending_security_setup import (
    PendingSecuritySetupFlow,
)
from backend.app.domain.authentication.security_link import SecurityLinkPurpose
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    PendingSecuritySetup,
    SecurityLink,
)


_PENDING_FLOW_BY_LINK_PURPOSE: Final[dict[SecurityLinkPurpose, str]] = {
    "initial_activation": "owner_activation",
    "invitation": "staff_activation",
    "totp_replacement": "totp_replacement",
}


class PostgresPendingSecurityStateStore(PendingSecurityStateStore):
    """Remove only incomplete state; active credentials always remain untouched."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def discard_for_expired_link(
        self, *, account_id: int, purpose: SecurityLinkPurpose, current_time: datetime
    ) -> None:
        """Expire the matching unconfirmed setup and an expired email reservation."""

        self._lock_account(account_id)
        self._discard_setup(
            account_id=account_id,
            purpose=purpose,
            status="expired",
            current_time=current_time,
        )
        if purpose == "email_change":
            self._release_reservation(account_id=account_id)

    def discard_abandoned_setup(
        self,
        *,
        account_id: int,
        flow: PendingSecuritySetupFlow,
        current_time: datetime,
    ) -> None:
        """Remove a user-abandoned pending TOTP secret without invalidating its link."""

        self._lock_account(account_id)
        self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.admin_account_id == account_id,
                PendingSecuritySetup.flow == flow,
                PendingSecuritySetup.status == "pending",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=current_time,
            )
        )

    def discard_for_replaced_link(
        self, *, account_id: int, purpose: SecurityLinkPurpose, current_time: datetime
    ) -> None:
        """Invalidate the matching unconfirmed setup and obsolete email reservation."""

        self._lock_account(account_id)
        self._discard_setup(
            account_id=account_id,
            purpose=purpose,
            status="invalidated",
            current_time=current_time,
        )
        if purpose == "email_change":
            self._release_reservation(account_id=account_id)

    def discard_after_completed_security_change(
        self, *, account_id: int, current_time: datetime
    ) -> None:
        """Apply RF-04-CA-08 while retaining active authentication material."""

        self._lock_account(account_id)
        self._connection.execute(
            update(SecurityLink)
            .where(
                SecurityLink.admin_account_id == account_id,
                SecurityLink.status == "active",
            )
            .values(
                status="invalidated",
                invalidated_at=current_time,
                updated_at=current_time,
            )
        )
        self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.admin_account_id == account_id,
                PendingSecuritySetup.status == "pending",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=current_time,
            )
        )
        self._release_reservation(account_id=account_id)

    def _discard_setup(
        self,
        *,
        account_id: int,
        purpose: SecurityLinkPurpose,
        status: str,
        current_time: datetime,
    ) -> None:
        flow = _PENDING_FLOW_BY_LINK_PURPOSE.get(purpose)
        if flow is None:
            return
        self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.admin_account_id == account_id,
                PendingSecuritySetup.flow == flow,
                PendingSecuritySetup.status == "pending",
            )
            .values(
                status=status,
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=current_time,
            )
        )

    def _release_reservation(self, *, account_id: int) -> None:
        self._connection.execute(
            delete(AdminEmailClaim).where(
                AdminEmailClaim.admin_account_id == account_id,
                AdminEmailClaim.claim_kind == "reserved",
            )
        )

    def _lock_account(self, account_id: int) -> None:
        exists = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(AdminAccount.admin_account_id == account_id)
            .with_for_update()
        ).scalar_one_or_none()
        if exists is None:
            raise ValueError("administrative account is unavailable.")

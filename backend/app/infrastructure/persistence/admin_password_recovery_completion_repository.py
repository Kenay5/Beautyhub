"""PostgreSQL persistence for completed administrative password recovery."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, select, update

from backend.app.application.admin_access.password_recovery_completion import (
    PasswordRecoveryCompletionStore,
    RecoveryAccount,
)
from backend.app.domain.authentication.security_link import SecurityLinkPurpose
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminEmailClaim,
    SecurityLink,
)
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector


class PostgresPasswordRecoveryCompletionStore(PasswordRecoveryCompletionStore):
    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector,
        link_protector: SecurityLinkProtector,
        current_time: datetime,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector
        self._link_protector = link_protector
        self._current_time = current_time

    def find_account_for_active_link(self, *, token: bytes) -> tuple[int, SecurityLinkPurpose] | None:
        """Resolve an unexpired, delivered recovery link by its keyed digest."""

        try:
            digest = self._link_protector.digest(token)
        except ValueError:
            return None
        # The exact expiry boundary is terminal, not merely filtered from lookup.
        # Retire forced-reset links here because this completion lookup otherwise
        # bypasses the generic link lifecycle's expiry transition.
        self._connection.execute(
            update(SecurityLink)
            .where(
                SecurityLink.token_digest == digest,
                SecurityLink.purpose == "forced_password_reset",
                SecurityLink.status == "active",
                SecurityLink.expires_at <= self._current_time,
            )
            .values(status="expired", updated_at=self._current_time)
        )
        row = self._connection.execute(
            select(SecurityLink.admin_account_id, SecurityLink.purpose).where(
                SecurityLink.token_digest == digest,
                SecurityLink.purpose.in_(("password_recovery", "forced_password_reset")),
                SecurityLink.status == "active",
                SecurityLink.delivery_status == "accepted",
                SecurityLink.expires_at > self._current_time,
            )
        ).one_or_none()
        return None if row is None else (row.admin_account_id, row.purpose)

    def lock_active_account(self, *, account_id: int, purpose: SecurityLinkPurpose) -> RecoveryAccount | None:
        row = self._connection.execute(
            select(
                AdminAccount.admin_account_id,
                AdminAccount.role,
                AdminAccount.password_hash,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            )
            .join(AdminEmailClaim, AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id)
            .where(
                AdminAccount.admin_account_id == account_id,
                AdminAccount.status == "active",
                AdminEmailClaim.claim_kind == "current",
            )
            .with_for_update(of=AdminAccount)
        ).one_or_none()
        if row is None:
            return None
        if purpose == "password_recovery" and row.password_hash is None:
            return None
        if purpose == "forced_password_reset" and (
            row.role != "staff" or row.password_hash is not None
        ):
            return None
        return RecoveryAccount(
            account_id=row.admin_account_id,
            purpose=purpose,
            current_email=self._email_protector.decrypt(
                email_ciphertext=row.email_ciphertext,
                key_version=row.key_version,
            ),
        )

    def replace_password(self, *, account_id: int, password_hash: str) -> None:
        updated = self._connection.execute(
            update(AdminAccount)
            .where(AdminAccount.admin_account_id == account_id, AdminAccount.status == "active")
            .values(password_hash=password_hash)
        )
        if updated.rowcount != 1:
            raise RuntimeError("administrative password recovery lost account state")

    def restrict_factor_replacement_until_login(self, *, account_id: int) -> None:
        updated = self._connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == account_id)
            .values(
                post_recovery_second_factor_restricted=True,
                updated_at=self._current_time,
            )
        )
        if updated.rowcount != 1:
            raise RuntimeError("administrative recovery security state is unavailable")

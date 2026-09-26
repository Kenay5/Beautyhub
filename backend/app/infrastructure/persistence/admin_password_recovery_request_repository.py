"""Minimal read-only account lookup for password-recovery requests."""

from sqlalchemy import Connection, select

from backend.app.application.admin_access.password_recovery_request import (
    AdministrativeRecoveryAccountStore,
    PasswordRecoveryRecipient,
)
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)


class PostgresAdministrativeRecoveryAccountStore(AdministrativeRecoveryAccountStore):
    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector | None = None,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def find_active_account_id(self, *, email_lookup_digest: bytes) -> int | None:
        return self._connection.execute(
            select(AdminAccount.admin_account_id)
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminEmailClaim.claim_kind == "current",
                AdminEmailClaim.lookup_digest == email_lookup_digest,
                AdminAccount.status == "active",
            )
            .with_for_update(of=AdminAccount)
        ).scalar_one_or_none()

    def load_active_account_recipient(
        self, *, account_id: int
    ) -> PasswordRecoveryRecipient | None:
        row = self._connection.execute(
            select(
                AdminAccount.admin_account_id,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            )
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminAccount.admin_account_id == account_id,
                AdminAccount.status == "active",
                AdminEmailClaim.claim_kind == "current",
            )
            .with_for_update(of=AdminAccount)
        ).one_or_none()
        if row is None:
            return None
        if self._email_protector is None:
            raise ValueError("administrative email protector is unavailable.")
        return PasswordRecoveryRecipient(
            account_id=row.admin_account_id,
            email=self._email_protector.decrypt(
                email_ciphertext=row.email_ciphertext,
                key_version=row.key_version,
            ),
        )

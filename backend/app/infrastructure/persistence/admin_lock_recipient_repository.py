"""Resolve encrypted administrative recipients for account-lock notices."""

from __future__ import annotations

from sqlalchemy import Connection, select

from backend.app.application.admin_access.account_security import (
    AdministrativeLockRecipientDirectory,
)
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)


class PostgresAdministrativeLockRecipientDirectory(
    AdministrativeLockRecipientDirectory
):
    """Return the account holder and, for staff locks, the owner."""

    def __init__(
        self,
        *,
        connection: Connection,
        email_protector: AdministrativeEmailProtector,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def lock_notification_recipients(self, *, account_id: int) -> tuple[str, ...]:
        account = self._connection.execute(
            select(
                AdminAccount.role,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            )
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminAccount.admin_account_id == account_id,
                AdminEmailClaim.claim_kind == "current",
            )
        ).one_or_none()
        if account is None:
            raise ValueError("administrative lock recipient is unavailable.")

        recipients = [self._decrypt(account)]
        if account.role == "staff":
            owner = self._connection.execute(
                select(
                    AdminEmailClaim.email_ciphertext,
                    AdminEmailClaim.key_version,
                )
                .join(
                    AdminAccount,
                    AdminAccount.admin_account_id
                    == AdminEmailClaim.admin_account_id,
                )
                .where(
                    AdminAccount.role == "owner",
                    AdminEmailClaim.claim_kind == "current",
                )
            ).one_or_none()
            if owner is None:
                raise ValueError("administrative owner lock recipient is unavailable.")
            recipients.append(self._decrypt(owner))
        return tuple(dict.fromkeys(recipients))

    def _decrypt(self, row) -> str:
        return self._email_protector.decrypt(
            email_ciphertext=row.email_ciphertext,
            key_version=row.key_version,
        )

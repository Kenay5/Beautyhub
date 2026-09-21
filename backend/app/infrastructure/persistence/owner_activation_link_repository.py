"""PostgreSQL recipient lookup for the protected initial activation link."""

from __future__ import annotations

from sqlalchemy import Connection, select

from backend.app.application.admin_access.owner_activation_link import (
    OwnerActivationRecipient,
    OwnerActivationRecipientStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    OwnerBootstrapState,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)


class PostgresOwnerActivationRecipientStore(OwnerActivationRecipientStore):
    """Read the protected current email while locking the inactive owner account."""

    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def load_inactive_owner_recipient(self) -> OwnerActivationRecipient | None:
        """Return no recipient unless the initial bootstrap remains safely open."""

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
            .join(
                OwnerBootstrapState,
                OwnerBootstrapState.bootstrap_state_id == 1,
            )
            .where(
                AdminAccount.role == "owner",
                AdminAccount.status == "inactive",
                AdminEmailClaim.claim_kind == "current",
                OwnerBootstrapState.status == "open",
                OwnerBootstrapState.owner_account_id.is_(None),
            )
            .with_for_update(of=AdminAccount)
        ).one_or_none()
        if row is None:
            return None
        return OwnerActivationRecipient(
            account_id=row.admin_account_id,
            email=self._email_protector.decrypt(
                email_ciphertext=row.email_ciphertext,
                key_version=row.key_version,
            ),
        )

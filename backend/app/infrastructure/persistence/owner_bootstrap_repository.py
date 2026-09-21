"""PostgreSQL transaction for protected owner bootstrap registration."""

from __future__ import annotations

from sqlalchemy import Connection, insert, select

from backend.app.application.admin_access.owner_bootstrap import (
    OwnerBootstrapRegistrationStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    OwnerBootstrapState,
)
from backend.app.infrastructure.security.admin_email_protection import (
    ProtectedAdministrativeEmail,
)


class OwnerBootstrapRegistrationError(ValueError):
    """Raised when the one protected owner-registration process is unavailable."""


class PostgresOwnerBootstrapRegistrationStore(OwnerBootstrapRegistrationStore):
    """Create exactly one inactive owner under the singleton bootstrap lock."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def register_inactive_owner(self, *, email: ProtectedAdministrativeEmail) -> None:
        """Create the account and current email claim in the caller transaction."""

        bootstrap_state = self._connection.execute(
            select(
                OwnerBootstrapState.status,
                OwnerBootstrapState.owner_account_id,
            )
            .where(OwnerBootstrapState.bootstrap_state_id == 1)
            .with_for_update()
        ).one_or_none()
        if (
            bootstrap_state is None
            or bootstrap_state.status != "open"
            or bootstrap_state.owner_account_id is not None
        ):
            raise OwnerBootstrapRegistrationError(
                "owner bootstrap registration is unavailable."
            )

        owner_exists = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(AdminAccount.role == "owner")
            .with_for_update()
        ).scalar_one_or_none()
        email_is_claimed = self._connection.execute(
            select(AdminEmailClaim.admin_email_claim_id).where(
                AdminEmailClaim.lookup_digest == email.lookup_digest
            )
        ).scalar_one_or_none()
        if owner_exists is not None or email_is_claimed is not None:
            raise OwnerBootstrapRegistrationError(
                "owner bootstrap registration is unavailable."
            )

        account_id = self._connection.execute(
            insert(AdminAccount)
            .values(role="owner", status="inactive")
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        self._connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=email.lookup_digest,
                email_ciphertext=email.email_ciphertext,
                key_version=email.key_version,
            )
        )

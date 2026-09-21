"""PostgreSQL transaction for a single pending staff invitation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from backend.app.application.admin_access.staff_invitation import (
    StaffInvitationError,
    StaffInvitationStore,
    PendingStaffRecipient,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
)
from backend.app.infrastructure.persistence.pending_security_state_repository import (
    PostgresPendingSecurityStateStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
    ProtectedAdministrativeEmail,
)


class PostgresStaffInvitationStore(StaffInvitationStore):
    """Serialize invitation creation through the authenticated owner and staff rows."""

    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector | None = None,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def create_pending_staff(
        self,
        *,
        owner_account_id: int,
        email: ProtectedAdministrativeEmail,
    ) -> int:
        """Claim email and add one pending staff account in the caller transaction."""

        owner = self._connection.execute(
            select(AdminAccount.role, AdminAccount.status)
            .where(AdminAccount.admin_account_id == owner_account_id)
            .with_for_update()
        ).one_or_none()
        if owner is None or (owner.role, owner.status) != ("owner", "active"):
            raise StaffInvitationError("staff invitation is unavailable.")

        current_staff = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(
                AdminAccount.role == "staff",
                AdminAccount.status.in_(("pending", "active")),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if current_staff is not None:
            raise StaffInvitationError("staff invitation is unavailable.")

        claimed_email = self._connection.execute(
            select(AdminEmailClaim.admin_email_claim_id).where(
                AdminEmailClaim.lookup_digest == email.lookup_digest
            )
        ).scalar_one_or_none()
        if claimed_email is not None:
            raise StaffInvitationError("staff invitation is unavailable.")

        try:
            with self._connection.begin_nested():
                account_id = self._connection.execute(
                    insert(AdminAccount)
                    .values(role="staff", status="pending")
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
        except IntegrityError as error:
            raise StaffInvitationError("staff invitation is unavailable.") from error
        return account_id

    def load_pending_staff_recipient(
        self, *, owner_account_id: int
    ) -> PendingStaffRecipient:
        """Return the locked pending account only while the caller is the active owner."""

        self._require_active_owner(owner_account_id)
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
                AdminAccount.role == "staff",
                AdminAccount.status == "pending",
                AdminEmailClaim.claim_kind == "current",
            )
            .with_for_update(of=AdminAccount)
        ).one_or_none()
        if row is None:
            raise StaffInvitationError("staff invitation is unavailable.")
        if self._email_protector is None:
            raise StaffInvitationError("staff invitation is unavailable.")
        return PendingStaffRecipient(
            account_id=row.admin_account_id,
            email=self._email_protector.decrypt(
                email_ciphertext=row.email_ciphertext,
                key_version=row.key_version,
            ),
        )

    def cancel_pending_staff(
        self, *, owner_account_id: int, current_time: datetime
    ) -> int:
        """Deactivate the locked pending account and remove all usable invitation state."""

        self._require_active_owner(owner_account_id)
        account_id = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(
                AdminAccount.role == "staff",
                AdminAccount.status == "pending",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if account_id is None:
            raise StaffInvitationError("staff invitation is unavailable.")

        # The shared cleanup locks the same account, invalidates every active link,
        # and destroys any incomplete setup before the account leaves pending state.
        PostgresPendingSecurityStateStore(
            self._connection
        ).discard_after_completed_security_change(
            account_id=account_id,
            current_time=current_time,
        )
        self._connection.execute(
            delete(AdminEmailClaim).where(
                AdminEmailClaim.admin_account_id == account_id,
                AdminEmailClaim.claim_kind == "current",
            )
        )
        updated = self._connection.execute(
            update(AdminAccount)
            .where(
                AdminAccount.admin_account_id == account_id,
                AdminAccount.role == "staff",
                AdminAccount.status == "pending",
            )
            .values(status="deactivated", updated_at=current_time)
        ).rowcount
        if updated != 1:
            raise StaffInvitationError("staff invitation is unavailable.")
        return account_id

    def _require_active_owner(self, owner_account_id: int) -> None:
        owner = self._connection.execute(
            select(AdminAccount.role, AdminAccount.status)
            .where(AdminAccount.admin_account_id == owner_account_id)
            .with_for_update()
        ).one_or_none()
        if owner is None or (owner.role, owner.status) != ("owner", "active"):
            raise StaffInvitationError("staff invitation is unavailable.")

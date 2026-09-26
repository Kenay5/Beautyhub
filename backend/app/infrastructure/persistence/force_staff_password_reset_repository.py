"""PostgreSQL transaction for owner-forced staff password resets."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Connection, select, update

from backend.app.application.admin_access.force_staff_password_reset import (
    ActiveStaffRecipient,
    ForceStaffPasswordResetStore,
    ForcedPasswordResetUnavailable,
)
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim, AdminSession
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector


class PostgresForceStaffPasswordResetStore(ForceStaffPasswordResetStore):
    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector,
        current_time: datetime,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector
        self._current_time = current_time.astimezone(timezone.utc)

    def invalidate_staff_access_and_load_recipient(
        self, *, owner_account_id: int
    ) -> ActiveStaffRecipient:
        owner = self._connection.execute(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == owner_account_id,
                AdminAccount.role == "owner",
                AdminAccount.status == "active",
            ).with_for_update()
        ).scalar_one_or_none()
        if owner is None:
            raise ForcedPasswordResetUnavailable("staff password reset is unavailable.")

        staff = self._connection.execute(
            select(
                AdminAccount.admin_account_id,
                AdminAccount.password_hash,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            )
            .join(AdminEmailClaim, AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id)
            .where(
                AdminAccount.role == "staff",
                AdminAccount.status == "active",
                AdminEmailClaim.claim_kind == "current",
            )
            .with_for_update(of=AdminAccount)
        ).one_or_none()
        if staff is None:
            raise ForcedPasswordResetUnavailable("staff password reset is unavailable.")

        email = self._email_protector.decrypt(
            email_ciphertext=staff.email_ciphertext,
            key_version=staff.key_version,
        )
        account_update = update(AdminAccount).where(
            AdminAccount.admin_account_id == staff.admin_account_id,
            AdminAccount.role == "staff",
            AdminAccount.status == "active",
        )
        if staff.password_hash is not None:
            account_update = account_update.where(AdminAccount.password_hash == staff.password_hash)
        updated = self._connection.execute(
            account_update.values(password_hash=None, updated_at=self._current_time)
        )
        if updated.rowcount != 1:
            raise ForcedPasswordResetUnavailable("staff password reset is unavailable.")

        self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.admin_account_id == staff.admin_account_id,
                AdminSession.status == "active",
            )
            .values(
                status="invalidated",
                invalidated_at=self._current_time,
                updated_at=self._current_time,
            )
        )
        return ActiveStaffRecipient(account_id=staff.admin_account_id, email=email)

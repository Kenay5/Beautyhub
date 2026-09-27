"""Atomic PostgreSQL cleanup when the owner deactivates staff."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, delete, insert, select, update

from backend.app.application.admin_access.staff_deactivation import (
    DeactivatedStaff,
    StaffDeactivationError,
    StaffDeactivationStore,
    StaffStatus,
)
from backend.app.domain.audit.retention import administrative_retention_deadline
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    AdminSession,
    DeactivatedStaffIdentity,
    PendingSecuritySetup,
    RecoveryCode,
    SecurityLink,
    TotpFactor,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)


class PostgresStaffDeactivationStore(StaffDeactivationStore):
    """Lock owner before staff, matching invitation and owner-management flows."""

    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def load_current_status(self, *, owner_account_id: int) -> StaffStatus:
        self._require_active_owner(owner_account_id)
        row = self._connection.execute(
            select(AdminAccount.status)
            .where(
                AdminAccount.role == "staff",
                AdminAccount.status.in_(("pending", "active")),
            )
        ).scalar_one_or_none()
        return row if row in {"pending", "active"} else "none"

    def deactivate_current_staff(
        self, *, owner_account_id: int, current_time: datetime
    ) -> DeactivatedStaff:
        owner = self._require_active_owner(owner_account_id)
        owner_claim = self._connection.execute(
            select(AdminEmailClaim.email_ciphertext, AdminEmailClaim.key_version).where(
                AdminEmailClaim.admin_account_id == owner_account_id,
                AdminEmailClaim.claim_kind == "current",
            )
        ).one_or_none()
        if owner_claim is None:
            raise StaffDeactivationError("staff account is unavailable.")
        owner_email = self._email_protector.decrypt(
            email_ciphertext=owner_claim.email_ciphertext,
            key_version=owner_claim.key_version,
        )

        staff_id = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(
                AdminAccount.role == "staff",
                AdminAccount.status.in_(("pending", "active")),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if staff_id is None or owner.status != "active":
            raise StaffDeactivationError("staff account is unavailable.")

        staff_claim = self._connection.execute(
            select(AdminEmailClaim.email_ciphertext, AdminEmailClaim.key_version).where(
                AdminEmailClaim.admin_account_id == staff_id,
                AdminEmailClaim.claim_kind == "current",
            )
        ).one_or_none()
        if staff_claim is None:
            raise StaffDeactivationError("staff account is unavailable.")
        identifiable_until = administrative_retention_deadline(current_time)
        self._connection.execute(
            insert(DeactivatedStaffIdentity).values(
                admin_account_id=staff_id,
                email_ciphertext=staff_claim.email_ciphertext,
                key_version=staff_claim.key_version,
                identifiable_until=identifiable_until,
            )
        )

        # Account row lock serializes this transition with login and credential changes.
        self._connection.execute(
            update(SecurityLink)
            .where(
                SecurityLink.admin_account_id == staff_id,
                SecurityLink.status == "active",
            )
            .values(status="invalidated", invalidated_at=current_time, updated_at=current_time)
        )
        self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.admin_account_id == staff_id,
                PendingSecuritySetup.status == "pending",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_period_counter=None,
                verified_totp_factor_id=None,
                verified_recovery_code_digest=None,
                updated_at=current_time,
            )
        )
        self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.admin_account_id == staff_id,
                AdminSession.status == "active",
            )
            .values(status="invalidated", invalidated_at=current_time, updated_at=current_time)
        )
        self._connection.execute(
            update(TotpFactor)
            .where(
                TotpFactor.admin_account_id == staff_id,
                TotpFactor.status == "active",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                invalidated_at=current_time,
                updated_at=current_time,
            )
        )
        self._connection.execute(
            delete(RecoveryCode).where(RecoveryCode.admin_account_id == staff_id)
        )
        self._connection.execute(
            delete(AdminEmailClaim).where(AdminEmailClaim.admin_account_id == staff_id)
        )
        updated = self._connection.execute(
            update(AdminAccount)
            .where(
                AdminAccount.admin_account_id == staff_id,
                AdminAccount.role == "staff",
                AdminAccount.status.in_(("pending", "active")),
            )
            .values(
                status="deactivated",
                password_hash=None,
                updated_at=current_time,
            )
        )
        if updated.rowcount != 1:
            raise StaffDeactivationError("staff account is unavailable.")
        return DeactivatedStaff(
            account_id=staff_id,
            owner_email=owner_email,
        )

    def _require_active_owner(self, owner_account_id: int):
        owner = self._connection.execute(
            select(AdminAccount.role, AdminAccount.status)
            .where(AdminAccount.admin_account_id == owner_account_id)
            .with_for_update()
        ).one_or_none()
        if owner is None or (owner.role, owner.status) != ("owner", "active"):
            raise StaffDeactivationError("staff account is unavailable.")
        return owner

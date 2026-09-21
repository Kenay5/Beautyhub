"""PostgreSQL persistence for unconfirmed TOTP setup material."""

from __future__ import annotations

from sqlalchemy import Connection, insert, select

from backend.app.application.admin_access.owner_activation_setup import (
    PendingTotpSetupStore,
    StoredPendingTotpSetup,
)
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    PendingSecuritySetup as PendingSecuritySetupModel,
)


class PostgresPendingTotpSetupStore(PendingTotpSetupStore):
    """Serialize creation of one pending setup through the account row."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def create_or_get(
        self, *, setup: PendingSecuritySetup
    ) -> StoredPendingTotpSetup:
        """Reuse a pending setup on refresh without exposing its plaintext secret."""

        account_status = self._connection.execute(
            select(AdminAccount.status)
            .where(AdminAccount.admin_account_id == setup.account_id)
            .with_for_update()
        ).scalar_one_or_none()
        allowed_status = {
            "owner_activation": "inactive",
            "staff_activation": "pending",
        }.get(setup.flow)
        if account_status != allowed_status:
            raise ValueError("administrative account is unavailable.")

        existing = self._pending(setup.account_id, setup.flow)
        if existing is not None:
            return _stored(existing)

        row = self._connection.execute(
            insert(PendingSecuritySetupModel)
            .values(
                admin_account_id=setup.account_id,
                flow=setup.flow,
                status=setup.status,
                totp_secret_ciphertext=setup.totp_secret_ciphertext,
                key_version=setup.key_version,
                created_at=setup.created_at,
                expires_at=setup.expires_at,
            )
            .returning(
                PendingSecuritySetupModel.admin_account_id,
                PendingSecuritySetupModel.totp_secret_ciphertext,
                PendingSecuritySetupModel.key_version,
            )
        ).one()
        return _stored(row)

    def _pending(self, account_id: int, flow: str):
        return self._connection.execute(
            select(
                PendingSecuritySetupModel.admin_account_id,
                PendingSecuritySetupModel.totp_secret_ciphertext,
                PendingSecuritySetupModel.key_version,
            ).where(
                PendingSecuritySetupModel.admin_account_id == account_id,
                PendingSecuritySetupModel.flow == flow,
                PendingSecuritySetupModel.status == "pending",
            )
        ).one_or_none()


def _stored(row) -> StoredPendingTotpSetup:
    return StoredPendingTotpSetup(
        account_id=row.admin_account_id,
        ciphertext=row.totp_secret_ciphertext,
        key_version=row.key_version,
    )

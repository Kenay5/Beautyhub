"""PostgreSQL state for authenticated TOTP-replacement preparation."""

from __future__ import annotations

from sqlalchemy import Connection, insert, select, update

from backend.app.application.admin_access.prepare_totp_replacement import (
    TotpReplacementCandidate,
    TotpReplacementStore,
)
from backend.app.application.admin_access.prepare_lost_factor_replacement import (
    StoredLostFactorTotpSetup,
)
from backend.app.domain.authentication.pending_security_setup import PendingSecuritySetup
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    PendingSecuritySetup as PendingSecuritySetupModel,
    RecoveryCode,
    SecurityLink,
    TotpFactor,
    TotpPeriodUse,
)


class PostgresTotpReplacementStore(TotpReplacementStore):
    """Serialize setup creation with account credential checks in one transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def load_candidate(self, *, account_id: int) -> TotpReplacementCandidate | None:
        account = self._connection.execute(
            select(AdminAccount.admin_account_id, AdminAccount.password_hash)
            .where(
                AdminAccount.admin_account_id == account_id,
                AdminAccount.status == "active",
            )
            .with_for_update()
        ).one_or_none()
        if account is None or account.password_hash is None:
            return None
        factor = self._connection.execute(
            select(
                TotpFactor.totp_factor_id,
                TotpFactor.totp_secret_ciphertext,
                TotpFactor.key_version,
                TotpFactor.algorithm,
            ).where(
                TotpFactor.admin_account_id == account_id,
                TotpFactor.status == "active",
            )
        ).one_or_none()
        if factor is None:
            return None
        return TotpReplacementCandidate(
            account_id=account_id,
            password_hash=account.password_hash,
            factor_id=factor.totp_factor_id,
            factor_ciphertext=factor.totp_secret_ciphertext,
            factor_key_version=factor.key_version,
            factor_algorithm=factor.algorithm,
            used_period_counters=tuple(
                self._connection.execute(
                    select(TotpPeriodUse.period_counter).where(
                        TotpPeriodUse.admin_account_id == account_id,
                        TotpPeriodUse.totp_factor_id == factor.totp_factor_id,
                    )
                ).scalars()
            ),
            active_recovery_digests=tuple(
                self._connection.execute(
                    select(RecoveryCode.lookup_digest).where(
                        RecoveryCode.admin_account_id == account_id,
                        RecoveryCode.status == "active",
                    )
                ).scalars()
            ),
        )

    def save_pending_setup(
        self,
        *,
        setup: PendingSecuritySetup,
        verified_totp_factor_id: int | None,
        verified_totp_period_counter: int | None,
        verified_recovery_code_digest: bytes | None,
    ) -> bool:
        account_status = self._connection.execute(
            select(AdminAccount.status)
            .where(AdminAccount.admin_account_id == setup.account_id)
            .with_for_update()
        ).scalar_one_or_none()
        if account_status != "active":
            return False

        self._connection.execute(
            update(PendingSecuritySetupModel)
            .where(
                PendingSecuritySetupModel.admin_account_id == setup.account_id,
                PendingSecuritySetupModel.flow == setup.flow,
                PendingSecuritySetupModel.status == "pending",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=setup.created_at,
            )
        )
        self._connection.execute(
            insert(PendingSecuritySetupModel).values(
                admin_account_id=setup.account_id,
                flow=setup.flow,
                status=setup.status,
                totp_secret_ciphertext=setup.totp_secret_ciphertext,
                key_version=setup.key_version,
                verified_totp_factor_id=verified_totp_factor_id,
                verified_totp_period_counter=verified_totp_period_counter,
                verified_recovery_code_digest=verified_recovery_code_digest,
                created_at=setup.created_at,
                expires_at=setup.expires_at,
            )
        )
        return True

    def save_pending_setup_for_link(
        self,
        *,
        setup: PendingSecuritySetup,
        link_id: int,
    ) -> StoredLostFactorTotpSetup | None:
        """Lock the account, revalidate its active link, and reuse one pending setup."""

        account_status = self._connection.execute(
            select(AdminAccount.status)
            .where(AdminAccount.admin_account_id == setup.account_id)
            .with_for_update()
        ).scalar_one_or_none()
        if account_status != "active":
            return None

        link_is_active = self._connection.execute(
            select(SecurityLink.security_link_id)
            .where(
                SecurityLink.security_link_id == link_id,
                SecurityLink.admin_account_id == setup.account_id,
                SecurityLink.purpose == "totp_replacement",
                SecurityLink.status == "active",
                SecurityLink.expires_at > setup.created_at,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if link_is_active is None:
            return None

        existing = self._connection.execute(
            select(
                PendingSecuritySetupModel.totp_secret_ciphertext,
                PendingSecuritySetupModel.key_version,
                PendingSecuritySetupModel.expires_at,
            )
            .where(
                PendingSecuritySetupModel.admin_account_id == setup.account_id,
                PendingSecuritySetupModel.flow == setup.flow,
                PendingSecuritySetupModel.status == "pending",
                PendingSecuritySetupModel.expires_at > setup.created_at,
            )
            .with_for_update()
        ).one_or_none()
        if existing is not None:
            return StoredLostFactorTotpSetup(
                ciphertext=existing.totp_secret_ciphertext,
                key_version=existing.key_version,
                expires_at=existing.expires_at,
            )

        self._connection.execute(
            update(PendingSecuritySetupModel)
            .where(
                PendingSecuritySetupModel.admin_account_id == setup.account_id,
                PendingSecuritySetupModel.flow == setup.flow,
                PendingSecuritySetupModel.status == "pending",
            )
            .values(
                status="expired",
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=setup.created_at,
            )
        )
        row = self._connection.execute(
            insert(PendingSecuritySetupModel)
            .values(
                admin_account_id=setup.account_id,
                flow=setup.flow,
                status=setup.status,
                totp_secret_ciphertext=setup.totp_secret_ciphertext,
                key_version=setup.key_version,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                created_at=setup.created_at,
                expires_at=setup.expires_at,
            )
            .returning(
                PendingSecuritySetupModel.totp_secret_ciphertext,
                PendingSecuritySetupModel.key_version,
                PendingSecuritySetupModel.expires_at,
            )
        ).one()
        return StoredLostFactorTotpSetup(
            ciphertext=row.totp_secret_ciphertext,
            key_version=row.key_version,
            expires_at=row.expires_at,
        )

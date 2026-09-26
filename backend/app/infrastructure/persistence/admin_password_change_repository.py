"""PostgreSQL credential replacement for an administrative account."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from backend.app.application.admin_access.change_password import (
    PasswordChangeCandidate,
    PasswordChangeStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)


class PostgresAdministrativePasswordChangeStore(PasswordChangeStore):
    def __init__(
        self, connection: Connection, email_protector: AdministrativeEmailProtector
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector

    def load_candidate(self, *, account_id: int) -> PasswordChangeCandidate | None:
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
        claim = self._connection.execute(
            select(AdminEmailClaim.email_ciphertext, AdminEmailClaim.key_version).where(
                AdminEmailClaim.admin_account_id == account_id,
                AdminEmailClaim.claim_kind == "current",
            )
        ).one_or_none()
        if factor is None or claim is None:
            return None
        used_periods = tuple(
            self._connection.execute(
                select(TotpPeriodUse.period_counter).where(
                    TotpPeriodUse.admin_account_id == account_id,
                    TotpPeriodUse.totp_factor_id == factor.totp_factor_id,
                )
            ).scalars()
        )
        return PasswordChangeCandidate(
            account_id=account_id,
            password_hash=account.password_hash,
            factor_id=factor.totp_factor_id,
            factor_ciphertext=factor.totp_secret_ciphertext,
            factor_key_version=factor.key_version,
            factor_algorithm=factor.algorithm,
            used_period_counters=used_periods,
            current_email=self._email_protector.decrypt(
                email_ciphertext=claim.email_ciphertext,
                key_version=claim.key_version,
            ),
        )

    def replace_password(
        self,
        *,
        candidate: PasswordChangeCandidate,
        password_hash: str,
        period_counter: int,
        current_time: datetime,
    ) -> bool:
        period_id = self._connection.execute(
            postgres_insert(TotpPeriodUse)
            .values(
                admin_account_id=candidate.account_id,
                totp_factor_id=candidate.factor_id,
                period_counter=period_counter,
                consumed_at=current_time,
            )
            .on_conflict_do_nothing(
                constraint="uq_totp_period_uses_account_factor_counter"
            )
            .returning(TotpPeriodUse.totp_period_use_id)
        ).scalar_one_or_none()
        if period_id is None:
            return False
        updated = self._connection.execute(
            update(AdminAccount)
            .where(
                AdminAccount.admin_account_id == candidate.account_id,
                AdminAccount.status == "active",
                AdminAccount.password_hash == candidate.password_hash,
            )
            .values(password_hash=password_hash)
        )
        if updated.rowcount != 1:
            raise RuntimeError("administrative password change lost account state")
        return True

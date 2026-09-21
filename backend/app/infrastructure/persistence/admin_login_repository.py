"""Read-only PostgreSQL adapter for administrative login validation."""

from sqlalchemy import Connection, select

from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginCandidate,
    AdministrativeLoginStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    RecoveryCode,
    TotpFactor,
    TotpPeriodUse,
)


class PostgresAdministrativeLoginStore(AdministrativeLoginStore):
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def load_candidate(self, *, email_lookup_digest: bytes) -> AdministrativeLoginCandidate | None:
        account = self._connection.execute(
            select(
                AdminAccount.admin_account_id,
                AdminAccount.role,
                AdminAccount.status,
                AdminAccount.password_hash,
            )
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminEmailClaim.claim_kind == "current",
                AdminEmailClaim.lookup_digest == email_lookup_digest,
            )
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
                TotpFactor.admin_account_id == account.admin_account_id,
                TotpFactor.status == "active",
            )
        ).one_or_none()

        used_periods: tuple[int, ...] = ()
        if factor is not None:
            used_periods = tuple(
                self._connection.execute(
                    select(TotpPeriodUse.period_counter).where(
                        TotpPeriodUse.admin_account_id == account.admin_account_id,
                        TotpPeriodUse.totp_factor_id == factor.totp_factor_id,
                    )
                ).scalars()
            )
        recovery_digests = tuple(
            self._connection.execute(
                select(RecoveryCode.lookup_digest).where(
                    RecoveryCode.admin_account_id == account.admin_account_id,
                    RecoveryCode.status == "active",
                )
            ).scalars()
        )

        return AdministrativeLoginCandidate(
            account_id=account.admin_account_id,
            role=account.role,
            status=account.status,
            password_hash=account.password_hash,
            factor_id=None if factor is None else factor.totp_factor_id,
            factor_ciphertext=None if factor is None else factor.totp_secret_ciphertext,
            factor_key_version=None if factor is None else factor.key_version,
            factor_algorithm=None if factor is None else factor.algorithm,
            used_period_counters=used_periods,
            active_recovery_digests=recovery_digests,
        )

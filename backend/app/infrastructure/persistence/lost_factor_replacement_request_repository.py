"""PostgreSQL lookup and account-state locking for T069 requests."""

from datetime import datetime

from sqlalchemy import Connection, select

from backend.app.application.admin_access.lost_factor_replacement_request import (
    LostFactorReplacementCandidate,
    LostFactorReplacementRequestStore,
)
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminEmailClaim,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)


class PostgresLostFactorReplacementRequestStore(LostFactorReplacementRequestStore):
    """Lock account and security state before checking eligibility or issuing links."""

    def __init__(
        self,
        connection: Connection,
        *,
        email_protector: AdministrativeEmailProtector,
        current_time: datetime,
    ) -> None:
        self._connection = connection
        self._email_protector = email_protector
        self._current_time = current_time

    def load_candidate(self, *, email_lookup_digest: bytes) -> LostFactorReplacementCandidate | None:
        row = self._connection.execute(
            select(
                AdminAccount.admin_account_id,
                AdminAccount.status,
                AdminAccount.password_hash,
                AdminEmailClaim.email_ciphertext,
                AdminEmailClaim.key_version,
            )
            .join(
                AdminEmailClaim,
                AdminEmailClaim.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminEmailClaim.claim_kind == "current",
                AdminEmailClaim.lookup_digest == email_lookup_digest,
            )
            .with_for_update(of=AdminAccount)
        ).one_or_none()
        if row is None:
            return None

        security = self._connection.execute(
            select(
                AdminAccountSecurityState.lock_until,
                AdminAccountSecurityState.post_recovery_second_factor_restricted,
            )
            .where(
                AdminAccountSecurityState.admin_account_id == row.admin_account_id
            )
            .with_for_update()
        ).one_or_none()
        if security is None:
            raise ValueError("administrative account security state is unavailable.")

        allowed = PostgresAdministrativeAccountSecurityStore(
            self._connection
        ).ensure_credential_check_allowed(
            account_id=row.admin_account_id,
            current_time=self._current_time,
        )
        return LostFactorReplacementCandidate(
            account_id=row.admin_account_id,
            status=row.status,
            password_hash=row.password_hash,
            recipient_email=self._email_protector.decrypt(
                email_ciphertext=row.email_ciphertext,
                key_version=row.key_version,
            ),
            credential_check_allowed=allowed,
            post_recovery_restricted=security.post_recovery_second_factor_restricted,
        )

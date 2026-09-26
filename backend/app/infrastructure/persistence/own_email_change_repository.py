"""Transactional PostgreSQL reservation for an administrator's own email change."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError

from backend.app.application.admin_access.request_own_email_change import (
    OwnEmailChangeCandidate,
    OwnEmailChangeStore,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    SecurityLink as SecurityLinkModel,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.security.admin_email_protection import (
    ProtectedAdministrativeEmail,
)


class PostgresOwnEmailChangeStore(OwnEmailChangeStore):
    """Serialize per-account requests and let the global unique index arbitrate races."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def load_candidate(self, *, account_id: int) -> OwnEmailChangeCandidate | None:
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
        if factor is None or factor.totp_secret_ciphertext is None or factor.key_version is None:
            return None
        return OwnEmailChangeCandidate(
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
        )

    def reserve_email(
        self,
        *,
        candidate: OwnEmailChangeCandidate,
        email: ProtectedAdministrativeEmail,
        period_counter: int,
        current_time: datetime,
    ) -> bool:
        """Insert the claim and consume its TOTP proof in one savepoint."""

        try:
            with self._connection.begin_nested():
                account_status = self._connection.execute(
                    select(AdminAccount.status)
                    .where(AdminAccount.admin_account_id == candidate.account_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if account_status != "active":
                    return False
                self._connection.execute(
                    update(SecurityLinkModel)
                    .where(
                        SecurityLinkModel.admin_account_id == candidate.account_id,
                        SecurityLinkModel.purpose == "email_change",
                        SecurityLinkModel.status == "active",
                        SecurityLinkModel.expires_at <= current_time,
                    )
                    .values(status="expired", updated_at=current_time)
                )
                self._connection.execute(
                    update(SecurityLinkModel)
                    .where(
                        SecurityLinkModel.admin_account_id == candidate.account_id,
                        SecurityLinkModel.purpose == "email_change",
                        SecurityLinkModel.status == "active",
                        SecurityLinkModel.expires_at > current_time,
                    )
                    .values(
                        status="invalidated",
                        invalidated_at=current_time,
                        updated_at=current_time,
                    )
                )
                self._connection.execute(
                    delete(AdminEmailClaim).where(
                        AdminEmailClaim.admin_account_id == candidate.account_id,
                        AdminEmailClaim.claim_kind == "reserved",
                    )
                )
                try:
                    with self._connection.begin_nested():
                        self._connection.execute(
                            insert(AdminEmailClaim).values(
                                admin_account_id=candidate.account_id,
                                claim_kind="reserved",
                                lookup_digest=email.lookup_digest,
                                email_ciphertext=email.email_ciphertext,
                                key_version=email.key_version,
                            )
                        )
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
                            raise _EmailReservationConflict
                except (IntegrityError, _EmailReservationConflict):
                    return False
            return True
        except IntegrityError:
            return False

    def invalidate_failed_delivery(
        self, *, account_id: int, link_id: int, current_time: datetime
    ) -> bool:
        """Release only the still-current reservation whose own mail failed."""

        locked_account = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(AdminAccount.admin_account_id == account_id)
            .with_for_update()
        ).scalar_one_or_none()
        if locked_account is None:
            return False
        invalidated = self._connection.execute(
            update(SecurityLinkModel)
            .where(
                SecurityLinkModel.security_link_id == link_id,
                SecurityLinkModel.admin_account_id == account_id,
                SecurityLinkModel.purpose == "email_change",
                SecurityLinkModel.status == "active",
                SecurityLinkModel.delivery_status == "pending",
            )
            .values(
                status="invalidated",
                delivery_status="failed",
                invalidated_at=current_time,
                updated_at=current_time,
            )
            .returning(SecurityLinkModel.security_link_id)
        ).scalar_one_or_none()
        if invalidated is None:
            return False
        self._connection.execute(
            delete(AdminEmailClaim).where(
                AdminEmailClaim.admin_account_id == account_id,
                AdminEmailClaim.claim_kind == "reserved",
            )
        )
        return True


class _EmailReservationConflict(Exception):
    """Rollback a partial reservation when any uniqueness guard rejects it."""

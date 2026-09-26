"""Atomic PostgreSQL persistence for confirming a pending TOTP replacement."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from backend.app.application.admin_access.confirm_totp_replacement import (
    TotpReplacementConfirmationCandidate,
    TotpReplacementConfirmationStore,
)
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminEmailClaim,
    PendingSecuritySetup,
    RecoveryCode as RecoveryCodeModel,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector


class PostgresTotpReplacementConfirmationStore(TotpReplacementConfirmationStore):
    def __init__(self, connection: Connection, email_protector: AdministrativeEmailProtector):
        self._connection = connection
        self._email_protector = email_protector

    def load_candidate(self, *, account_id: int) -> TotpReplacementConfirmationCandidate | None:
        account = self._connection.execute(
            select(AdminAccount.admin_account_id)
            .where(AdminAccount.admin_account_id == account_id, AdminAccount.status == "active")
            .with_for_update()
        ).one_or_none()
        if account is None:
            return None
        pending = self._connection.execute(
            select(
                PendingSecuritySetup.pending_security_setup_id,
                PendingSecuritySetup.totp_secret_ciphertext,
                PendingSecuritySetup.key_version,
                PendingSecuritySetup.expires_at,
                PendingSecuritySetup.verified_totp_factor_id,
                PendingSecuritySetup.verified_totp_period_counter,
                PendingSecuritySetup.verified_recovery_code_digest,
            )
            .where(
                PendingSecuritySetup.admin_account_id == account_id,
                PendingSecuritySetup.flow == "totp_replacement",
                PendingSecuritySetup.status == "pending",
            )
            .with_for_update()
        ).one_or_none()
        factor = self._connection.execute(
            select(TotpFactor.totp_factor_id)
            .where(TotpFactor.admin_account_id == account_id, TotpFactor.status == "active")
            .with_for_update()
        ).one_or_none()
        claim = self._connection.execute(
            select(AdminEmailClaim.email_ciphertext, AdminEmailClaim.key_version).where(
                AdminEmailClaim.admin_account_id == account_id,
                AdminEmailClaim.claim_kind == "current",
            )
        ).one_or_none()
        if pending is None or factor is None or claim is None:
            return None
        return TotpReplacementConfirmationCandidate(
            account_id=account_id,
            pending_setup_id=pending[0],
            pending_ciphertext=pending[1],
            pending_key_version=pending[2],
            expires_at=pending[3],
            verified_totp_factor_id=pending[4],
            verified_totp_period_counter=pending[5],
            verified_recovery_code_digest=pending[6],
            active_factor_id=factor[0],
            current_email=self._email_protector.decrypt(
                email_ciphertext=claim.email_ciphertext,
                key_version=claim.key_version,
            ),
        )

    def complete_replacement(
        self,
        *,
        candidate: TotpReplacementConfirmationCandidate,
        factor_ciphertext: bytes,
        factor_key_version: str,
        recovery_codes: tuple[RecoveryCode, ...],
        new_period_counter: int,
        current_time: datetime,
        require_original_proof: bool = True,
    ) -> bool:
        if candidate.verified_totp_period_counter is not None:
            proof_use = self._connection.execute(
                postgres_insert(TotpPeriodUse)
                .values(
                    admin_account_id=candidate.account_id,
                    totp_factor_id=candidate.verified_totp_factor_id,
                    period_counter=candidate.verified_totp_period_counter,
                    consumed_at=current_time,
                )
                .on_conflict_do_nothing(constraint="uq_totp_period_uses_account_factor_counter")
                .returning(TotpPeriodUse.totp_period_use_id)
            ).scalar_one_or_none()
            if proof_use is None:
                return False
        elif candidate.verified_recovery_code_digest is not None:
            consumed = self._connection.execute(
                update(RecoveryCodeModel)
                .where(
                    RecoveryCodeModel.admin_account_id == candidate.account_id,
                    RecoveryCodeModel.lookup_digest == candidate.verified_recovery_code_digest,
                    RecoveryCodeModel.status == "active",
                )
                .values(status="used", used_at=current_time, updated_at=current_time)
                .returning(RecoveryCodeModel.recovery_code_id)
            ).scalar_one_or_none()
            if consumed is None:
                return False
        elif require_original_proof:
            return False

        old_factor = self._connection.execute(
            update(TotpFactor)
            .where(
                TotpFactor.admin_account_id == candidate.account_id,
                TotpFactor.totp_factor_id == candidate.active_factor_id,
                TotpFactor.status == "active",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                invalidated_at=current_time,
                updated_at=current_time,
            )
            .returning(TotpFactor.totp_factor_id)
        ).scalar_one_or_none()
        if old_factor is None:
            raise RuntimeError("active TOTP factor changed during replacement")

        new_factor_id = self._connection.execute(
            insert(TotpFactor)
            .values(
                admin_account_id=candidate.account_id,
                totp_secret_ciphertext=factor_ciphertext,
                key_version=factor_key_version,
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                status="active",
                confirmed_at=current_time,
                invalidated_at=None,
            )
            .returning(TotpFactor.totp_factor_id)
        ).scalar_one()
        self._connection.execute(
            insert(TotpPeriodUse).values(
                admin_account_id=candidate.account_id,
                totp_factor_id=new_factor_id,
                period_counter=new_period_counter,
                consumed_at=current_time,
            )
        )
        self._connection.execute(
            update(RecoveryCodeModel)
            .where(
                RecoveryCodeModel.admin_account_id == candidate.account_id,
                RecoveryCodeModel.status.in_(("active", "used")),
            )
            .values(status="invalidated", invalidated_at=current_time, updated_at=current_time)
        )
        self._connection.execute(
            insert(RecoveryCodeModel),
            [
                {
                    "admin_account_id": code.account_id,
                    "lookup_digest": code.lookup_digest,
                    "key_version": code.key_version,
                    "position": code.position,
                    "status": code.status,
                    "used_at": code.used_at,
                    "invalidated_at": code.invalidated_at,
                }
                for code in recovery_codes
            ],
        )
        finalized = self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.pending_security_setup_id == candidate.pending_setup_id,
                PendingSecuritySetup.admin_account_id == candidate.account_id,
                PendingSecuritySetup.flow == "totp_replacement",
                PendingSecuritySetup.status == "pending",
                PendingSecuritySetup.expires_at > current_time,
            )
            .values(
                status="confirmed",
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=current_time,
            )
            .returning(PendingSecuritySetup.pending_security_setup_id)
        ).scalar_one_or_none()
        if finalized is None:
            raise RuntimeError("pending TOTP replacement changed during confirmation")
        return True

    def discard_pending(
        self, *, candidate: TotpReplacementConfirmationCandidate, status: str, current_time: datetime
    ) -> None:
        if status not in {"invalidated", "expired"}:
            raise ValueError("pending setup disposition is invalid")
        self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.pending_security_setup_id == candidate.pending_setup_id,
                PendingSecuritySetup.admin_account_id == candidate.account_id,
                PendingSecuritySetup.status == "pending",
            )
            .values(
                status=status,
                totp_secret_ciphertext=None,
                key_version=None,
                verified_totp_factor_id=None,
                verified_totp_period_counter=None,
                verified_recovery_code_digest=None,
                updated_at=current_time,
            )
        )

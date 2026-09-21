"""PostgreSQL transaction for completing initial owner activation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, insert, select, update

from backend.app.application.admin_access.owner_activation import (
    LockedOwnerActivation,
    OwnerActivationStore,
)
from backend.app.domain.authentication.recovery_code import RecoveryCode
from backend.app.domain.authentication.totp_factor import TotpFactor
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    OwnerBootstrapState,
    PendingSecuritySetup,
    RecoveryCode as RecoveryCodeModel,
    SecurityLink,
    TotpFactor as TotpFactorModel,
    TotpPeriodUse,
)


class PostgresOwnerActivationStore(OwnerActivationStore):
    """Lock and transition every owner-activation row in one transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_candidate(
        self,
        *,
        link_id: int,
        account_id: int,
        current_time: datetime,
    ) -> LockedOwnerActivation | None:
        """Revalidate bootstrap, owner, link and setup under a stable lock order."""

        bootstrap = self._connection.execute(
            select(
                OwnerBootstrapState.status,
                OwnerBootstrapState.owner_account_id,
            )
            .where(OwnerBootstrapState.bootstrap_state_id == 1)
            .with_for_update()
        ).one_or_none()
        if (
            bootstrap is None
            or bootstrap.status != "open"
            or bootstrap.owner_account_id is not None
        ):
            return None

        account = self._connection.execute(
            select(AdminAccount.role, AdminAccount.status)
            .where(AdminAccount.admin_account_id == account_id)
            .with_for_update()
        ).one_or_none()
        if account is None or (account.role, account.status) != ("owner", "inactive"):
            return None

        link = self._connection.execute(
            select(SecurityLink.security_link_id)
            .where(
                SecurityLink.security_link_id == link_id,
                SecurityLink.admin_account_id == account_id,
                SecurityLink.purpose == "initial_activation",
                SecurityLink.status == "active",
                SecurityLink.expires_at > current_time,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if link is None:
            return None

        setup = self._connection.execute(
            select(
                PendingSecuritySetup.pending_security_setup_id,
                PendingSecuritySetup.totp_secret_ciphertext,
                PendingSecuritySetup.key_version,
            )
            .where(
                PendingSecuritySetup.admin_account_id == account_id,
                PendingSecuritySetup.flow == "owner_activation",
                PendingSecuritySetup.status == "pending",
                PendingSecuritySetup.expires_at > current_time,
            )
            .with_for_update()
        ).one_or_none()
        if setup is None:
            return None

        return LockedOwnerActivation(
            link_id=link_id,
            account_id=account_id,
            setup_id=setup.pending_security_setup_id,
            pending_totp_ciphertext=setup.totp_secret_ciphertext,
            pending_key_version=setup.key_version,
        )

    def discard_pending(
        self,
        *,
        candidate: LockedOwnerActivation,
        current_time: datetime,
    ) -> None:
        """Invalidate the exact locked setup and erase its recoverable secret."""

        self._connection.execute(
            update(PendingSecuritySetup)
            .where(
                PendingSecuritySetup.pending_security_setup_id == candidate.setup_id,
                PendingSecuritySetup.status == "pending",
            )
            .values(
                status="invalidated",
                totp_secret_ciphertext=None,
                key_version=None,
                updated_at=current_time,
            )
        )

    def activate(
        self,
        *,
        candidate: LockedOwnerActivation,
        password_hash: str,
        factor: TotpFactor,
        period_counter: int,
        recovery_codes: tuple[RecoveryCode, ...],
        current_time: datetime,
    ) -> None:
        """Apply all successful owner-activation writes before the caller commits."""

        factor_id = self._connection.execute(
            insert(TotpFactorModel)
            .values(
                admin_account_id=factor.account_id,
                totp_secret_ciphertext=factor.secret_ciphertext,
                key_version=factor.key_version,
                algorithm=factor.algorithm,
                digits=factor.digits,
                period_seconds=factor.period_seconds,
                status=factor.status,
                confirmed_at=factor.confirmed_at,
                invalidated_at=factor.invalidated_at,
            )
            .returning(TotpFactorModel.totp_factor_id)
        ).scalar_one()
        self._connection.execute(
            insert(TotpPeriodUse).values(
                admin_account_id=candidate.account_id,
                totp_factor_id=factor_id,
                period_counter=period_counter,
                consumed_at=current_time,
            )
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
        _require_one(
            self._connection.execute(
                update(AdminAccount)
                .where(
                    AdminAccount.admin_account_id == candidate.account_id,
                    AdminAccount.role == "owner",
                    AdminAccount.status == "inactive",
                )
                .values(
                    status="active",
                    password_hash=password_hash,
                    updated_at=current_time,
                )
            ).rowcount
        )
        _require_one(
            self._connection.execute(
                update(PendingSecuritySetup)
                .where(
                    PendingSecuritySetup.pending_security_setup_id == candidate.setup_id,
                    PendingSecuritySetup.status == "pending",
                )
                .values(
                    status="confirmed",
                    totp_secret_ciphertext=None,
                    key_version=None,
                    updated_at=current_time,
                )
            ).rowcount
        )
        _require_one(
            self._connection.execute(
                update(SecurityLink)
                .where(
                    SecurityLink.security_link_id == candidate.link_id,
                    SecurityLink.status == "active",
                )
                .values(
                    status="consumed",
                    consumed_at=current_time,
                    updated_at=current_time,
                )
            ).rowcount
        )
        _require_one(
            self._connection.execute(
                update(OwnerBootstrapState)
                .where(
                    OwnerBootstrapState.bootstrap_state_id == 1,
                    OwnerBootstrapState.status == "open",
                    OwnerBootstrapState.owner_account_id.is_(None),
                )
                .values(
                    status="closed",
                    owner_account_id=candidate.account_id,
                    closed_at=current_time,
                )
            ).rowcount
        )


def _require_one(rowcount: int | None) -> None:
    if rowcount != 1:
        raise RuntimeError("owner activation transition was not atomic.")

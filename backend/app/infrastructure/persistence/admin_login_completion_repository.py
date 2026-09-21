"""Atomic PostgreSQL consumption of validated administrative login factors."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, exists, literal, select, update
from sqlalchemy.dialects.postgresql import insert

from backend.app.application.admin_access.login_completion import (
    AdministrativeLoginFactorStore,
)
from backend.app.application.admin_access.login_validation import (
    ValidatedAdministrativeLogin,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    RecoveryCode,
    TotpFactor,
    TotpPeriodUse,
)


class PostgresAdministrativeLoginFactorStore(AdministrativeLoginFactorStore):
    """Conditionally consume exactly the factor referenced by validation."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def consume_validated_factor(
        self,
        *,
        validated: ValidatedAdministrativeLogin,
        current_time: datetime,
    ) -> bool:
        if validated.totp_period_counter is not None:
            consumed = self._consume_totp_period(
                validated=validated,
                current_time=current_time,
            )
        else:
            consumed = self._consume_recovery_code(
                validated=validated,
                current_time=current_time,
            )

        if consumed and validated.upgraded_password_hash is not None:
            self._connection.execute(
                update(AdminAccount)
                .where(
                    AdminAccount.admin_account_id == validated.account_id,
                    AdminAccount.status == "active",
                )
                .values(password_hash=validated.upgraded_password_hash)
            )
        return consumed

    def _consume_totp_period(
        self,
        *,
        validated: ValidatedAdministrativeLogin,
        current_time: datetime,
    ) -> bool:
        eligible_period = (
            select(
                literal(validated.account_id),
                literal(validated.factor_id),
                literal(validated.totp_period_counter),
                literal(current_time),
            )
            .select_from(AdminAccount)
            .join(
                TotpFactor,
                TotpFactor.admin_account_id == AdminAccount.admin_account_id,
            )
            .where(
                AdminAccount.admin_account_id == validated.account_id,
                AdminAccount.status == "active",
                TotpFactor.totp_factor_id == validated.factor_id,
                TotpFactor.status == "active",
            )
        )
        statement = (
            insert(TotpPeriodUse)
            .from_select(
                (
                    TotpPeriodUse.admin_account_id,
                    TotpPeriodUse.totp_factor_id,
                    TotpPeriodUse.period_counter,
                    TotpPeriodUse.consumed_at,
                ),
                eligible_period,
            )
            .on_conflict_do_nothing(
                constraint="uq_totp_period_uses_account_factor_counter"
            )
            .returning(TotpPeriodUse.totp_period_use_id)
        )
        return self._connection.execute(statement).scalar_one_or_none() is not None

    def _consume_recovery_code(
        self,
        *,
        validated: ValidatedAdministrativeLogin,
        current_time: datetime,
    ) -> bool:
        active_factor_exists = exists(
            select(TotpFactor.totp_factor_id).where(
                TotpFactor.totp_factor_id == validated.factor_id,
                TotpFactor.admin_account_id == validated.account_id,
                TotpFactor.status == "active",
            )
        )
        active_account_exists = exists(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == validated.account_id,
                AdminAccount.status == "active",
            )
        )
        statement = (
            update(RecoveryCode)
            .where(
                RecoveryCode.admin_account_id == validated.account_id,
                RecoveryCode.lookup_digest == validated.recovery_code_digest,
                RecoveryCode.status == "active",
                active_factor_exists,
                active_account_exists,
            )
            .values(status="used", used_at=current_time)
            .returning(RecoveryCode.recovery_code_id)
        )
        return self._connection.execute(statement).scalar_one_or_none() is not None

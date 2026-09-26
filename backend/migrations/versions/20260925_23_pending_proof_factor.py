"""Bind a pending TOTP proof to the factor whose code was checked."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260925_23"
down_revision: Union[str, None] = "20260925_22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pending_security_setups",
        sa.Column("verified_totp_factor_id", sa.BigInteger(), nullable=True),
    )
    op.drop_constraint(
        "ck_pending_security_setups_verified_proof",
        "pending_security_setups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pending_security_setups_verified_proof",
        "pending_security_setups",
        "((verified_totp_period_counter IS NULL AND verified_totp_factor_id IS NULL) OR "
        "(verified_totp_period_counter IS NOT NULL AND verified_totp_factor_id IS NOT NULL)) AND "
        "NOT (verified_totp_period_counter IS NOT NULL AND "
        "verified_recovery_code_digest IS NOT NULL) AND "
        "(status = 'pending' OR (verified_totp_period_counter IS NULL AND "
        "verified_totp_factor_id IS NULL AND verified_recovery_code_digest IS NULL)) AND "
        "(verified_recovery_code_digest IS NULL OR "
        "octet_length(verified_recovery_code_digest) = 32)",
    )
    op.create_foreign_key(
        "fk_pending_security_setups_verified_factor_account",
        "pending_security_setups",
        "totp_factors",
        ["verified_totp_factor_id", "admin_account_id"],
        ["totp_factor_id", "admin_account_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_pending_security_setups_verified_factor_account",
        "pending_security_setups",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_pending_security_setups_verified_proof",
        "pending_security_setups",
        type_="check",
    )
    op.create_check_constraint(
        "ck_pending_security_setups_verified_proof",
        "pending_security_setups",
        "NOT (verified_totp_period_counter IS NOT NULL AND "
        "verified_recovery_code_digest IS NOT NULL) AND "
        "(status = 'pending' OR (verified_totp_period_counter IS NULL AND "
        "verified_recovery_code_digest IS NULL)) AND "
        "(verified_recovery_code_digest IS NULL OR "
        "octet_length(verified_recovery_code_digest) = 32)",
    )
    op.drop_column("pending_security_setups", "verified_totp_factor_id")

"""Retain the unconsumed credential proof for authenticated TOTP replacement."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260925_22"
down_revision: Union[str, None] = "20260918_21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pending_security_setups",
        sa.Column("verified_totp_period_counter", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "pending_security_setups",
        sa.Column("verified_recovery_code_digest", sa.LargeBinary(), nullable=True),
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


def downgrade() -> None:
    op.drop_constraint(
        "ck_pending_security_setups_verified_proof",
        "pending_security_setups",
        type_="check",
    )
    op.drop_column("pending_security_setups", "verified_recovery_code_digest")
    op.drop_column("pending_security_setups", "verified_totp_period_counter")

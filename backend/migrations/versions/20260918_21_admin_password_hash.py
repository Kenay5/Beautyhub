"""Add the non-recoverable administrative password hash."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_21"
down_revision: Union[str, None] = "20260918_20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admin_accounts",
        sa.Column("password_hash", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_admin_accounts_password_hash_format",
        "admin_accounts",
        "password_hash IS NULL OR password_hash LIKE '$argon2id$%'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_admin_accounts_password_hash_format",
        "admin_accounts",
        type_="check",
    )
    op.drop_column("admin_accounts", "password_hash")

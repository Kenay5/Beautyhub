"""Retain encrypted staff identity only for the administrative-history period."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260926_24"
down_revision: Union[str, None] = "20260925_23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deactivated_staff_identities",
        sa.Column(
            "admin_account_id",
            sa.BigInteger(),
            sa.ForeignKey("admin_accounts.admin_account_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("email_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column("identifiable_until", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(email_ciphertext) > 0",
            name="ck_deactivated_staff_identities_ciphertext_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_deactivated_staff_identities_key_version_nonempty",
        ),
    )
    op.create_index(
        "ix_deactivated_staff_identities_identifiable_until",
        "deactivated_staff_identities",
        ["identifiable_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_deactivated_staff_identities_identifiable_until",
        table_name="deactivated_staff_identities",
    )
    op.drop_table("deactivated_staff_identities")

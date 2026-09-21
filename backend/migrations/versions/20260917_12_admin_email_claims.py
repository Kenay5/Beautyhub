"""Create protected current and reserved administrative email claims."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_12"
down_revision: Union[str, None] = "20260917_11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_email_claims",
        sa.Column(
            "admin_email_claim_id", sa.BigInteger(), sa.Identity(), nullable=False
        ),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("claim_kind", sa.String(length=20), nullable=False),
        sa.Column("lookup_digest", sa.LargeBinary(), nullable=False),
        sa.Column("email_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "claim_kind IN ('current', 'reserved')",
            name="ck_admin_email_claims_kind",
        ),
        sa.CheckConstraint(
            "octet_length(lookup_digest) = 32",
            name="ck_admin_email_claims_lookup_digest_length",
        ),
        sa.CheckConstraint(
            "octet_length(email_ciphertext) > 0",
            name="ck_admin_email_claims_ciphertext_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_admin_email_claims_key_version_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("admin_email_claim_id"),
        sa.UniqueConstraint("lookup_digest", name="uq_admin_email_claims_lookup_digest"),
    )
    op.create_index(
        "uq_admin_email_claims_current_per_account",
        "admin_email_claims",
        ["admin_account_id"],
        unique=True,
        postgresql_where=sa.text("claim_kind = 'current'"),
    )
    op.create_index(
        "uq_admin_email_claims_reserved_per_account",
        "admin_email_claims",
        ["admin_account_id"],
        unique=True,
        postgresql_where=sa.text("claim_kind = 'reserved'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admin_email_claims_reserved_per_account",
        table_name="admin_email_claims",
    )
    op.drop_index(
        "uq_admin_email_claims_current_per_account",
        table_name="admin_email_claims",
    )
    op.drop_table("admin_email_claims")

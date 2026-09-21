"""Create administrative security links and pending TOTP setups."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_13"
down_revision: Union[str, None] = "20260917_12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_links",
        sa.Column("security_link_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("delivery_status", sa.String(length=20), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
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
            "purpose IN ('initial_activation', 'invitation', 'password_recovery', "
            "'forced_password_reset', 'totp_replacement', 'email_change')",
            name="ck_security_links_purpose",
        ),
        sa.CheckConstraint(
            "octet_length(token_digest) = 32",
            name="ck_security_links_token_digest_length",
        ),
        sa.CheckConstraint(
            "expires_at > issued_at", name="ck_security_links_expiry_range"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'consumed', 'invalidated', 'expired')",
            name="ck_security_links_status",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'accepted', 'failed', 'uncertain')",
            name="ck_security_links_delivery_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND consumed_at IS NULL AND invalidated_at IS NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND consumed_at IS NULL AND invalidated_at IS NOT NULL) OR "
            "(status = 'expired' AND consumed_at IS NULL AND invalidated_at IS NULL)",
            name="ck_security_links_state_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("security_link_id"),
        sa.UniqueConstraint("token_digest", name="uq_security_links_token_digest"),
    )
    op.create_index(
        "uq_security_links_active_account_purpose",
        "security_links",
        ["admin_account_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "pending_security_setups",
        sa.Column(
            "pending_security_setup_id", sa.BigInteger(), sa.Identity(), nullable=False
        ),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("flow", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("totp_secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("key_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "flow IN ('owner_activation', 'staff_activation', 'totp_replacement')",
            name="ck_pending_security_setups_flow",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'invalidated', 'expired')",
            name="ck_pending_security_setups_status",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_pending_security_setups_expiry_range",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND totp_secret_ciphertext IS NOT NULL "
            "AND key_version IS NOT NULL AND char_length(btrim(key_version)) > 0) OR "
            "(status <> 'pending' AND totp_secret_ciphertext IS NULL AND key_version IS NULL)",
            name="ck_pending_security_setups_secret_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pending_security_setup_id"),
    )
    op.create_index(
        "uq_pending_security_setups_account_flow",
        "pending_security_setups",
        ["admin_account_id", "flow"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_pending_security_setups_account_flow",
        table_name="pending_security_setups",
    )
    op.drop_table("pending_security_setups")
    op.drop_index(
        "uq_security_links_active_account_purpose",
        table_name="security_links",
    )
    op.drop_table("security_links")

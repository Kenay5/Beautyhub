"""Create protected TOTP factors, consumed periods, and recovery codes."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_14"
down_revision: Union[str, None] = "20260917_13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "totp_factors",
        sa.Column("totp_factor_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("totp_secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("key_version", sa.String(length=64), nullable=True),
        sa.Column("algorithm", sa.String(length=10), nullable=False),
        sa.Column("digits", sa.SmallInteger(), nullable=False),
        sa.Column("period_seconds", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
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
            "algorithm IN ('SHA1', 'SHA256', 'SHA512')",
            name="ck_totp_factors_algorithm",
        ),
        sa.CheckConstraint("digits = 6", name="ck_totp_factors_six_digits"),
        sa.CheckConstraint(
            "period_seconds = 30", name="ck_totp_factors_thirty_second_period"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invalidated')",
            name="ck_totp_factors_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND totp_secret_ciphertext IS NOT NULL "
            "AND octet_length(totp_secret_ciphertext) > 0 "
            "AND key_version IS NOT NULL AND char_length(btrim(key_version)) > 0 "
            "AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND totp_secret_ciphertext IS NULL "
            "AND key_version IS NULL AND invalidated_at IS NOT NULL)",
            name="ck_totp_factors_secret_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("totp_factor_id"),
        sa.UniqueConstraint(
            "totp_factor_id",
            "admin_account_id",
            name="uq_totp_factors_id_account",
        ),
    )
    op.create_index(
        "uq_totp_factors_active_per_account",
        "totp_factors",
        ["admin_account_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "totp_period_uses",
        sa.Column(
            "totp_period_use_id", sa.BigInteger(), sa.Identity(), nullable=False
        ),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("totp_factor_id", sa.BigInteger(), nullable=False),
        sa.Column("period_counter", sa.BigInteger(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "period_counter >= 0", name="ck_totp_period_uses_counter_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["totp_factor_id", "admin_account_id"],
            ["totp_factors.totp_factor_id", "totp_factors.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("totp_period_use_id"),
        sa.UniqueConstraint(
            "admin_account_id",
            "totp_factor_id",
            "period_counter",
            name="uq_totp_period_uses_account_factor_counter",
        ),
    )

    op.create_table(
        "recovery_codes",
        sa.Column("recovery_code_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("lookup_digest", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
            "octet_length(lookup_digest) = 32",
            name="ck_recovery_codes_lookup_digest_length",
        ),
        sa.CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_recovery_codes_key_version_nonempty",
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 10", name="ck_recovery_codes_position_range"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'used', 'invalidated')",
            name="ck_recovery_codes_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND used_at IS NULL AND invalidated_at IS NULL) OR "
            "(status = 'used' AND used_at IS NOT NULL AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND invalidated_at IS NOT NULL)",
            name="ck_recovery_codes_state_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("recovery_code_id"),
        sa.UniqueConstraint("lookup_digest", name="uq_recovery_codes_lookup_digest"),
    )
    op.create_index(
        "uq_recovery_codes_active_account_position",
        "recovery_codes",
        ["admin_account_id", "position"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.execute(
        """
        CREATE FUNCTION prevent_totp_factor_reactivation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'invalidated' AND NEW.status <> 'invalidated' THEN
                RAISE EXCEPTION 'Invalidated TOTP factor cannot be reactivated';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_totp_factors_prevent_reactivation
        BEFORE UPDATE ON totp_factors
        FOR EACH ROW
        EXECUTE FUNCTION prevent_totp_factor_reactivation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_recovery_code_reactivation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('used', 'invalidated') AND NEW.status = 'active' THEN
                RAISE EXCEPTION 'Consumed recovery code cannot be reactivated';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_recovery_codes_prevent_reactivation
        BEFORE UPDATE ON recovery_codes
        FOR EACH ROW
        EXECUTE FUNCTION prevent_recovery_code_reactivation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recovery_codes_prevent_reactivation ON recovery_codes"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_recovery_code_reactivation")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_totp_factors_prevent_reactivation ON totp_factors"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_totp_factor_reactivation")
    op.drop_index(
        "uq_recovery_codes_active_account_position", table_name="recovery_codes"
    )
    op.drop_table("recovery_codes")
    op.drop_table("totp_period_uses")
    op.drop_index("uq_totp_factors_active_per_account", table_name="totp_factors")
    op.drop_table("totp_factors")

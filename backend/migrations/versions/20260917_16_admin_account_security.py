"""Create row-locked administrative credential failure persistence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_16"
down_revision: Union[str, None] = "20260917_15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_credential_failure_events",
        sa.Column(
            "admin_credential_failure_event_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('login', 'password_change', 'email_change', "
            "'totp_replacement', 'recovery_code_regeneration')",
            name="ck_admin_credential_failure_events_operation",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("admin_credential_failure_event_id"),
        sa.UniqueConstraint(
            "admin_credential_failure_event_id",
            "admin_account_id",
            name="uq_admin_credential_failure_events_id_account",
        ),
    )
    op.create_index(
        "ix_admin_credential_failure_events_account_occurred_at",
        "admin_credential_failure_events",
        ["admin_account_id", "occurred_at"],
    )
    op.create_table(
        "admin_account_security_states",
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("lock_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fifth_failure_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "post_recovery_second_factor_restricted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(lock_until IS NULL AND fifth_failure_event_id IS NULL) OR "
            "(lock_until IS NOT NULL AND fifth_failure_event_id IS NOT NULL)",
            name="ck_admin_account_security_states_lock_reference",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fifth_failure_event_id", "admin_account_id"],
            [
                "admin_credential_failure_events.admin_credential_failure_event_id",
                "admin_credential_failure_events.admin_account_id",
            ],
        ),
        sa.PrimaryKeyConstraint("admin_account_id"),
    )
    op.execute(
        """
        INSERT INTO admin_account_security_states (admin_account_id)
        SELECT admin_account_id FROM admin_accounts
        ON CONFLICT (admin_account_id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE FUNCTION create_admin_account_security_state()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO admin_account_security_states (admin_account_id)
            VALUES (NEW.admin_account_id);
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_accounts_create_security_state
        AFTER INSERT ON admin_accounts
        FOR EACH ROW
        EXECUTE FUNCTION create_admin_account_security_state();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_accounts_create_security_state ON admin_accounts"
    )
    op.execute("DROP FUNCTION IF EXISTS create_admin_account_security_state")
    op.drop_table("admin_account_security_states")
    op.drop_index(
        "ix_admin_credential_failure_events_account_occurred_at",
        table_name="admin_credential_failure_events",
    )
    op.drop_table("admin_credential_failure_events")

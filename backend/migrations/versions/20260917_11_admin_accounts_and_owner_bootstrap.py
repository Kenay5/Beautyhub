"""Create administrative account identities and the singleton owner bootstrap."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_11"
down_revision: Union[str, None] = "20260914_10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_accounts",
        sa.Column("admin_account_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            "(role = 'owner' AND status IN ('inactive', 'active')) OR "
            "(role = 'staff' AND status IN ('pending', 'active', 'deactivated'))",
            name="ck_admin_accounts_role_status",
        ),
        sa.PrimaryKeyConstraint("admin_account_id"),
    )
    op.create_index(
        "uq_admin_accounts_single_owner",
        "admin_accounts",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index(
        "uq_admin_accounts_single_pending_or_active_staff",
        "admin_accounts",
        ["role"],
        unique=True,
        postgresql_where=sa.text(
            "role = 'staff' AND status IN ('pending', 'active')"
        ),
    )

    op.create_table(
        "owner_bootstrap_state",
        sa.Column("bootstrap_state_id", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("owner_account_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "bootstrap_state_id = 1", name="ck_owner_bootstrap_state_singleton"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed')",
            name="ck_owner_bootstrap_state_status",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status = 'closed' AND owner_account_id IS NOT NULL "
            "AND closed_at IS NOT NULL)",
            name="ck_owner_bootstrap_state_closure",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("bootstrap_state_id"),
    )
    op.execute(
        "INSERT INTO owner_bootstrap_state (bootstrap_state_id, status) "
        "VALUES (1, 'open')"
    )

    op.execute(
        """
        CREATE FUNCTION protect_owner_account()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND OLD.role = 'owner' THEN
                RAISE EXCEPTION 'Owner account cannot be deleted';
            END IF;

            IF TG_OP = 'UPDATE' AND OLD.role = 'owner' THEN
                IF NEW.role <> 'owner' THEN
                    RAISE EXCEPTION 'Owner account role cannot change';
                END IF;
                IF OLD.status = 'active' AND NEW.status <> 'active' THEN
                    RAISE EXCEPTION 'Active owner account cannot be deactivated';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_accounts_protect_owner
        BEFORE UPDATE OR DELETE ON admin_accounts
        FOR EACH ROW
        EXECUTE FUNCTION protect_owner_account()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_owner_bootstrap_state()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Owner bootstrap state cannot be deleted';
            END IF;
            IF NEW.bootstrap_state_id <> OLD.bootstrap_state_id THEN
                RAISE EXCEPTION 'Owner bootstrap state identifier cannot change';
            END IF;
            IF OLD.status = 'closed' THEN
                RAISE EXCEPTION 'Owner bootstrap state cannot be reopened';
            END IF;
            IF NEW.status = 'closed' AND NOT EXISTS (
                SELECT 1
                FROM admin_accounts
                WHERE admin_account_id = NEW.owner_account_id
                  AND role = 'owner'
            ) THEN
                RAISE EXCEPTION 'Closed owner bootstrap requires the owner account';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_owner_bootstrap_state_irreversible
        BEFORE UPDATE OR DELETE ON owner_bootstrap_state
        FOR EACH ROW
        EXECUTE FUNCTION protect_owner_bootstrap_state()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_owner_bootstrap_state_irreversible "
        "ON owner_bootstrap_state"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_owner_bootstrap_state()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_accounts_protect_owner ON admin_accounts"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_owner_account()")
    op.drop_table("owner_bootstrap_state")
    op.drop_index(
        "uq_admin_accounts_single_pending_or_active_staff",
        table_name="admin_accounts",
    )
    op.drop_index("uq_admin_accounts_single_owner", table_name="admin_accounts")
    op.drop_table("admin_accounts")

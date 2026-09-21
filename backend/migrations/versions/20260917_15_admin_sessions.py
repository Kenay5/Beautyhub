"""Create opaque administrative session persistence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_15"
down_revision: Union[str, None] = "20260917_14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_sessions",
        sa.Column("admin_session_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("admin_account_id", sa.BigInteger(), nullable=False),
        sa.Column("session_digest", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_digest", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_human_activity_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(session_digest) = 32",
            name="ck_admin_sessions_session_digest_length",
        ),
        sa.CheckConstraint(
            "octet_length(csrf_digest) = 32",
            name="ck_admin_sessions_csrf_digest_length",
        ),
        sa.CheckConstraint(
            "char_length(btrim(key_version)) > 0",
            name="ck_admin_sessions_key_version_nonempty",
        ),
        sa.CheckConstraint(
            "absolute_expires_at = created_at + INTERVAL '8 hours'",
            name="ck_admin_sessions_absolute_expiry",
        ),
        sa.CheckConstraint(
            "last_human_activity_at >= created_at "
            "AND last_human_activity_at <= absolute_expires_at",
            name="ck_admin_sessions_activity_range",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invalidated')",
            name="ck_admin_sessions_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND invalidated_at IS NULL) OR "
            "(status = 'invalidated' AND invalidated_at IS NOT NULL)",
            name="ck_admin_sessions_invalidation_state",
        ),
        sa.ForeignKeyConstraint(
            ["admin_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("admin_session_id"),
        sa.UniqueConstraint("session_digest", name="uq_admin_sessions_session_digest"),
    )
    op.create_index(
        "uq_admin_sessions_active_per_account",
        "admin_sessions",
        ["admin_account_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.execute(
        """
        CREATE FUNCTION prevent_admin_session_reactivation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'invalidated' AND NEW.status <> 'invalidated' THEN
                RAISE EXCEPTION 'Invalidated administrative session cannot be reactivated';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_sessions_prevent_reactivation
        BEFORE UPDATE ON admin_sessions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_admin_session_reactivation();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_sessions_prevent_reactivation ON admin_sessions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_admin_session_reactivation")
    op.drop_index("uq_admin_sessions_active_per_account", table_name="admin_sessions")
    op.drop_table("admin_sessions")

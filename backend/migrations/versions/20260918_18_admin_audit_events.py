"""Create minimum administrative audit-event persistence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_18"
down_revision: Union[str, None] = "20260918_17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACTIONS = (
    "'login', 'account_locked', 'logout', 'account_activation', "
    "'staff_invitation', 'staff_deactivation', 'password_change', "
    "'password_recovery', 'email_change', 'totp_replacement', "
    "'recovery_code_regeneration', 'appointment_created', "
    "'appointment_modified', 'appointment_cancelled', "
    "'appointment_result_recorded', 'appointment_private_code_resent', "
    "'availability_block_created', 'availability_block_modified', "
    "'availability_block_deleted', 'service_created', 'service_modified', "
    "'service_activated', 'service_deactivated', 'authorization_denied'"
)


def upgrade() -> None:
    op.create_table(
        "admin_audit_events",
        sa.Column("admin_audit_event_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actor_account_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_reference", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            f"action IN ({_ACTIONS})", name="ck_admin_audit_events_action"
        ),
        sa.CheckConstraint(
            "result IN ('succeeded', 'failed', 'denied')",
            name="ck_admin_audit_events_result",
        ),
        sa.CheckConstraint(
            "target_reference IS NULL OR "
            "target_reference ~ "
            "'^(appointment|availability_block|service|admin_account):[1-9][0-9]*$'",
            name="ck_admin_audit_events_internal_reference",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["admin_accounts.admin_account_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("admin_audit_event_id"),
    )
    op.create_index(
        "ix_admin_audit_events_actor_occurred_at",
        "admin_audit_events",
        ["actor_account_id", "occurred_at"],
    )
    op.create_index(
        "ix_admin_audit_events_action_occurred_at",
        "admin_audit_events",
        ["action", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_audit_events_action_occurred_at",
        table_name="admin_audit_events",
    )
    op.drop_index(
        "ix_admin_audit_events_actor_occurred_at",
        table_name="admin_audit_events",
    )
    op.drop_table("admin_audit_events")

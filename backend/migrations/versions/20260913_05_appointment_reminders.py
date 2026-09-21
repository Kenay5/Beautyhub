"""Create durable appointment reminders and their delivery relationship."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_05"
down_revision: Union[str, None] = "20260913_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointment_reminders",
        sa.Column(
            "appointment_reminder_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("appointment_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "appointment_scheduled_start", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "send_at = appointment_scheduled_start - interval '24 hours'",
            name="ck_appointment_reminders_exact_send_time",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'claimed', 'completed', 'invalidated', 'omitted')",
            name="ck_appointment_reminders_status",
        ),
        sa.CheckConstraint(
            "(status = 'claimed' AND claimed_at IS NOT NULL "
            "AND claim_expires_at > claimed_at) OR "
            "(status <> 'claimed' AND claimed_at IS NULL "
            "AND claim_expires_at IS NULL)",
            name="ck_appointment_reminders_claim_state",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.appointment_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("appointment_reminder_id"),
        sa.UniqueConstraint(
            "appointment_id",
            "appointment_scheduled_start",
            name="uq_appointment_reminders_appointment_schedule",
        ),
        sa.UniqueConstraint(
            "appointment_reminder_id",
            "appointment_id",
            name="uq_appointment_reminders_id_appointment",
        ),
    )
    op.create_index(
        "ix_appointment_reminders_status_send_at",
        "appointment_reminders",
        ["status", "send_at"],
    )
    op.add_column(
        "notification_deliveries",
        sa.Column("appointment_reminder_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_deliveries_reminder_appointment",
        "notification_deliveries",
        "appointment_reminders",
        ["appointment_reminder_id", "appointment_id"],
        ["appointment_reminder_id", "appointment_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "uq_notification_deliveries_reminder_channel",
        "notification_deliveries",
        ["appointment_reminder_id", "channel"],
        unique=True,
        postgresql_where=sa.text("appointment_reminder_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_notification_deliveries_reminder_channel",
        table_name="notification_deliveries",
    )
    op.drop_constraint(
        "fk_notification_deliveries_reminder_appointment",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_column("notification_deliveries", "appointment_reminder_id")
    op.drop_index(
        "ix_appointment_reminders_status_send_at",
        table_name="appointment_reminders",
    )
    op.drop_table("appointment_reminders")

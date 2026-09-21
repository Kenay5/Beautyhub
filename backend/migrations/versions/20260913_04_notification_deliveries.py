"""Create persistent per-channel notification delivery records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_04"
down_revision: Union[str, None] = "20260913_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column(
            "notification_delivery_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("appointment_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("previous_delivery_id", sa.BigInteger(), nullable=True),
        sa.Column("sanitized_error", sa.Text(), nullable=True),
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
            "char_length(btrim(event)) > 0",
            name="ck_notification_deliveries_event_nonempty",
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'whatsapp')",
            name="ck_notification_deliveries_channel",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'delivered', 'failed')",
            name="ck_notification_deliveries_status",
        ),
        sa.CheckConstraint(
            "sanitized_error IS NULL OR char_length(btrim(sanitized_error)) > 0",
            name="ck_notification_deliveries_sanitized_error_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.appointment_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_delivery_id"],
            ["notification_deliveries.notification_delivery_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("notification_delivery_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")

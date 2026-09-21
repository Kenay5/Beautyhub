"""Create disassociated monthly appointment statistics."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_08"
down_revision: Union[str, None] = "20260913_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_appointment_statistics",
        sa.Column(
            "monthly_appointment_statistic_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("service_id", sa.BigInteger(), nullable=False),
        sa.Column("branch", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("appointment_count", sa.BigInteger(), nullable=False),
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
            "month_start = date_trunc('month', month_start)::date",
            name="ck_monthly_appointment_statistics_month_start",
        ),
        sa.CheckConstraint(
            "branch IN ('chiconcuac', 'texcoco')",
            name="ck_monthly_appointment_statistics_branch",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed', 'no_show', "
            "'unrecorded_result')",
            name="ck_monthly_appointment_statistics_status",
        ),
        sa.CheckConstraint(
            "appointment_count >= 0",
            name="ck_monthly_appointment_statistics_nonnegative_count",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.service_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("monthly_appointment_statistic_id"),
        sa.UniqueConstraint(
            "month_start",
            "service_id",
            "branch",
            "status",
            name="uq_monthly_appointment_statistics_aggregate",
        ),
    )


def downgrade() -> None:
    op.drop_table("monthly_appointment_statistics")

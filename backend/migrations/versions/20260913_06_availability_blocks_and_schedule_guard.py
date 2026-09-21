"""Create availability blocks and the schedule transaction guard."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_06"
down_revision: Union[str, None] = "20260913_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "availability_blocks",
        sa.Column(
            "availability_block_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("branch", sa.String(length=20), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=False),
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
            "scope IN ('global', 'branch')",
            name="ck_availability_blocks_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND branch IS NULL) OR "
            "(scope = 'branch' AND branch IN ('chiconcuac', 'texcoco'))",
            name="ck_availability_blocks_scope_branch",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at", name="ck_availability_blocks_time_range"
        ),
        sa.PrimaryKeyConstraint("availability_block_id"),
    )
    op.create_table(
        "schedule_guard",
        sa.Column("guard_id", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("guard_id = 1", name="ck_schedule_guard_singleton"),
        sa.PrimaryKeyConstraint("guard_id"),
    )
    op.execute("INSERT INTO schedule_guard (guard_id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("schedule_guard")
    op.drop_table("availability_blocks")

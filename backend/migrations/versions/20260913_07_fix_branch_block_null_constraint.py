"""Reject branch-scoped availability blocks without a branch."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_07"
down_revision: Union[str, None] = "20260913_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_availability_blocks_scope_branch",
        "availability_blocks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_availability_blocks_scope_branch",
        "availability_blocks",
        "(scope = 'global' AND branch IS NULL) OR "
        "(scope = 'branch' AND branch IS NOT NULL "
        "AND branch IN ('chiconcuac', 'texcoco'))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_availability_blocks_scope_branch",
        "availability_blocks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_availability_blocks_scope_branch",
        "availability_blocks",
        "(scope = 'global' AND branch IS NULL) OR "
        "(scope = 'branch' AND branch IN ('chiconcuac', 'texcoco'))",
    )

"""Create minimum public request protection events."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_09"
down_revision: Union[str, None] = "20260913_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "public_request_events",
        sa.Column(
            "public_request_event_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("subject_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(category)) > 0",
            name="ck_public_request_events_category_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(result)) > 0",
            name="ck_public_request_events_result_nonempty",
        ),
        sa.CheckConstraint(
            "octet_length(subject_fingerprint) > 0",
            name="ck_public_request_events_fingerprint_nonempty",
        ),
        sa.CheckConstraint(
            "expires_at > occurred_at",
            name="ck_public_request_events_expiry_range",
        ),
        sa.PrimaryKeyConstraint("public_request_event_id"),
    )
    op.create_index(
        "ix_public_request_events_fingerprint_category_occurred_at",
        "public_request_events",
        ["subject_fingerprint", "category", "occurred_at"],
    )
    op.create_index(
        "ix_public_request_events_expires_at",
        "public_request_events",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_public_request_events_expires_at", table_name="public_request_events")
    op.drop_index(
        "ix_public_request_events_fingerprint_category_occurred_at",
        table_name="public_request_events",
    )
    op.drop_table("public_request_events")

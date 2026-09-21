"""Create opaque administrative moving-window rate-limit persistence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_17"
down_revision: Union[str, None] = "20260917_16"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CATEGORIES = (
    "'authentication_recovery_lost_factor', "
    "'authenticated_administrative_operation', "
    "'security_message_action', "
    "'appointment_notification_operation'"
)


def upgrade() -> None:
    op.create_table(
        "rate_limit_events",
        sa.Column("rate_limit_event_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("subject_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("request_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"category IN ({_CATEGORIES})", name="ck_rate_limit_events_category"
        ),
        sa.CheckConstraint(
            "octet_length(subject_fingerprint) = 32",
            name="ck_rate_limit_events_subject_fingerprint_length",
        ),
        sa.CheckConstraint(
            "octet_length(request_fingerprint) = 32",
            name="ck_rate_limit_events_request_fingerprint_length",
        ),
        sa.PrimaryKeyConstraint("rate_limit_event_id"),
        sa.UniqueConstraint(
            "category",
            "subject_fingerprint",
            "request_fingerprint",
            name="uq_rate_limit_events_idempotent_request",
        ),
    )
    op.create_index(
        "ix_rate_limit_events_subject_category_occurred_at",
        "rate_limit_events",
        ["subject_fingerprint", "category", "occurred_at"],
    )
    op.create_table(
        "rate_limit_guards",
        sa.Column("rate_limit_guard_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("subject_fingerprint", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            f"category IN ({_CATEGORIES})", name="ck_rate_limit_guards_category"
        ),
        sa.CheckConstraint(
            "octet_length(subject_fingerprint) = 32",
            name="ck_rate_limit_guards_subject_fingerprint_length",
        ),
        sa.PrimaryKeyConstraint("rate_limit_guard_id"),
        sa.UniqueConstraint(
            "category",
            "subject_fingerprint",
            name="uq_rate_limit_guards_subject_category",
        ),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_guards")
    op.drop_index(
        "ix_rate_limit_events_subject_category_occurred_at",
        table_name="rate_limit_events",
    )
    op.drop_table("rate_limit_events")

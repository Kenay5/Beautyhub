"""Create secret confirmation references for appointment booking."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_03"
down_revision: Union[str, None] = "20260913_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "booking_confirmation_references",
        sa.Column(
            "booking_confirmation_reference_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("reference_digest", sa.LargeBinary(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("appointment_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(reference_digest) > 0",
            name="ck_booking_confirmation_references_digest_nonempty",
        ),
        sa.CheckConstraint(
            "expires_at = generated_at + interval '24 hours'",
            name="ck_booking_confirmation_references_exact_expiry",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR "
            "(consumed_at >= generated_at AND consumed_at < expires_at)",
            name="ck_booking_confirmation_references_consumption_range",
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.appointment_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("booking_confirmation_reference_id"),
        sa.UniqueConstraint(
            "reference_digest",
            name="uq_booking_confirmation_references_digest",
        ),
        sa.UniqueConstraint(
            "appointment_id",
            name="uq_booking_confirmation_references_appointment",
        ),
    )


def downgrade() -> None:
    op.drop_table("booking_confirmation_references")

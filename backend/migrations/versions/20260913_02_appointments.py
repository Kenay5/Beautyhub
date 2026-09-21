"""Create appointments with service snapshots and consent evidence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_02"
down_revision: Union[str, None] = "20260913_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("appointment_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("private_code_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("private_code_digest", sa.LargeBinary(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=10), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("service_id", sa.BigInteger(), nullable=False),
        sa.Column("service_snapshot_name", sa.String(length=100), nullable=False),
        sa.Column(
            "service_snapshot_duration_minutes", sa.SmallInteger(), nullable=False
        ),
        sa.Column("service_snapshot_price", sa.Numeric(), nullable=False),
        sa.Column("branch", sa.String(length=20), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("cancellation_reason", sa.String(length=250), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("created_by_account_id", sa.BigInteger(), nullable=True),
        sa.Column("privacy_notice_version_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "privacy_notice_accepted_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("contact_processing_authorized", sa.Boolean(), nullable=False),
        sa.Column("adult_responsibility_declared", sa.Boolean(), nullable=False),
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
            "char_length(first_name) BETWEEN 1 AND 100 "
            "AND first_name = btrim(first_name)",
            name="ck_appointments_first_name",
        ),
        sa.CheckConstraint(
            "char_length(last_name) BETWEEN 1 AND 100 "
            "AND last_name = btrim(last_name)",
            name="ck_appointments_last_name",
        ),
        sa.CheckConstraint(
            "phone ~ '^[0-9]{10}$'", name="ck_appointments_phone_format"
        ),
        sa.CheckConstraint(
            "char_length(email) BETWEEN 1 AND 254 AND email = btrim(email)",
            name="ck_appointments_email_length_and_trimmed",
        ),
        sa.CheckConstraint(
            "branch IN ('chiconcuac', 'texcoco')",
            name="ck_appointments_branch",
        ),
        sa.CheckConstraint(
            "service_snapshot_name = btrim(service_snapshot_name) "
            "AND char_length(service_snapshot_name) BETWEEN 1 AND 100",
            name="ck_appointments_snapshot_name",
        ),
        sa.CheckConstraint(
            "service_snapshot_duration_minutes BETWEEN 5 AND 600 "
            "AND service_snapshot_duration_minutes % 5 = 0",
            name="ck_appointments_snapshot_duration",
        ),
        sa.CheckConstraint(
            "service_snapshot_price > 0 AND service_snapshot_price <= 20000.00 "
            "AND service_snapshot_price = round(service_snapshot_price, 2)",
            name="ck_appointments_snapshot_price",
        ),
        sa.CheckConstraint(
            "scheduled_end > scheduled_start", name="ck_appointments_schedule_range"
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed', 'no_show', "
            "'unrecorded_result')",
            name="ck_appointments_status",
        ),
        sa.CheckConstraint(
            "origin IN ('public', 'administrative')",
            name="ck_appointments_origin",
        ),
        sa.CheckConstraint(
            "(origin = 'public' AND created_by_account_id IS NULL) OR "
            "(origin = 'administrative' AND created_by_account_id IS NOT NULL)",
            name="ck_appointments_origin_account",
        ),
        sa.CheckConstraint(
            "contact_processing_authorized AND adult_responsibility_declared",
            name="ck_appointments_required_consent",
        ),
        sa.CheckConstraint(
            "cancellation_reason IS NULL OR "
            "(char_length(cancellation_reason) <= 250 "
            "AND cancellation_reason = btrim(cancellation_reason))",
            name="ck_appointments_cancellation_reason",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.service_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["privacy_notice_version_id"],
            ["privacy_notice_versions.privacy_notice_version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("appointment_id"),
        sa.UniqueConstraint(
            "private_code_digest", name="uq_appointments_private_code_digest"
        ),
    )


def downgrade() -> None:
    op.drop_table("appointments")

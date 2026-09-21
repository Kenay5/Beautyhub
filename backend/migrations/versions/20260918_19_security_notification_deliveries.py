"""Create private idempotent administrative security-delivery records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260918_19"
down_revision: Union[str, None] = "20260918_18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_notification_deliveries",
        sa.Column(
            "security_notification_delivery_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("recipient_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("recipient_key_version", sa.String(length=64), nullable=True),
        sa.Column("template", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key_digest", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            "event ~ '^[a-z][a-z0-9_]{0,99}$'",
            name="ck_security_notification_deliveries_event",
        ),
        sa.CheckConstraint(
            "template ~ '^[a-z][a-z0-9_]{0,99}$'",
            name="ck_security_notification_deliveries_template",
        ),
        sa.CheckConstraint(
            "(recipient_ciphertext IS NOT NULL "
            "AND octet_length(recipient_ciphertext) > 0 "
            "AND recipient_key_version IS NOT NULL "
            "AND char_length(btrim(recipient_key_version)) > 0) "
            "OR (recipient_ciphertext IS NULL AND recipient_key_version IS NULL)",
            name="ck_security_notification_deliveries_recipient_lifecycle",
        ),
        sa.CheckConstraint(
            "octet_length(idempotency_key_digest) = 32",
            name="ck_security_notification_deliveries_idempotency_digest_length",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'failed', 'uncertain')",
            name="ck_security_notification_deliveries_status",
        ),
        sa.CheckConstraint(
            "(status = 'failed' AND sanitized_error = 'security delivery failed.') "
            "OR (status <> 'failed' AND sanitized_error IS NULL)",
            name="ck_security_notification_deliveries_sanitized_error",
        ),
        sa.PrimaryKeyConstraint("security_notification_delivery_id"),
        sa.UniqueConstraint(
            "idempotency_key_digest",
            name="uq_security_notification_deliveries_idempotency_digest",
        ),
    )


def downgrade() -> None:
    op.drop_table("security_notification_deliveries")

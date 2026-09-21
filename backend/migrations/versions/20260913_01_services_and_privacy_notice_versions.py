"""Create service catalog and privacy notice version tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260913_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("service_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "canonical_name",
            sa.String(length=100),
            sa.Computed("lower(btrim(name))", persisted=True),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=250), nullable=True),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("price", sa.Numeric(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("available_chiconcuac", sa.Boolean(), nullable=False),
        sa.Column("available_texcoco", sa.Boolean(), nullable=False),
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
            "char_length(name) >= 1", name="ck_services_name_nonempty"
        ),
        sa.CheckConstraint("name = btrim(name)", name="ck_services_name_trimmed"),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 5 AND 600 AND duration_minutes % 5 = 0",
            name="ck_services_duration_range_and_interval",
        ),
        sa.CheckConstraint(
            "price > 0 AND price <= 20000.00 AND price = round(price, 2)",
            name="ck_services_price_range",
        ),
        sa.CheckConstraint(
            "available_chiconcuac OR available_texcoco",
            name="ck_services_available_at_a_branch",
        ),
        sa.PrimaryKeyConstraint("service_id"),
        sa.UniqueConstraint("canonical_name", name="uq_services_canonical_name"),
    )

    op.create_table(
        "privacy_notice_versions",
        sa.Column(
            "privacy_notice_version_id",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(version)) > 0",
            name="ck_privacy_notice_versions_version_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_privacy_notice_versions_content_nonempty",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_privacy_notice_versions_validity_range",
        ),
        sa.PrimaryKeyConstraint("privacy_notice_version_id"),
        sa.UniqueConstraint("version", name="uq_privacy_notice_versions_version"),
    )

    op.execute(
        """
        CREATE FUNCTION prevent_privacy_notice_content_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.version IS DISTINCT FROM OLD.version
                OR NEW.content IS DISTINCT FROM OLD.content THEN
                RAISE EXCEPTION 'Privacy notice version and content are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_privacy_notice_versions_immutable_content
        BEFORE UPDATE ON privacy_notice_versions
        FOR EACH ROW
        EXECUTE FUNCTION prevent_privacy_notice_content_change()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_privacy_notice_versions_immutable_content "
        "ON privacy_notice_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_privacy_notice_content_change()")
    op.drop_table("privacy_notice_versions")
    op.drop_table("services")

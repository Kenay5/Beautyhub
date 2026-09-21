"""Protect privacy notice versions once appointment consent references them."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260914_10"
down_revision: Union[str, None] = "20260913_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_privacy_notice_content_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.version IS DISTINCT FROM OLD.version
                OR NEW.content IS DISTINCT FROM OLD.content THEN
                RAISE EXCEPTION 'Privacy notice version and content are immutable';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM appointments
                WHERE privacy_notice_version_id = OLD.privacy_notice_version_id
            ) AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'Accepted privacy notice versions are immutable';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_privacy_notice_content_change()
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

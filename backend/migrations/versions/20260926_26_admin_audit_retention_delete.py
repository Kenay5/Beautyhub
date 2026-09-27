"""Allow audit event deletion only inside the internal retention transaction."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260926_26"
down_revision: Union[str, None] = "20260926_25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_admin_audit_event_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF current_setting(
                'beautyhub.administrative_history_retention_delete', TRUE
            ) = 'authorized' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Administrative audit events cannot be deleted';
            RETURN OLD;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_admin_audit_event_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Administrative audit events cannot be deleted';
            RETURN OLD;
        END;
        $$
        """
    )

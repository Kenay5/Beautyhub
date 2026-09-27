"""Prevent ordinary deletion of administrative audit events."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260926_25"
down_revision: Union[str, None] = "20260926_24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_admin_audit_event_delete()
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
    op.execute(
        """
        CREATE TRIGGER trg_admin_audit_events_prevent_delete
        BEFORE DELETE ON admin_audit_events
        FOR EACH ROW
        EXECUTE FUNCTION prevent_admin_audit_event_delete()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_audit_events_prevent_delete "
        "ON admin_audit_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_admin_audit_event_delete()")

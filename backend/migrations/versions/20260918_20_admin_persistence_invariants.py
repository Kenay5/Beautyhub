"""Enforce administrative persistence transitions and audit immutability."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260918_20"
down_revision: Union[str, None] = "20260918_19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_admin_account_transitions()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.role <> NEW.role THEN
                RAISE EXCEPTION 'Administrative account role cannot change';
            END IF;
            IF OLD.role = 'staff'
               AND OLD.status = 'deactivated'
               AND NEW.status <> 'deactivated' THEN
                RAISE EXCEPTION 'Deactivated staff account cannot be reactivated';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_accounts_enforce_transitions
        BEFORE UPDATE ON admin_accounts
        FOR EACH ROW
        EXECUTE FUNCTION enforce_admin_account_transitions()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_security_link_transitions()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status <> NEW.status
               AND NOT (
                   OLD.status = 'active'
                   AND NEW.status IN ('consumed', 'invalidated', 'expired')
               ) THEN
                RAISE EXCEPTION 'Security link transition is invalid';
            END IF;

            IF OLD.delivery_status <> NEW.delivery_status
               AND NOT (
                   (OLD.delivery_status = 'pending'
                    AND NEW.delivery_status IN ('accepted', 'failed', 'uncertain'))
                   OR (OLD.delivery_status = 'uncertain'
                       AND NEW.delivery_status IN ('accepted', 'failed'))
                   OR (OLD.delivery_status = 'accepted'
                       AND NEW.delivery_status = 'failed')
               ) THEN
                RAISE EXCEPTION 'Security link delivery transition is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_security_links_enforce_transitions
        BEFORE UPDATE ON security_links
        FOR EACH ROW
        EXECUTE FUNCTION enforce_security_link_transitions()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_pending_security_setup_transitions()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status <> NEW.status
               AND NOT (
                   OLD.status = 'pending'
                   AND NEW.status IN ('confirmed', 'invalidated', 'expired')
               ) THEN
                RAISE EXCEPTION 'Pending security setup transition is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_pending_security_setups_enforce_transitions
        BEFORE UPDATE ON pending_security_setups
        FOR EACH ROW
        EXECUTE FUNCTION enforce_pending_security_setup_transitions()
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_security_notification_delivery_transitions()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status <> NEW.status
               AND NOT (
                   (OLD.status = 'pending'
                    AND NEW.status IN ('accepted', 'failed', 'uncertain'))
                   OR (OLD.status = 'uncertain'
                       AND NEW.status IN ('accepted', 'failed'))
                   OR (OLD.status = 'accepted' AND NEW.status = 'failed')
               ) THEN
                RAISE EXCEPTION 'Security delivery transition is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_security_notification_deliveries_enforce_transitions
        BEFORE UPDATE ON security_notification_deliveries
        FOR EACH ROW
        EXECUTE FUNCTION enforce_security_notification_delivery_transitions()
        """
    )

    op.execute(
        """
        CREATE FUNCTION prevent_admin_audit_event_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Administrative audit events cannot be updated';
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_admin_audit_events_prevent_update
        BEFORE UPDATE ON admin_audit_events
        FOR EACH ROW
        EXECUTE FUNCTION prevent_admin_audit_event_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_audit_events_prevent_update "
        "ON admin_audit_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_admin_audit_event_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_security_notification_deliveries_enforce_transitions "
        "ON security_notification_deliveries"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS enforce_security_notification_delivery_transitions()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_pending_security_setups_enforce_transitions "
        "ON pending_security_setups"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS enforce_pending_security_setup_transitions()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_security_links_enforce_transitions "
        "ON security_links"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_security_link_transitions()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_admin_accounts_enforce_transitions "
        "ON admin_accounts"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_admin_account_transitions()")

"""Bound audit-event deletion to the internal retention function and deadline."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260926_27"
down_revision: Union[str, None] = "20260926_26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION purge_expired_administrative_history_event_batch(
            p_current_time timestamptz,
            p_batch_limit integer
        )
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            deleted_count integer;
        BEGIN
            PERFORM set_config(
                'beautyhub.administrative_history_retention_delete',
                'authorized',
                TRUE
            );
            WITH expired_batch AS MATERIALIZED (
                SELECT admin_audit_event_id
                FROM public.admin_audit_events
                WHERE (
                    (occurred_at AT TIME ZONE 'America/Mexico_City'
                        + INTERVAL '1 year')
                    AT TIME ZONE 'America/Mexico_City'
                ) <= p_current_time
                ORDER BY
                    (occurred_at AT TIME ZONE 'America/Mexico_City'
                        + INTERVAL '1 year'),
                    admin_audit_event_id
                LIMIT LEAST(GREATEST(p_batch_limit, 1), 500)
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM public.admin_audit_events AS event
            USING expired_batch
            WHERE event.admin_audit_event_id = expired_batch.admin_audit_event_id;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            PERFORM set_config(
                'beautyhub.administrative_history_retention_delete',
                'inactive',
                TRUE
            );
            RETURN deleted_count;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_admin_audit_event_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF current_setting(
                'beautyhub.administrative_history_retention_delete', TRUE
            ) = 'authorized'
            AND position(
                'purge_expired_administrative_history_event_batch'
                IN current_query()
            ) > 0 THEN
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
    op.execute(
        "DROP FUNCTION IF EXISTS purge_expired_administrative_history_event_batch"
        "(timestamptz, integer)"
    )

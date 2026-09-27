"""Prevent a caller-supplied future cutoff from expiring audit history early."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260926_28"
down_revision: Union[str, None] = "20260926_27"
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
            effective_current_time timestamptz;
        BEGIN
            IF p_current_time IS NULL THEN
                RAISE EXCEPTION 'Administrative-history retention cutoff is required';
            END IF;
            effective_current_time := LEAST(p_current_time, clock_timestamp());
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
                ) <= effective_current_time
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


def downgrade() -> None:
    # Restore the batch routine from the preceding revision. That routine is
    # still bounded and trigger-protected; callers must continue using it.
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

"""Isolate audit history from ordinary SQL and authorize bounded retention by role."""

from typing import Sequence, Union

from alembic import op


revision: str = "20260926_29"
down_revision: Union[str, None] = "20260926_28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The owner cannot log in or be assumed by the application role. A role
    # capable of running migrations must have CREATEROLE and own the schema.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = 'beautyhub_audit_retention_owner'
            ) THEN
                CREATE ROLE beautyhub_audit_retention_owner NOLOGIN NOINHERIT;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = 'beautyhub_audit_retention_owner'
                  AND (rolcanlogin OR rolsuper OR rolcreaterole OR rolcreatedb
                       OR rolreplication OR rolbypassrls)
            ) THEN
                RAISE EXCEPTION 'Audit retention owner must be an unprivileged NOLOGIN role';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_admin_audit_event_delete()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF current_user = 'beautyhub_audit_retention_owner' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Administrative audit events cannot be deleted';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION purge_expired_administrative_history_event_batch(
            p_current_time timestamptz, p_batch_limit integer
        ) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
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
            RETURN deleted_count;
        END;
        $$
        """
    )
    op.execute("REVOKE UPDATE, DELETE ON public.admin_audit_events FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE application_role text := current_user;
        BEGIN
            EXECUTE format(
                'REVOKE UPDATE, DELETE ON public.admin_audit_events FROM %I',
                application_role
            );
            EXECUTE format(
                'ALTER TABLE public.admin_audit_events OWNER TO %I',
                'beautyhub_audit_retention_owner'
            );
            EXECUTE format(
                'GRANT SELECT, UPDATE, DELETE ON public.admin_audit_events TO %I',
                'beautyhub_audit_retention_owner'
            );
            EXECUTE format(
                'ALTER FUNCTION public.purge_expired_administrative_history_event_batch(timestamptz, integer) OWNER TO %I',
                'beautyhub_audit_retention_owner'
            );
            EXECUTE format(
                'ALTER FUNCTION public.prevent_admin_audit_event_delete() OWNER TO %I',
                'beautyhub_audit_retention_owner'
            );
            EXECUTE format(
                'ALTER FUNCTION public.prevent_admin_audit_event_update() OWNER TO %I',
                'beautyhub_audit_retention_owner'
            );
            EXECUTE format(
                'GRANT SELECT, INSERT ON public.admin_audit_events TO %I',
                application_role
            );
            EXECUTE format(
                'GRANT USAGE ON SEQUENCE public.admin_audit_events_admin_audit_event_id_seq TO %I',
                application_role
            );
            EXECUTE format(
                'REVOKE ALL ON FUNCTION public.purge_expired_administrative_history_event_batch(timestamptz, integer) FROM PUBLIC'
            );
            EXECUTE format(
                'GRANT EXECUTE ON FUNCTION public.purge_expired_administrative_history_event_batch(timestamptz, integer) TO %I',
                application_role
            );
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.oid = membership.roleid
                WHERE owner_role.rolname = 'beautyhub_audit_retention_owner'
                  AND membership.member = (
                      SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user
                  )
            ) THEN
                EXECUTE format(
                    'REVOKE beautyhub_audit_retention_owner FROM %I', current_user
                );
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS owner_role
                  ON owner_role.oid = membership.roleid
                WHERE owner_role.rolname = 'beautyhub_audit_retention_owner'
            ) THEN
                RAISE EXCEPTION 'Audit retention owner must have no members';
            END IF;
        END;
        $$
        """
    )


def downgrade() -> None:
    # A rollback must fail closed. Revision 28's spoofable trigger is not
    # restored; retention remains unavailable until this revision is applied.
    op.execute("ALTER TABLE public.admin_audit_events OWNER TO CURRENT_USER")
    op.execute("ALTER FUNCTION public.prevent_admin_audit_event_delete() OWNER TO CURRENT_USER")
    op.execute("ALTER FUNCTION public.prevent_admin_audit_event_update() OWNER TO CURRENT_USER")
    op.execute(
        "ALTER FUNCTION public.purge_expired_administrative_history_event_batch"
        "(timestamptz, integer) OWNER TO CURRENT_USER"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_admin_audit_event_delete()
        RETURNS trigger LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Administrative audit events cannot be deleted';
        END;
        $$
        """
    )

"""PostgreSQL replacement of one administrative account session."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, delete, exists, insert, or_, select, update

from backend.app.application.admin_access.login_session import (
    AdministrativeLoginSessionStore,
    StoredAdministrativeLoginSession,
)
from backend.app.application.admin_access.logout import (
    AdministrativeSessionLogoutStore,
)
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeCsrfSessionStore,
)
from backend.app.application.admin_access.session_context import (
    AdministrativeSessionContextStore,
    StoredAdministrativeSessionContext,
)
from backend.app.domain.sessions.admin_session import (
    SESSION_ABSOLUTE_LIMIT,
    SESSION_INACTIVITY_LIMIT,
    AdminSession as AdministrativeSession,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminAccountSecurityState,
    AdminCredentialFailureEvent,
    AdminSession,
)


class AdministrativeLoginSessionStateError(RuntimeError):
    """Raised so the caller transaction rolls back an incomplete login."""


class PostgresAdministrativeLoginSessionStore(AdministrativeLoginSessionStore):
    """Serialize login success per account and leave exactly one active session."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def replace_active_session(
        self,
        *,
        account_id: int,
        session_digest: bytes,
        csrf_digest: bytes,
        key_version: str,
        current_time: datetime,
    ) -> StoredAdministrativeLoginSession:
        account = self._connection.execute(
            select(AdminAccount.admin_account_id, AdminAccount.role)
            .where(
                AdminAccount.admin_account_id == account_id,
                AdminAccount.status == "active",
            )
            .with_for_update()
        ).one_or_none()
        if account is None:
            raise AdministrativeLoginSessionStateError(
                "administrative login account is unavailable."
            )

        self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.admin_account_id == account_id,
                AdminSession.status == "active",
            )
            .values(status="invalidated", invalidated_at=current_time)
        )
        self._connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == account_id)
            .values(
                lock_until=None,
                fifth_failure_event_id=None,
                post_recovery_second_factor_restricted=False,
            )
        )
        self._connection.execute(
            delete(AdminCredentialFailureEvent).where(
                AdminCredentialFailureEvent.admin_account_id == account_id
            )
        )
        session_id = self._connection.execute(
            insert(AdminSession)
            .values(
                admin_account_id=account_id,
                session_digest=session_digest,
                csrf_digest=csrf_digest,
                key_version=key_version,
                created_at=current_time,
                last_human_activity_at=current_time,
                absolute_expires_at=current_time + SESSION_ABSOLUTE_LIMIT,
                status="active",
                invalidated_at=None,
            )
            .returning(AdminSession.admin_session_id)
        ).scalar_one()
        return StoredAdministrativeLoginSession(
            session_id=session_id,
            role=account.role,
        )


class PostgresAdministrativeCsrfSessionStore(
    AdministrativeCsrfSessionStore,
    AdministrativeSessionLogoutStore,
    AdministrativeSessionContextStore,
):
    """Load and conditionally renew one active administrative session."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def load_active_session(
        self, *, session_digest: bytes
    ) -> AdministrativeSession | None:
        row = self._connection.execute(
            select(
                AdminSession.admin_account_id,
                AdminSession.session_digest,
                AdminSession.csrf_digest,
                AdminSession.key_version,
                AdminSession.created_at,
                AdminSession.last_human_activity_at,
                AdminSession.absolute_expires_at,
                AdminSession.status,
                AdminSession.invalidated_at,
            )
            .join(
                AdminAccount,
                AdminAccount.admin_account_id == AdminSession.admin_account_id,
            )
            .where(
                AdminSession.session_digest == session_digest,
                AdminSession.status == "active",
                AdminAccount.status == "active",
            )
        ).one_or_none()
        if row is None:
            return None
        return AdministrativeSession(
            account_id=row.admin_account_id,
            session_digest=row.session_digest,
            csrf_digest=row.csrf_digest,
            key_version=row.key_version,
            created_at=row.created_at,
            last_human_activity_at=row.last_human_activity_at,
            absolute_expires_at=row.absolute_expires_at,
            status=row.status,
            invalidated_at=row.invalidated_at,
        )

    def load_active_context(
        self, *, session_digest: bytes
    ) -> StoredAdministrativeSessionContext | None:
        row = self._connection.execute(
            select(
                AdminAccount.role,
                AdminSession.admin_account_id,
                AdminSession.session_digest,
                AdminSession.csrf_digest,
                AdminSession.key_version,
                AdminSession.created_at,
                AdminSession.last_human_activity_at,
                AdminSession.absolute_expires_at,
                AdminSession.status,
                AdminSession.invalidated_at,
            )
            .join(
                AdminAccount,
                AdminAccount.admin_account_id == AdminSession.admin_account_id,
            )
            .where(
                AdminSession.session_digest == session_digest,
                AdminSession.status == "active",
                AdminAccount.status == "active",
            )
        ).one_or_none()
        if row is None:
            return None
        return StoredAdministrativeSessionContext(
            session=AdministrativeSession(
                account_id=row.admin_account_id,
                session_digest=row.session_digest,
                csrf_digest=row.csrf_digest,
                key_version=row.key_version,
                created_at=row.created_at,
                last_human_activity_at=row.last_human_activity_at,
                absolute_expires_at=row.absolute_expires_at,
                status=row.status,
                invalidated_at=row.invalidated_at,
            ),
            role=row.role,
        )

    def replace_csrf_digest(
        self,
        *,
        session_digest: bytes,
        csrf_digest: bytes,
        current_time: datetime,
    ) -> bool:
        active_account = exists(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == AdminSession.admin_account_id,
                AdminAccount.status == "active",
            )
        )
        result = self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.session_digest == session_digest,
                AdminSession.status == "active",
                AdminSession.last_human_activity_at
                > current_time - SESSION_INACTIVITY_LIMIT,
                AdminSession.absolute_expires_at > current_time,
                active_account,
            )
            .values(csrf_digest=csrf_digest)
        )
        return result.rowcount == 1

    def touch_human_activity(
        self, *, session_digest: bytes, current_time: datetime
    ) -> bool:
        active_account = exists(
            select(AdminAccount.admin_account_id).where(
                AdminAccount.admin_account_id == AdminSession.admin_account_id,
                AdminAccount.status == "active",
            )
        )
        result = self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.session_digest == session_digest,
                AdminSession.status == "active",
                AdminSession.last_human_activity_at
                > current_time - SESSION_INACTIVITY_LIMIT,
                AdminSession.absolute_expires_at > current_time,
                active_account,
            )
            .values(last_human_activity_at=current_time)
        )
        return result.rowcount == 1

    def invalidate_if_expired(
        self, *, session_digest: bytes, current_time: datetime
    ) -> None:
        self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.session_digest == session_digest,
                AdminSession.status == "active",
                or_(
                    AdminSession.last_human_activity_at
                    <= current_time - SESSION_INACTIVITY_LIMIT,
                    AdminSession.absolute_expires_at <= current_time,
                ),
            )
            .values(status="invalidated", invalidated_at=current_time)
        )

    def invalidate_active_session(
        self, *, session_digest: bytes, current_time: datetime
    ) -> int | None:
        return self._connection.execute(
            update(AdminSession)
            .where(
                AdminSession.session_digest == session_digest,
                AdminSession.status == "active",
            )
            .values(status="invalidated", invalidated_at=current_time)
            .returning(AdminSession.admin_account_id)
        ).scalar_one_or_none()

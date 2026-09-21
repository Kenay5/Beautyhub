"""PostgreSQL row-locked persistence for administrative account security."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, func, insert, select, update

from backend.app.application.admin_access.account_security import (
    AdministrativeAccountSecurityStore,
)
from backend.app.domain.authentication.account_security import (
    ADMINISTRATIVE_CREDENTIAL_FAILURE_LIMIT,
    ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW,
    AdministrativeCredentialFailureResult,
    AdministrativeCredentialOperation,
    is_administrative_account_locked,
)
from backend.app.infrastructure.persistence.models import (
    AdminAccountSecurityState,
    AdminCredentialFailureEvent,
)


class PostgresAdministrativeAccountSecurityStore(AdministrativeAccountSecurityStore):
    """Serialize one account's credential failures through its security row."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_rejected_credential_request(
        self,
        *,
        account_id: int,
        operation: AdministrativeCredentialOperation,
        current_time: datetime,
    ) -> AdministrativeCredentialFailureResult:
        """Append one safe event or preserve an already-active account lock."""

        state = self._lock_state(account_id)
        current_lock_until = state.lock_until
        if is_administrative_account_locked(
            lock_until=current_lock_until,
            now=current_time,
        ):
            return AdministrativeCredentialFailureResult(
                failure_count=self._active_failure_count(
                    account_id=account_id,
                    current_time=current_time,
                ),
                lock_until=current_lock_until,
                blocked=True,
            )

        if current_lock_until is not None:
            self._connection.execute(
                update(AdminAccountSecurityState)
                .where(AdminAccountSecurityState.admin_account_id == account_id)
                .values(lock_until=None, fifth_failure_event_id=None)
            )

        active_failures = self._active_failure_count(
            account_id=account_id,
            current_time=current_time,
        )
        failure_count = active_failures + 1
        event_id = self._connection.execute(
            insert(AdminCredentialFailureEvent)
            .values(
                admin_account_id=account_id,
                operation=operation,
                occurred_at=current_time,
            )
            .returning(AdminCredentialFailureEvent.admin_credential_failure_event_id)
        ).scalar_one()

        lock_until: datetime | None = None
        if failure_count == ADMINISTRATIVE_CREDENTIAL_FAILURE_LIMIT:
            lock_until = current_time + ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW
            self._connection.execute(
                update(AdminAccountSecurityState)
                .where(AdminAccountSecurityState.admin_account_id == account_id)
                .values(
                    lock_until=lock_until,
                    fifth_failure_event_id=event_id,
                )
            )

        return AdministrativeCredentialFailureResult(
            failure_count=failure_count,
            lock_until=lock_until,
            blocked=False,
            failure_event_id=event_id,
        )

    def set_post_recovery_second_factor_restriction(
        self, *, account_id: int
    ) -> None:
        """Set only the later-factor-replacement restriction under the same lock."""

        self._lock_state(account_id)
        self._connection.execute(
            update(AdminAccountSecurityState)
            .where(AdminAccountSecurityState.admin_account_id == account_id)
            .values(post_recovery_second_factor_restricted=True)
        )

    def ensure_credential_check_allowed(
        self, *, account_id: int, current_time: datetime
    ) -> bool:
        """Clear an expired lock or reject without mutating its active state."""

        state = self._lock_state(account_id)
        if is_administrative_account_locked(
            lock_until=state.lock_until,
            now=current_time,
        ):
            return False
        if state.lock_until is not None:
            self._connection.execute(
                update(AdminAccountSecurityState)
                .where(AdminAccountSecurityState.admin_account_id == account_id)
                .values(lock_until=None, fifth_failure_event_id=None)
            )
        return True

    def _lock_state(self, account_id: int):
        state = self._connection.execute(
            select(
                AdminAccountSecurityState.admin_account_id,
                AdminAccountSecurityState.lock_until,
            )
            .where(AdminAccountSecurityState.admin_account_id == account_id)
            .with_for_update()
        ).mappings().one_or_none()
        if state is None:
            raise ValueError("administrative account security state is unavailable.")
        return state

    def _active_failure_count(self, *, account_id: int, current_time: datetime) -> int:
        window_start = current_time - ADMINISTRATIVE_CREDENTIAL_FAILURE_WINDOW
        return self._connection.execute(
            select(func.count())
            .select_from(AdminCredentialFailureEvent)
            .where(
                AdminCredentialFailureEvent.admin_account_id == account_id,
                AdminCredentialFailureEvent.occurred_at > window_start,
            )
        ).scalar_one()

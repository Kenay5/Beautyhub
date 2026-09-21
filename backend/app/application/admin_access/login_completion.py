"""Complete validated administrative credentials without creating a session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginValidationOutcome,
    INVALID_LOGIN_REJECTION,
    ValidatedAdministrativeLogin,
)
from backend.app.application.clock import Clock
from backend.app.domain.time import normalize_instant


@dataclass(frozen=True)
class AdministrativeLoginCredentialOutcome:
    """Internal result that T047 may use inside the same transaction."""

    account_id: int | None = None
    role: Literal["owner", "staff"] | None = None
    rejection: str | None = None

    @property
    def accepted(self) -> bool:
        return (
            self.account_id is not None
            and self.role is not None
            and self.rejection is None
        )


class AdministrativeLoginFactorStore(Protocol):
    def consume_validated_factor(
        self,
        *,
        validated: ValidatedAdministrativeLogin,
        current_time: datetime,
    ) -> bool: ...


class AdministrativeLoginFailureRecorder(Protocol):
    def record(self, *, account_id: int, operation: Literal["login"]): ...


class CompleteAdministrativeLoginCredentials:
    """Consume one factor only after every credential has been validated.

    The persistence connection and transaction belong to the caller. This use case
    deliberately does not commit so session creation can join the same transaction.
    """

    def __init__(
        self,
        *,
        factor_store: AdministrativeLoginFactorStore,
        failure_recorder: AdministrativeLoginFailureRecorder,
        clock: Clock,
    ) -> None:
        self._factor_store = factor_store
        self._failure_recorder = failure_recorder
        self._clock = clock

    def complete(
        self,
        *,
        validation: AdministrativeLoginValidationOutcome,
    ) -> AdministrativeLoginCredentialOutcome:
        if not validation.accepted or validation.validated is None:
            if validation.records_failure:
                self._record_one_failure(validation.rejected_account_id)
            return AdministrativeLoginCredentialOutcome(
                rejection=INVALID_LOGIN_REJECTION
            )

        validated = validation.validated
        consumed = self._factor_store.consume_validated_factor(
            validated=validated,
            current_time=normalize_instant(self._clock.now()),
        )
        if not consumed:
            self._record_one_failure(validated.account_id)
            return AdministrativeLoginCredentialOutcome(
                rejection=INVALID_LOGIN_REJECTION
            )

        return AdministrativeLoginCredentialOutcome(
            account_id=validated.account_id,
            role=validated.role,
        )

    def _record_one_failure(self, account_id: int | None) -> None:
        if account_id is not None:
            self._failure_recorder.record(
                account_id=account_id,
                operation="login",
            )

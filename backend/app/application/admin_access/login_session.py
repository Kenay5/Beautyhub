"""Create one administrative session after complete credential validation."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from backend.app.application.admin_access.login_completion import (
    CompleteAdministrativeLoginCredentials,
)
from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginValidationOutcome,
    INVALID_LOGIN_REJECTION,
)
from backend.app.application.clock import Clock
from backend.app.application.entropy import SecretGenerator
from backend.app.domain.time import normalize_instant


ADMINISTRATIVE_SESSION_VALUE_BYTES = 32


class AdministrativeLoginSessionValueError(RuntimeError):
    """Reject an unusable pair so the surrounding login transaction rolls back."""


@dataclass(frozen=True)
class StoredAdministrativeLoginSession:
    session_id: int
    role: Literal["owner", "staff"]


@dataclass(frozen=True)
class AdministrativeLoginSessionOutcome:
    """Internal login result whose raw values are emitted only by T048."""

    account_id: int | None = None
    role: Literal["owner", "staff"] | None = None
    session_id: int | None = None
    session_token: bytes | None = field(default=None, repr=False)
    csrf_token: bytes | None = field(default=None, repr=False)
    rejection: str | None = None

    @property
    def accepted(self) -> bool:
        return (
            self.account_id is not None
            and self.role is not None
            and self.session_id is not None
            and self.session_token is not None
            and self.csrf_token is not None
            and self.rejection is None
        )


class AdministrativeLoginSessionStore(Protocol):
    def replace_active_session(
        self,
        *,
        account_id: int,
        session_digest: bytes,
        csrf_digest: bytes,
        key_version: str,
        current_time: datetime,
    ) -> StoredAdministrativeLoginSession: ...


class AdministrativeSessionValueProtector(Protocol):
    key_version: str

    def digest_session_token(self, token: bytes) -> bytes: ...

    def digest_csrf_token(self, token: bytes) -> bytes: ...


class AdministrativeLoginAuditRecorder(Protocol):
    def record(
        self,
        *,
        actor_account_id: int | None,
        action: Literal["login"],
        result: Literal["succeeded", "failed"],
        target_reference: str | None = None,
    ) -> None: ...


class CreateAdministrativeLoginSession:
    """Complete credentials and replace the account session in one caller transaction."""

    def __init__(
        self,
        *,
        credentials: CompleteAdministrativeLoginCredentials,
        store: AdministrativeLoginSessionStore,
        protector: AdministrativeSessionValueProtector,
        secret_generator: SecretGenerator,
        audit: AdministrativeLoginAuditRecorder,
        clock: Clock,
    ) -> None:
        self._credentials = credentials
        self._store = store
        self._protector = protector
        self._secret_generator = secret_generator
        self._audit = audit
        self._clock = clock

    def create(
        self,
        *,
        validation: AdministrativeLoginValidationOutcome,
    ) -> AdministrativeLoginSessionOutcome:
        credentials = self._credentials.complete(validation=validation)
        if not credentials.accepted or credentials.account_id is None:
            failed_account_id = validation.rejected_account_id
            if failed_account_id is None and validation.validated is not None:
                failed_account_id = validation.validated.account_id
            self._audit.record(
                actor_account_id=failed_account_id,
                action="login",
                result="failed",
            )
            return AdministrativeLoginSessionOutcome(
                rejection=credentials.rejection or INVALID_LOGIN_REJECTION
            )

        session_token = self._secret_generator.token_bytes(
            ADMINISTRATIVE_SESSION_VALUE_BYTES
        )
        csrf_token = self._secret_generator.token_bytes(
            ADMINISTRATIVE_SESSION_VALUE_BYTES
        )
        if hmac.compare_digest(session_token, csrf_token):
            raise AdministrativeLoginSessionValueError(
                "administrative session and CSRF values must be distinct."
            )
        stored = self._store.replace_active_session(
            account_id=credentials.account_id,
            session_digest=self._protector.digest_session_token(session_token),
            csrf_digest=self._protector.digest_csrf_token(csrf_token),
            key_version=self._protector.key_version,
            current_time=normalize_instant(self._clock.now()),
        )
        self._audit.record(
            actor_account_id=credentials.account_id,
            action="login",
            result="succeeded",
        )
        return AdministrativeLoginSessionOutcome(
            account_id=credentials.account_id,
            role=stored.role,
            session_id=stored.session_id,
            session_token=session_token,
            csrf_token=csrf_token,
        )

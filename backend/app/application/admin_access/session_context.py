"""Server-derived context for an administrative browser session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeRole,
)
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
)
from backend.app.application.clock import Clock
from backend.app.application.entropy import SecretGenerator
from backend.app.domain.sessions.admin_session import (
    AdminSession,
    is_admin_session_valid,
)
from backend.app.domain.time import normalize_instant


@dataclass(frozen=True)
class StoredAdministrativeSessionContext:
    """Active-account data loaded with its opaque session."""

    session: AdminSession
    role: AdministrativeRole


@dataclass(frozen=True)
class AdministrativeSessionContext:
    """Minimum authenticated context returned to the same-origin browser."""

    actor: AdministrativeActor
    csrf_token: bytes


class AdministrativeSessionContextStore(Protocol):
    def load_active_context(
        self, *, session_digest: bytes
    ) -> StoredAdministrativeSessionContext | None: ...

    def replace_csrf_digest(
        self,
        *,
        session_digest: bytes,
        csrf_digest: bytes,
        current_time: datetime,
    ) -> bool: ...

    def invalidate_if_expired(
        self, *, session_digest: bytes, current_time: datetime
    ) -> None: ...


class AdministrativeSessionContextProtector(Protocol):
    def digest_session_token(self, token: bytes) -> bytes: ...

    def digest_csrf_token(self, token: bytes) -> bytes: ...


class LoadAdministrativeSessionContext:
    """Revalidate the opaque session and current account state on every call."""

    def __init__(
        self,
        *,
        store: AdministrativeSessionContextStore,
        protector: AdministrativeSessionContextProtector,
        secret_generator: SecretGenerator,
        clock: Clock,
    ) -> None:
        self._store = store
        self._protector = protector
        self._secret_generator = secret_generator
        self._clock = clock

    def authenticate(self, *, session_token: bytes | None) -> AdministrativeActor:
        """Return only identity derived from a currently valid server session."""

        actor, _, _ = self._load(session_token=session_token)
        return actor

    def refresh(self, *, session_token: bytes | None) -> AdministrativeSessionContext:
        """Rotate CSRF for a valid context without extending human activity."""

        actor, session_digest, current_time = self._load(session_token=session_token)
        csrf_token = self._secret_generator.token_bytes(32)
        if not self._store.replace_csrf_digest(
            session_digest=session_digest,
            csrf_digest=self._protector.digest_csrf_token(csrf_token),
            current_time=current_time,
        ):
            raise _authentication_error()
        return AdministrativeSessionContext(actor=actor, csrf_token=csrf_token)

    def _load(
        self, *, session_token: bytes | None
    ) -> tuple[AdministrativeActor, bytes, datetime]:
        if not isinstance(session_token, bytes) or len(session_token) != 32:
            raise _authentication_error()
        session_digest = self._protector.digest_session_token(session_token)
        stored = self._store.load_active_context(session_digest=session_digest)
        current_time = normalize_instant(self._clock.now())
        if stored is None:
            raise _authentication_error()
        if not is_admin_session_valid(session=stored.session, now=current_time):
            self._store.invalidate_if_expired(
                session_digest=session_digest,
                current_time=current_time,
            )
            raise _authentication_error()
        return (
            AdministrativeActor(
                account_id=stored.session.account_id,
                role=stored.role,
            ),
            session_digest,
            current_time,
        )


def _authentication_error() -> AdministrativeSessionAuthenticationError:
    return AdministrativeSessionAuthenticationError(
        "administrative session is unavailable."
    )

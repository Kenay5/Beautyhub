"""Same-origin and synchronizer-token protection for administrative mutations."""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Protocol
from urllib.parse import SplitResult, urlsplit

from backend.app.application.clock import Clock
from backend.app.domain.sessions.admin_session import AdminSession, is_admin_session_valid
from backend.app.domain.time import normalize_instant


class AdministrativeSessionAuthenticationError(PermissionError):
    """Raised when no active opaque session can be identified."""


class AdministrativeMutationProtectionError(PermissionError):
    """Raised when same-origin or CSRF proof is absent or invalid."""


class AdministrativeCsrfSessionStore(Protocol):
    def load_active_session(self, *, session_digest: bytes) -> AdminSession | None: ...

    def touch_human_activity(
        self, *, session_digest: bytes, current_time: datetime
    ) -> bool: ...

    def invalidate_if_expired(
        self, *, session_digest: bytes, current_time: datetime
    ) -> None: ...


class AdministrativeSessionDigestProtector(Protocol):
    def digest_session_token(self, token: bytes) -> bytes: ...

    def digest_csrf_token(self, token: bytes) -> bytes: ...


class ValidateAdministrativeMutationProtection:
    """Require an active session, approved browser origin and its CSRF token."""

    def __init__(
        self,
        *,
        store: AdministrativeCsrfSessionStore,
        protector: AdministrativeSessionDigestProtector,
        clock: Clock,
    ) -> None:
        self._store = store
        self._protector = protector
        self._clock = clock

    def validate(
        self,
        *,
        session_token: bytes | None,
        csrf_token: bytes | None,
        approved_origin: str,
        origin: str | None,
        referer: str | None,
        human_initiated: bool,
    ) -> None:
        if session_token is None:
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )
        session_digest = self._protector.digest_session_token(session_token)
        session = self._store.load_active_session(
            session_digest=session_digest
        )
        current_time = normalize_instant(self._clock.now())
        if session is None:
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )
        if not is_admin_session_valid(session=session, now=current_time):
            self._store.invalidate_if_expired(
                session_digest=session_digest,
                current_time=current_time,
            )
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )

        source = origin if origin is not None else referer
        allow_path = origin is None
        if not _same_origin(
            approved_origin=approved_origin,
            source=source,
            allow_source_path=allow_path,
        ):
            raise AdministrativeMutationProtectionError(
                "administrative request origin is invalid."
            )
        if csrf_token is None:
            raise AdministrativeMutationProtectionError(
                "administrative CSRF token is invalid."
            )
        supplied_digest = self._protector.digest_csrf_token(csrf_token)
        if not hmac.compare_digest(session.csrf_digest, supplied_digest):
            raise AdministrativeMutationProtectionError(
                "administrative CSRF token is invalid."
            )
        if human_initiated and not self._store.touch_human_activity(
            session_digest=session_digest,
            current_time=current_time,
        ):
            self._store.invalidate_if_expired(
                session_digest=session_digest,
                current_time=current_time,
            )
            raise AdministrativeSessionAuthenticationError(
                "administrative session is unavailable."
            )


def _same_origin(
    *,
    approved_origin: str,
    source: str | None,
    allow_source_path: bool,
) -> bool:
    if source is None:
        return False
    approved = _canonical_origin(approved_origin, allow_path=False)
    candidate = _canonical_origin(source, allow_path=allow_source_path)
    return approved is not None and hmac.compare_digest(approved, candidate or "")


def _canonical_origin(value: str, *, allow_path: bool) -> str | None:
    if not isinstance(value, str) or not value or "," in value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if not _valid_origin_parts(parsed, allow_path=allow_path):
        return None
    scheme = parsed.scheme.lower()
    effective_port = port if port is not None else {"http": 80, "https": 443}[scheme]
    return f"{scheme}://{parsed.hostname.lower()}:{effective_port}"


def _valid_origin_parts(parsed: SplitResult, *, allow_path: bool) -> bool:
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if allow_path:
        return True
    return parsed.path in {"", "/"}

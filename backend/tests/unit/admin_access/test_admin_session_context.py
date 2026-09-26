"""T053 unit evidence for server-derived administrative session context."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
)
from backend.app.application.admin_access.session_context import (
    LoadAdministrativeSessionContext,
    StoredAdministrativeSessionContext,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.sessions.admin_session import AdminSession
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
)


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
SESSION_TOKEN = b"\x91" * 32
CSRF_TOKEN = b"\x92" * 32
NEW_CSRF_TOKEN = b"\x93" * 32


def _protector() -> AdminSessionProtector:
    return AdminSessionProtector(
        key_ring=CryptographyKeyRing(
            CryptographyKeyConfiguration(
                root_key=SecretValue(
                    base64.urlsafe_b64encode(b"\x90" * 32).decode("ascii")
                ),
                key_version="v1",
            )
        )
    )


class ContextStore:
    def __init__(self, *, available: bool = True, rotation_succeeds: bool = True):
        protector = _protector()
        self.available = available
        self.rotation_succeeds = rotation_succeeds
        self.invalidations = []
        self.rotations = []
        self.context = StoredAdministrativeSessionContext(
            session=AdminSession(
                account_id=7,
                session_digest=protector.digest_session_token(SESSION_TOKEN),
                csrf_digest=protector.digest_csrf_token(CSRF_TOKEN),
                key_version="v1",
                created_at=NOW,
                last_human_activity_at=NOW,
                absolute_expires_at=NOW + timedelta(hours=8),
                status="active",
                invalidated_at=None,
            ),
            role="owner",
        )

    def load_active_context(self, *, session_digest):
        if not self.available or session_digest != self.context.session.session_digest:
            return None
        return self.context

    def replace_csrf_digest(self, *, session_digest, csrf_digest, current_time):
        self.rotations.append((session_digest, csrf_digest, current_time))
        return self.rotation_succeeds

    def invalidate_if_expired(self, *, session_digest, current_time):
        self.invalidations.append((session_digest, current_time))


def _loader(store: ContextStore, *, now: datetime = NOW):
    return LoadAdministrativeSessionContext(
        store=store,
        protector=_protector(),
        secret_generator=SequenceSecretGenerator((NEW_CSRF_TOKEN,)),
        clock=FixedClock(now),
    )


def test_t053_authentication_derives_actor_without_rotating_session() -> None:
    store = ContextStore()

    actor = _loader(store).authenticate(session_token=SESSION_TOKEN)

    assert (actor.account_id, actor.role) == (7, "owner")
    assert store.rotations == []


def test_t053_context_refresh_rotates_only_the_csrf_digest() -> None:
    store = ContextStore()

    context = _loader(store).refresh(session_token=SESSION_TOKEN)

    assert context.actor.account_id == 7
    assert context.csrf_token == NEW_CSRF_TOKEN
    assert store.rotations == [
        (
            _protector().digest_session_token(SESSION_TOKEN),
            _protector().digest_csrf_token(NEW_CSRF_TOKEN),
            NOW,
        )
    ]


@pytest.mark.parametrize("session_token", [None, b"short", b"\x94" * 32])
def test_t053_missing_or_unknown_session_has_one_generic_outcome(session_token) -> None:
    store = ContextStore(available=session_token != b"\x94" * 32)

    with pytest.raises(
        AdministrativeSessionAuthenticationError,
        match="administrative session is unavailable",
    ):
        _loader(store).authenticate(session_token=session_token)


def test_t053_exact_expiry_is_invalidated_and_returns_no_context() -> None:
    store = ContextStore()
    expiry = NOW + timedelta(minutes=30)

    with pytest.raises(AdministrativeSessionAuthenticationError):
        _loader(store, now=expiry).authenticate(session_token=SESSION_TOKEN)

    assert store.invalidations == [
        (_protector().digest_session_token(SESSION_TOKEN), expiry)
    ]


def test_t053_failed_conditional_rotation_returns_no_context() -> None:
    store = ContextStore(rotation_succeeds=False)

    with pytest.raises(AdministrativeSessionAuthenticationError):
        _loader(store).refresh(session_token=SESSION_TOKEN)

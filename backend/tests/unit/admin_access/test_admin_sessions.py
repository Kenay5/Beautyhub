"""T013 unit evidence for opaque administrative session persistence rules."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Literal

import pytest

from backend.app.application.clock import FixedClock
from backend.app.domain.sessions.admin_session import (
    AdminSession,
    AdminSessionInvariantError,
    SESSION_ABSOLUTE_LIMIT,
    is_admin_session_valid,
)
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


def _key_ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(
                base64.urlsafe_b64encode(b"\x41" * 32).decode("ascii")
            ),
            key_version="v1",
        )
    )


def _session(
    *,
    last_human_activity_at: datetime,
    status: Literal["active", "invalidated"] = "active",
    invalidated_at: datetime | None = None,
) -> AdminSession:
    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    return AdminSession(
        account_id=1,
        session_digest=b"\x42" * 32,
        csrf_digest=b"\x43" * 32,
        key_version="v1",
        created_at=created_at,
        last_human_activity_at=last_human_activity_at,
        absolute_expires_at=created_at + SESSION_ABSOLUTE_LIMIT,
        status=status,
        invalidated_at=invalidated_at,
    )


def test_t013_uses_separate_opaque_digests_for_session_and_csrf_values() -> None:
    protector = AdminSessionProtector(key_ring=_key_ring())
    session_token = b"\x44" * 32
    csrf_token = b"\x45" * 32

    session_digest = protector.digest_session_token(session_token)
    csrf_digest = protector.digest_csrf_token(csrf_token)

    assert len(session_digest) == len(csrf_digest) == 32
    assert session_token not in session_digest
    assert csrf_token not in csrf_digest
    assert session_digest != csrf_digest


def test_t013_rejects_session_at_exact_inactivity_expiry() -> None:
    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    session = _session(last_human_activity_at=created_at)

    assert is_admin_session_valid(
        session=session,
        now=FixedClock(created_at + timedelta(minutes=29, seconds=59)).now(),
    )
    assert not is_admin_session_valid(
        session=session,
        now=FixedClock(created_at + timedelta(minutes=30)).now(),
    )


def test_t013_rejects_session_at_exact_absolute_expiry() -> None:
    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    session = _session(
        last_human_activity_at=created_at + timedelta(hours=7, minutes=30)
    )

    assert is_admin_session_valid(
        session=session,
        now=FixedClock(
            created_at + SESSION_ABSOLUTE_LIMIT - timedelta(seconds=1)
        ).now(),
    )
    assert not is_admin_session_valid(
        session=session,
        now=FixedClock(created_at + SESSION_ABSOLUTE_LIMIT).now(),
    )


def test_t013_rejects_an_invalidated_session_immediately() -> None:
    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    session = _session(
        last_human_activity_at=created_at,
        status="invalidated",
        invalidated_at=created_at + timedelta(minutes=1),
    )

    assert not is_admin_session_valid(
        session=session,
        now=FixedClock(created_at + timedelta(minutes=1)).now(),
    )


def test_t013_rejects_a_session_without_the_exact_absolute_deadline() -> None:
    created_at = datetime(2030, 6, 15, 10, tzinfo=timezone.utc)
    with pytest.raises(AdminSessionInvariantError):
        AdminSession(
            account_id=1,
            session_digest=b"\x42" * 32,
            csrf_digest=b"\x43" * 32,
            key_version="v1",
            created_at=created_at,
            last_human_activity_at=created_at,
            absolute_expires_at=created_at + timedelta(hours=7, minutes=59),
            status="active",
            invalidated_at=None,
        )

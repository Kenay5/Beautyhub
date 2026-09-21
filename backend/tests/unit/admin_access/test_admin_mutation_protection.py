"""T049 unit evidence for administrative same-origin and CSRF protection."""

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.mutation_protection import (
    AdministrativeMutationProtectionError,
    AdministrativeSessionAuthenticationError,
    ValidateAdministrativeMutationProtection,
)
from backend.app.application.clock import FixedClock
from backend.app.domain.sessions.admin_session import AdminSession
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


SESSION_TOKEN = b"\x71" * 32
CSRF_TOKEN = b"\x72" * 32
OTHER_CSRF_TOKEN = b"\x73" * 32
APPROVED_ORIGIN = "https://beautyhub.example.test"
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


def _protector() -> AdminSessionProtector:
    return AdminSessionProtector(
        key_ring=CryptographyKeyRing(
            CryptographyKeyConfiguration(
                root_key=SecretValue(
                    base64.urlsafe_b64encode(b"\x70" * 32).decode("ascii")
                ),
                key_version="v1",
            )
        )
    )


class SessionStore:
    def __init__(self, *, available: bool = True) -> None:
        self.protector = _protector()
        self.available = available
        self.calls = []
        self.touches = []
        self.invalidations = []
        self.session = AdminSession(
            account_id=7,
            session_digest=self.protector.digest_session_token(SESSION_TOKEN),
            csrf_digest=self.protector.digest_csrf_token(CSRF_TOKEN),
            key_version="v1",
            created_at=NOW,
            last_human_activity_at=NOW,
            absolute_expires_at=NOW + timedelta(hours=8),
            status="active",
            invalidated_at=None,
        )

    def load_active_session(self, *, session_digest):
        self.calls.append(session_digest)
        if not self.available or session_digest != self.protector.digest_session_token(
            SESSION_TOKEN
        ):
            return None
        return self.session

    def touch_human_activity(self, *, session_digest, current_time):
        self.touches.append((session_digest, current_time))
        self.session = replace(self.session, last_human_activity_at=current_time)
        return True

    def invalidate_if_expired(self, *, session_digest, current_time):
        self.invalidations.append((session_digest, current_time))


def _validator(store: SessionStore | None = None, *, now: datetime = NOW):
    selected_store = store or SessionStore()
    return (
        ValidateAdministrativeMutationProtection(
            store=selected_store,
            protector=_protector(),
            clock=FixedClock(now),
        ),
        selected_store,
    )


@pytest.mark.parametrize(
    ("origin", "referer"),
    (
        (APPROVED_ORIGIN, None),
        ("https://BEAUTYHUB.example.test:443", None),
        (None, f"{APPROVED_ORIGIN}/admin/agenda"),
    ),
)
def test_t049_accepts_exact_origin_or_same_origin_referer(origin, referer) -> None:
    validator, store = _validator()

    validator.validate(
        session_token=SESSION_TOKEN,
        csrf_token=CSRF_TOKEN,
        approved_origin=APPROVED_ORIGIN,
        origin=origin,
        referer=referer,
        human_initiated=False,
    )

    assert store.calls == [_protector().digest_session_token(SESSION_TOKEN)]


@pytest.mark.parametrize(
    ("origin", "referer"),
    (
        (None, None),
        ("https://foreign.example.test", None),
        ("null", None),
        ("https://foreign.example.test", f"{APPROVED_ORIGIN}/admin"),
        (f"{APPROVED_ORIGIN}/not-an-origin", None),
    ),
)
def test_t049_rejects_missing_or_unapproved_origin(origin, referer) -> None:
    validator, _ = _validator()

    with pytest.raises(AdministrativeMutationProtectionError):
        validator.validate(
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            approved_origin=APPROVED_ORIGIN,
            origin=origin,
            referer=referer,
            human_initiated=False,
        )


@pytest.mark.parametrize("csrf_token", (None, OTHER_CSRF_TOKEN))
def test_t049_rejects_missing_or_different_csrf(csrf_token) -> None:
    validator, _ = _validator()

    with pytest.raises(AdministrativeMutationProtectionError):
        validator.validate(
            session_token=SESSION_TOKEN,
            csrf_token=csrf_token,
            approved_origin=APPROVED_ORIGIN,
            origin=APPROVED_ORIGIN,
            referer=None,
            human_initiated=False,
        )


@pytest.mark.parametrize(
    ("session_token", "available"),
    ((None, True), (b"\x74" * 32, True), (SESSION_TOKEN, False)),
)
def test_t049_rejects_an_unavailable_session_before_authorizing_mutation(
    session_token, available
) -> None:
    validator, _ = _validator(SessionStore(available=available))

    with pytest.raises(AdministrativeSessionAuthenticationError):
        validator.validate(
            session_token=session_token,
            csrf_token=CSRF_TOKEN,
            approved_origin=APPROVED_ORIGIN,
            origin=APPROVED_ORIGIN,
            referer=None,
            human_initiated=False,
        )


def test_t050_human_activity_renews_only_the_inactivity_window() -> None:
    current_time = NOW + timedelta(minutes=29, seconds=59)
    validator, store = _validator(now=current_time)

    validator.validate(
        session_token=SESSION_TOKEN,
        csrf_token=CSRF_TOKEN,
        approved_origin=APPROVED_ORIGIN,
        origin=APPROVED_ORIGIN,
        referer=None,
        human_initiated=True,
    )

    assert store.session.last_human_activity_at == current_time
    assert store.touches == [
        (_protector().digest_session_token(SESSION_TOKEN), current_time)
    ]


def test_t050_background_validation_does_not_renew_and_exact_inactivity_expires() -> None:
    store = SessionStore()
    automatic, _ = _validator(store, now=NOW + timedelta(minutes=29, seconds=59))
    automatic.validate(
        session_token=SESSION_TOKEN,
        csrf_token=CSRF_TOKEN,
        approved_origin=APPROVED_ORIGIN,
        origin=APPROVED_ORIGIN,
        referer=None,
        human_initiated=False,
    )
    expired, _ = _validator(store, now=NOW + timedelta(minutes=30))

    with pytest.raises(AdministrativeSessionAuthenticationError):
        expired.validate(
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            approved_origin=APPROVED_ORIGIN,
            origin=APPROVED_ORIGIN,
            referer=None,
            human_initiated=False,
        )

    assert store.touches == []
    assert store.invalidations == [
        (_protector().digest_session_token(SESSION_TOKEN), NOW + timedelta(minutes=30))
    ]


def test_t050_absolute_expiry_rejects_even_after_recent_human_activity() -> None:
    store = SessionStore()
    store.session = replace(
        store.session,
        last_human_activity_at=NOW + timedelta(hours=7, minutes=59),
    )
    validator, _ = _validator(store, now=NOW + timedelta(hours=8))

    with pytest.raises(AdministrativeSessionAuthenticationError):
        validator.validate(
            session_token=SESSION_TOKEN,
            csrf_token=CSRF_TOKEN,
            approved_origin=APPROVED_ORIGIN,
            origin=APPROVED_ORIGIN,
            referer=None,
            human_initiated=True,
        )

    assert store.touches == []
    assert store.invalidations == [
        (_protector().digest_session_token(SESSION_TOKEN), NOW + timedelta(hours=8))
    ]

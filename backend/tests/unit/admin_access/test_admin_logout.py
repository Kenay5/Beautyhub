"""T051 unit evidence for idempotent administrative session logout."""

from datetime import datetime, timezone

from backend.app.application.admin_access.logout import CloseAdministrativeSession
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
SESSION_TOKEN = b"\x81" * 32
SESSION_DIGEST = b"session-digest"


class SessionStore:
    def __init__(self, outcomes: list[int | None]) -> None:
        self._outcomes = outcomes
        self.calls = []

    def invalidate_active_session(self, *, session_digest, current_time):
        self.calls.append((session_digest, current_time))
        return self._outcomes.pop(0)


class SessionProtector:
    def digest_session_token(self, token: bytes) -> bytes:
        assert token == SESSION_TOKEN
        return SESSION_DIGEST


class AuditRecorder:
    def __init__(self) -> None:
        self.events = []

    def record(self, **event) -> None:
        self.events.append(event)


def test_t051_invalidates_the_active_session_and_records_minimum_evidence() -> None:
    store = SessionStore([7])
    audit = AuditRecorder()
    logout = CloseAdministrativeSession(
        store=store,
        protector=SessionProtector(),
        audit=audit,
        clock=FixedClock(NOW),
    )

    assert logout.close(session_token=SESSION_TOKEN) is True
    assert store.calls == [(SESSION_DIGEST, NOW)]
    assert audit.events == [
        {
            "actor_account_id": 7,
            "action": "logout",
            "result": "succeeded",
        }
    ]
    assert SESSION_TOKEN.hex() not in repr(audit.events)


def test_t051_repeated_logout_cannot_revive_state_or_duplicate_the_audit() -> None:
    store = SessionStore([7, None])
    audit = AuditRecorder()
    logout = CloseAdministrativeSession(
        store=store,
        protector=SessionProtector(),
        audit=audit,
        clock=FixedClock(NOW),
    )

    assert logout.close(session_token=SESSION_TOKEN) is True
    assert logout.close(session_token=SESSION_TOKEN) is False
    assert store.calls == [(SESSION_DIGEST, NOW), (SESSION_DIGEST, NOW)]
    assert len(audit.events) == 1

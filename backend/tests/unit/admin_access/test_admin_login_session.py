"""T047 unit evidence for successful administrative session creation."""

from datetime import datetime, timezone

import pytest

from backend.app.application.admin_access.login_completion import (
    AdministrativeLoginCredentialOutcome,
)
from backend.app.application.admin_access.login_session import (
    AdministrativeLoginSessionValueError,
    CreateAdministrativeLoginSession,
    StoredAdministrativeLoginSession,
)
from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginValidationOutcome,
    INVALID_LOGIN_REJECTION,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
SESSION_TOKEN = b"\x11" * 32
CSRF_TOKEN = b"\x12" * 32


class CredentialCompleter:
    def __init__(self, outcome: AdministrativeLoginCredentialOutcome) -> None:
        self.outcome = outcome
        self.calls = []

    def complete(self, *, validation):
        self.calls.append(validation)
        return self.outcome


class SessionStore:
    def __init__(self) -> None:
        self.calls = []

    def replace_active_session(self, **values):
        self.calls.append(values)
        return StoredAdministrativeLoginSession(session_id=19, role="staff")


class SessionProtector:
    key_version = "v7"

    def digest_session_token(self, token: bytes) -> bytes:
        assert token == SESSION_TOKEN
        return b"\x21" * 32

    def digest_csrf_token(self, token: bytes) -> bytes:
        assert token == CSRF_TOKEN
        return b"\x22" * 32


class AuditRecorder:
    def __init__(self) -> None:
        self.calls = []

    def record(self, **values) -> None:
        self.calls.append(values)


def _use_case(*, credentials, store, audit, tokens):
    return CreateAdministrativeLoginSession(
        credentials=credentials,
        store=store,
        protector=SessionProtector(),
        secret_generator=SequenceSecretGenerator(tokens),
        audit=audit,
        clock=FixedClock(NOW),
    )


def test_t047_success_creates_protected_values_and_uses_the_stored_real_role() -> None:
    validation = AdministrativeLoginValidationOutcome(rejection="unused fixture")
    credentials = CredentialCompleter(
        AdministrativeLoginCredentialOutcome(account_id=7, role="owner")
    )
    store = SessionStore()
    audit = AuditRecorder()

    outcome = _use_case(
        credentials=credentials,
        store=store,
        audit=audit,
        tokens=(SESSION_TOKEN, CSRF_TOKEN),
    ).create(validation=validation)

    assert outcome.accepted
    assert (outcome.account_id, outcome.session_id, outcome.role) == (7, 19, "staff")
    assert (outcome.session_token, outcome.csrf_token) == (SESSION_TOKEN, CSRF_TOKEN)
    assert credentials.calls == [validation]
    assert store.calls == [
        {
            "account_id": 7,
            "session_digest": b"\x21" * 32,
            "csrf_digest": b"\x22" * 32,
            "key_version": "v7",
            "current_time": NOW,
        }
    ]
    assert audit.calls == [
        {
            "actor_account_id": 7,
            "action": "login",
            "result": "succeeded",
        }
    ]
    assert SESSION_TOKEN.hex() not in repr(outcome)
    assert CSRF_TOKEN.hex() not in repr(outcome)


@pytest.mark.parametrize("rejected_account_id", (7, None), ids=("known", "unknown"))
def test_t084_rejected_login_is_audited_without_creating_a_session(
    rejected_account_id: int | None,
) -> None:
    validation = AdministrativeLoginValidationOutcome(
        rejection=INVALID_LOGIN_REJECTION,
        rejected_account_id=rejected_account_id,
    )
    credentials = CredentialCompleter(
        AdministrativeLoginCredentialOutcome(rejection=INVALID_LOGIN_REJECTION)
    )
    store = SessionStore()
    audit = AuditRecorder()

    outcome = _use_case(
        credentials=credentials,
        store=store,
        audit=audit,
        tokens=(),
    ).create(validation=validation)

    assert not outcome.accepted
    assert outcome.rejection == INVALID_LOGIN_REJECTION
    assert store.calls == []
    assert audit.calls == [
        {
            "actor_account_id": rejected_account_id,
            "action": "login",
            "result": "failed",
        }
    ]


def test_t048_equal_session_and_csrf_values_fail_before_persistence() -> None:
    credentials = CredentialCompleter(
        AdministrativeLoginCredentialOutcome(account_id=7, role="owner")
    )
    store = SessionStore()
    audit = AuditRecorder()

    with pytest.raises(AdministrativeLoginSessionValueError):
        _use_case(
            credentials=credentials,
            store=store,
            audit=audit,
            tokens=(SESSION_TOKEN, SESSION_TOKEN),
        ).create(validation=AdministrativeLoginValidationOutcome(rejection="fixture"))

    assert store.calls == []
    assert audit.calls == []

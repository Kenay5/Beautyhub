"""T058: an internal recovery intent exists only for an active account."""

from backend.app.application.admin_access.password_recovery_request import (
    PasswordRecoveryIntent,
    RequestAdministrativePasswordRecovery,
)


class EmailLookup:
    def __init__(self) -> None:
        self.values: list[str] = []

    def lookup_digest(self, value: str) -> bytes:
        self.values.append(value)
        return b"\x51" * 32


class ActiveAccountStore:
    def __init__(self, account_id: int | None) -> None:
        self.account_id = account_id
        self.digests: list[bytes] = []

    def find_active_account_id(self, *, email_lookup_digest: bytes) -> int | None:
        self.digests.append(email_lookup_digest)
        return self.account_id


def test_t058_valid_email_is_normalized_before_active_account_lookup() -> None:
    lookup = EmailLookup()
    store = ActiveAccountStore(7)
    requester = RequestAdministrativePasswordRecovery(store=store, email_lookup=lookup)

    assert requester.request(email=" SYNTHETIC.OWNER@EXAMPLE.TEST ") == PasswordRecoveryIntent(7)
    assert lookup.values == ["synthetic.owner@example.test"]
    assert store.digests == [b"\x51" * 32]


def test_t058_missing_account_and_invalid_email_cannot_create_intent() -> None:
    lookup = EmailLookup()
    store = ActiveAccountStore(None)
    requester = RequestAdministrativePasswordRecovery(store=store, email_lookup=lookup)

    assert requester.request(email="synthetic.missing@example.test") is None
    assert requester.request(email="not-an-email") is None
    assert lookup.values == ["synthetic.missing@example.test"]
    assert store.digests == [b"\x51" * 32]

"""T027 unit evidence for the common one-use security-link lifecycle."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.application.admin_access.security_links import (
    SECURITY_LINK_LIFETIMES,
    SecurityLinkLifecycle,
    StoredSecurityLink,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.domain.authentication.security_link import (
    SecurityLink,
    SecurityLinkPurpose,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue


NOW = datetime(2032, 4, 5, 16, tzinfo=timezone.utc)


@dataclass
class LinkState:
    link_id: int
    link: SecurityLink
    status: str = "active"


class InMemorySecurityLinkStore:
    def __init__(self) -> None:
        self.rows: list[LinkState] = []

    def replace_active(self, *, link: SecurityLink) -> StoredSecurityLink:
        for row in self.rows:
            if (
                row.link.account_id == link.account_id
                and row.link.purpose == link.purpose
                and row.status == "active"
            ):
                row.status = (
                    "expired" if row.link.expires_at <= link.issued_at else "invalidated"
                )
        row = LinkState(link_id=len(self.rows) + 1, link=link)
        self.rows.append(row)
        return self._stored(row)

    def inspect_active(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose, now: datetime
    ) -> StoredSecurityLink | None:
        row = self._find(token_digest=token_digest, purpose=purpose)
        if row is None or row.status != "active" or now >= row.link.expires_at:
            return None
        return self._stored(row)

    def consume_active(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose, now: datetime
    ) -> StoredSecurityLink | None:
        row = self._find(token_digest=token_digest, purpose=purpose)
        if row is None or row.status != "active":
            return None
        if now >= row.link.expires_at:
            row.status = "expired"
            return None
        row.status = "consumed"
        return self._stored(row)

    def _find(
        self, *, token_digest: bytes, purpose: SecurityLinkPurpose
    ) -> LinkState | None:
        return next(
            (
                row
                for row in self.rows
                if row.link.token_digest == token_digest and row.link.purpose == purpose
            ),
            None,
        )

    @staticmethod
    def _stored(row: LinkState) -> StoredSecurityLink:
        return StoredSecurityLink(
            link_id=row.link_id,
            account_id=row.link.account_id,
            purpose=row.link.purpose,
            expires_at=row.link.expires_at,
        )


def _protector() -> SecurityLinkProtector:
    return SecurityLinkProtector(
        key_ring=CryptographyKeyRing(
            CryptographyKeyConfiguration(
                root_key=SecretValue(
                    base64.urlsafe_b64encode(b"\x71" * 32).decode("ascii")
                ),
                key_version="v1",
            )
        )
    )


def _lifecycle(
    *, store: InMemorySecurityLinkStore, now: datetime, tokens: tuple[bytes, ...]
) -> SecurityLinkLifecycle:
    return SecurityLinkLifecycle(
        store=store,
        clock=FixedClock(now),
        secret_generator=SequenceSecretGenerator(tokens),
        protector=_protector(),
    )


@pytest.mark.parametrize(
    "purpose",
    tuple(SECURITY_LINK_LIFETIMES),
)
def test_t027_issues_each_purpose_with_its_exact_approved_lifetime(
    purpose: SecurityLinkPurpose,
) -> None:
    store = InMemorySecurityLinkStore()
    issued = _lifecycle(
        store=store, now=NOW, tokens=(b"\x72" * 32,)
    ).issue(account_id=7, purpose=purpose)

    assert issued.stored_link.expires_at == NOW + SECURITY_LINK_LIFETIMES[purpose]
    assert issued.token == b"\x72" * 32
    assert issued.token not in store.rows[0].link.token_digest
    assert store.rows[0].link.delivery_status == "pending"


def test_t027_replacement_invalidates_the_previous_link_and_gets_a_full_window() -> None:
    store = InMemorySecurityLinkStore()
    first = _lifecycle(store=store, now=NOW, tokens=(b"\x73" * 32,)).issue(
        account_id=8, purpose="invitation"
    )
    replacement_time = NOW + timedelta(hours=2)
    second = _lifecycle(
        store=store, now=replacement_time, tokens=(b"\x74" * 32,)
    ).issue(account_id=8, purpose="invitation")

    assert [row.status for row in store.rows] == ["invalidated", "active"]
    assert second.stored_link.expires_at == replacement_time + timedelta(hours=24)
    assert _lifecycle(store=store, now=replacement_time, tokens=()).inspect(
        token=first.token, purpose="invitation"
    ) is None


def test_t027_inspection_does_not_consume_and_consumption_succeeds_once() -> None:
    store = InMemorySecurityLinkStore()
    lifecycle = _lifecycle(store=store, now=NOW, tokens=(b"\x75" * 32,))
    issued = lifecycle.issue(account_id=9, purpose="password_recovery")

    assert lifecycle.inspect(
        token=issued.token, purpose="password_recovery"
    ) == issued.stored_link
    assert lifecycle.inspect(
        token=issued.token, purpose="password_recovery"
    ) == issued.stored_link
    assert store.rows[0].status == "active"
    assert lifecycle.consume(
        token=issued.token, purpose="password_recovery"
    ) == issued.stored_link
    assert lifecycle.consume(token=issued.token, purpose="password_recovery") is None
    assert lifecycle.inspect(token=issued.token, purpose="password_recovery") is None


def test_t027_rejects_at_exact_expiry_and_for_the_wrong_purpose() -> None:
    store = InMemorySecurityLinkStore()
    issued = _lifecycle(store=store, now=NOW, tokens=(b"\x76" * 32,)).issue(
        account_id=10, purpose="email_change"
    )

    assert _lifecycle(store=store, now=NOW, tokens=()).consume(
        token=issued.token, purpose="totp_replacement"
    ) is None
    assert _lifecycle(
        store=store, now=issued.stored_link.expires_at, tokens=()
    ).consume(token=issued.token, purpose="email_change") is None
    assert store.rows[0].status == "expired"


def test_t027_rejects_a_malformed_token_without_touching_state() -> None:
    store = InMemorySecurityLinkStore()
    lifecycle = _lifecycle(store=store, now=NOW, tokens=(b"\x77" * 32,))
    lifecycle.issue(account_id=11, purpose="initial_activation")

    assert lifecycle.inspect(token=b"short", purpose="initial_activation") is None
    assert lifecycle.consume(token=b"short", purpose="initial_activation") is None
    assert store.rows[0].status == "active"

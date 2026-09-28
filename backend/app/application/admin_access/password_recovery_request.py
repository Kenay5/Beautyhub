"""Resolve a public password-recovery request without exposing account existence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.app.application.admin_access.rate_limit import (
    PublicSecurityMessageBudget,
    SecurityMessageActionBudget,
)

from backend.app.application.admin_access.security_links import (
    IssuedSecurityLink,
    SecurityLinkLifecycle,
)
from backend.app.domain.authentication.admin_email_claim import (
    AdministrativeEmailClaimError,
    normalize_administrative_email_address,
)


class AdministrativeRecoveryEmailLookup(Protocol):
    def lookup_digest(self, value: str) -> bytes: ...


class AdministrativeRecoveryAccountStore(Protocol):
    def find_active_account_id(self, *, email_lookup_digest: bytes) -> int | None: ...

    def load_active_account_recipient(
        self, *, account_id: int
    ) -> "PasswordRecoveryRecipient" | None: ...


@dataclass(frozen=True)
class PasswordRecoveryRecipient:
    account_id: int
    email: str = field(repr=False)


@dataclass(frozen=True)
class PasswordRecoveryIntent:
    """Internal handoff for a later link-issuance operation; never an HTTP value."""

    account_id: int


@dataclass(frozen=True)
class PreparedPasswordRecoveryLink:
    """An issued link and its recipient, transient until provider delivery."""

    recipient: PasswordRecoveryRecipient = field(repr=False)
    issued_link: IssuedSecurityLink = field(repr=False)


class RequestAdministrativePasswordRecovery:
    """Only a current claim on an active account can produce an internal intent."""

    def __init__(
        self,
        *,
        store: AdministrativeRecoveryAccountStore,
        email_lookup: AdministrativeRecoveryEmailLookup,
    ) -> None:
        self._store = store
        self._email_lookup = email_lookup

    def request(self, *, email: str) -> PasswordRecoveryIntent | None:
        try:
            normalized = normalize_administrative_email_address(email)
        except AdministrativeEmailClaimError:
            return None
        digest = self._email_lookup.lookup_digest(normalized)
        account_id = self._store.find_active_account_id(email_lookup_digest=digest)
        return None if account_id is None else PasswordRecoveryIntent(account_id)


class PrepareAdministrativePasswordRecovery:
    """Issue one 30-minute link for a locked, current active-account claim."""

    def __init__(
        self,
        *,
        requester: RequestAdministrativePasswordRecovery,
        store: AdministrativeRecoveryAccountStore,
        link_lifecycle: SecurityLinkLifecycle,
        security_message_budget: SecurityMessageActionBudget,
        public_security_message_budget: PublicSecurityMessageBudget | None = None,
    ) -> None:
        self._requester = requester
        self._store = store
        self._link_lifecycle = link_lifecycle
        self._security_message_budget = security_message_budget
        self._public_security_message_budget = public_security_message_budget

    def prepare(self, *, email: str) -> PreparedPasswordRecoveryLink | None:
        intent = self._requester.request(email=email)
        if intent is None:
            if self._public_security_message_budget is not None:
                self._public_security_message_budget.reserve(account_id=None)
            return None
        if self._public_security_message_budget is not None:
            if not self._public_security_message_budget.reserve(
                account_id=intent.account_id
            ):
                return None
        elif not self._security_message_budget.reserve(account_id=intent.account_id):
            return None
        recipient = self._store.load_active_account_recipient(
            account_id=intent.account_id
        )
        if recipient is None:
            return None
        issued_link = self._link_lifecycle.issue(
            account_id=recipient.account_id,
            purpose="password_recovery",
        )
        return PreparedPasswordRecoveryLink(
            recipient=recipient,
            issued_link=issued_link,
        )

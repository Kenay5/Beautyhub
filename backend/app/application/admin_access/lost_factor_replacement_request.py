"""Prepare a public lost-factor replacement request without account disclosure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend.app.application.admin_access.rate_limit import (
    PublicSecurityMessageBudget,
    SecurityMessageActionBudget,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.security_links import (
    IssuedSecurityLink,
    SecurityLinkLifecycle,
)


@dataclass(frozen=True)
class LostFactorReplacementCandidate:
    account_id: int
    status: str
    password_hash: str | None = field(repr=False)
    recipient_email: str = field(repr=False)
    credential_check_allowed: bool
    post_recovery_restricted: bool


@dataclass(frozen=True)
class PreparedLostFactorReplacement:
    recipient_email: str = field(repr=False)
    issued_link: IssuedSecurityLink = field(repr=False)


class LostFactorReplacementRequestStore(Protocol):
    def load_candidate(self, *, email_lookup_digest: bytes) -> LostFactorReplacementCandidate | None: ...


class AdministrativePasswordVerifier(Protocol):
    def verify_and_upgrade(self, *, stored_hash: str, password: str): ...
    def verify_unknown_account(self, *, password: str): ...


class CredentialFailureRecorder(Protocol):
    def record(self, *, account_id: int, operation: str): ...


class RequestAdministrativeLostFactorReplacement:
    """Issue only after every account and credential condition is satisfied."""

    def __init__(
        self,
        *,
        store: LostFactorReplacementRequestStore,
        email_lookup,
        password_verifier: AdministrativePasswordVerifier,
        failure_recorder: CredentialFailureRecorder,
        links: SecurityLinkLifecycle,
        audit: RecordAdministrativeAuditEvent,
        security_message_budget: SecurityMessageActionBudget,
        public_security_message_budget: PublicSecurityMessageBudget | None = None,
    ) -> None:
        self._store = store
        self._email_lookup = email_lookup
        self._password_verifier = password_verifier
        self._failure_recorder = failure_recorder
        self._links = links
        self._audit = audit
        self._security_message_budget = security_message_budget
        self._public_security_message_budget = public_security_message_budget

    def prepare(self, *, email: str, password: str) -> PreparedLostFactorReplacement | None:
        """Return a delivery intent only for an active, unlocked, eligible account."""

        try:
            lookup_digest = self._email_lookup.lookup_digest(email)
        except (TypeError, ValueError):
            if self._public_security_message_budget is not None:
                self._public_security_message_budget.reserve(account_id=None)
            self._password_verifier.verify_unknown_account(password=password)
            return None

        candidate = self._store.load_candidate(email_lookup_digest=lookup_digest)
        if candidate is None or candidate.password_hash is None:
            if self._public_security_message_budget is not None:
                self._public_security_message_budget.reserve(account_id=None)
            self._password_verifier.verify_unknown_account(password=password)
            return None

        if self._public_security_message_budget is not None:
            if not self._public_security_message_budget.reserve(
                account_id=candidate.account_id
            ):
                return None
        elif not self._security_message_budget.reserve(account_id=candidate.account_id):
            return None

        if not candidate.credential_check_allowed:
            # Preserve timing without checking a credential while the lock is active.
            self._password_verifier.verify_unknown_account(password=password)
            return None

        verification = self._password_verifier.verify_and_upgrade(
            stored_hash=candidate.password_hash,
            password=password,
        )
        if not verification.verified:
            self._failure_recorder.record(
                account_id=candidate.account_id,
                operation="totp_replacement",
            )
            self._audit.record(
                actor_account_id=candidate.account_id,
                action="totp_replacement",
                result="failed",
            )
            return None

        if (
            candidate.status != "active"
            or candidate.post_recovery_restricted
        ):
            return None

        issued = self._links.issue(
            account_id=candidate.account_id,
            purpose="totp_replacement",
        )
        return PreparedLostFactorReplacement(
            recipient_email=candidate.recipient_email,
            issued_link=issued,
        )

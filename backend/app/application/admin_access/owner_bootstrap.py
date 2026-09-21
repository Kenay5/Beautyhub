"""Use case for the protected initial owner-email registration."""

from __future__ import annotations

from typing import Protocol

from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
    ProtectedAdministrativeEmail,
)


class OwnerBootstrapRegistrationStore(Protocol):
    """Persist the initial inactive owner and its protected email claim."""

    def register_inactive_owner(self, *, email: ProtectedAdministrativeEmail) -> None:
        """Create the one owner atomically or reject without a partial account."""


class RegisterOwnerBootstrap:
    """Register only the email needed before the owner activates their account."""

    def __init__(
        self,
        *,
        store: OwnerBootstrapRegistrationStore,
        email_protector: AdministrativeEmailProtector,
    ) -> None:
        self._store = store
        self._email_protector = email_protector

    def register(self, *, email: str) -> None:
        """Protect a validated email before the store creates an inactive owner."""

        self._store.register_inactive_owner(email=self._email_protector.protect(email))

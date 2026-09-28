"""Shared HTTP guard for manually initiated administrative security messages."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from fastapi import Depends, HTTPException

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.rate_limit import (
    ReserveCoordinatedAdministrativeRateLimits,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.domain.authentication.rate_limit import (
    AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT,
    SECURITY_MESSAGE_ACTION_LIMIT,
)
from backend.app.infrastructure.persistence.admin_rate_limit_repository import (
    PostgresAdministrativeRateLimitStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.session_context import get_revalidated_admin_actor


_RATE_LIMIT_DETAIL = "Demasiadas solicitudes. Inténtalo más tarde."


class SecurityMessageActionLimiter(Protocol):
    """Reserve one message action for an already authenticated account."""

    def ensure_allowed(self, *, actor: AdministrativeActor) -> None: ...


def get_security_message_action_limiter() -> Iterator[SecurityMessageActionLimiter]:
    """Defer DB and key configuration access until a valid actor is available."""

    yield _PostgresSecurityMessageActionLimiter()


def get_authenticated_security_message_actor(
    actor: AdministrativeActor = Depends(get_revalidated_admin_actor),
    limiter: SecurityMessageActionLimiter = Depends(
        get_security_message_action_limiter
    ),
) -> AdministrativeActor:
    """Apply the shared message budget before CSRF activity or business work."""

    limiter.ensure_allowed(actor=actor)
    return actor


class _PostgresSecurityMessageActionLimiter:
    def __init__(self, *, engine=None) -> None:
        self._engine = engine

    def ensure_allowed(self, *, actor: AdministrativeActor) -> None:
        if not isinstance(actor, AdministrativeActor):
            raise TypeError("revalidated administrative actor is required.")
        engine = self._engine or create_postgres_engine(load_settings().database_url)
        try:
            with engine.begin() as connection:
                subject = AdministrativeRateLimitSubjectProtector(
                    key_ring=CryptographyKeyRing(
                        load_cryptography_key_configuration()
                    )
                ).fingerprint_account(actor.account_id)
                allowed = ReserveCoordinatedAdministrativeRateLimits(
                    store=PostgresAdministrativeRateLimitStore(connection),
                    clock=SystemClock(),
                    secret_generator=SystemSecretGenerator(),
                ).reserve(
                    limits=(
                        (
                            AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
                            subject,
                        ),
                        (SECURITY_MESSAGE_ACTION_LIMIT.category, subject),
                    )
                )
            if not allowed.allowed:
                raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL)
        finally:
            if self._engine is None:
                engine.dispose()

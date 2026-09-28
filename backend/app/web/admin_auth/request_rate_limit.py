"""HTTP composition of the authenticated administrative account budget."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from fastapi import HTTPException

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.rate_limit import (
    AuthenticatedAdministrativeRequestLimitError,
    LimitAuthenticatedAdministrativeRequests,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
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


_RATE_LIMIT_DETAIL = "Demasiadas solicitudes. Inténtalo más tarde."


class AuthenticatedAdministrativeRequestLimiter(Protocol):
    """Reserve a request using an actor already revalidated by the backend."""

    def ensure_allowed(self, *, actor: AdministrativeActor) -> None: ...


def get_authenticated_administrative_request_limiter(
) -> Iterator[AuthenticatedAdministrativeRequestLimiter]:
    """Build the shared PostgreSQL-backed per-account moving-window guard."""

    yield _PostgresAuthenticatedAdministrativeRequestLimiter()


class _PostgresAuthenticatedAdministrativeRequestLimiter:
    """Commit each account reservation independently of protected business work."""

    def __init__(self, *, engine=None) -> None:
        self._engine = engine

    def ensure_allowed(self, *, actor: AdministrativeActor) -> None:
        if not isinstance(actor, AdministrativeActor):
            raise TypeError("revalidated administrative actor is required.")
        subject_fingerprint = AdministrativeRateLimitSubjectProtector(
            key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
        ).fingerprint_account(
            actor.account_id
        )
        engine = self._engine or create_postgres_engine(load_settings().database_url)
        try:
            with engine.begin() as connection:
                LimitAuthenticatedAdministrativeRequests(
                    store=PostgresAdministrativeRateLimitStore(connection),
                    clock=SystemClock(),
                    subject_fingerprint=subject_fingerprint,
                    secret_generator=SystemSecretGenerator(),
                ).ensure_allowed()
        except AuthenticatedAdministrativeRequestLimitError as error:
            raise HTTPException(status_code=429, detail=_RATE_LIMIT_DETAIL) from error
        finally:
            if self._engine is None:
                engine.dispose()

"""PostgreSQL adapter for account-scoped manual security-message budgets."""

from __future__ import annotations

from sqlalchemy import Connection

from backend.app.application.admin_access.rate_limit import (
    ReserveCoordinatedAdministrativeRateLimits,
    ReserveAdministrativeRateLimit,
    PublicSecurityMessageBudget,
    SecurityMessageActionBudget,
)
from backend.app.application.clock import Clock
from backend.app.application.entropy import SecretGenerator
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.authentication.rate_limit import (
    AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT,
    SECURITY_MESSAGE_ACTION_LIMIT,
)
from backend.app.infrastructure.persistence.admin_rate_limit_repository import (
    PostgresAdministrativeRateLimitStore,
)
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)


class PostgresSecurityMessageActionBudget(SecurityMessageActionBudget):
    """Use the shared rate-limit guard with a purpose-separated account HMAC."""

    def __init__(
        self,
        *,
        connection: Connection,
        subject_protector: AdministrativeRateLimitSubjectProtector,
        clock: Clock,
        secret_generator: SecretGenerator,
    ) -> None:
        self._connection = connection
        self._subject_protector = subject_protector
        self._clock = clock
        self._secret_generator = secret_generator

    def reserve(self, *, account_id: int) -> bool:
        subject_fingerprint = self._subject_protector.fingerprint_account(account_id)
        return ReserveAdministrativeRateLimit(
            store=PostgresAdministrativeRateLimitStore(self._connection),
            clock=self._clock,
        ).reserve(
            category=SECURITY_MESSAGE_ACTION_LIMIT.category,
            subject_fingerprint=subject_fingerprint,
            request_fingerprint=self._secret_generator.token_bytes(32),
        )


class PostgresPublicSecurityMessageBudget(PublicSecurityMessageBudget):
    """Reserve the public-origin and optional account budgets as one action."""

    def __init__(
        self,
        *,
        connection: Connection,
        public_subject_fingerprint: bytes,
        subject_protector: AdministrativeRateLimitSubjectProtector,
        clock: Clock,
        secret_generator: SecretGenerator,
    ) -> None:
        self._connection = connection
        self._public_subject_fingerprint = public_subject_fingerprint
        self._subject_protector = subject_protector
        self._clock = clock
        self._secret_generator = secret_generator

    def reserve(self, *, account_id: int | None) -> bool:
        """Raise a public 429, hide account-budget exhaustion, and write neither partially."""

        limits = [
            (
                AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.category,
                self._public_subject_fingerprint,
            )
        ]
        if account_id is not None:
            limits.append(
                (
                    SECURITY_MESSAGE_ACTION_LIMIT.category,
                    self._subject_protector.fingerprint_account(account_id),
                )
            )
        outcome = ReserveCoordinatedAdministrativeRateLimits(
            store=PostgresAdministrativeRateLimitStore(self._connection),
            clock=self._clock,
            secret_generator=self._secret_generator,
        ).reserve(limits=tuple(limits))
        if (
            not outcome.allowed
            and outcome.denied_category
            == AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.category
        ):
            raise PublicRequestRateLimitError(
                "Public authentication request limit exceeded."
            )
        return outcome.allowed

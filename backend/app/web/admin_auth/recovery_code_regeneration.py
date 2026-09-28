"""Authenticated HTTP contract for replacing recovery codes."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
    SecurityNotificationDispatch,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.regenerate_recovery_codes import (
    RegenerateAdministrativeRecoveryCodes,
    RecoveryCodeRegenerationOutcome,
)
from backend.app.application.admin_access.security_change_invalidation import (
    InvalidateAfterSecurityChange,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import (
    EmailSimulator,
    EmailSimulatorUncertainOutcome,
)
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import (
    PostgresAdministrativeLockRecipientDirectory,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.recovery_code_regeneration_repository import (
    PostgresRecoveryCodeRegenerationStore,
)
from backend.app.infrastructure.persistence.security_change_invalidation_repository import (
    PostgresSecurityChangeInvalidationStore,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtector,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices


router = APIRouter(prefix="/api/admin/recovery-codes", tags=["admin-recovery-codes"])
_CREDENTIAL_DETAIL = "No fue posible comprobar las credenciales."
_UNAVAILABLE_DETAIL = "No fue posible regenerar los códigos de recuperación."
_RECOVERY_CODES_NOTICE = (
    "Los códigos de recuperación de tu cuenta administrativa fueron regenerados."
)
_SECURITY_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
_LOGGER = logging.getLogger(__name__)


class RecoveryCodeRegenerationBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(
        alias="currentPassword", min_length=1, max_length=128, repr=False
    )
    totp_code: str = Field(alias="totpCode", min_length=1, max_length=32, repr=False)


class RecoveryCodeRegenerationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recovery_codes: tuple[str, ...] = Field(
        serialization_alias="recoveryCodes",
        min_length=10,
        max_length=10,
        repr=False,
    )


class RecoveryCodeRegenerationOperation(Protocol):
    def regenerate(
        self, *, account_id: int, current_password: str, totp_code: str
    ) -> RecoveryCodeRegenerationOutcome: ...


def get_recovery_code_regeneration_operation(
) -> Iterator[RecoveryCodeRegenerationOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresRecoveryCodeRegenerationOperation(engine)
    finally:
        engine.dispose()


class _PostgresRecoveryCodeRegenerationOperation:
    """Commit the replacement before attempting its security-notice email."""

    def __init__(
        self,
        engine: Engine,
        email_sender: TransactionalNotificationPort | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")

    def regenerate(
        self, *, account_id: int, current_password: str, totp_code: str
    ) -> RecoveryCodeRegenerationOutcome:
        dispatches: list[SecurityNotificationDispatch] = []
        with self._engine.begin() as connection:
            outcome = _compose_regeneration(
                connection, dispatches=dispatches
            ).regenerate(
                account_id=account_id,
                current_password=current_password,
                totp_code=totp_code,
            )
        deliver_security_notices(
            engine=self._engine,
            email_sender=self._email_sender,
            notices=dispatches,
        )
        if outcome.status == "regenerated":
            assert outcome.notification_recipient is not None
            assert outcome.notification_delivery_id is not None
            self._deliver(
                recipient=outcome.notification_recipient,
                delivery_id=outcome.notification_delivery_id,
            )
        return outcome

    def _deliver(self, *, recipient: str, delivery_id: int) -> None:
        try:
            sent = self._email_sender.send(
                OutboundNotification(
                    channel=EMAIL_CHANNEL,
                    recipient=recipient,
                    content=_RECOVERY_CODES_NOTICE,
                )
            )
            delivery_outcome = sent.outcome
        except EmailSimulatorUncertainOutcome:
            delivery_outcome = "uncertain"
        except Exception:
            delivery_outcome = "failed"
        try:
            with self._engine.begin() as connection:
                PostgresSecurityNotificationDeliveryStore(
                    connection
                ).record_immediate_result(
                    delivery_id=delivery_id,
                    outcome=delivery_outcome,
                )
        except Exception:
            _LOGGER.error("administrative recovery-code notice status was not recorded")


def _compose_regeneration(
    connection: Connection,
    *,
    dispatches: list[SecurityNotificationDispatch] | None = None,
) -> RegenerateAdministrativeRecoveryCodes:
    clock = SystemClock()
    entropy = SystemSecretGenerator()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    account_security = PostgresAdministrativeAccountSecurityStore(connection)
    audit = RecordAdministrativeAuditEvent(
        store=PostgresAdministrativeAuditStore(connection), clock=clock
    )
    email_protector = AdministrativeEmailProtector(
        key_ring=key_ring, secret_generator=entropy
    )
    return RegenerateAdministrativeRecoveryCodes(
        store=PostgresRecoveryCodeRegenerationStore(
            connection=connection,
            email_protector=email_protector,
        ),
        credential_guard=EnsureAdministrativeCredentialCheck(
            store=account_security, clock=clock
        ),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(
                store=account_security, clock=clock
            ),
            audit=audit,
            notifications=RecordSecurityNotificationDelivery(
                store=PostgresSecurityNotificationDeliveryStore(connection),
                protector=SecurityNotificationDeliveryProtector(
                    key_ring=key_ring,
                    secret_generator=entropy,
                ),
            ),
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection,
                email_protector=email_protector,
            ),
            dispatches=dispatches,
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=key_ring,
            secret_generator=entropy,
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=key_ring),
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection),
            clock=clock,
        ),
        audit=audit,
        notifications=RecordSecurityNotificationDelivery(
            store=PostgresSecurityNotificationDeliveryStore(connection),
            protector=SecurityNotificationDeliveryProtector(
                key_ring=key_ring,
                secret_generator=entropy,
            ),
        ),
        clock=clock,
    )


@router.post("/regenerate", response_model=RecoveryCodeRegenerationResponse)
def regenerate_recovery_codes(
    body: RecoveryCodeRegenerationBody,
    response: Response,
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    protection: Annotated[
        None,
        Depends(require_administrative_mutation_protection, scope="function"),
    ],
    operation: Annotated[
        RecoveryCodeRegenerationOperation,
        Depends(get_recovery_code_regeneration_operation, scope="function"),
    ],
) -> RecoveryCodeRegenerationResponse | JSONResponse:
    del protection
    response.headers.update(_SECURITY_RESPONSE_HEADERS)
    outcome = operation.regenerate(
        account_id=actor.account_id,
        current_password=body.current_password,
        totp_code=body.totp_code,
    )
    if outcome.status == "invalid_credentials":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": _CREDENTIAL_DETAIL},
            headers=_SECURITY_RESPONSE_HEADERS,
        )
    if outcome.status != "regenerated":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": _UNAVAILABLE_DETAIL},
            headers=_SECURITY_RESPONSE_HEADERS,
        )

    response.delete_cookie(
        key=ADMINISTRATIVE_SESSION_COOKIE,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.status_code = status.HTTP_200_OK
    return RecoveryCodeRegenerationResponse(recovery_codes=outcome.recovery_codes)

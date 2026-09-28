"""Authenticated API for preparing a new TOTP factor without activating it."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
    SecurityNotificationDispatch,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.prepare_totp_replacement import (
    PrepareAdministrativeTotpReplacement,
    PreparedTotpReplacement,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
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
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.totp_replacement_repository import (
    PostgresTotpReplacementStore,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.security.pending_totp_protection import (
    PendingTotpProtector,
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
from backend.app.web.admin_auth.mutation_protection import (
    require_administrative_mutation_protection,
)
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices


router = APIRouter(prefix="/api/admin/totp-replacement", tags=["admin-totp-replacement"])
_CREDENTIAL_DETAIL = "No fue posible comprobar las credenciales."
_UNAVAILABLE_DETAIL = "No fue posible iniciar la configuración."
_SECURITY_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class TotpReplacementPreparationBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(alias="currentPassword", min_length=1, max_length=128, repr=False)
    totp_code: str | None = Field(default=None, alias="totpCode", min_length=1, max_length=32, repr=False)
    recovery_code: str | None = Field(default=None, alias="recoveryCode", min_length=1, max_length=64, repr=False)

    @model_validator(mode="after")
    def exactly_one_factor_proof(self) -> "TotpReplacementPreparationBody":
        if (self.totp_code is None) == (self.recovery_code is None):
            raise ValueError("exactly one current factor proof is required")
        return self


class TotpReplacementPreparationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provisioning_uri: str = Field(serialization_alias="provisioningUri", repr=False)
    manual_key: str = Field(serialization_alias="manualKey", repr=False)


class TotpReplacementOperation(Protocol):
    def prepare(self, **kwargs) -> PreparedTotpReplacement | str: ...


def get_totp_replacement_operation() -> Iterator[TotpReplacementOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresTotpReplacementOperation(engine)
    finally:
        engine.dispose()


class _PostgresTotpReplacementOperation:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def prepare(self, **kwargs) -> PreparedTotpReplacement | str:
        dispatches: list[SecurityNotificationDispatch] = []
        with self._engine.begin() as connection:
            operation = _compose(connection, dispatches=dispatches)
            outcome = operation.prepare(**kwargs)
        deliver_security_notices(
            engine=self._engine,
            email_sender=EmailSimulator(outcome="accepted"),
            notices=dispatches,
        )
        return outcome


def _compose(
    connection: Connection,
    *,
    dispatches: list[SecurityNotificationDispatch] | None = None,
) -> PrepareAdministrativeTotpReplacement:
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
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(
            key_ring=key_ring, secret_generator=entropy
        ),
    )
    return PrepareAdministrativeTotpReplacement(
        store=PostgresTotpReplacementStore(connection),
        credential_guard=EnsureAdministrativeCredentialCheck(
            store=account_security, clock=clock
        ),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(
                store=account_security, clock=clock
            ),
            audit=audit,
            notifications=notifications,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection, email_protector
            ),
            dispatches=dispatches,
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(key_ring=key_ring, secret_generator=entropy),
        pending_factor_protector=PendingTotpProtector(key_ring=key_ring, secret_generator=entropy),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=key_ring),
        ),
        audit=audit,
        clock=clock,
    )


@router.post("/prepare", response_model=TotpReplacementPreparationResponse)
def prepare_administrative_totp_replacement(
    body: TotpReplacementPreparationBody,
    response: Response,
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    protection: Annotated[None, Depends(require_administrative_mutation_protection, scope="function")],
    operation: Annotated[TotpReplacementOperation, Depends(get_totp_replacement_operation, scope="function")],
) -> TotpReplacementPreparationResponse | JSONResponse:
    del protection
    response.headers.update(_SECURITY_HEADERS)
    outcome = operation.prepare(
        account_id=actor.account_id,
        current_password=body.current_password,
        totp_code=body.totp_code,
        recovery_code=body.recovery_code,
    )
    if outcome == "invalid_credentials":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": _CREDENTIAL_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    if not isinstance(outcome, PreparedTotpReplacement):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": _UNAVAILABLE_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    return TotpReplacementPreparationResponse(
        provisioning_uri=outcome.provisioning_uri,
        manual_key=outcome.manual_key,
    )

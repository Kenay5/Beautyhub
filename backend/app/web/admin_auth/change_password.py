"""Authenticated administrative password-change HTTP contract."""

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
from backend.app.application.admin_access.change_password import ChangeAdministrativePassword
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import EmailSimulator, EmailSimulatorUncertainOutcome
from backend.app.infrastructure.persistence.admin_account_security_repository import PostgresAdministrativeAccountSecurityStore
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import PostgresAdministrativeLockRecipientDirectory
from backend.app.infrastructure.persistence.admin_password_change_repository import PostgresAdministrativePasswordChangeStore
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordList
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration, load_settings
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import require_administrative_mutation_protection
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices


router = APIRouter(prefix="/api/admin/password", tags=["admin-password"])
_PASSWORD_NOTICE = "La contraseña de tu cuenta administrativa fue cambiada."
_LOGGER = logging.getLogger(__name__)


class PasswordChangeBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(
        alias="currentPassword", min_length=1, max_length=128, repr=False
    )
    totp_code: str = Field(alias="totpCode", min_length=1, max_length=32, repr=False)
    new_password: str = Field(
        alias="newPassword", min_length=1, max_length=128, repr=False
    )


class PasswordChangeOperation(Protocol):
    def change(
        self,
        *,
        account_id: int,
        current_password: str,
        totp_code: str,
        new_password: str,
    ) -> str: ...


def get_password_change_operation() -> Iterator[PasswordChangeOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresPasswordChangeOperation(engine)
    finally:
        engine.dispose()


class _PostgresPasswordChangeOperation:
    """Commit the credential change before attempting its security email."""

    def __init__(
        self, engine: Engine, email_sender: TransactionalNotificationPort | None = None
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")

    def change(
        self,
        *,
        account_id: int,
        current_password: str,
        totp_code: str,
        new_password: str,
    ) -> str:
        dispatches: list[SecurityNotificationDispatch] = []
        with self._engine.begin() as connection:
            outcome = _compose_change_password(
                connection, dispatches=dispatches
            ).change(
                account_id=account_id,
                current_password=current_password,
                totp_code=totp_code,
                new_password=new_password,
            )
        deliver_security_notices(
            engine=self._engine,
            email_sender=self._email_sender,
            notices=dispatches,
        )
        if outcome.status == "changed":
            assert outcome.notification_recipient is not None
            assert outcome.notification_delivery_id is not None
            self._deliver(
                recipient=outcome.notification_recipient,
                delivery_id=outcome.notification_delivery_id,
            )
        return outcome.status

    def _deliver(self, *, recipient: str, delivery_id: int) -> None:
        try:
            sent = self._email_sender.send(
                OutboundNotification(
                    channel=EMAIL_CHANNEL,
                    recipient=recipient,
                    content=_PASSWORD_NOTICE,
                )
            )
            outcome = sent.outcome
        except EmailSimulatorUncertainOutcome:
            outcome = "uncertain"
        except Exception:
            outcome = "failed"
        # A failed update leaves the durable pending intent for later reconciliation.
        try:
            with self._engine.begin() as connection:
                PostgresSecurityNotificationDeliveryStore(connection).record_immediate_result(
                    delivery_id=delivery_id, outcome=outcome
                )
        except Exception:
            _LOGGER.error("administrative password notice status was not recorded")


def _compose_change_password(
    connection: Connection,
    *,
    dispatches: list[SecurityNotificationDispatch] | None = None,
) -> ChangeAdministrativePassword:
    clock = SystemClock()
    entropy = SystemSecretGenerator()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    security_store = PostgresAdministrativeAccountSecurityStore(connection)
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
    return ChangeAdministrativePassword(
        store=PostgresAdministrativePasswordChangeStore(connection, email_protector),
        credential_guard=EnsureAdministrativeCredentialCheck(
            store=security_store, clock=clock
        ),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(
                store=security_store, clock=clock
            ),
            audit=audit,
            notifications=notifications,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection, email_protector=email_protector
            ),
            dispatches=dispatches,
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=key_ring, secret_generator=entropy
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        blocked_passwords=BlockedPasswordList.load(clock=clock),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection),
            clock=clock,
        ),
        audit=audit,
        notifications=notifications,
        clock=clock,
    )


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def change_administrative_password(
    body: PasswordChangeBody,
    response: Response,
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    protection: Annotated[None, Depends(require_administrative_mutation_protection, scope="function")],
    operation: Annotated[PasswordChangeOperation, Depends(get_password_change_operation, scope="function")],
) -> Response:
    del protection
    result = operation.change(
        account_id=actor.account_id,
        current_password=body.current_password,
        totp_code=body.totp_code,
        new_password=body.new_password,
    )
    if result == "invalid_credentials":
        return JSONResponse(status_code=400, content={"detail": "No fue posible comprobar las credenciales."})
    if result == "invalid_password":
        return JSONResponse(status_code=422, content={"detail": "La nueva contraseña no es válida."})
    if result != "changed":
        return JSONResponse(status_code=409, content={"detail": "No fue posible cambiar la contraseña."})
    response.delete_cookie(
        key=ADMINISTRATIVE_SESSION_COOKIE,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response

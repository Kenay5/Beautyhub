"""Public, one-use password-recovery completion contract."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.password_recovery_completion import CompleteAdministrativePasswordRecovery
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, OutboundNotification, TransactionalNotificationPort
from backend.app.infrastructure.email_simulator import EmailSimulator, EmailSimulatorUncertainOutcome
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.admin_password_recovery_completion_repository import PostgresPasswordRecoveryCompletionStore
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordList
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration, load_settings
from backend.app.web.admin_auth.security_link_transport import SecurityLinkTokenBody


router = APIRouter(prefix="/api/admin/password-recovery", tags=["admin-password-recovery"])
_PASSWORD_NOTICE = "La contraseña de tu cuenta administrativa fue restablecida."
_GENERIC_LINK_MESSAGE = "No fue posible completar la recuperación. Verifica la contraseña y que el enlace siga vigente."
_LOGGER = logging.getLogger(__name__)


class PasswordRecoveryCompletionBody(SecurityLinkTokenBody):
    model_config = ConfigDict(populate_by_name=True)
    new_password: str = Field(alias="newPassword", min_length=1, max_length=128, repr=False)


class PasswordRecoveryCompletionOperation(Protocol):
    def complete(self, *, token: bytes, new_password: str) -> str: ...


def get_password_recovery_completion_operation() -> Iterator[PasswordRecoveryCompletionOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresPasswordRecoveryCompletionOperation(engine)
    finally:
        engine.dispose()


class _PostgresPasswordRecoveryCompletionOperation:
    def __init__(self, engine: Engine, email_sender: TransactionalNotificationPort | None = None) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")

    def complete(self, *, token: bytes, new_password: str) -> str:
        with self._engine.begin() as connection:
            outcome = _compose_completion(connection).complete(token=token, new_password=new_password)
        if outcome.status == "completed":
            assert outcome.notification_delivery_id is not None
            assert outcome.notification_recipient is not None
            self._deliver(delivery_id=outcome.notification_delivery_id, recipient=outcome.notification_recipient)
        return outcome.status

    def _deliver(self, *, delivery_id: int, recipient: str) -> None:
        try:
            sent = self._email_sender.send(
                OutboundNotification(channel=EMAIL_CHANNEL, recipient=recipient, content=_PASSWORD_NOTICE)
            )
            result = sent.outcome
        except EmailSimulatorUncertainOutcome:
            result = "uncertain"
        except Exception:
            result = "failed"
        try:
            with self._engine.begin() as connection:
                PostgresSecurityNotificationDeliveryStore(connection).record_immediate_result(
                    delivery_id=delivery_id, outcome=result
                )
        except Exception:
            _LOGGER.error("administrative recovery notice status was not recorded")


def _compose_completion(connection: Connection) -> CompleteAdministrativePasswordRecovery:
    clock = SystemClock()
    entropy = SystemSecretGenerator()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    email_protector = AdministrativeEmailProtector(key_ring=key_ring, secret_generator=entropy)
    link_protector = SecurityLinkProtector(key_ring=key_ring)
    return CompleteAdministrativePasswordRecovery(
        store=PostgresPasswordRecoveryCompletionStore(
            connection,
            email_protector=email_protector,
            link_protector=link_protector,
            current_time=clock.now(),
        ),
        links=SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=clock,
            secret_generator=entropy,
            protector=link_protector,
        ),
        password_hasher=AdministrativePasswordHasher(),
        blocked_passwords=BlockedPasswordList.load(clock=clock),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection), clock=clock
        ),
        audit=RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection), clock=clock
        ),
        notifications=RecordSecurityNotificationDelivery(
            store=PostgresSecurityNotificationDeliveryStore(connection),
            protector=SecurityNotificationDeliveryProtector(key_ring=key_ring, secret_generator=entropy),
        ),
        clock=clock,
    )


def get_password_recovery_completion_operations() -> Iterator[PasswordRecoveryCompletionOperation]:
    yield from get_password_recovery_completion_operation()


@router.post("/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_administrative_password_recovery(
    body: PasswordRecoveryCompletionBody,
    operation: Annotated[PasswordRecoveryCompletionOperation, Depends(get_password_recovery_completion_operations, scope="function")],
):
    result = operation.complete(token=body.decoded_token(), new_password=body.new_password)
    if result == "invalid_password":
        return JSONResponse(status_code=422, content={"detail": "La contraseña no cumple los requisitos de seguridad."})
    if result != "completed":
        return JSONResponse(status_code=400, content={"detail": _GENERIC_LINK_MESSAGE})
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Public one-use confirmation of a reserved administrative email."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.confirm_own_email_change import (
    ConfirmOwnAdministrativeEmailChange,
    EmailChangeConfirmationOutcome,
    EmailChangeConsumptionConflict,
)
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.clock import Clock, SystemClock
from backend.app.application.entropy import SecretGenerator, SystemSecretGenerator
from backend.app.application.transactional_notifications import EMAIL_CHANNEL, OutboundNotification, TransactionalNotificationPort
from backend.app.infrastructure.email_simulator import EmailSimulator, EmailSimulatorUncertainOutcome
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.own_email_change_confirmation_repository import PostgresOwnEmailChangeConfirmationStore
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration, load_settings
from backend.app.web.admin_auth.security_link_transport import SecurityLinkTokenBody


router = APIRouter(prefix="/api/admin/account/email-change", tags=["admin-email-change"])
_SECURITY_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_UNAVAILABLE_DETAIL = "No fue posible confirmar el cambio de correo. Verifica que el enlace siga vigente."
_OLD_NOTICE = "El correo de tu cuenta administrativa fue cambiado."
_NEW_NOTICE = "Este correo quedó registrado en tu cuenta administrativa."
_LOGGER = logging.getLogger(__name__)


class OwnEmailChangeConfirmationOperation(Protocol):
    def confirm(self, *, token: bytes) -> str: ...


def get_own_email_change_confirmation_operation() -> Iterator[OwnEmailChangeConfirmationOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresOwnEmailChangeConfirmationOperation(engine)
    finally:
        engine.dispose()


class _PostgresOwnEmailChangeConfirmationOperation:
    def __init__(
        self,
        engine: Engine,
        *,
        email_sender: TransactionalNotificationPort | None = None,
        clock: Clock | None = None,
        entropy: SecretGenerator | None = None,
        key_ring: CryptographyKeyRing | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")
        self._clock = clock or SystemClock()
        self._entropy = entropy or SystemSecretGenerator()
        self._key_ring = key_ring or CryptographyKeyRing(load_cryptography_key_configuration())

    def confirm(self, *, token: bytes) -> str:
        try:
            with self._engine.begin() as connection:
                outcome = _compose_confirmation(
                    connection,
                    clock=self._clock,
                    entropy=self._entropy,
                    key_ring=self._key_ring,
                ).confirm(token=token)
        except EmailChangeConsumptionConflict:
            return "unavailable"
        if outcome.status == "completed":
            for index, (delivery_id, recipient) in enumerate(outcome.notices):
                self._deliver(
                    delivery_id=delivery_id,
                    recipient=recipient,
                    content=_OLD_NOTICE if index == 0 else _NEW_NOTICE,
                )
        return outcome.status

    def _deliver(self, *, delivery_id: int, recipient: str, content: str) -> None:
        try:
            sent = self._email_sender.send(
                OutboundNotification(channel=EMAIL_CHANNEL, recipient=recipient, content=content)
            )
            result = sent.outcome if sent.channel == EMAIL_CHANNEL else "failed"
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
            _LOGGER.error("administrative email change notice status was not recorded")


def _compose_confirmation(
    connection: Connection,
    *,
    clock: Clock,
    entropy: SecretGenerator,
    key_ring: CryptographyKeyRing,
) -> ConfirmOwnAdministrativeEmailChange:
    email_protector = AdministrativeEmailProtector(key_ring=key_ring, secret_generator=entropy)
    return ConfirmOwnAdministrativeEmailChange(
        store=PostgresOwnEmailChangeConfirmationStore(connection, email_protector),
        links=SecurityLinkLifecycle(
            store=PostgresSecurityLinkStore(connection),
            clock=clock,
            secret_generator=entropy,
            protector=SecurityLinkProtector(key_ring=key_ring),
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection), clock=clock
        ),
        audit=RecordAdministrativeAuditEvent(
            store=PostgresAdministrativeAuditStore(connection), clock=clock
        ),
        notifications=RecordSecurityNotificationDelivery(
            store=PostgresSecurityNotificationDeliveryStore(connection),
            protector=SecurityNotificationDeliveryProtector(
                key_ring=key_ring, secret_generator=entropy
            ),
        ),
        clock=clock,
    )


@router.post("/complete", status_code=status.HTTP_204_NO_CONTENT)
def confirm_own_administrative_email_change(
    body: SecurityLinkTokenBody,
    operation: Annotated[
        OwnEmailChangeConfirmationOperation,
        Depends(get_own_email_change_confirmation_operation, scope="function"),
    ],
) -> Response:
    if operation.confirm(token=body.decoded_token()) != "completed":
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": _UNAVAILABLE_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_SECURITY_HEADERS)

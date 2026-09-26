"""Public, account-enumeration-safe password-recovery request contract."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.password_recovery_request import (
    PrepareAdministrativePasswordRecovery,
    RequestAdministrativePasswordRecovery,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_password_recovery_request_repository import (
    PostgresAdministrativeRecoveryAccountStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.web.admin_auth.security_link_transport import security_link_fragment


router = APIRouter(prefix="/api/admin/password-recovery", tags=["admin-password-recovery"])
_GENERIC_MESSAGE = "Si existe una cuenta activa con ese correo, recibirás instrucciones para recuperar tu contraseña."


class PasswordRecoveryRequestBody(BaseModel):
    email: str = Field(min_length=1, max_length=254, repr=False)


class PasswordRecoveryRequestResponse(BaseModel):
    message: str


class PasswordRecoveryOperations(Protocol):
    def request(self, *, email: str) -> bool | None: ...


class PostgresPasswordRecoveryOperations:
    """Issue links transactionally and send them outside the database transaction."""

    def __init__(
        self,
        *,
        engine: Engine,
        email_sender: TransactionalNotificationPort | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")
        self._clock = SystemClock()
        self._key_ring = CryptographyKeyRing(load_cryptography_key_configuration())

    def request(self, *, email: str) -> bool | None:
        email_protector = AdministrativeEmailProtector(
            key_ring=self._key_ring,
            secret_generator=SystemSecretGenerator(),
        )
        with self._engine.begin() as connection:
            store = PostgresAdministrativeRecoveryAccountStore(
                connection,
                email_protector=email_protector,
            )
            prepared = PrepareAdministrativePasswordRecovery(
                requester=RequestAdministrativePasswordRecovery(
                    store=store,
                    email_lookup=email_protector,
                ),
                store=store,
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=self._clock,
                    secret_generator=SystemSecretGenerator(),
                    protector=SecurityLinkProtector(key_ring=self._key_ring),
                ),
            ).prepare(email=email)
        if prepared is None:
            return None

        content = (
            "Para recuperar tu contraseña, abre este enlace dentro de los próximos "
            "30 minutos: /admin/password-recovery"
            + security_link_fragment(prepared.issued_link.token)
        )
        try:
            result = self._email_sender.send(
                OutboundNotification(
                    channel=EMAIL_CHANNEL,
                    recipient=prepared.recipient.email,
                    content=content,
                )
            )
        except Exception:
            result = NotificationSendResult.failed(EMAIL_CHANNEL)

        accepted = result.channel == EMAIL_CHANNEL and result.outcome == "accepted"
        current_time = self._clock.now()
        with self._engine.begin() as connection:
            links = PostgresSecurityLinkStore(connection)
            link_id = prepared.issued_link.stored_link.link_id
            if accepted:
                links.mark_delivery_accepted(
                    link_id=link_id,
                    current_time=current_time,
                )
            else:
                links.invalidate_failed_delivery(
                    link_id=link_id,
                    current_time=current_time,
                )
                RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection),
                    clock=self._clock,
                ).record(
                    actor_account_id=None,
                    action="password_recovery",
                    result="failed",
                )
        return accepted


def get_password_recovery_operations() -> Iterator[PasswordRecoveryOperations]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield PostgresPasswordRecoveryOperations(engine=engine)
    finally:
        engine.dispose()


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=PasswordRecoveryRequestResponse)
def request_administrative_password_recovery(
    body: PasswordRecoveryRequestBody,
    operations: Annotated[
        PasswordRecoveryOperations,
        Depends(get_password_recovery_operations, scope="function"),
    ],
) -> PasswordRecoveryRequestResponse:
    """Never distinguish missing accounts or failed recovery-link delivery."""

    operations.request(email=body.email)
    return PasswordRecoveryRequestResponse(message=_GENERIC_MESSAGE)

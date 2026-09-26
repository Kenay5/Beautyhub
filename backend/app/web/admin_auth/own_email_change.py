"""Authenticated request API for reserving an administrator's replacement email."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.request_own_email_change import (
    RequestOwnAdministrativeEmailChange,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import Clock, SystemClock
from backend.app.application.entropy import SecretGenerator, SystemSecretGenerator
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    NotificationSendResult,
    OutboundNotification,
    TransactionalNotificationPort,
)
from backend.app.domain.authentication.admin_email_claim import (
    normalize_administrative_email_address,
)
from backend.app.infrastructure.email_simulator import EmailSimulator
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
from backend.app.infrastructure.persistence.own_email_change_repository import (
    PostgresOwnEmailChangeStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
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
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
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
from backend.app.web.admin_auth.security_link_transport import security_link_fragment


router = APIRouter(prefix="/api/admin/account/email-change", tags=["admin-email-change"])
_CREDENTIAL_DETAIL = "No fue posible comprobar las credenciales."
_UNAVAILABLE_DETAIL = "No fue posible reservar el correo solicitado."
_SECURITY_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_LOGGER = logging.getLogger(__name__)


class OwnEmailChangeRequestBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    new_email: str = Field(alias="newEmail", min_length=1, max_length=254, repr=False)
    current_password: str = Field(
        alias="currentPassword", min_length=1, max_length=128, repr=False
    )
    totp_code: str = Field(alias="totpCode", min_length=1, max_length=32, repr=False)


class OwnEmailChangeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    delivery_status: Literal["accepted", "failed"] = Field(
        serialization_alias="deliveryStatus"
    )
    detail: str


class OwnEmailChangeOperation(Protocol):
    def request(self, **kwargs) -> str: ...


def get_own_email_change_operation() -> Iterator[OwnEmailChangeOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresOwnEmailChangeOperation(engine=engine)
    finally:
        engine.dispose()


class _PostgresOwnEmailChangeOperation:
    def __init__(
        self,
        *,
        engine: Engine,
        email_sender: TransactionalNotificationPort | None = None,
        clock: Clock | None = None,
        entropy: SecretGenerator | None = None,
        key_ring: CryptographyKeyRing | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")
        self._clock = clock or SystemClock()
        self._entropy = entropy or SystemSecretGenerator()
        self._key_ring = key_ring or CryptographyKeyRing(
            load_cryptography_key_configuration()
        )

    def request(self, **kwargs) -> str:
        entropy = self._entropy
        email_protector = AdministrativeEmailProtector(
            key_ring=self._key_ring, secret_generator=entropy
        )
        account_id = kwargs["account_id"]
        new_email = kwargs["new_email"]
        with self._engine.begin() as connection:
            outcome = _compose(
                connection,
                email_protector=email_protector,
                entropy=entropy,
                key_ring=self._key_ring,
                clock=self._clock,
            ).request(**kwargs)
            if outcome != "reserved":
                return outcome
            issued_link = SecurityLinkLifecycle(
                store=PostgresSecurityLinkStore(connection),
                clock=self._clock,
                secret_generator=entropy,
                protector=SecurityLinkProtector(key_ring=self._key_ring),
            ).issue(account_id=account_id, purpose="email_change")

        content = (
            "Para confirmar el cambio de correo, abre este enlace dentro de los "
            "próximos 30 minutos: /admin/email-change"
            + security_link_fragment(issued_link.token)
        )
        try:
            sent = self._email_sender.send(
                OutboundNotification(
                    channel=EMAIL_CHANNEL,
                    recipient=normalize_administrative_email_address(new_email),
                    content=content,
                )
            )
            accepted = sent.channel == EMAIL_CHANNEL and sent.outcome == "accepted"
        except Exception:
            _LOGGER.warning("administrative email-change link delivery failed")
            accepted = False

        now = self._clock.now()
        with self._engine.begin() as connection:
            link_store = PostgresSecurityLinkStore(connection)
            link_id = issued_link.stored_link.link_id
            if accepted:
                link_store.mark_delivery_accepted(link_id=link_id, current_time=now)
            else:
                released = PostgresOwnEmailChangeStore(connection).invalidate_failed_delivery(
                    account_id=account_id,
                    link_id=link_id,
                    current_time=now,
                )
                if released:
                    RecordAdministrativeAuditEvent(
                        store=PostgresAdministrativeAuditStore(connection),
                        clock=self._clock,
                    ).record(
                        actor_account_id=account_id,
                        action="email_change",
                        result="failed",
                    )
        return "reserved" if accepted else "delivery_failed"


def _compose(
    connection: Connection,
    *,
    email_protector: AdministrativeEmailProtector | None = None,
    entropy: SecretGenerator | None = None,
    key_ring: CryptographyKeyRing | None = None,
    clock: Clock | None = None,
) -> RequestOwnAdministrativeEmailChange:
    clock = clock or SystemClock()
    entropy = entropy or SystemSecretGenerator()
    key_ring = key_ring or CryptographyKeyRing(load_cryptography_key_configuration())
    security_store = PostgresAdministrativeAccountSecurityStore(connection)
    email_protector = email_protector or AdministrativeEmailProtector(
        key_ring=key_ring, secret_generator=entropy
    )
    audit = RecordAdministrativeAuditEvent(
        store=PostgresAdministrativeAuditStore(connection), clock=clock
    )
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(
            key_ring=key_ring, secret_generator=entropy
        ),
    )
    return RequestOwnAdministrativeEmailChange(
        store=PostgresOwnEmailChangeStore(connection),
        email_protector=email_protector,
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
        ),
        password_hasher=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=key_ring, secret_generator=entropy
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        audit=audit,
        clock=clock,
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=OwnEmailChangeResponse,
)
def request_own_administrative_email_change(
    body: OwnEmailChangeRequestBody,
    response: Response,
    protection: Annotated[None, Depends(require_administrative_mutation_protection, scope="function")],
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operation: Annotated[OwnEmailChangeOperation, Depends(get_own_email_change_operation, scope="function")],
) -> OwnEmailChangeResponse:
    del protection
    response.headers.update(_SECURITY_HEADERS)
    outcome = operation.request(
        account_id=actor.account_id,
        new_email=body.new_email,
        current_password=body.current_password,
        totp_code=body.totp_code,
    )
    if outcome == "invalid_credentials":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": _CREDENTIAL_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    if outcome == "invalid_email":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "El correo no tiene un formato válido."},
            headers=_SECURITY_HEADERS,
        )
    if outcome == "unavailable":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": _UNAVAILABLE_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    if outcome == "delivery_failed":
        response.status_code = status.HTTP_202_ACCEPTED
        return OwnEmailChangeResponse(
            delivery_status="failed",
            detail="No se pudo enviar el enlace. Tu correo actual sigue activo. Inténtalo de nuevo.",
        )
    if outcome != "reserved":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": _UNAVAILABLE_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    response.status_code = status.HTTP_202_ACCEPTED
    return OwnEmailChangeResponse(
        delivery_status="accepted",
        detail="Revisa el correo nuevo para confirmar. El actual sigue activo.",
    )

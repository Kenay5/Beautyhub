"""Enumeration-safe public request contract for lost-factor replacement."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from backend.app.application.admin_access.account_security import (
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
    SecurityNotificationDispatch,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.lost_factor_replacement_request import (
    RequestAdministrativeLostFactorReplacement,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.security_link_delivery import send_security_link_notification
from backend.app.application.transactional_notifications import (
    EMAIL_CHANNEL,
    OutboundNotification,
    TransactionalNotificationPort,
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
from backend.app.infrastructure.persistence.lost_factor_replacement_request_repository import (
    PostgresLostFactorReplacementRequestStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.persistence.security_message_rate_limit_repository import (
    PostgresPublicSecurityMessageBudget,
    PostgresSecurityMessageActionBudget,
)
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.public_request_subject import (
    PublicRequestSubjectProtector,
)
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
    load_trusted_proxy_networks,
)
from backend.app.web.admin_auth.security_link_transport import security_link_fragment
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices
from backend.app.web.public_request_protection import resolve_public_client_ip


router = APIRouter(prefix="/api/admin/totp-replacement", tags=["admin-totp-replacement"])
_GENERIC_MESSAGE = "Si la cuenta puede iniciar el reemplazo del segundo factor, recibirás instrucciones en el correo registrado."
_RATE_LIMIT_DETAIL = "Demasiadas solicitudes. Inténtalo más tarde."
_LINK_PAGE = "/admin/totp-replacement"


class LostFactorReplacementRequestBody(BaseModel):
    email: str = Field(min_length=1, max_length=254, repr=False)
    password: str = Field(min_length=1, max_length=128, repr=False)


class LostFactorReplacementRequestResponse(BaseModel):
    message: str


class LostFactorReplacementRequestOperations(Protocol):
    def request(
        self, *, email: str, password: str, subject_fingerprint: bytes
    ) -> bool | None | Literal["rate_limited"]: ...


class PostgresLostFactorReplacementRequestOperations:
    """Issue and send a link without exposing eligibility to the caller."""

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
        self._entropy = SystemSecretGenerator()

    def request(
        self, *, email: str, password: str, subject_fingerprint: bytes
    ) -> bool | None | Literal["rate_limited"]:
        dispatches: list[SecurityNotificationDispatch] = []
        try:
            with self._engine.begin() as connection:
                email_protector = AdministrativeEmailProtector(
                    key_ring=self._key_ring,
                    secret_generator=self._entropy,
                )
                account_security = PostgresAdministrativeAccountSecurityStore(connection)
                audit = RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection),
                    clock=self._clock,
                )
                lock_recipients = PostgresAdministrativeLockRecipientDirectory(
                    connection=connection,
                    email_protector=email_protector,
                )
                failures = RecordProtectedAdministrativeCredentialFailure(
                    failure_recorder=RecordAdministrativeCredentialFailure(
                        store=account_security,
                        clock=self._clock,
                    ),
                    audit=audit,
                    notifications=RecordSecurityNotificationDelivery(
                        store=PostgresSecurityNotificationDeliveryStore(connection),
                        protector=SecurityNotificationDeliveryProtector(
                            key_ring=self._key_ring,
                            secret_generator=self._entropy,
                        ),
                    ),
                    recipients=lock_recipients,
                    dispatches=dispatches,
                )
                now = self._clock.now()
                store = PostgresLostFactorReplacementRequestStore(
                    connection,
                    email_protector=email_protector,
                    current_time=now,
                )
                prepared = RequestAdministrativeLostFactorReplacement(
                    store=store,
                    email_lookup=email_protector,
                    password_verifier=AdministrativePasswordHasher(),
                    failure_recorder=failures,
                    links=SecurityLinkLifecycle(
                        store=PostgresSecurityLinkStore(connection),
                        clock=self._clock,
                        secret_generator=self._entropy,
                        protector=SecurityLinkProtector(key_ring=self._key_ring),
                    ),
                    audit=audit,
                    security_message_budget=PostgresSecurityMessageActionBudget(
                        connection=connection,
                        subject_protector=AdministrativeRateLimitSubjectProtector(
                            key_ring=self._key_ring
                        ),
                        clock=self._clock,
                        secret_generator=self._entropy,
                    ),
                    public_security_message_budget=PostgresPublicSecurityMessageBudget(
                        connection=connection,
                        public_subject_fingerprint=subject_fingerprint,
                        subject_protector=AdministrativeRateLimitSubjectProtector(
                            key_ring=self._key_ring
                        ),
                        clock=self._clock,
                        secret_generator=self._entropy,
                    ),
                ).prepare(email=email, password=password)
        except PublicRequestRateLimitError:
            return "rate_limited"

        deliver_security_notices(
            engine=self._engine,
            email_sender=self._email_sender,
            notices=dispatches,
        )

        if prepared is None:
            return None

        content = (
            "Para reemplazar tu segundo factor, abre este enlace dentro de los próximos "
            "30 minutos: " + _LINK_PAGE + security_link_fragment(prepared.issued_link.token)
        )
        result = send_security_link_notification(
            sender=self._email_sender,
            notification=OutboundNotification(
                channel=EMAIL_CHANNEL,
                recipient=prepared.recipient_email,
                content=content,
                idempotency_key=(
                    f"security-link:{prepared.issued_link.stored_link.link_id}"
                ),
            )
        )

        accepted = result.channel == EMAIL_CHANNEL and result.outcome == "accepted"
        with self._engine.begin() as connection:
            links = PostgresSecurityLinkStore(connection)
            link_id = prepared.issued_link.stored_link.link_id
            if accepted:
                links.mark_delivery_accepted(link_id=link_id, current_time=self._clock.now())
            elif result.outcome == "uncertain":
                links.mark_delivery_uncertain(link_id=link_id, current_time=self._clock.now())
            else:
                links.invalidate_failed_delivery(link_id=link_id, current_time=self._clock.now())
                RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection),
                    clock=self._clock,
                ).record(actor_account_id=None, action="totp_replacement", result="failed")
        return accepted


def get_lost_factor_replacement_request_operations(
) -> Iterator[LostFactorReplacementRequestOperations]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield PostgresLostFactorReplacementRequestOperations(engine=engine)
    finally:
        engine.dispose()


@router.post(
    "/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LostFactorReplacementRequestResponse,
)
def request_lost_factor_replacement(
    body: LostFactorReplacementRequestBody,
    request: Request,
    operations: Annotated[
        LostFactorReplacementRequestOperations,
        Depends(get_lost_factor_replacement_request_operations, scope="function"),
    ],
) -> LostFactorReplacementRequestResponse | JSONResponse:
    direct_host = request.client.host if request.client is not None else ""
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = resolve_public_client_ip(
        direct_host=direct_host,
        forwarded_for=forwarded_for,
        trusted_proxy_networks=load_trusted_proxy_networks(),
    )
    subject = PublicRequestSubjectProtector(
        key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
    ).fingerprint_ip(client_ip)
    result = operations.request(
        email=body.email,
        password=body.password,
        subject_fingerprint=subject,
    )
    if result == "rate_limited":
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": _RATE_LIMIT_DETAIL},
        )
    return LostFactorReplacementRequestResponse(message=_GENERIC_MESSAGE)

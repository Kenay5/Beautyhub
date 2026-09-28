"""Authenticated HTTP contract for confirming a TOTP replacement."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status
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
from backend.app.application.admin_access.confirm_totp_replacement import (
    ConfirmAdministrativeTotpReplacement,
    LostFactorLinkConsumptionConflict,
    TotpReplacementConfirmationOutcome,
)
from backend.app.application.admin_access.prepare_lost_factor_replacement import (
    PrepareLostFactorTotpReplacement,
    PreparedLostFactorTotpSetup,
)
from backend.app.application.admin_access.security_change_invalidation import InvalidateAfterSecurityChange
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
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
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_change_invalidation_repository import PostgresSecurityChangeInvalidationStore
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.totp_replacement_confirmation_repository import PostgresTotpReplacementConfirmationStore
from backend.app.infrastructure.persistence.totp_replacement_repository import PostgresTotpReplacementStore
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration, load_settings
from backend.app.web.admin_auth.owner_activation_setup import TotpSetupResponse
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE
from backend.app.web.admin_auth.mutation_protection import require_administrative_mutation_protection
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor
from backend.app.web.admin_auth.security_link_transport import SecurityLinkTokenBody
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices


router = APIRouter(prefix="/api/admin/totp-replacement", tags=["admin-totp-replacement"])
_SECURITY_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_CREDENTIAL_DETAIL = "No fue posible comprobar las credenciales."
_UNAVAILABLE_DETAIL = "No fue posible confirmar el reemplazo."
_NOTICE = "La configuración de verificación en dos pasos de tu cuenta administrativa fue reemplazada."
_GENERIC_LINK_DETAIL = "Este enlace o configuración no está disponible."
_LOGGER = logging.getLogger(__name__)


class TotpReplacementConfirmationBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totp_code: str = Field(alias="totpCode", min_length=1, max_length=32, repr=False)


class LostFactorTotpReplacementConfirmationBody(SecurityLinkTokenBody):
    model_config = ConfigDict(populate_by_name=True)

    totp_code: str = Field(
        alias="totpCode",
        min_length=6,
        max_length=6,
        pattern=r"^[0-9]{6}$",
        repr=False,
    )


class LostFactorTotpReplacementSetupResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totp_setup: TotpSetupResponse = Field(serialization_alias="totpSetup")


class TotpReplacementConfirmationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recovery_codes: tuple[str, ...] = Field(
        serialization_alias="recoveryCodes", min_length=10, max_length=10, repr=False
    )


class TotpReplacementConfirmationOperation(Protocol):
    def confirm(self, *, account_id: int, totp_code: str) -> TotpReplacementConfirmationOutcome: ...
    def prepare_lost_factor(self, *, token: bytes) -> PreparedLostFactorTotpSetup: ...
    def confirm_lost_factor(self, *, token: bytes, totp_code: str) -> TotpReplacementConfirmationOutcome: ...


def get_totp_replacement_confirmation_operation() -> Iterator[TotpReplacementConfirmationOperation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresTotpReplacementConfirmationOperation(engine)
    finally:
        engine.dispose()


class _PostgresTotpReplacementConfirmationOperation:
    def __init__(self, engine: Engine, email_sender: TransactionalNotificationPort | None = None):
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")

    def confirm(self, *, account_id: int, totp_code: str) -> TotpReplacementConfirmationOutcome:
        dispatches: list[SecurityNotificationDispatch] = []
        with self._engine.begin() as connection:
            outcome = _compose(
                connection, dispatches=dispatches
            ).confirm(account_id=account_id, totp_code=totp_code)
        deliver_security_notices(
            engine=self._engine,
            email_sender=self._email_sender,
            notices=dispatches,
        )
        if outcome.status == "replaced":
            assert outcome.notification_delivery_id is not None
            assert outcome.notification_recipient is not None
            self._deliver(outcome.notification_delivery_id, outcome.notification_recipient)
        return outcome

    def prepare_lost_factor(self, *, token: bytes) -> PreparedLostFactorTotpSetup:
        with self._engine.begin() as connection:
            clock = SystemClock()
            entropy = SystemSecretGenerator()
            key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
            return PrepareLostFactorTotpReplacement(
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=clock,
                    secret_generator=entropy,
                    protector=SecurityLinkProtector(key_ring=key_ring),
                ),
                setup_store=PostgresTotpReplacementStore(connection),
                pending_protector=PendingTotpProtector(
                    key_ring=key_ring,
                    secret_generator=entropy,
                ),
                totp=TotpAuthenticator(secret_generator=entropy),
                clock=clock,
            ).prepare(token=token)

    def confirm_lost_factor(
        self, *, token: bytes, totp_code: str
    ) -> TotpReplacementConfirmationOutcome:
        dispatches: list[SecurityNotificationDispatch] = []
        try:
            with self._engine.begin() as connection:
                clock = SystemClock()
                key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
                entropy = SystemSecretGenerator()
                links = SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=clock,
                    secret_generator=entropy,
                    protector=SecurityLinkProtector(key_ring=key_ring),
                )
                outcome = _compose(
                    connection, dispatches=dispatches
                ).confirm_lost_factor(
                    token=token,
                    link_lifecycle=links,
                    totp_code=totp_code,
                )
        except LostFactorLinkConsumptionConflict:
            outcome = TotpReplacementConfirmationOutcome("unavailable")
        deliver_security_notices(
            engine=self._engine,
            email_sender=self._email_sender,
            notices=dispatches,
        )
        if outcome.status == "replaced":
            assert outcome.notification_delivery_id is not None
            assert outcome.notification_recipient is not None
            self._deliver(outcome.notification_delivery_id, outcome.notification_recipient)
        return outcome

    def _deliver(self, delivery_id: int, recipient: str) -> None:
        try:
            sent = self._email_sender.send(
                OutboundNotification(channel=EMAIL_CHANNEL, recipient=recipient, content=_NOTICE)
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
            _LOGGER.error("administrative TOTP replacement notice status was not recorded")


def _compose(
    connection: Connection,
    *,
    dispatches: list[SecurityNotificationDispatch] | None = None,
) -> ConfirmAdministrativeTotpReplacement:
    clock = SystemClock()
    entropy = SystemSecretGenerator()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    account_security = PostgresAdministrativeAccountSecurityStore(connection)
    audit = RecordAdministrativeAuditEvent(
        store=PostgresAdministrativeAuditStore(connection), clock=clock
    )
    email_protector = AdministrativeEmailProtector(key_ring=key_ring, secret_generator=entropy)
    notifications = RecordSecurityNotificationDelivery(
        store=PostgresSecurityNotificationDeliveryStore(connection),
        protector=SecurityNotificationDeliveryProtector(key_ring=key_ring, secret_generator=entropy),
    )
    return ConfirmAdministrativeTotpReplacement(
        store=PostgresTotpReplacementConfirmationStore(connection, email_protector),
        credential_guard=EnsureAdministrativeCredentialCheck(store=account_security, clock=clock),
        failure_recorder=RecordProtectedAdministrativeCredentialFailure(
            failure_recorder=RecordAdministrativeCredentialFailure(store=account_security, clock=clock),
            audit=audit,
            notifications=notifications,
            recipients=PostgresAdministrativeLockRecipientDirectory(
                connection=connection,
                email_protector=email_protector,
            ),
            dispatches=dispatches,
        ),
        pending_factor_protector=PendingTotpProtector(key_ring=key_ring, secret_generator=entropy),
        factor_protector=TotpFactorProtector(key_ring=key_ring, secret_generator=entropy),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=key_ring),
        ),
        invalidator=InvalidateAfterSecurityChange(
            store=PostgresSecurityChangeInvalidationStore(connection), clock=clock
        ),
        audit=audit,
        notifications=notifications,
        clock=clock,
    )


@router.post("/confirm", response_model=TotpReplacementConfirmationResponse)
def confirm_administrative_totp_replacement(
    body: TotpReplacementConfirmationBody,
    response: Response,
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    protection: Annotated[None, Depends(require_administrative_mutation_protection, scope="function")],
    operation: Annotated[TotpReplacementConfirmationOperation, Depends(get_totp_replacement_confirmation_operation, scope="function")],
) -> TotpReplacementConfirmationResponse | JSONResponse:
    del protection
    response.headers.update(_SECURITY_HEADERS)
    outcome = operation.confirm(account_id=actor.account_id, totp_code=body.totp_code)
    if outcome.status == "invalid_credentials":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": _CREDENTIAL_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    if outcome.status != "replaced":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": _UNAVAILABLE_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    response.delete_cookie(
        key=ADMINISTRATIVE_SESSION_COOKIE,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.status_code = status.HTTP_200_OK
    return TotpReplacementConfirmationResponse(recovery_codes=outcome.recovery_codes)


@router.post(
    "/prepare-lost",
    response_model=LostFactorTotpReplacementSetupResponse,
    response_model_by_alias=True,
)
def prepare_lost_factor_totp_replacement(
    body: SecurityLinkTokenBody,
    response: Response,
    operation: Annotated[
        TotpReplacementConfirmationOperation,
        Depends(get_totp_replacement_confirmation_operation, scope="function"),
    ],
) -> LostFactorTotpReplacementSetupResponse:
    """Prepare only encrypted setup material; the previous factor remains active."""

    response.headers.update(_SECURITY_HEADERS)
    try:
        prepared = operation.prepare_lost_factor(token=body.decoded_token())
    except (ValueError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_GENERIC_LINK_DETAIL,
            headers=_SECURITY_HEADERS,
        ) from error
    return LostFactorTotpReplacementSetupResponse(
        totp_setup=TotpSetupResponse(
            provisioning_uri=prepared.provisioning_uri,
            manual_key=prepared.manual_key,
        )
    )


@router.post(
    "/complete-lost",
    response_model=TotpReplacementConfirmationResponse,
    response_model_by_alias=True,
)
def complete_lost_factor_totp_replacement(
    body: LostFactorTotpReplacementConfirmationBody,
    response: Response,
    operation: Annotated[
        TotpReplacementConfirmationOperation,
        Depends(get_totp_replacement_confirmation_operation, scope="function"),
    ],
) -> TotpReplacementConfirmationResponse | JSONResponse:
    """Replace the old factor only after atomic success, without opening a session."""

    response.headers.update(_SECURITY_HEADERS)
    outcome = operation.confirm_lost_factor(
        token=body.decoded_token(),
        totp_code=body.totp_code,
    )
    if outcome.status != "replaced":
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": _GENERIC_LINK_DETAIL},
            headers=_SECURITY_HEADERS,
        )
    return TotpReplacementConfirmationResponse(recovery_codes=outcome.recovery_codes)

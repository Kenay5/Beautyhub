"""Public HTTP contract for an invited staff member's own activation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.account_security import SecurityNotificationDispatch
from backend.app.application.admin_access.pending_security_state import DiscardPendingSecurityState
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.security_notification_deliveries import RecordSecurityNotificationDelivery
from backend.app.application.transactional_notifications import TransactionalNotificationPort
from backend.app.application.admin_access.staff_activation import (
    AbandonStaffActivationSetup,
    CompleteStaffActivation,
    PrepareStaffActivationSetup,
    StaffActivationError,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import PostgresAdministrativeLockRecipientDirectory
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.security_notification_delivery_repository import PostgresSecurityNotificationDeliveryStore
from backend.app.infrastructure.persistence.pending_security_state_repository import PostgresPendingSecurityStateStore
from backend.app.infrastructure.persistence.pending_totp_setup_repository import PostgresPendingTotpSetupStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.staff_activation_repository import PostgresStaffActivationStore
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordList
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.security_notification_delivery_protection import SecurityNotificationDeliveryProtector
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import load_cryptography_key_configuration, load_settings
from backend.app.web.admin_auth.owner_activation_setup import (
    CompleteOwnerActivationBody,
    OwnerActivationCompletionResponse,
    OwnerActivationSetupResponse,
    TotpSetupResponse,
)
from backend.app.web.admin_auth.security_link_transport import SecurityLinkTokenBody
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices


router = APIRouter(prefix="/api/admin/staff-security-links", tags=["admin-security-links"])
_GENERIC_DETAIL = "Este enlace no es válido o ya no está disponible."
_INVALID_PASSWORD_DETAIL = "La contraseña no cumple los requisitos de seguridad."
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _components():
    clock = SystemClock()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    return clock, key_ring


def _links(connection, clock, key_ring) -> SecurityLinkLifecycle:
    return SecurityLinkLifecycle(
        store=PostgresSecurityLinkStore(connection),
        clock=clock,
        secret_generator=SystemSecretGenerator(),
        protector=SecurityLinkProtector(key_ring=key_ring),
    )


def get_staff_activation_preparer() -> Iterator[PrepareStaffActivationSetup]:
    engine = create_postgres_engine(load_settings().database_url)
    clock, key_ring = _components()
    try:
        with engine.begin() as connection:
            yield PrepareStaffActivationSetup(
                link_lifecycle=_links(connection, clock, key_ring),
                setup_store=PostgresPendingTotpSetupStore(connection),
                totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),
                protector=PendingTotpProtector(key_ring=key_ring, secret_generator=SystemSecretGenerator()),
                clock=clock,
            )
    finally:
        engine.dispose()


def get_staff_activation_abandoner() -> Iterator[AbandonStaffActivationSetup]:
    engine = create_postgres_engine(load_settings().database_url)
    clock, key_ring = _components()
    try:
        with engine.begin() as connection:
            yield AbandonStaffActivationSetup(
                link_lifecycle=_links(connection, clock, key_ring),
                pending_state=DiscardPendingSecurityState(
                    store=PostgresPendingSecurityStateStore(connection),
                    clock=clock,
                ),
            )
    finally:
        engine.dispose()


def get_staff_activation_completer() -> Iterator[CompleteStaffActivation]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield _PostgresStaffActivationCompleter(engine=engine)
    finally:
        engine.dispose()


class _PostgresStaffActivationCompleter:
    """Commit staff activation and its owner notice before provider delivery."""

    def __init__(
        self,
        *,
        engine,
        email_sender: TransactionalNotificationPort | None = None,
    ) -> None:
        self._engine = engine
        self._email_sender = email_sender or EmailSimulator(outcome="accepted")

    def complete(self, *, token: bytes, password: str, totp_code: str):
        clock, key_ring = _components()
        entropy = SystemSecretGenerator()
        with self._engine.begin() as connection:
            outcome = CompleteStaffActivation(
                link_lifecycle=_links(connection, clock, key_ring),
                store=PostgresStaffActivationStore(connection),
                blocked_passwords=BlockedPasswordList.load(clock=clock),
                password_hasher=AdministrativePasswordHasher(),
                pending_totp_protector=PendingTotpProtector(
                    key_ring=key_ring, secret_generator=entropy
                ),
                factor_protector=TotpFactorProtector(
                    key_ring=key_ring, secret_generator=entropy
                ),
                totp=TotpAuthenticator(secret_generator=entropy),
                recovery_codes=RecoveryCodeService(
                    secret_generator=entropy,
                    protector=RecoveryCodeProtector(key_ring=key_ring),
                ),
                audit=RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection), clock=clock
                ),
                clock=clock,
            ).complete(token=token, password=password, totp_code=totp_code)
            if outcome.rejection is None and outcome.account_id is not None:
                email_protector = AdministrativeEmailProtector(
                    key_ring=key_ring, secret_generator=entropy
                )
                recipients = PostgresAdministrativeLockRecipientDirectory(
                    connection=connection, email_protector=email_protector
                ).lock_notification_recipients(account_id=outcome.account_id)
                owner_email = recipients[-1]
                intent = RecordSecurityNotificationDelivery(
                    store=PostgresSecurityNotificationDeliveryStore(connection),
                    protector=SecurityNotificationDeliveryProtector(
                        key_ring=key_ring, secret_generator=entropy
                    ),
                ).record(
                    event="staff_activated",
                    template="staff_activation_notice",
                    recipient=owner_email,
                    idempotency_reference=f"staff_activation:{outcome.account_id}",
                )
                outcome = replace(
                    outcome,
                    notification_delivery_id=intent.delivery_id,
                    notification_recipient=owner_email,
                )

        if outcome.notification_delivery_id is not None:
            deliver_security_notices(
                engine=self._engine,
                email_sender=self._email_sender,
                notices=(
                    SecurityNotificationDispatch(
                        delivery_id=outcome.notification_delivery_id,
                        event="staff_activated",
                        template="staff_activation_notice",
                        recipient=outcome.notification_recipient,
                    ),
                ),
            )
        return outcome


@router.post("/prepare", response_model=OwnerActivationSetupResponse)
def prepare_staff_activation(
    body: SecurityLinkTokenBody,
    response: Response,
    preparer: Annotated[PrepareStaffActivationSetup, Depends(get_staff_activation_preparer)],
) -> OwnerActivationSetupResponse:
    response.headers.update(_HEADERS)
    try:
        prepared = preparer.prepare(token=body.decoded_token())
    except (StaffActivationError, ValueError) as error:
        raise HTTPException(status_code=404, detail=_GENERIC_DETAIL, headers=_HEADERS) from error
    return OwnerActivationSetupResponse(
        totp_setup=TotpSetupResponse(
            provisioning_uri=prepared.provisioning_uri,
            manual_key=prepared.manual_key,
        )
    )


@router.post("/abandon", status_code=status.HTTP_204_NO_CONTENT)
def abandon_staff_activation(
    body: SecurityLinkTokenBody,
    response: Response,
    abandoner: Annotated[AbandonStaffActivationSetup, Depends(get_staff_activation_abandoner)],
) -> None:
    response.headers.update(_HEADERS)
    try:
        abandoner.abandon(token=body.decoded_token())
    except (StaffActivationError, ValueError) as error:
        raise HTTPException(status_code=404, detail=_GENERIC_DETAIL, headers=_HEADERS) from error


@router.post("/complete", response_model=OwnerActivationCompletionResponse)
def complete_staff_activation(
    body: CompleteOwnerActivationBody,
    response: Response,
    completer: Annotated[CompleteStaffActivation, Depends(get_staff_activation_completer, scope="function")],
) -> OwnerActivationCompletionResponse | JSONResponse:
    response.headers.update(_HEADERS)
    outcome = completer.complete(
        token=body.decoded_token(),
        password=body.password,
        totp_code=body.totp_code,
    )
    if outcome.rejection is not None:
        invalid_password = outcome.rejection == "invalid_password"
        return JSONResponse(
            status_code=422 if invalid_password else 404,
            content={"detail": _INVALID_PASSWORD_DETAIL if invalid_password else _GENERIC_DETAIL},
            headers=_HEADERS,
        )
    return OwnerActivationCompletionResponse(recovery_codes=outcome.recovery_codes)

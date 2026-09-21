"""Public HTTP contract for an invited staff member's own activation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.pending_security_state import DiscardPendingSecurityState
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.admin_access.staff_activation import (
    AbandonStaffActivationSetup,
    CompleteStaffActivation,
    PrepareStaffActivationSetup,
    StaffActivationError,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_audit_repository import PostgresAdministrativeAuditStore
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.pending_security_state_repository import PostgresPendingSecurityStateStore
from backend.app.infrastructure.persistence.pending_totp_setup_repository import PostgresPendingTotpSetupStore
from backend.app.infrastructure.persistence.security_link_repository import PostgresSecurityLinkStore
from backend.app.infrastructure.persistence.staff_activation_repository import PostgresStaffActivationStore
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordList
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import SecurityLinkProtector
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
    clock, key_ring = _components()
    try:
        with engine.begin() as connection:
            yield CompleteStaffActivation(
                link_lifecycle=_links(connection, clock, key_ring),
                store=PostgresStaffActivationStore(connection),
                blocked_passwords=BlockedPasswordList.load(clock=clock),
                password_hasher=AdministrativePasswordHasher(),
                pending_totp_protector=PendingTotpProtector(key_ring=key_ring, secret_generator=SystemSecretGenerator()),
                factor_protector=TotpFactorProtector(key_ring=key_ring, secret_generator=SystemSecretGenerator()),
                totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),
                recovery_codes=RecoveryCodeService(
                    secret_generator=SystemSecretGenerator(),
                    protector=RecoveryCodeProtector(key_ring=key_ring),
                ),
                audit=RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection),
                    clock=clock,
                ),
                clock=clock,
            )
    finally:
        engine.dispose()


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

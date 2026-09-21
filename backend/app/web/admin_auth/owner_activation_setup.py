"""Public HTTP contract for preparing or abandoning initial owner activation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.owner_activation import CompleteOwnerActivation
from backend.app.application.admin_access.owner_activation_setup import (
    AbandonOwnerActivationSetup,
    OwnerActivationSetupError,
    PrepareOwnerActivationSetup,
)
from backend.app.application.admin_access.pending_security_state import (
    DiscardPendingSecurityState,
)
from backend.app.application.admin_access.security_links import SecurityLinkLifecycle
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.owner_activation_repository import (
    PostgresOwnerActivationStore,
)
from backend.app.infrastructure.persistence.pending_security_state_repository import (
    PostgresPendingSecurityStateStore,
)
from backend.app.infrastructure.persistence.pending_totp_setup_repository import (
    PostgresPendingTotpSetupStore,
)
from backend.app.infrastructure.persistence.security_link_repository import (
    PostgresSecurityLinkStore,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.blocked_passwords import BlockedPasswordList
from backend.app.infrastructure.security.pending_totp_protection import PendingTotpProtector
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_link_protection import (
    SecurityLinkProtector,
)
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.security_link_transport import SecurityLinkTokenBody


router = APIRouter(prefix="/api/admin/security-links", tags=["admin-security-links"])
_GENERIC_LINK_DETAIL = "Este enlace no es válido o ya no está disponible."
_INVALID_PASSWORD_DETAIL = "La contraseña no cumple los requisitos de seguridad."
_SECURITY_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


class TotpSetupResponse(BaseModel):
    """TOTP material visible only while this setup remains unconfirmed."""

    model_config = ConfigDict(populate_by_name=True)

    provisioning_uri: str = Field(serialization_alias="provisioningUri", repr=False)
    manual_key: str = Field(serialization_alias="manualKey", repr=False)


class OwnerActivationSetupResponse(BaseModel):
    """Minimum public response for one authorized owner activation flow."""

    model_config = ConfigDict(populate_by_name=True)

    totp_setup: TotpSetupResponse = Field(serialization_alias="totpSetup")


class CompleteOwnerActivationBody(SecurityLinkTokenBody):
    """The three transient values required by the atomic activation."""

    model_config = ConfigDict(populate_by_name=True)

    password: str = Field(min_length=1, max_length=128, repr=False)
    totp_code: str = Field(
        alias="totpCode",
        min_length=6,
        max_length=6,
        pattern=r"^[0-9]{6}$",
        repr=False,
    )


class OwnerActivationCompletionResponse(BaseModel):
    """One-time recovery codes returned only by a successful activation."""

    model_config = ConfigDict(populate_by_name=True)

    recovery_codes: tuple[str, ...] = Field(
        serialization_alias="recoveryCodes",
        min_length=10,
        max_length=10,
        repr=False,
    )


def get_owner_activation_preparer() -> Iterator[PrepareOwnerActivationSetup]:
    """Open one short transaction for link inspection and pending setup creation."""

    engine = create_postgres_engine(load_settings().database_url)
    clock = SystemClock()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    try:
        with engine.begin() as connection:
            yield PrepareOwnerActivationSetup(
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=clock,
                    secret_generator=SystemSecretGenerator(),
                    protector=SecurityLinkProtector(key_ring=key_ring),
                ),
                setup_store=PostgresPendingTotpSetupStore(connection),
                totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),
                protector=PendingTotpProtector(
                    key_ring=key_ring,
                    secret_generator=SystemSecretGenerator(),
                ),
                clock=clock,
            )
    finally:
        engine.dispose()


def get_owner_activation_abandoner() -> Iterator[AbandonOwnerActivationSetup]:
    """Open one short transaction for explicit pending-secret cleanup."""

    engine = create_postgres_engine(load_settings().database_url)
    clock = SystemClock()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    try:
        with engine.begin() as connection:
            yield AbandonOwnerActivationSetup(
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=clock,
                    secret_generator=SystemSecretGenerator(),
                    protector=SecurityLinkProtector(key_ring=key_ring),
                ),
                pending_state=DiscardPendingSecurityState(
                    store=PostgresPendingSecurityStateStore(connection),
                    clock=clock,
                ),
            )
    finally:
        engine.dispose()


def get_owner_activation_completer() -> Iterator[CompleteOwnerActivation]:
    """Open the single transaction that either completes every owner write or none."""

    engine = create_postgres_engine(load_settings().database_url)
    clock = SystemClock()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    try:
        with engine.begin() as connection:
            yield CompleteOwnerActivation(
                link_lifecycle=SecurityLinkLifecycle(
                    store=PostgresSecurityLinkStore(connection),
                    clock=clock,
                    secret_generator=SystemSecretGenerator(),
                    protector=SecurityLinkProtector(key_ring=key_ring),
                ),
                store=PostgresOwnerActivationStore(connection),
                blocked_passwords=BlockedPasswordList.load(clock=clock),
                password_hasher=AdministrativePasswordHasher(),
                pending_totp_protector=PendingTotpProtector(
                    key_ring=key_ring,
                    secret_generator=SystemSecretGenerator(),
                ),
                factor_protector=TotpFactorProtector(
                    key_ring=key_ring,
                    secret_generator=SystemSecretGenerator(),
                ),
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
def prepare_owner_activation(
    body: SecurityLinkTokenBody,
    response: Response,
    preparer: Annotated[
        PrepareOwnerActivationSetup,
        Depends(get_owner_activation_preparer),
    ],
) -> OwnerActivationSetupResponse:
    """Prepare TOTP without consuming the link or activating the owner."""

    response.headers.update(_SECURITY_RESPONSE_HEADERS)
    try:
        prepared = preparer.prepare(token=body.decoded_token())
    except (OwnerActivationSetupError, ValueError) as error:
        raise HTTPException(
            status_code=404,
            detail=_GENERIC_LINK_DETAIL,
            headers=_SECURITY_RESPONSE_HEADERS,
        ) from error
    return OwnerActivationSetupResponse(
        totp_setup=TotpSetupResponse(
            provisioning_uri=prepared.provisioning_uri,
            manual_key=prepared.manual_key,
        )
    )


@router.post("/abandon", status_code=status.HTTP_204_NO_CONTENT)
def abandon_owner_activation(
    body: SecurityLinkTokenBody,
    response: Response,
    abandoner: Annotated[
        AbandonOwnerActivationSetup,
        Depends(get_owner_activation_abandoner),
    ],
) -> None:
    """Erase the pending secret without consuming the still-valid link."""

    response.headers.update(_SECURITY_RESPONSE_HEADERS)
    try:
        abandoner.abandon(token=body.decoded_token())
    except (OwnerActivationSetupError, ValueError) as error:
        raise HTTPException(
            status_code=404,
            detail=_GENERIC_LINK_DETAIL,
            headers=_SECURITY_RESPONSE_HEADERS,
        ) from error


@router.post("/complete", response_model=OwnerActivationCompletionResponse)
def complete_owner_activation(
    body: CompleteOwnerActivationBody,
    response: Response,
    completer: Annotated[
        CompleteOwnerActivation,
        Depends(get_owner_activation_completer, scope="function"),
    ],
) -> OwnerActivationCompletionResponse | JSONResponse:
    """Activate the owner atomically and return recovery codes without a session."""

    response.headers.update(_SECURITY_RESPONSE_HEADERS)
    outcome = completer.complete(
        token=body.decoded_token(),
        password=body.password,
        totp_code=body.totp_code,
    )
    if outcome.rejection is not None:
        detail = (
            _INVALID_PASSWORD_DETAIL
            if outcome.rejection == "invalid_password"
            else _GENERIC_LINK_DETAIL
        )
        status_code = 422 if outcome.rejection == "invalid_password" else 404
        return JSONResponse(
            status_code=status_code,
            content={"detail": detail},
            headers=_SECURITY_RESPONSE_HEADERS,
        )
    return OwnerActivationCompletionResponse(recovery_codes=outcome.recovery_codes)

"""HTTP login contract that emits the opaque administrative session safely."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
    RecordProtectedAdministrativeCredentialFailure,
    SecurityNotificationDispatch,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.login_completion import (
    CompleteAdministrativeLoginCredentials,
)
from backend.app.application.admin_access.login_session import (
    CreateAdministrativeLoginSession,
)
from backend.app.application.admin_access.login_validation import (
    ValidateAdministrativeLogin,
)
from backend.app.application.admin_access.security_notification_deliveries import (
    RecordSecurityNotificationDelivery,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.public_request_limit import (
    PublicRequestLimiter,
    PublicRequestRateLimitError,
)
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.admin_lock_recipient_repository import (
    PostgresAdministrativeLockRecipientDirectory,
)
from backend.app.infrastructure.persistence.admin_login_completion_repository import (
    PostgresAdministrativeLoginFactorStore,
)
from backend.app.infrastructure.persistence.admin_login_repository import (
    PostgresAdministrativeLoginStore,
)
from backend.app.infrastructure.persistence.admin_session_repository import (
    PostgresAdministrativeLoginSessionStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.email_simulator import EmailSimulator
from backend.app.infrastructure.persistence.security_notification_delivery_repository import (
    PostgresSecurityNotificationDeliveryStore,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.security_notification_delivery_protection import (
    SecurityNotificationDeliveryProtector,
)
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import (
    TotpFactorProtector,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.public_request_protection import (
    get_public_authentication_request_limiter,
)
from backend.app.web.admin_auth.security_notice_delivery import deliver_security_notices


router = APIRouter(prefix="/api/admin/sessions", tags=["admin-sessions"])
ADMINISTRATIVE_SESSION_COOKIE = "__Host-beautyhub-session"
_INVALID_CREDENTIALS_DETAIL = "Las credenciales no son válidas."
_RATE_LIMIT_DETAIL = "Demasiadas solicitudes. Inténtalo más tarde."


class AdministrativeLoginBody(BaseModel):
    """Bound credential input whose values never enter representations."""

    model_config = ConfigDict(populate_by_name=True)

    email: str = Field(min_length=1, max_length=254, repr=False)
    password: str = Field(min_length=1, max_length=128, repr=False)
    totp_code: str | None = Field(
        default=None,
        alias="totpCode",
        min_length=1,
        max_length=32,
        repr=False,
    )
    recovery_code: str | None = Field(
        default=None,
        alias="recoveryCode",
        min_length=1,
        max_length=64,
        repr=False,
    )


class AdministrativeLoginResponse(BaseModel):
    """Minimum browser context; the session token remains cookie-only."""

    model_config = ConfigDict(populate_by_name=True)

    role: Literal["owner", "staff"]
    csrf_token: str = Field(serialization_alias="csrfToken", repr=False)


def get_administrative_login() -> Iterator[_AdministrativeLoginOperation]:
    """Compose validation, factor consumption, session and audit in one transaction."""

    engine = create_postgres_engine(load_settings().database_url)
    clock = SystemClock()
    entropy = SystemSecretGenerator()
    key_ring = CryptographyKeyRing(load_cryptography_key_configuration())
    dispatches: list[SecurityNotificationDispatch] = []
    try:
        with engine.begin() as connection:
            security_store = PostgresAdministrativeAccountSecurityStore(connection)
            audit = RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection),
                clock=clock,
            )
            email_protector = AdministrativeEmailProtector(
                key_ring=key_ring,
                secret_generator=entropy,
            )
            failure_recorder = RecordProtectedAdministrativeCredentialFailure(
                failure_recorder=RecordAdministrativeCredentialFailure(
                    store=security_store,
                    clock=clock,
                ),
                audit=audit,
                notifications=RecordSecurityNotificationDelivery(
                    store=PostgresSecurityNotificationDeliveryStore(connection),
                    protector=SecurityNotificationDeliveryProtector(
                        key_ring=key_ring,
                        secret_generator=entropy,
                    ),
                ),
                recipients=PostgresAdministrativeLockRecipientDirectory(
                    connection=connection,
                    email_protector=email_protector,
                ),
                dispatches=dispatches,
            )
            validation = ValidateAdministrativeLogin(
                store=PostgresAdministrativeLoginStore(connection),
                email_lookup=email_protector,
                password_verifier=AdministrativePasswordHasher(),
                factor_protector=TotpFactorProtector(
                    key_ring=key_ring,
                    secret_generator=entropy,
                ),
                totp=TotpAuthenticator(secret_generator=entropy),
                recovery_codes=RecoveryCodeService(
                    secret_generator=entropy,
                    protector=RecoveryCodeProtector(key_ring=key_ring),
                ),
                credential_check_guard=EnsureAdministrativeCredentialCheck(
                    store=security_store,
                    clock=clock,
                ),
                clock=clock,
            )
            yield _AdministrativeLoginOperation(
                validation=validation,
                sessions=CreateAdministrativeLoginSession(
                    credentials=CompleteAdministrativeLoginCredentials(
                        factor_store=PostgresAdministrativeLoginFactorStore(connection),
                        failure_recorder=failure_recorder,
                        clock=clock,
                    ),
                    store=PostgresAdministrativeLoginSessionStore(connection),
                    protector=AdminSessionProtector(key_ring=key_ring),
                    secret_generator=entropy,
                    audit=audit,
                    clock=clock,
                ),
            )
        if dispatches:
            deliver_security_notices(
                engine=engine,
                email_sender=EmailSimulator(outcome="accepted"),
                notices=dispatches,
            )
    finally:
        engine.dispose()


class _AdministrativeLoginOperation:
    """Keep the HTTP adapter unaware of validation's internal proof."""

    def __init__(self, *, validation, sessions) -> None:
        self._validation = validation
        self._sessions = sessions

    def login(self, *, email, password, totp_code=None, recovery_code=None):
        validated = self._validation.validate(
            email=email,
            password=password,
            totp_code=totp_code,
            recovery_code=recovery_code,
        )
        return self._sessions.create(validation=validated)


@router.post("", response_model=AdministrativeLoginResponse)
def create_administrative_session(
    body: AdministrativeLoginBody,
    response: Response,
    limiter: Annotated[
        PublicRequestLimiter,
        Depends(get_public_authentication_request_limiter),
    ],
    login: Annotated[
        _AdministrativeLoginOperation,
        Depends(get_administrative_login, scope="function"),
    ],
) -> AdministrativeLoginResponse | JSONResponse:
    """Authenticate once and emit separate session-cookie and CSRF values."""

    try:
        limiter.ensure_allowed("login")
    except PublicRequestRateLimitError:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": _RATE_LIMIT_DETAIL},
        )

    outcome = login.login(
        email=body.email,
        password=body.password,
        totp_code=body.totp_code,
        recovery_code=body.recovery_code,
    )
    if not outcome.accepted:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": _INVALID_CREDENTIALS_DETAIL},
        )

    session_value = _encode_browser_secret(outcome.session_token)
    csrf_value = _encode_browser_secret(outcome.csrf_token)
    response.set_cookie(
        key=ADMINISTRATIVE_SESSION_COOKIE,
        value=session_value,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return AdministrativeLoginResponse(
        role=outcome.role,
        csrf_token=csrf_value,
    )


def _encode_browser_secret(value: bytes | None) -> str:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("administrative browser secret is invalid.")
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

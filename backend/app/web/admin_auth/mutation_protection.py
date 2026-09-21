"""FastAPI dependency for administrative same-origin and CSRF enforcement."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request

from backend.app.application.admin_access.mutation_protection import (
    AdministrativeMutationProtectionError,
    AdministrativeSessionAuthenticationError,
    ValidateAdministrativeMutationProtection,
)
from backend.app.application.clock import SystemClock
from backend.app.infrastructure.persistence.admin_session_repository import (
    PostgresAdministrativeCsrfSessionStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.security.admin_session_protection import (
    AdminSessionProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import (
    CryptographyKeyRing,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_settings,
)
from backend.app.web.admin_auth.login import ADMINISTRATIVE_SESSION_COOKIE


ADMINISTRATIVE_CSRF_HEADER = "X-CSRF-Token"
_AUTHENTICATION_DETAIL = "Autenticación administrativa requerida."
_FORBIDDEN_DETAIL = "No tienes permiso para realizar esta operación."


def get_administrative_mutation_validator(
) -> Iterator[ValidateAdministrativeMutationProtection]:
    """Load CSRF state without implementing the later session-lifecycle rules."""

    engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.connect() as connection:
            committed_connection = connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            yield ValidateAdministrativeMutationProtection(
                store=PostgresAdministrativeCsrfSessionStore(committed_connection),
                protector=AdminSessionProtector(
                    key_ring=CryptographyKeyRing(
                        load_cryptography_key_configuration()
                    ),
                ),
                clock=SystemClock(),
            )
    finally:
        engine.dispose()


def require_administrative_mutation_protection(
    request: Request,
    validator: Annotated[
        ValidateAdministrativeMutationProtection,
        Depends(get_administrative_mutation_validator, scope="function"),
    ],
    session_cookie: Annotated[
        str | None,
        Cookie(alias=ADMINISTRATIVE_SESSION_COOKIE),
    ] = None,
    csrf_header: Annotated[
        str | None,
        Header(alias=ADMINISTRATIVE_CSRF_HEADER),
    ] = None,
) -> None:
    """Reject before the protected path operation can execute any effect."""

    try:
        validator.validate(
            session_token=decode_administrative_browser_secret(session_cookie),
            csrf_token=decode_administrative_browser_secret(csrf_header),
            approved_origin=f"{request.url.scheme}://{request.url.netloc}",
            origin=request.headers.get("origin"),
            referer=request.headers.get("referer"),
            human_initiated=True,
        )
    except AdministrativeSessionAuthenticationError as error:
        raise HTTPException(status_code=401, detail=_AUTHENTICATION_DETAIL) from error
    except (AdministrativeMutationProtectionError, ValueError) as error:
        raise HTTPException(status_code=403, detail=_FORBIDDEN_DETAIL) from error


def decode_administrative_browser_secret(value: str | None) -> bytes | None:
    if value is None:
        return None
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeEncodeError, ValueError):
        return None
    return decoded if len(decoded) == 32 else None

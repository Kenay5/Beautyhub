"""HTTP endpoint for ending the current administrative session."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.logout import CloseAdministrativeSession
from backend.app.application.clock import SystemClock
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
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
from backend.app.web.admin_auth.mutation_protection import (
    decode_administrative_browser_secret,
    require_administrative_mutation_protection,
)


router = APIRouter(prefix="/api/admin/sessions", tags=["admin-sessions"])
_AUTHENTICATION_DETAIL = "Autenticación administrativa requerida."


def get_administrative_session_closer() -> Iterator[CloseAdministrativeSession]:
    """Use one short transaction for the invalidation and its audit evidence."""

    engine = create_postgres_engine(load_settings().database_url)
    clock = SystemClock()
    try:
        with engine.begin() as connection:
            yield CloseAdministrativeSession(
                store=PostgresAdministrativeCsrfSessionStore(connection),
                protector=AdminSessionProtector(
                    key_ring=CryptographyKeyRing(
                        load_cryptography_key_configuration()
                    ),
                ),
                audit=RecordAdministrativeAuditEvent(
                    store=PostgresAdministrativeAuditStore(connection),
                    clock=clock,
                ),
                clock=clock,
            )
    finally:
        engine.dispose()


@router.delete("/current", status_code=status.HTTP_204_NO_CONTENT)
def close_administrative_session(
    response: Response,
    protection: Annotated[
        None,
        Depends(require_administrative_mutation_protection, scope="function"),
    ],
    closer: Annotated[
        CloseAdministrativeSession,
        Depends(get_administrative_session_closer, scope="function"),
    ],
    session_cookie: Annotated[
        str | None,
        Cookie(alias=ADMINISTRATIVE_SESSION_COOKIE),
    ] = None,
) -> None:
    """End the authenticated session and remove its browser cookie."""

    del protection
    session_token = decode_administrative_browser_secret(session_cookie)
    if session_token is None:
        raise HTTPException(status_code=401, detail=_AUTHENTICATION_DETAIL)
    closer.close(session_token=session_token)
    response.delete_cookie(
        key=ADMINISTRATIVE_SESSION_COOKIE,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT

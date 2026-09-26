"""HTTP context for the current administrative browser session."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.application.admin_access.authorization import AdministrativeActor
from backend.app.application.admin_access.mutation_protection import (
    AdministrativeSessionAuthenticationError,
)
from backend.app.application.admin_access.session_context import (
    LoadAdministrativeSessionContext,
)
from backend.app.application.clock import SystemClock
from backend.app.application.entropy import SystemSecretGenerator
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
)


router = APIRouter(prefix="/api/admin/sessions", tags=["admin-sessions"])
_AUTHENTICATION_DETAIL = "Autenticación administrativa requerida."


class AdministrativeSessionContextResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: int = Field(serialization_alias="accountId")
    role: Literal["owner", "staff"]
    csrf_token: str = Field(serialization_alias="csrfToken", repr=False)


def get_administrative_session_context_loader(
) -> Iterator[LoadAdministrativeSessionContext]:
    """Use one short transaction for account revalidation and optional CSRF rotation."""

    engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.begin() as connection:
            yield LoadAdministrativeSessionContext(
                store=PostgresAdministrativeCsrfSessionStore(connection),
                protector=AdminSessionProtector(
                    key_ring=CryptographyKeyRing(
                        load_cryptography_key_configuration()
                    )
                ),
                secret_generator=SystemSecretGenerator(),
                clock=SystemClock(),
            )
    finally:
        engine.dispose()


def get_authenticated_admin_actor(
    loader: Annotated[
        LoadAdministrativeSessionContext,
        Depends(get_administrative_session_context_loader, scope="function"),
    ],
    session_cookie: Annotated[
        str | None,
        Cookie(alias=ADMINISTRATIVE_SESSION_COOKIE),
    ] = None,
) -> AdministrativeActor:
    """Derive identity and role from current PostgreSQL state, never the client."""

    try:
        return loader.authenticate(
            session_token=decode_administrative_browser_secret(session_cookie)
        )
    except (AdministrativeSessionAuthenticationError, ValueError) as error:
        raise HTTPException(status_code=401, detail=_AUTHENTICATION_DETAIL) from error


@router.get("/current", response_model=AdministrativeSessionContextResponse)
def read_administrative_session_context(
    loader: Annotated[
        LoadAdministrativeSessionContext,
        Depends(get_administrative_session_context_loader, scope="function"),
    ],
    session_cookie: Annotated[
        str | None,
        Cookie(alias=ADMINISTRATIVE_SESSION_COOKIE),
    ] = None,
) -> AdministrativeSessionContextResponse:
    """Return a freshly revalidated context without extending inactivity."""

    try:
        context = loader.refresh(
            session_token=decode_administrative_browser_secret(session_cookie)
        )
    except (AdministrativeSessionAuthenticationError, ValueError) as error:
        raise HTTPException(status_code=401, detail=_AUTHENTICATION_DETAIL) from error
    return AdministrativeSessionContextResponse(
        account_id=context.actor.account_id,
        role=context.actor.role,
        csrf_token=_encode_browser_secret(context.csrf_token),
    )


def _encode_browser_secret(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

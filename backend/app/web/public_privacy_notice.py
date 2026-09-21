"""Public HTTP contract for the currently valid privacy notice."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Connection

from backend.app.application.clock import Clock, SystemClock
from backend.app.application.get_current_privacy_notice import (
    CurrentPrivacyNoticeReader,
    GetCurrentPrivacyNotice,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.privacy_notice_repository import (
    PostgresCurrentPrivacyNoticeReader,
)
from backend.app.infrastructure.settings import load_settings


router = APIRouter(prefix="/api/public/privacy-notice")
_NOTICE_UNAVAILABLE_DETAIL = "No hay un aviso de privacidad disponible."


class PublicPrivacyNoticeResponse(BaseModel):
    """The visible version and content required before public confirmation."""

    version: str
    content: str


def get_current_privacy_notice_reader() -> Iterator[CurrentPrivacyNoticeReader]:
    """Open a short-lived PostgreSQL connection for one public read."""

    engine = create_postgres_engine(load_settings().database_url)
    connection: Connection | None = None
    try:
        connection = engine.connect()
        yield PostgresCurrentPrivacyNoticeReader(connection)
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


def get_clock() -> Clock:
    """Provide the system clock at the HTTP composition boundary."""

    return SystemClock()


@router.get("", response_model=PublicPrivacyNoticeResponse)
def get_public_privacy_notice(
    reader: Annotated[
        CurrentPrivacyNoticeReader, Depends(get_current_privacy_notice_reader)
    ],
    clock: Annotated[Clock, Depends(get_clock)],
) -> PublicPrivacyNoticeResponse:
    """Return the current notice, never its database identifier."""

    notice = GetCurrentPrivacyNotice(reader, clock).execute()
    if notice is None:
        raise HTTPException(status_code=404, detail=_NOTICE_UNAVAILABLE_DETAIL)
    return PublicPrivacyNoticeResponse(version=notice.version, content=notice.content)

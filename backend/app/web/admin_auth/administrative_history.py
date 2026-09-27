"""Owner-only read endpoints for the minimum administrative audit history."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine

from backend.app.application.admin_access.administrative_history import (
    AdministrativeHistoryEntry,
    AdministrativeHistoryFilters,
    QueryAdministrativeHistory,
)
from backend.app.application.admin_access.audit import RecordAdministrativeAuditEvent
from backend.app.application.admin_access.authorization import (
    AdministrativeActor,
    AdministrativeAuthorizationError,
)
from backend.app.application.clock import Clock, SystemClock
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditAction
from backend.app.domain.audit.admin_audit_event import AdministrativeAuditResult
from backend.app.domain.audit.history_period import history_period_utc_bounds
from backend.app.infrastructure.persistence.admin_audit_repository import (
    PostgresAdministrativeAuditStore,
)
from backend.app.infrastructure.persistence.administrative_history_repository import (
    PostgresAdministrativeHistoryStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_settings
from backend.app.web.admin_auth.session_context import get_authenticated_admin_actor


router = APIRouter(prefix="/api/admin/history", tags=["admin-history"])
_FORBIDDEN_DETAIL = "No tienes permiso para consultar el historial administrativo."
_NOT_FOUND_DETAIL = "No se encontró el evento solicitado."


class AdministrativeHistoryItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: int = Field(serialization_alias="eventId")
    actor_account_id: int | None = Field(serialization_alias="actorAccountId")
    action: AdministrativeAuditAction
    result: AdministrativeAuditResult
    occurred_at: datetime = Field(serialization_alias="occurredAt")
    target_reference: str | None = Field(serialization_alias="targetReference")


class AdministrativeHistoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    events: tuple[AdministrativeHistoryItemResponse, ...]
    account_ids: tuple[int, ...] = Field(serialization_alias="accountIds")


class AdministrativeHistoryOperations(Protocol):
    def list_events(
        self,
        *,
        actor: AdministrativeActor,
        filters: AdministrativeHistoryFilters,
    ) -> tuple[tuple[AdministrativeHistoryEntry, ...], tuple[int, ...]]: ...

    def get_event(
        self, *, actor: AdministrativeActor, event_id: int
    ) -> AdministrativeHistoryEntry | None: ...


class PostgresAdministrativeHistoryOperations:
    def __init__(self, *, engine: Engine, clock: Clock | None = None) -> None:
        self._engine = engine
        self._clock = clock or SystemClock()

    def list_events(
        self,
        *,
        actor: AdministrativeActor,
        filters: AdministrativeHistoryFilters,
    ) -> tuple[tuple[AdministrativeHistoryEntry, ...], tuple[int, ...]]:
        with self._engine.connect() as connection:
            return self._query(connection).list_events(actor=actor, filters=filters)

    def get_event(
        self, *, actor: AdministrativeActor, event_id: int
    ) -> AdministrativeHistoryEntry | None:
        with self._engine.connect() as connection:
            return self._query(connection).get_event(actor=actor, event_id=event_id)

    def _query(self, connection: Connection) -> QueryAdministrativeHistory:
        return QueryAdministrativeHistory(
            store=PostgresAdministrativeHistoryStore(connection),
            clock=self._clock,
            denial_recorder=_CommittedHistoryDenialRecorder(
                engine=self._engine, clock=self._clock
            ),
        )


class _CommittedHistoryDenialRecorder:
    """Commit a minimal permission denial separately from the read transaction."""

    def __init__(self, *, engine: Engine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    def record(
        self,
        *,
        actor_account_id: int | None,
        action: AdministrativeAuditAction,
        result: AdministrativeAuditResult,
    ) -> None:
        with self._engine.begin() as connection:
            RecordAdministrativeAuditEvent(
                store=PostgresAdministrativeAuditStore(connection), clock=self._clock
            ).record(
                actor_account_id=actor_account_id,
                action=action,
                result=result,
            )


def get_administrative_history_operations() -> Iterator[AdministrativeHistoryOperations]:
    engine = create_postgres_engine(load_settings().database_url)
    try:
        yield PostgresAdministrativeHistoryOperations(engine=engine)
    finally:
        engine.dispose()


@router.get("", response_model=AdministrativeHistoryResponse)
def list_administrative_history(
    response: Response,
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[
        AdministrativeHistoryOperations,
        Depends(get_administrative_history_operations),
    ],
    account_id: Annotated[int | None, Query(alias="accountId", gt=0)] = None,
    action: Annotated[AdministrativeAuditAction | None, Query()] = None,
    start_date: Annotated[date | None, Query(alias="fromDate")] = None,
    end_date: Annotated[date | None, Query(alias="toDate")] = None,
) -> AdministrativeHistoryResponse:
    response.headers["Cache-Control"] = "no-store"
    filters = _filters(
        account_id=account_id,
        action=action,
        start_date=start_date,
        end_date=end_date,
    )
    try:
        events, account_ids = operations.list_events(actor=actor, filters=filters)
    except AdministrativeAuthorizationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL
        ) from error
    return AdministrativeHistoryResponse(
        events=tuple(_response(event) for event in events), account_ids=account_ids
    )


@router.get("/{event_id}", response_model=AdministrativeHistoryItemResponse)
def read_administrative_history_event(
    event_id: Annotated[int, Path(gt=0)],
    response: Response,
    actor: Annotated[AdministrativeActor, Depends(get_authenticated_admin_actor)],
    operations: Annotated[
        AdministrativeHistoryOperations,
        Depends(get_administrative_history_operations),
    ],
) -> AdministrativeHistoryItemResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        event = operations.get_event(actor=actor, event_id=event_id)
    except AdministrativeAuthorizationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN_DETAIL
        ) from error
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)
    return _response(event)


def _filters(
    *,
    account_id: int | None,
    action: AdministrativeAuditAction | None,
    start_date: date | None,
    end_date: date | None,
) -> AdministrativeHistoryFilters:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El periodo indicado no es válido.",
        )
    try:
        start, end = history_period_utc_bounds(
            start_date=start_date, end_date=end_date
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El periodo indicado no es válido.",
        ) from error
    return AdministrativeHistoryFilters(
        account_id=account_id,
        action=action,
        start_inclusive=start,
        end_exclusive=end,
    )


def _response(event: AdministrativeHistoryEntry) -> AdministrativeHistoryItemResponse:
    return AdministrativeHistoryItemResponse(
        event_id=event.event_id,
        actor_account_id=event.actor_account_id,
        action=event.action,
        result=event.result,
        occurred_at=event.occurred_at,
        target_reference=event.target_reference,
    )

"""PostgreSQL persistence primitives for serialized schedule changes."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.engine import Connection

from backend.app.domain.schedule import ScheduledInterval, TimeInterval
from backend.app.infrastructure.persistence.models import (
    Appointment,
    AvailabilityBlock,
    ScheduleGuard,
    Service,
)


class PostgresScheduleRepository:
    """Read scheduled intervals while holding the shared agenda guard."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_schedule(self) -> None:
        """Lock the singleton row until the caller's transaction finishes."""

        self._connection.execute(
            select(ScheduleGuard.guard_id)
            .where(ScheduleGuard.guard_id == 1)
            .with_for_update()
        ).scalar_one()

    def list_scheduled_intervals(
        self,
        *,
        lock: bool = False,
    ) -> tuple[ScheduledInterval, ...]:
        """Read current appointments after acquiring the agenda guard."""

        statement = select(
                Appointment.scheduled_start,
                Appointment.scheduled_end,
                Appointment.branch,
                Appointment.status,
            ).where(Appointment.status == "scheduled")
        if lock:
            statement = statement.with_for_update()
        rows = self._connection.execute(statement)
        return tuple(
            ScheduledInterval(
                interval=TimeInterval(row.scheduled_start, row.scheduled_end),
                branch=row.branch,
                status=row.status,
            )
            for row in rows
        )

    def list_applicable_blocks(
        self,
        branch: str,
        *,
        lock: bool = False,
    ) -> tuple[TimeInterval, ...]:
        """Read global and selected-branch blocks under the agenda guard."""

        statement = select(
            AvailabilityBlock.starts_at,
            AvailabilityBlock.ends_at,
        ).where(
            or_(
                AvailabilityBlock.scope == "global",
                AvailabilityBlock.branch == branch,
            )
        )
        if lock:
            statement = statement.with_for_update()
        return tuple(
            TimeInterval(row.starts_at, row.ends_at)
            for row in self._connection.execute(statement)
        )


class PostgresPublicAvailabilityReader:
    """Read the minimum PostgreSQL state required for public availability."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_active_service_duration(self, branch: str, service_name: str) -> int | None:
        """Find one active service by its public catalog name and branch."""

        availability_column = (
            Service.available_chiconcuac
            if branch == "chiconcuac"
            else Service.available_texcoco
        )
        return self._connection.execute(
            select(Service.duration_minutes).where(
                Service.is_active.is_(True),
                availability_column.is_(True),
                Service.canonical_name == service_name.lower(),
            )
        ).scalar_one_or_none()

    def list_scheduled_intervals(self) -> tuple[ScheduledInterval, ...]:
        """Return only appointments that currently occupy the professional."""

        return PostgresScheduleRepository(self._connection).list_scheduled_intervals()

    def list_applicable_blocks(self, branch: str) -> tuple[TimeInterval, ...]:
        """Return global and selected-branch block windows without metadata."""

        return PostgresScheduleRepository(self._connection).list_applicable_blocks(branch)

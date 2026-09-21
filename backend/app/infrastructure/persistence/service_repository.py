"""PostgreSQL adapter for internal service creation."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Connection, select, update

from backend.app.application.list_active_services import PublicService
from backend.app.domain.service import ServiceDraft
from backend.app.infrastructure.persistence.models import Service
from backend.app.infrastructure.persistence.schedule_repository import (
    PostgresScheduleRepository,
)


class PostgresServiceCreationRepository:
    """Persist services through a caller-owned PostgreSQL transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_service_names(self) -> Iterable[str]:
        """Return all service names for the domain's canonical comparison."""

        return tuple(self._connection.execute(select(Service.name)).scalars())

    def create_service(self, service: ServiceDraft) -> int:
        """Insert a validated service and return its generated identifier."""

        result = self._connection.execute(
            Service.__table__.insert()
            .values(
                name=service.name,
                description=service.description,
                duration_minutes=service.duration_minutes,
                price=service.price,
                is_active=service.is_active,
                available_chiconcuac=service.available_chiconcuac,
                available_texcoco=service.available_texcoco,
            )
            .returning(Service.service_id)
        )
        return result.scalar_one()


class PostgresServiceEditingRepository:
    """Edit services through a caller-owned PostgreSQL transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get_service(self, service_id: int) -> ServiceDraft | None:
        """Return the stored service data needed to preserve its active state."""

        row = self._connection.execute(
            select(
                Service.name,
                Service.description,
                Service.duration_minutes,
                Service.price,
                Service.is_active,
                Service.available_chiconcuac,
                Service.available_texcoco,
            ).where(Service.service_id == service_id)
        ).one_or_none()
        if row is None:
            return None
        return ServiceDraft(
            name=row.name,
            description=row.description,
            duration_minutes=row.duration_minutes,
            price=row.price,
            is_active=row.is_active,
            available_chiconcuac=row.available_chiconcuac,
            available_texcoco=row.available_texcoco,
        )

    def list_service_names(self, excluding_service_id: int) -> Iterable[str]:
        """Return every other service name for duplicate validation."""

        statement = select(Service.name).where(Service.service_id != excluding_service_id)
        return tuple(self._connection.execute(statement).scalars())

    def update_service(self, service_id: int, service: ServiceDraft) -> bool:
        """Update only the approved editable service fields."""

        result = self._connection.execute(
            update(Service)
            .where(Service.service_id == service_id)
            .values(
                name=service.name,
                description=service.description,
                duration_minutes=service.duration_minutes,
                price=service.price,
                available_chiconcuac=service.available_chiconcuac,
                available_texcoco=service.available_texcoco,
            )
        )
        return result.rowcount == 1


class PostgresServiceStatusRepository:
    """Change service status through a caller-owned PostgreSQL transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def set_service_active(self, service_id: int, is_active: bool) -> bool:
        """Persist a status change while serializing with schedule mutations."""

        PostgresScheduleRepository(self._connection).lock_schedule()
        result = self._connection.execute(
            update(Service)
            .where(Service.service_id == service_id)
            .values(is_active=is_active)
        )
        return result.rowcount == 1


class PostgresActiveServiceCatalog:
    """Read the public catalog from PostgreSQL without exposing service IDs."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def list_active_services(self, branch: str) -> Iterable[PublicService]:
        """Return active services that are available in the requested branch."""

        availability_column = (
            Service.available_chiconcuac
            if branch == "chiconcuac"
            else Service.available_texcoco
        )
        statement = select(
            Service.name,
            Service.duration_minutes,
            Service.price,
        ).where(Service.is_active.is_(True), availability_column.is_(True))
        return tuple(
            PublicService(
                name=row.name,
                duration_minutes=row.duration_minutes,
                price=row.price,
            )
            for row in self._connection.execute(statement)
        )

"""PostgreSQL checks that the current migration chain is reversible."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_test_database_url


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_TABLES = {
    "services",
    "privacy_notice_versions",
    "appointments",
    "booking_confirmation_references",
    "notification_deliveries",
    "appointment_reminders",
    "availability_blocks",
    "schedule_guard",
    "monthly_appointment_statistics",
    "public_request_events",
}


def migration_config(connection: object) -> Config:
    """Create Alembic configuration bound to the PostgreSQL test connection."""

    config = Config(str(REPOSITORY_ROOT / "backend" / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.mark.integration
def test_current_migrations_downgrade_to_base_and_upgrade_to_head() -> None:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = migration_config(connection)
            command.upgrade(config, "head")
            command.downgrade(config, "base")

            assert APPLICATION_TABLES.isdisjoint(
                set(inspect(connection).get_table_names())
            )

            command.upgrade(config, "head")
            assert APPLICATION_TABLES.issubset(
                set(inspect(connection).get_table_names())
            )
    finally:
        engine.dispose()

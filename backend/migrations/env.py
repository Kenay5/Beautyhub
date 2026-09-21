"""Alembic environment for the approved PostgreSQL persistence adapter."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.engine import Engine

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import Base
from backend.app.infrastructure.settings import load_settings


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    database_url = load_settings().database_url.reveal()
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def configure_connection(connection: Connection) -> None:
    """Run migrations using a caller-owned connection when supplied."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using PostgreSQL and external runtime configuration."""
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure_connection(supplied_connection)
        return

    engine: Engine = create_postgres_engine(load_settings().database_url)
    try:
        with engine.connect() as connection:
            configure_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

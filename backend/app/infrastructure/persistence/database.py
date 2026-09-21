"""PostgreSQL engine construction for infrastructure adapters."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from backend.app.infrastructure.settings import SecretValue


def create_postgres_engine(database_url: SecretValue) -> Engine:
    """Create an SQLAlchemy engine without exposing the URL in representations."""
    parsed_url = make_url(database_url.reveal())
    if parsed_url.drivername == "postgresql":
        parsed_url = parsed_url.set(drivername="postgresql+psycopg")
    return create_engine(parsed_url, pool_pre_ping=True)

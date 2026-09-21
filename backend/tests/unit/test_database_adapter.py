"""Tests for PostgreSQL SQLAlchemy adapter configuration."""

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import SecretValue


def test_postgresql_scheme_uses_the_approved_psycopg_driver() -> None:
    engine = create_postgres_engine(
        SecretValue("postgresql://test_user:dummy@localhost/beautyhub_test")
    )

    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()

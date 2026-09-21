"""Real PostgreSQL smoke test for transaction rollback and database cleanliness."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.settings import load_test_database_url


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_postgres_transaction_rolls_back_and_leaves_database_clean(
    postgres_engine: Engine,
) -> None:
    table_name = f"beautyhub_rollback_probe_{uuid4().hex}"
    qualified_name = f"public.{table_name}"

    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(f"CREATE TABLE {qualified_name} (id integer PRIMARY KEY)")
            )
            connection.execute(
                text(f"INSERT INTO {qualified_name} (id) VALUES (1)")
            )
        finally:
            transaction.rollback()

    with postgres_engine.connect() as verification_connection:
        remaining_table = verification_connection.execute(
            text("SELECT to_regclass(:qualified_name)"),
            {"qualified_name": qualified_name},
        ).scalar_one()

    assert remaining_table is None

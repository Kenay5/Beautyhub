"""Tests for the dedicated PostgreSQL integration-test configuration."""

import pytest

from backend.app.infrastructure.settings import (
    ConfigurationError,
    TEST_DATABASE_URL_ENVIRONMENT_VARIABLE,
    load_test_database_url,
)


def test_loads_dedicated_postgres_test_database_url() -> None:
    database_url = "postgresql+psycopg://tester:dummy@localhost:5432/beautyhub_test"

    settings = load_test_database_url(
        {TEST_DATABASE_URL_ENVIRONMENT_VARIABLE: database_url}
    )

    assert settings.reveal() == database_url
    assert repr(settings) == "SecretValue(<redacted>)"


@pytest.mark.parametrize(
    "database_url",
    [
        "",
        "sqlite:///beautyhub_test.db",
        "postgresql+psycopg://tester:dummy@localhost:5432/beautyhub",
        "not a database URL",
    ],
)
def test_rejects_missing_or_unsafe_test_database_url(database_url: str) -> None:
    with pytest.raises(ConfigurationError) as error:
        load_test_database_url(
            {TEST_DATABASE_URL_ENVIRONMENT_VARIABLE: database_url}
        )

    assert "dummy" not in str(error.value)

"""T095 PostgreSQL evidence for all-or-none overlapping limit reservations."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, delete, func, select

from backend.app.application.admin_access.rate_limit import (
    ReserveCoordinatedAdministrativeRateLimits,
    ReserveAdministrativeRateLimit,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SystemSecretGenerator
from backend.app.application.public_request_limit import PublicRequestRateLimitError
from backend.app.domain.authentication.rate_limit import (
    ADMINISTRATIVE_RATE_LIMITS,
    AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT,
    AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT,
    APPOINTMENT_NOTIFICATION_OPERATION_LIMIT,
    SECURITY_MESSAGE_ACTION_LIMIT,
    AdministrativeRateLimitCategory,
)
from backend.app.infrastructure.persistence.admin_rate_limit_repository import (
    PostgresAdministrativeRateLimitStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import RateLimitEvent, RateLimitGuard
from backend.app.infrastructure.persistence.security_message_rate_limit_repository import (
    PostgresPublicSecurityMessageBudget,
)
from backend.app.infrastructure.settings import (
    load_cryptography_key_configuration,
    load_test_database_url,
)
from backend.app.infrastructure.security.administrative_rate_limit_subject import (
    AdministrativeRateLimitSubjectProtector,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2030, 6, 1, 10, tzinfo=timezone.utc)
ACCOUNT_SUBJECT = b"a" * 32
PUBLIC_SUBJECT = b"p" * 32
_SUBJECTS = AdministrativeRateLimitSubjectProtector(
    key_ring=CryptographyKeyRing(load_cryptography_key_configuration())
)


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.mark.integration
def test_t095_one_action_reserves_each_applicable_budget_once(
    migrated_engine: Engine,
) -> None:
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)
    outcome = _reserve(
        migrated_engine,
        (
            (AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category, ACCOUNT_SUBJECT),
            (AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category, ACCOUNT_SUBJECT),
            (SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT),
        ),
        NOW,
    )

    assert outcome.allowed
    assert _active_count(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
    ) == 1
    assert _active_count(
        migrated_engine, SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT, NOW
    ) == 1
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("exhausted_category", "capacity"),
    (
        (
            AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
            AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.capacity,
        ),
        (SECURITY_MESSAGE_ACTION_LIMIT.category, SECURITY_MESSAGE_ACTION_LIMIT.capacity),
    ),
)
def test_t095_exhausting_either_limit_consumes_neither_other_budget(
    migrated_engine: Engine,
    exhausted_category: AdministrativeRateLimitCategory,
    capacity: int,
) -> None:
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)
    _seed(migrated_engine, exhausted_category, ACCOUNT_SUBJECT, NOW, capacity)
    other_category = (
        SECURITY_MESSAGE_ACTION_LIMIT.category
        if exhausted_category
        == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category
        else AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category
    )

    outcome = _reserve(
        migrated_engine,
        (
            (AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category, ACCOUNT_SUBJECT),
            (SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT),
        ),
        NOW,
    )

    assert not outcome.allowed
    assert outcome.denied_category == exhausted_category
    assert _active_count(migrated_engine, other_category, ACCOUNT_SUBJECT, NOW) == 0
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)


@pytest.mark.integration
def test_t095_simultaneous_exhaustion_is_safe_and_adds_no_partial_events(
    migrated_engine: Engine,
) -> None:
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)
    _seed(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.capacity,
    )
    _seed(
        migrated_engine,
        SECURITY_MESSAGE_ACTION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
        SECURITY_MESSAGE_ACTION_LIMIT.capacity,
    )

    outcome = _reserve(
        migrated_engine,
        (
            (AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category, ACCOUNT_SUBJECT),
            (SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT),
        ),
        NOW,
    )

    assert not outcome.allowed
    assert outcome.denied_category == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category
    assert _active_count(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
    ) == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.capacity
    assert _active_count(
        migrated_engine, SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT, NOW
    ) == SECURITY_MESSAGE_ACTION_LIMIT.capacity
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)


@pytest.mark.integration
def test_t095_concurrent_composite_reservations_have_one_winner_and_no_partial_use(
    migrated_engine: Engine,
) -> None:
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)
    _seed(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.capacity - 1,
    )
    _seed(
        migrated_engine,
        SECURITY_MESSAGE_ACTION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
        SECURITY_MESSAGE_ACTION_LIMIT.capacity - 1,
    )
    barrier = Barrier(12)

    def attempt(_: int) -> bool:
        barrier.wait(timeout=20)
        return _reserve(
            migrated_engine,
            (
                (AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category, ACCOUNT_SUBJECT),
                (SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT),
            ),
            NOW,
        ).allowed

    with ThreadPoolExecutor(max_workers=12) as executor:
        outcomes = list(executor.map(attempt, range(12)))

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 11
    assert _active_count(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
    ) == AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.capacity
    assert _active_count(
        migrated_engine, SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT, NOW
    ) == SECURITY_MESSAGE_ACTION_LIMIT.capacity
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)


@pytest.mark.integration
def test_t095_public_ip_and_account_budgets_are_atomic_on_denial(
    migrated_engine: Engine,
) -> None:
    account_subject = _SUBJECTS.fingerprint_account(8_500_001)
    _clear_subject(migrated_engine, account_subject)
    _clear_subject(migrated_engine, PUBLIC_SUBJECT)
    _seed(
        migrated_engine,
        SECURITY_MESSAGE_ACTION_LIMIT.category,
        account_subject,
        NOW,
        SECURITY_MESSAGE_ACTION_LIMIT.capacity,
    )

    with migrated_engine.begin() as connection:
        budget = _public_message_budget(connection)
        assert not budget.reserve(account_id=8_500_001)
    assert _active_count(
        migrated_engine,
        AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.category,
        PUBLIC_SUBJECT,
        NOW,
    ) == 0

    _clear_subject(migrated_engine, account_subject)
    _seed(
        migrated_engine,
        AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.category,
        PUBLIC_SUBJECT,
        NOW,
        AUTHENTICATION_RECOVERY_LOST_FACTOR_LIMIT.capacity,
    )
    with migrated_engine.begin() as connection:
        budget = _public_message_budget(connection)
        with pytest.raises(PublicRequestRateLimitError):
            budget.reserve(account_id=8_500_001)
    assert _active_count(
        migrated_engine,
        SECURITY_MESSAGE_ACTION_LIMIT.category,
        account_subject,
        NOW,
    ) == 0
    _clear_subject(migrated_engine, PUBLIC_SUBJECT)
    _clear_subject(migrated_engine, account_subject)


@pytest.mark.integration
def test_t095_both_windows_expire_without_stranding_the_composite_action(
    migrated_engine: Engine,
) -> None:
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)


@pytest.mark.integration
def test_t098_appointment_budget_has_exact_boundary_and_serializes_a_full_burst(
    migrated_engine: Engine,
) -> None:
    subject = b"\x98" * 32
    category = APPOINTMENT_NOTIFICATION_OPERATION_LIMIT.category
    capacity = APPOINTMENT_NOTIFICATION_OPERATION_LIMIT.capacity
    _clear_subject(migrated_engine, subject)
    try:
        _seed(migrated_engine, category, subject, NOW, capacity - 1)
        assert _reserve(migrated_engine, ((category, subject),), NOW).allowed
        assert not _reserve(migrated_engine, ((category, subject),), NOW).allowed
        assert _reserve(
            migrated_engine,
            ((category, subject),),
            NOW + APPOINTMENT_NOTIFICATION_OPERATION_LIMIT.window,
        ).allowed

        _clear_subject(migrated_engine, subject)
        barrier = Barrier(capacity + 1)

        def attempt(_: int) -> bool:
            barrier.wait(timeout=20)
            return _reserve(migrated_engine, ((category, subject),), NOW).allowed

        with ThreadPoolExecutor(max_workers=capacity + 1) as executor:
            outcomes = list(executor.map(attempt, range(capacity + 1)))

        assert outcomes.count(True) == capacity
        assert outcomes.count(False) == 1
        assert _active_count(migrated_engine, category, subject, NOW) == capacity
    finally:
        _clear_subject(migrated_engine, subject)


@pytest.mark.integration
def test_t098_two_channels_for_one_action_reserve_one_appointment_slot(
    migrated_engine: Engine,
) -> None:
    subject = b"\x99" * 32
    category = APPOINTMENT_NOTIFICATION_OPERATION_LIMIT.category
    _clear_subject(migrated_engine, subject)
    try:
        # The duplicate category entries model email and WhatsApp preparations
        # belonging to one request. The coordinator gives the action one key.
        outcome = _reserve(
            migrated_engine,
            ((category, subject), (category, subject)),
            NOW,
        )
        assert outcome.allowed
        assert _active_count(migrated_engine, category, subject, NOW) == 1
    finally:
        _clear_subject(migrated_engine, subject)
    _seed(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW - timedelta(minutes=2),
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.capacity,
    )
    _seed(
        migrated_engine,
        SECURITY_MESSAGE_ACTION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW - timedelta(minutes=16),
        SECURITY_MESSAGE_ACTION_LIMIT.capacity,
    )

    outcome = _reserve(
        migrated_engine,
        (
            (AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category, ACCOUNT_SUBJECT),
            (SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT),
        ),
        NOW,
    )

    assert outcome.allowed
    assert _active_count(
        migrated_engine,
        AUTHENTICATED_ADMINISTRATIVE_OPERATION_LIMIT.category,
        ACCOUNT_SUBJECT,
        NOW,
    ) == 1
    assert _active_count(
        migrated_engine, SECURITY_MESSAGE_ACTION_LIMIT.category, ACCOUNT_SUBJECT, NOW
    ) == 1
    _clear_subject(migrated_engine, ACCOUNT_SUBJECT)


def _reserve(
    engine: Engine,
    limits: tuple[tuple[AdministrativeRateLimitCategory, bytes], ...],
    current_time: datetime,
):
    with engine.begin() as connection:
        return ReserveCoordinatedAdministrativeRateLimits(
            store=PostgresAdministrativeRateLimitStore(connection),
            clock=FixedClock(current_time),
            secret_generator=SystemSecretGenerator(),
        ).reserve(limits=limits)


def _seed(
    engine: Engine,
    category: AdministrativeRateLimitCategory,
    subject: bytes,
    current_time: datetime,
    count: int,
) -> None:
    limit = ADMINISTRATIVE_RATE_LIMITS[category]
    for index in range(count):
        with engine.begin() as connection:
            assert ReserveAdministrativeRateLimit(
                store=PostgresAdministrativeRateLimitStore(connection),
                clock=FixedClock(current_time),
            ).reserve(
                category=category,
                subject_fingerprint=subject,
                request_fingerprint=(index + 1).to_bytes(32, "big"),
            )


def _active_count(
    engine: Engine,
    category: AdministrativeRateLimitCategory,
    subject: bytes,
    current_time: datetime,
) -> int:
    limit = ADMINISTRATIVE_RATE_LIMITS[category]
    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.category == category,
                RateLimitEvent.subject_fingerprint == subject,
                RateLimitEvent.occurred_at > current_time - limit.window,
            )
        ).scalar_one()


def _clear_subject(engine: Engine, subject: bytes) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(RateLimitEvent).where(
                RateLimitEvent.subject_fingerprint == subject,
                RateLimitEvent.category.in_(tuple(ADMINISTRATIVE_RATE_LIMITS)),
            )
        )
        connection.execute(
            delete(RateLimitGuard).where(
                RateLimitGuard.subject_fingerprint == subject,
                RateLimitGuard.category.in_(tuple(ADMINISTRATIVE_RATE_LIMITS)),
            )
        )


def _public_message_budget(connection):
    from backend.app.infrastructure.persistence.security_message_rate_limit_repository import (
        PostgresPublicSecurityMessageBudget,
    )

    return PostgresPublicSecurityMessageBudget(
        connection=connection,
        public_subject_fingerprint=PUBLIC_SUBJECT,
        subject_protector=_SUBJECTS,
        clock=FixedClock(NOW),
        secret_generator=SystemSecretGenerator(),
    )

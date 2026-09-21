"""T044 PostgreSQL evidence for atomic administrative factor consumption."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, insert, select, text

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
    RecordAdministrativeCredentialFailure,
)
from backend.app.application.admin_access.login_completion import (
    CompleteAdministrativeLoginCredentials,
)
from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginValidationOutcome,
    ValidateAdministrativeLogin,
)
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.admin_login_completion_repository import (
    PostgresAdministrativeLoginFactorStore,
)
from backend.app.infrastructure.persistence.admin_login_repository import (
    PostgresAdministrativeLoginStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import (
    AdminAccount,
    AdminCredentialFailureEvent,
    AdminEmailClaim,
    RecoveryCode,
    TotpFactor,
    TotpPeriodUse,
)
from backend.app.infrastructure.security.admin_email_protection import (
    AdministrativeEmailProtector,
)
from backend.app.infrastructure.security.administrative_password_hashing import (
    AdministrativePasswordHasher,
)
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.recovery_code_protection import (
    RecoveryCodeProtector,
)
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import (
    CryptographyKeyConfiguration,
    SecretValue,
    load_test_database_url,
)


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
EMAIL = "synthetic.owner@example.test"
PASSWORD = "synthetic owner password"
SECRET = b"JBSWY3DPEHPK3PXP"
RECOVERY_ONE = "ABCD-EFGH-JKLM-NPQR"
RECOVERY_TWO = "2345-6789-ABCD-EFGH"


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE admin_accounts, owner_bootstrap_state "
                    "RESTART IDENTITY CASCADE"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO owner_bootstrap_state "
                    "(bootstrap_state_id, status) VALUES (1, 'open')"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(
                base64.urlsafe_b64encode(b"\xe1" * 32).decode("ascii")
            ),
            key_version="v1",
        )
    )


def _seed(engine: Engine) -> None:
    ring = _ring()
    email = AdministrativeEmailProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xe2" * 12,)),
    ).protect(EMAIL)
    factor_ciphertext = TotpFactorProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xe3" * 12,)),
    ).encrypt(account_id=1, secret=SECRET)
    recovery = RecoveryCodeProtector(key_ring=ring)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount)
            .values(
                role="owner",
                status="active",
                password_hash=AdministrativePasswordHasher().hash_password(PASSWORD),
            )
            .returning(AdminAccount.admin_account_id)
        ).scalar_one()
        assert account_id == 1
        connection.execute(
            insert(AdminEmailClaim).values(
                admin_account_id=account_id,
                claim_kind="current",
                lookup_digest=email.lookup_digest,
                email_ciphertext=email.email_ciphertext,
                key_version=email.key_version,
            )
        )
        connection.execute(
            insert(TotpFactor).values(
                admin_account_id=account_id,
                totp_secret_ciphertext=factor_ciphertext,
                key_version="v1",
                algorithm="SHA1",
                digits=6,
                period_seconds=30,
                status="active",
                confirmed_at=NOW,
            )
        )
        connection.execute(
            insert(RecoveryCode),
            (
                {
                    "admin_account_id": account_id,
                    "lookup_digest": recovery.digest(RECOVERY_ONE.replace("-", "")),
                    "key_version": "v1",
                    "position": 1,
                    "status": "active",
                },
                {
                    "admin_account_id": account_id,
                    "lookup_digest": recovery.digest(RECOVERY_TWO.replace("-", "")),
                    "key_version": "v1",
                    "position": 2,
                    "status": "active",
                },
            ),
        )


def _validator(connection) -> ValidateAdministrativeLogin:
    ring = _ring()
    entropy = SystemSecretGenerator()
    return ValidateAdministrativeLogin(
        store=PostgresAdministrativeLoginStore(connection),
        email_lookup=AdministrativeEmailProtector(
            key_ring=ring,
            secret_generator=entropy,
        ),
        password_verifier=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(
            key_ring=ring,
            secret_generator=entropy,
        ),
        totp=TotpAuthenticator(secret_generator=entropy),
        recovery_codes=RecoveryCodeService(
            secret_generator=entropy,
            protector=RecoveryCodeProtector(key_ring=ring),
        ),
        credential_check_guard=EnsureAdministrativeCredentialCheck(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


def _completer(connection) -> CompleteAdministrativeLoginCredentials:
    return CompleteAdministrativeLoginCredentials(
        factor_store=PostgresAdministrativeLoginFactorStore(connection),
        failure_recorder=RecordAdministrativeCredentialFailure(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


@pytest.mark.integration
def test_t044_rejection_counts_once_without_consuming_a_correct_factor(
    migrated_engine: Engine,
) -> None:
    _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        validation = _validator(connection).validate(
            email=EMAIL,
            password="wrong password",
            totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
        )
        outcome = _completer(connection).complete(validation=validation)

    with migrated_engine.connect() as connection:
        failure_count = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()
        period_count = connection.execute(
            select(func.count()).select_from(TotpPeriodUse)
        ).scalar_one()
        recovery_states = tuple(
            connection.execute(
                select(RecoveryCode.status).order_by(RecoveryCode.position)
            ).scalars()
        )

    assert not outcome.accepted
    assert failure_count == 1
    assert period_count == 0
    assert recovery_states == ("active", "active")
    assert PASSWORD not in repr(outcome)


@pytest.mark.integration
def test_t044_success_uses_only_the_presented_recovery_code(
    migrated_engine: Engine,
) -> None:
    _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        validation = _validator(connection).validate(
            email=EMAIL,
            password=PASSWORD,
            recovery_code=RECOVERY_ONE.lower(),
        )
        outcome = _completer(connection).complete(validation=validation)

    with migrated_engine.connect() as connection:
        recovery_states = tuple(
            connection.execute(
                select(RecoveryCode.position, RecoveryCode.status).order_by(
                    RecoveryCode.position
                )
            )
        )
        failure_count = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()

    assert outcome.accepted
    assert recovery_states == ((1, "used"), (2, "active"))
    assert failure_count == 0
    assert RECOVERY_ONE not in repr(outcome)


@pytest.mark.integration
def test_t044_incorrect_recovery_code_preserves_every_valid_code(
    migrated_engine: Engine,
) -> None:
    _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        validation = _validator(connection).validate(
            email=EMAIL,
            password=PASSWORD,
            recovery_code="ZZZZ-ZZZZ-ZZZZ-ZZZZ",
        )
        outcome = _completer(connection).complete(validation=validation)

    with migrated_engine.connect() as connection:
        recovery_states = tuple(
            connection.execute(
                select(RecoveryCode.status).order_by(RecoveryCode.position)
            ).scalars()
        )
        failure_count = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()

    assert not outcome.accepted
    assert recovery_states == ("active", "active")
    assert failure_count == 1


@pytest.mark.integration
def test_t044_consumption_rolls_back_with_the_surrounding_login_transaction(
    migrated_engine: Engine,
) -> None:
    _seed(migrated_engine)
    connection = migrated_engine.connect()
    transaction = connection.begin()
    try:
        validation = _validator(connection).validate(
            email=EMAIL,
            password=PASSWORD,
            totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
        )
        outcome = _completer(connection).complete(validation=validation)
        assert outcome.accepted
        transaction.rollback()
    finally:
        connection.close()

    with migrated_engine.connect() as verification:
        assert verification.execute(
            select(func.count()).select_from(TotpPeriodUse)
        ).scalar_one() == 0


@pytest.mark.integration
def test_t044_concurrent_totp_completion_allows_exactly_one_success(
    migrated_engine: Engine,
) -> None:
    _seed(migrated_engine)
    with migrated_engine.connect() as connection:
        validation = _validator(connection).validate(
            email=EMAIL,
            password=PASSWORD,
            totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
        )
    assert validation.accepted

    outcomes = _run_concurrently(
        (
            lambda: _complete_in_transaction(migrated_engine, validation),
            lambda: _complete_in_transaction(migrated_engine, validation),
        )
    )

    with migrated_engine.connect() as connection:
        period_count = connection.execute(
            select(func.count()).select_from(TotpPeriodUse)
        ).scalar_one()
        failure_count = connection.execute(
            select(func.count()).select_from(AdminCredentialFailureEvent)
        ).scalar_one()

    assert sorted(outcomes) == [False, True]
    assert period_count == 1
    assert failure_count == 1


def _run_concurrently(workers: tuple[Callable[[], bool], ...]) -> list[bool]:
    barrier = Barrier(len(workers))

    def synchronized(worker: Callable[[], bool]) -> bool:
        barrier.wait(timeout=10)
        return worker()

    with ThreadPoolExecutor(max_workers=len(workers)) as executor:
        return list(executor.map(synchronized, workers))


def _complete_in_transaction(
    engine: Engine,
    validation: AdministrativeLoginValidationOutcome,
) -> bool:
    with engine.begin() as connection:
        return _completer(connection).complete(validation=validation).accepted

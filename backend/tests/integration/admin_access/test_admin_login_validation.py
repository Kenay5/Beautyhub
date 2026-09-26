"""T043 PostgreSQL evidence for read-only administrative login validation."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, text, update

from backend.app.application.admin_access.account_security import (
    EnsureAdministrativeCredentialCheck,
)
from backend.app.application.admin_access.login_validation import ValidateAdministrativeLogin
from backend.app.application.clock import FixedClock
from backend.app.application.entropy import SequenceSecretGenerator, SystemSecretGenerator
from backend.app.infrastructure.persistence.admin_login_repository import PostgresAdministrativeLoginStore
from backend.app.infrastructure.persistence.admin_account_security_repository import (
    PostgresAdministrativeAccountSecurityStore,
)
from backend.app.infrastructure.persistence.database import create_postgres_engine
from backend.app.infrastructure.persistence.models import AdminAccount, AdminEmailClaim, RecoveryCode, TotpFactor
from backend.app.infrastructure.security.admin_email_protection import AdministrativeEmailProtector
from backend.app.infrastructure.security.administrative_password_hashing import AdministrativePasswordHasher
from backend.app.infrastructure.security.cryptography_key_ring import CryptographyKeyRing
from backend.app.infrastructure.security.recovery_code_protection import RecoveryCodeProtector
from backend.app.infrastructure.security.recovery_codes import RecoveryCodeService
from backend.app.infrastructure.security.totp import TotpAuthenticator
from backend.app.infrastructure.security.totp_factor_protection import TotpFactorProtector
from backend.app.infrastructure.settings import CryptographyKeyConfiguration, SecretValue, load_test_database_url


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)
EMAIL = "synthetic.owner@example.test"
PASSWORD = "synthetic owner password"
SECRET = b"JBSWY3DPEHPK3PXP"
RECOVERY = "ABCD-EFGH-JKLM-NPQR"


@pytest.fixture()
def migrated_engine() -> Iterator[Engine]:
    engine = create_postgres_engine(load_test_database_url())
    try:
        with engine.connect() as connection:
            config = Config(str(ROOT / "backend" / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE admin_accounts, owner_bootstrap_state RESTART IDENTITY CASCADE"))
            connection.execute(text("INSERT INTO owner_bootstrap_state (bootstrap_state_id, status) VALUES (1, 'open')"))
        yield engine
    finally:
        engine.dispose()


def _ring() -> CryptographyKeyRing:
    return CryptographyKeyRing(
        CryptographyKeyConfiguration(
            root_key=SecretValue(base64.urlsafe_b64encode(b"\xe1" * 32).decode("ascii")),
            key_version="v1",
        )
    )


def _seed(engine: Engine) -> None:
    ring = _ring()
    email = AdministrativeEmailProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xe2" * 12,)),
    ).protect(EMAIL)
    password_hash = AdministrativePasswordHasher().hash_password(PASSWORD)
    factor_ciphertext = TotpFactorProtector(
        key_ring=ring,
        secret_generator=SequenceSecretGenerator((b"\xe3" * 12,)),
    ).encrypt(account_id=1, secret=SECRET)
    recovery_digest = RecoveryCodeProtector(key_ring=ring).digest(RECOVERY.replace("-", ""))
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(AdminAccount).values(role="owner", status="active", password_hash=password_hash).returning(AdminAccount.admin_account_id)
        ).scalar_one()
        assert account_id == 1
        connection.execute(insert(AdminEmailClaim).values(admin_account_id=account_id, claim_kind="current", lookup_digest=email.lookup_digest, email_ciphertext=email.email_ciphertext, key_version=email.key_version))
        connection.execute(insert(TotpFactor).values(admin_account_id=account_id, totp_secret_ciphertext=factor_ciphertext, key_version="v1", algorithm="SHA1", digits=6, period_seconds=30, status="active", confirmed_at=NOW))
        connection.execute(insert(RecoveryCode).values(admin_account_id=account_id, lookup_digest=recovery_digest, key_version="v1", position=1, status="active"))


def _validator(connection) -> ValidateAdministrativeLogin:
    ring = _ring()
    return ValidateAdministrativeLogin(
        store=PostgresAdministrativeLoginStore(connection),
        email_lookup=AdministrativeEmailProtector(key_ring=ring, secret_generator=SystemSecretGenerator()),
        password_verifier=AdministrativePasswordHasher(),
        factor_protector=TotpFactorProtector(key_ring=ring, secret_generator=SystemSecretGenerator()),
        totp=TotpAuthenticator(secret_generator=SystemSecretGenerator()),
        recovery_codes=RecoveryCodeService(secret_generator=SystemSecretGenerator(), protector=RecoveryCodeProtector(key_ring=ring)),
        credential_check_guard=EnsureAdministrativeCredentialCheck(
            store=PostgresAdministrativeAccountSecurityStore(connection),
            clock=FixedClock(NOW),
        ),
        clock=FixedClock(NOW),
    )


@pytest.mark.integration
def test_t043_postgres_validates_either_factor_without_consuming_or_creating_state(migrated_engine: Engine) -> None:
    _seed(migrated_engine)
    with migrated_engine.connect() as connection:
        validator = _validator(connection)
        totp_outcome = validator.validate(email=EMAIL, password=PASSWORD, totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW))
        recovery_outcome = validator.validate(email=EMAIL, password=PASSWORD, recovery_code=RECOVERY.lower())
        state = connection.execute(text("SELECT (SELECT count(*) FROM totp_period_uses), (SELECT status FROM recovery_codes), (SELECT count(*) FROM admin_sessions)")).one()

    assert totp_outcome.accepted
    assert recovery_outcome.accepted
    assert tuple(state) == (0, "active", 0)


@pytest.mark.integration
def test_t043_postgres_returns_the_same_rejection_for_unknown_account_and_wrong_credentials(migrated_engine: Engine) -> None:
    _seed(migrated_engine)
    with migrated_engine.connect() as connection:
        validator = _validator(connection)
        outcomes = (
            validator.validate(email="unknown@example.test", password=PASSWORD, totp_code="123456"),
            validator.validate(email=EMAIL, password="wrong password", totp_code="123456"),
            validator.validate(email=EMAIL, password=PASSWORD, totp_code="000000"),
            validator.validate(email=EMAIL, password=PASSWORD),
            validator.validate(email=EMAIL, password=PASSWORD, totp_code="123456", recovery_code=RECOVERY),
        )

    assert {outcome.rejection for outcome in outcomes} == {"invalid_credentials"}
    assert all(outcome.validated is None for outcome in outcomes)


@pytest.mark.integration
@pytest.mark.parametrize("credential_state", ["absent", "invalidated"])
def test_t071_login_never_bypasses_missing_or_invalidated_second_factors(
    migrated_engine: Engine,
    credential_state: str,
) -> None:
    _seed(migrated_engine)
    with migrated_engine.begin() as connection:
        if credential_state == "absent":
            connection.execute(
                text("DELETE FROM recovery_codes WHERE admin_account_id = 1")
            )
            connection.execute(
                text("DELETE FROM totp_factors WHERE admin_account_id = 1")
            )
        else:
            connection.execute(
                update(TotpFactor)
                .where(TotpFactor.admin_account_id == 1)
                .values(
                    status="invalidated",
                    totp_secret_ciphertext=None,
                    key_version=None,
                    invalidated_at=NOW,
                )
            )
            connection.execute(
                update(RecoveryCode)
                .where(RecoveryCode.admin_account_id == 1)
                .values(status="invalidated", invalidated_at=NOW)
            )

    with migrated_engine.connect() as connection:
        validator = _validator(connection)
        outcomes = (
            validator.validate(email=EMAIL, password=PASSWORD),
            validator.validate(
                email=EMAIL,
                password=PASSWORD,
                totp_code=pyotp.TOTP(SECRET.decode("ascii")).at(NOW),
            ),
            validator.validate(
                email=EMAIL,
                password=PASSWORD,
                recovery_code=RECOVERY,
            ),
        )
        state = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM admin_sessions), "
                "(SELECT count(*) FROM totp_period_uses)"
            )
        ).one()

    assert {outcome.rejection for outcome in outcomes} == {"invalid_credentials"}
    assert all(outcome.validated is None for outcome in outcomes)
    assert tuple(state) == (0, 0)

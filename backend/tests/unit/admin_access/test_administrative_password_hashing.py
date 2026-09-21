"""T023 unit evidence for non-recoverable Argon2id administrative passwords."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher
from argon2.low_level import Type

from backend.app.infrastructure.security.administrative_password_hashing import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    AdministrativePasswordHashError,
    AdministrativePasswordHasher,
    PasswordVerification,
)


def test_t023_generates_distinct_argon2id_salts_that_both_verify() -> None:
    password_hasher = AdministrativePasswordHasher()
    password = "synthetic administrative phrase 2030"

    first_hash = password_hasher.hash_password(password)
    second_hash = password_hasher.hash_password(password)

    assert first_hash != second_hash
    assert first_hash.startswith("$argon2id$")
    assert f"m={ARGON2_MEMORY_COST_KIB},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}" in first_hash
    assert password not in first_hash
    assert password_hasher.verify_and_upgrade(
        stored_hash=first_hash, password=password
    ) == PasswordVerification(verified=True, upgraded_hash=None)
    assert password_hasher.verify_and_upgrade(
        stored_hash=second_hash, password=password
    ) == PasswordVerification(verified=True, upgraded_hash=None)


def test_t023_never_returns_a_clear_password_or_accepts_an_incorrect_one() -> None:
    password_hasher = AdministrativePasswordHasher()
    stored_hash = password_hasher.hash_password("synthetic administrative phrase 2030")

    result = password_hasher.verify_and_upgrade(
        stored_hash=stored_hash, password="different synthetic phrase 2030"
    )

    assert result == PasswordVerification(verified=False, upgraded_hash=None)
    assert "password" not in PasswordVerification.__dataclass_fields__


def test_t023_rehashes_an_old_argon2id_hash_only_after_successful_verification() -> None:
    old_hasher = PasswordHasher(
        time_cost=1,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        type=Type.ID,
    )
    password_hasher = AdministrativePasswordHasher()
    password = "synthetic administrative phrase 2030"
    old_hash = old_hasher.hash(password)

    result = password_hasher.verify_and_upgrade(
        stored_hash=old_hash, password=password
    )

    assert result.verified is True
    assert result.upgraded_hash is not None
    assert result.upgraded_hash != old_hash
    assert password_hasher.verify_and_upgrade(
        stored_hash=result.upgraded_hash, password=password
    ).verified is True


def test_t023_does_not_rehash_when_the_supplied_password_is_incorrect() -> None:
    password_hasher = AdministrativePasswordHasher()
    old_hash = PasswordHasher(
        time_cost=1,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
        type=Type.ID,
    ).hash("synthetic administrative phrase 2030")

    result = password_hasher.verify_and_upgrade(
        stored_hash=old_hash, password="incorrect synthetic phrase 2030"
    )

    assert result == PasswordVerification(verified=False, upgraded_hash=None)


def test_t023_performs_dummy_work_for_an_unknown_account() -> None:
    password_hasher = AdministrativePasswordHasher()

    result = password_hasher.verify_unknown_account(
        password="synthetic administrative phrase 2030"
    )

    assert result == PasswordVerification(verified=False, upgraded_hash=None)


@pytest.mark.parametrize("value", (None, 12), ids=("none", "number"))
def test_t023_rejects_non_string_values_without_coercion(value: object) -> None:
    password_hasher = AdministrativePasswordHasher()

    with pytest.raises(AdministrativePasswordHashError):
        password_hasher.hash_password(value)  # type: ignore[arg-type]

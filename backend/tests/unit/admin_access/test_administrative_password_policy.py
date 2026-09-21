"""T022 unit evidence for approved administrative-password validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.application.clock import FixedClock
from backend.app.domain.authentication.password_policy import (
    AdministrativePasswordValidationError,
    validate_administrative_password,
)
from backend.app.infrastructure.security.blocked_passwords import (
    BLOCKED_PASSWORDS_ENTRY_COUNT,
    BlockedPasswordList,
    BlockedPasswordListError,
)


def _clock(*, year: int = 2030, month: int = 1, day: int = 1) -> FixedClock:
    return FixedClock(datetime(year, month, day, 18, tzinfo=timezone.utc))


def _write_list(
    directory: Path,
    *,
    hashes: list[str],
    review_due: str = "2030-04-01",
    checksum: str | None = None,
) -> None:
    content = ("\n".join(hashes) + "\n").encode("ascii")
    (directory / "blocked_passwords.sha1").write_bytes(content)
    (directory / "blocked_passwords.metadata.json").write_text(
        json.dumps(
            {
                "entry_count": BLOCKED_PASSWORDS_ENTRY_COUNT,
                "sha256": checksum or hashlib.sha256(content).hexdigest().upper(),
                "review_due": review_due,
            }
        ),
        encoding="utf-8",
    )


def _valid_hashes(*, first: str | None = None) -> list[str]:
    hashes = [
        f"{value:040X}" for value in range(1, BLOCKED_PASSWORDS_ENTRY_COUNT + 1)
    ]
    if first is not None:
        hashes[0] = first
    return hashes


@pytest.mark.parametrize(
    "password",
    (
        "simple phrase",
        "lowercase phrase only",
        "UPPERCASE PHRASE ONLY",
        "frase con espacios 2026",
        "contraseña con ñ válida",
    ),
)
def test_t022_accepts_passwords_without_composition_rules(
    tmp_path: Path, password: str
) -> None:
    _write_list(tmp_path, hashes=_valid_hashes())
    blocked_passwords = BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())

    validate_administrative_password(password, blocked_passwords=blocked_passwords)


@pytest.mark.parametrize(
    "password",
    ("a" * 11, "a" * 129, " " * 12, "\t" * 12),
    ids=("below-minimum", "above-maximum", "only-spaces", "only-whitespace"),
)
def test_t022_rejects_only_out_of_range_or_whitespace_only_passwords(
    tmp_path: Path, password: str
) -> None:
    _write_list(tmp_path, hashes=_valid_hashes())
    blocked_passwords = BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())

    with pytest.raises(AdministrativePasswordValidationError):
        validate_administrative_password(password, blocked_passwords=blocked_passwords)


def test_t022_accepts_both_exact_length_boundaries(tmp_path: Path) -> None:
    _write_list(tmp_path, hashes=_valid_hashes())
    blocked_passwords = BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())

    validate_administrative_password("a" * 12, blocked_passwords=blocked_passwords)
    validate_administrative_password("a" * 128, blocked_passwords=blocked_passwords)


def test_t022_blocks_only_the_exact_received_password_without_normalizing_it(
    tmp_path: Path,
) -> None:
    blocked = "Exact phrase 2026"
    blocked_hash = hashlib.sha1(blocked.encode("utf-8")).hexdigest().upper()
    _write_list(tmp_path, hashes=_valid_hashes(first=blocked_hash))
    blocked_passwords = BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())

    with pytest.raises(AdministrativePasswordValidationError):
        validate_administrative_password(blocked, blocked_passwords=blocked_passwords)
    validate_administrative_password(
        "exact phrase 2026", blocked_passwords=blocked_passwords
    )


def test_t022_fails_safely_when_the_list_is_missing(tmp_path: Path) -> None:
    with pytest.raises(BlockedPasswordListError):
        BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())


def test_t022_fails_safely_when_the_list_checksum_is_corrupt(tmp_path: Path) -> None:
    _write_list(tmp_path, hashes=_valid_hashes(), checksum="0" * 64)

    with pytest.raises(BlockedPasswordListError):
        BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())


def test_t022_fails_safely_on_the_exact_review_due_date(tmp_path: Path) -> None:
    _write_list(tmp_path, hashes=_valid_hashes(), review_due="2030-01-01")
    blocked_passwords = BlockedPasswordList.load(resource_directory=tmp_path, clock=_clock())

    with pytest.raises(BlockedPasswordListError):
        validate_administrative_password(
            "still a valid phrase", blocked_passwords=blocked_passwords
        )


def test_t022_does_not_apply_an_age_based_password_expiry(tmp_path: Path) -> None:
    _write_list(tmp_path, hashes=_valid_hashes(), review_due="2100-01-01")
    blocked_passwords = BlockedPasswordList.load(
        resource_directory=tmp_path, clock=_clock(year=2099)
    )

    validate_administrative_password(
        "a password without periodic expiry", blocked_passwords=blocked_passwords
    )


def test_t022_loads_the_committed_password_list_before_its_review_date() -> None:
    blocked_passwords = BlockedPasswordList.load(clock=_clock(year=2026, month=9, day=18))

    validate_administrative_password(
        "BeautyHub unique administrative phrase 2030", blocked_passwords=blocked_passwords
    )

"""T025 unit evidence for the approved RFC 6238 TOTP primitive."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.application.entropy import SequenceSecretGenerator
from backend.app.infrastructure.security.totp import (
    TOTP_PERIOD_SECONDS,
    TotpAuthenticator,
    TotpError,
)


SECRET = b"GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
NOW = datetime(1970, 1, 1, 0, 1, tzinfo=timezone.utc)


def _authenticator() -> TotpAuthenticator:
    return TotpAuthenticator(secret_generator=SequenceSecretGenerator([b"\x51" * 20]))


def test_t025_generates_a_160_bit_base32_totp_secret() -> None:
    secret = _authenticator().generate_secret()

    assert secret == b"KFIVCUKRKFIVCUKRKFIVCUKRKFIVCUKR"
    assert len(secret) == 32
    assert b"=" not in secret


@pytest.mark.parametrize(
    ("code", "expected_counter"),
    (
        ("287082", 1),
        ("359152", 2),
        ("969429", 3),
    ),
    ids=("previous", "current", "next"),
)
def test_t025_accepts_only_the_adjacent_totp_periods(
    code: str, expected_counter: int
) -> None:
    result = _authenticator().verify(secret=SECRET, code=code, now=NOW)

    assert result == expected_counter


@pytest.mark.parametrize("code", ("755224", "338314", "12345", "1234567", "ABCDEF"))
def test_t025_rejects_codes_outside_the_window_or_wrong_format(code: str) -> None:
    result = _authenticator().verify(secret=SECRET, code=code, now=NOW)

    assert result is None


def test_t025_rejects_a_period_already_committed_by_a_successful_operation() -> None:
    result = _authenticator().verify(
        secret=SECRET,
        code="359152",
        now=NOW,
        used_period_counters={2},
    )

    assert result is None


def test_t025_does_not_consume_a_valid_period_while_verifying() -> None:
    used_period_counters: set[int] = set()

    result = _authenticator().verify(
        secret=SECRET,
        code="359152",
        now=NOW,
        used_period_counters=used_period_counters,
    )

    assert result == 2
    assert used_period_counters == set()
    assert TOTP_PERIOD_SECONDS == 30


@pytest.mark.parametrize(
    ("secret", "code", "now"),
    (
        (b"not-base32!", "359152", NOW),
        (SECRET, "359152", datetime(1970, 1, 1)),
    ),
)
def test_t025_rejects_invalid_secret_or_clock_input(
    secret: bytes, code: str, now: datetime
) -> None:
    with pytest.raises(TotpError):
        _authenticator().verify(secret=secret, code=code, now=now)

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.application.clock import FixedClock, SystemClock
from backend.app.application.entropy import (
    SequenceSecretGenerator,
    SystemSecretGenerator,
)


FIXED_INSTANT = datetime(2026, 9, 13, 15, 30, tzinfo=timezone.utc)


def test_fixed_clock_returns_the_configured_aware_instant() -> None:
    clock = FixedClock(FIXED_INSTANT)

    assert clock.now() == FIXED_INSTANT


def test_fixed_clock_rejects_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="aware datetime"):
        FixedClock(datetime(2026, 9, 13, 15, 30))


def test_system_clock_returns_an_aware_utc_instant() -> None:
    instant = SystemClock().now()

    assert instant.tzinfo is timezone.utc


def test_system_secret_generator_returns_the_requested_number_of_bytes() -> None:
    token = SystemSecretGenerator().token_bytes(16)

    assert len(token) == 16


@pytest.mark.parametrize("size", [0, -1])
def test_secret_generators_reject_non_positive_sizes(size: int) -> None:
    generators = (
        SystemSecretGenerator(),
        SequenceSecretGenerator([b"\x00" * 16]),
    )

    for generator in generators:
        with pytest.raises(ValueError, match="greater than zero"):
            generator.token_bytes(size)


def test_sequence_secret_generator_returns_controlled_values_in_order() -> None:
    first_token = b"\x01" * 16
    second_token = b"\x02" * 16
    generator = SequenceSecretGenerator([first_token, second_token])

    assert generator.token_bytes(16) == first_token
    assert generator.token_bytes(16) == second_token


def test_sequence_secret_generator_rejects_an_incorrect_fixture_size_without_consuming_it() -> None:
    token = b"\x03" * 16
    generator = SequenceSecretGenerator([token])

    with pytest.raises(ValueError, match="does not match"):
        generator.token_bytes(32)

    assert generator.token_bytes(16) == token


def test_sequence_secret_generator_rejects_exhausted_test_entropy() -> None:
    generator = SequenceSecretGenerator([])

    with pytest.raises(RuntimeError, match="No deterministic secret"):
        generator.token_bytes(16)

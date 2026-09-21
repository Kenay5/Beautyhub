"""T044 unit evidence for complete-only administrative factor consumption."""

from datetime import datetime, timezone

from backend.app.application.admin_access.login_completion import (
    CompleteAdministrativeLoginCredentials,
)
from backend.app.application.admin_access.login_validation import (
    AdministrativeLoginValidationOutcome,
    INVALID_LOGIN_REJECTION,
    ValidatedAdministrativeLogin,
)
from backend.app.application.clock import FixedClock


NOW = datetime(2034, 1, 2, 12, tzinfo=timezone.utc)


class FactorStore:
    def __init__(self, *, consumed: bool = True) -> None:
        self.consumed = consumed
        self.calls = []

    def consume_validated_factor(self, *, validated, current_time):
        self.calls.append((validated, current_time))
        return self.consumed


class FailureRecorder:
    def __init__(self) -> None:
        self.calls = []

    def record(self, *, account_id, operation):
        self.calls.append((account_id, operation))


def _completion(*, factor_store=None, failure_recorder=None):
    return CompleteAdministrativeLoginCredentials(
        factor_store=factor_store or FactorStore(),
        failure_recorder=failure_recorder or FailureRecorder(),
        clock=FixedClock(NOW),
    )


def test_t044_rejected_known_account_records_one_failure_and_preserves_factor() -> None:
    factors = FactorStore()
    failures = FailureRecorder()
    validation = AdministrativeLoginValidationOutcome(
        rejection=INVALID_LOGIN_REJECTION,
        rejected_account_id=7,
    )

    outcome = _completion(
        factor_store=factors,
        failure_recorder=failures,
    ).complete(validation=validation)

    assert not outcome.accepted
    assert outcome.rejection == INVALID_LOGIN_REJECTION
    assert failures.calls == [(7, "login")]
    assert factors.calls == []


def test_t044_rejected_unknown_account_preserves_factor_without_account_event() -> None:
    factors = FactorStore()
    failures = FailureRecorder()

    outcome = _completion(
        factor_store=factors,
        failure_recorder=failures,
    ).complete(
        validation=AdministrativeLoginValidationOutcome(
            rejection=INVALID_LOGIN_REJECTION
        )
    )

    assert not outcome.accepted
    assert failures.calls == []
    assert factors.calls == []


def test_t046_blocked_rejection_does_not_record_an_additional_failure() -> None:
    factors = FactorStore()
    failures = FailureRecorder()

    outcome = _completion(
        factor_store=factors,
        failure_recorder=failures,
    ).complete(
        validation=AdministrativeLoginValidationOutcome(
            rejection=INVALID_LOGIN_REJECTION,
            rejected_account_id=7,
            records_failure=False,
        )
    )

    assert not outcome.accepted
    assert factors.calls == []
    assert failures.calls == []


def test_t044_success_consumes_exactly_the_validated_factor_without_failure() -> None:
    factors = FactorStore()
    failures = FailureRecorder()
    proof = ValidatedAdministrativeLogin(
        account_id=7,
        role="owner",
        factor_id=9,
        totp_period_counter=123,
    )

    outcome = _completion(
        factor_store=factors,
        failure_recorder=failures,
    ).complete(
        validation=AdministrativeLoginValidationOutcome(validated=proof)
    )

    assert outcome.accepted
    assert (outcome.account_id, outcome.role) == (7, "owner")
    assert factors.calls == [(proof, NOW)]
    assert failures.calls == []


def test_t044_contested_factor_is_rejected_and_counts_once() -> None:
    factors = FactorStore(consumed=False)
    failures = FailureRecorder()
    proof = ValidatedAdministrativeLogin(
        account_id=7,
        role="staff",
        factor_id=9,
        recovery_code_digest=b"\x44" * 32,
    )

    outcome = _completion(
        factor_store=factors,
        failure_recorder=failures,
    ).complete(
        validation=AdministrativeLoginValidationOutcome(validated=proof)
    )

    assert not outcome.accepted
    assert outcome.rejection == INVALID_LOGIN_REJECTION
    assert failures.calls == [(7, "login")]

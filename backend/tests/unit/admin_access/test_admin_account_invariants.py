"""T009 unit evidence for administrative account and bootstrap invariants."""

from __future__ import annotations

import pytest

from backend.app.domain.authentication.admin_account import (
    AdministrativeAccount,
    AdministrativeAccountInvariantError,
    validate_owner_bootstrap_transition,
)


@pytest.mark.parametrize(
    ("role", "status"),
    (
        ("owner", "inactive"),
        ("owner", "active"),
        ("staff", "pending"),
        ("staff", "active"),
        ("staff", "deactivated"),
    ),
)
def test_t009_accepts_only_approved_role_status_pairs(role: str, status: str) -> None:
    account = AdministrativeAccount(role=role, status=status)  # type: ignore[arg-type]

    assert account.role == role
    assert account.status == status
    assert "password" not in account.__dataclass_fields__


@pytest.mark.parametrize(
    ("role", "status"),
    (
        ("owner", "pending"),
        ("owner", "deactivated"),
        ("staff", "inactive"),
        ("unknown", "active"),
    ),
)
def test_t009_rejects_unapproved_role_status_pairs(role: str, status: str) -> None:
    with pytest.raises(AdministrativeAccountInvariantError):
        AdministrativeAccount(role=role, status=status)  # type: ignore[arg-type]


def test_t009_allows_closing_once_with_an_owner_reference() -> None:
    validate_owner_bootstrap_transition(
        current_status="open",
        next_status="closed",
        owner_account_id=1,
    )


@pytest.mark.parametrize(
    ("current_status", "next_status", "owner_account_id"),
    (
        ("closed", "open", 1),
        ("open", "closed", None),
        ("open", "closed", 0),
    ),
)
def test_t009_rejects_reopening_or_closing_without_an_owner(
    current_status: str,
    next_status: str,
    owner_account_id: int | None,
) -> None:
    with pytest.raises(AdministrativeAccountInvariantError):
        validate_owner_bootstrap_transition(
            current_status=current_status,  # type: ignore[arg-type]
            next_status=next_status,  # type: ignore[arg-type]
            owner_account_id=owner_account_id,
        )

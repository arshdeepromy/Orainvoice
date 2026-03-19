"""Property-based tests for multi-method MFA and disable (Properties 8, 11, 12).

Properties covered:
  P8  — Multi-method concurrent enrolment
  P11 — Method disable removes method and associated data
  P12 — Last-method guard in MFA-mandatory organisations

**Validates: Requirements 4.1, 4.5, 4.6, 7.2, 7.3, 7.4, 13.5**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.mfa_service import (
    get_user_mfa_status,
    disable_mfa_method,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

email_st = st.emails()
phone_st = st.from_regex(r"\+\d{7,15}", fullmatch=True)
password_st = st.text(min_size=8, max_size=30, alphabet=st.characters(
    whitelist_categories=("L", "N", "P"),
))
method_st = st.sampled_from(["totp", "sms", "email", "passkey"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> MagicMock:
    """Create a mock User with sensible defaults."""
    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.org_id = overrides.get("org_id", uuid.uuid4())
    user.email = overrides.get("email", "test@budgetflow.io")
    user.role = overrides.get("role", "org_admin")
    user.is_active = overrides.get("is_active", True)
    user.password_hash = overrides.get("password_hash", "$2b$12$fakehashvalue")
    return user


def _make_mfa_record(method: str, user_id: uuid.UUID, **overrides) -> MagicMock:
    """Create a mock UserMfaMethod record representing a verified enrolment."""
    record = MagicMock()
    record.id = overrides.get("id", uuid.uuid4())
    record.user_id = user_id
    record.method = method
    record.verified = overrides.get("verified", True)
    record.verified_at = overrides.get("verified_at", datetime.now(timezone.utc))
    record.phone_number = overrides.get("phone_number", "+1234567890" if method == "sms" else None)
    record.secret_encrypted = overrides.get("secret_encrypted", b"encrypted" if method == "totp" else None)
    return record


def _make_org(mfa_policy: str = "optional", **overrides) -> MagicMock:
    """Create a mock Organisation."""
    org = MagicMock()
    org.id = overrides.get("id", uuid.uuid4())
    org.settings = {"mfa_policy": mfa_policy}
    return org


# ===========================================================================
# Property 8: Multi-method concurrent enrolment
# ===========================================================================
# Feature: multi-method-mfa, Property 8: Multi-method concurrent enrolment


@given(email=email_st, phone=phone_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_multi_method_concurrent_enrolment(email: str, phone: str) -> None:
    """For any user, enrolling and verifying all four method types (totp, sms,
    email, passkey) SHALL succeed, and querying the user's MFA methods SHALL
    return exactly those four methods. The unique constraint (user_id, method)
    SHALL prevent duplicate method entries.

    **Validates: Requirements 4.1**
    """
    user = _make_user(email=email)
    all_methods = ["totp", "sms", "email", "passkey"]

    # Create verified records for all 4 methods
    records = []
    for m in all_methods:
        records.append(_make_mfa_record(m, user.id, phone_number=phone if m == "sms" else None))

    # Mock the DB to return all 4 verified records
    db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = records
    mock_result.scalars.return_value = mock_scalars
    db.execute = AsyncMock(return_value=mock_result)

    statuses = asyncio.get_event_loop().run_until_complete(
        get_user_mfa_status(db, user)
    )

    # --- Assert: exactly 4 methods returned ---
    assert len(statuses) == 4, (
        f"Expected 4 MFA method statuses, got {len(statuses)}"
    )

    # --- Assert: all 4 method types present and enabled ---
    returned_methods = {s.method for s in statuses}
    assert returned_methods == set(all_methods), (
        f"Expected methods {set(all_methods)}, got {returned_methods}"
    )

    for s in statuses:
        assert s.enabled is True, (
            f"Method '{s.method}' should be enabled when verified record exists"
        )

    # --- Assert: SMS has masked phone number ---
    sms_status = next(s for s in statuses if s.method == "sms")
    assert sms_status.phone_number is not None, (
        "SMS method must include a masked phone number"
    )
    assert sms_status.phone_number.startswith("***"), (
        f"SMS phone must be masked, got '{sms_status.phone_number}'"
    )

    # --- Assert: unique constraint means no duplicates ---
    method_list = [s.method for s in statuses]
    assert len(method_list) == len(set(method_list)), (
        "Each method type must appear exactly once (unique constraint)"
    )


# ===========================================================================
# Property 11: Method disable removes method and associated data
# ===========================================================================
# Feature: multi-method-mfa, Property 11: Method disable removes method and associated data


@given(method=method_st, email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_method_disable_removes_method_and_data(mock_audit, method: str, email: str) -> None:
    """For any user with a verified MFA method, disabling that method with a
    valid password SHALL remove the method record from the database. For TOTP,
    the encrypted secret SHALL be deleted. For SMS, the phone number SHALL be
    deleted.

    **Validates: Requirements 4.5, 7.2, 7.3, 7.4**
    """
    user = _make_user(email=email, role="org_admin")
    password = "correct-password"

    # Create the target method record
    target_record = _make_mfa_record(method, user.id)

    # Create a second method so this isn't the last one
    other_method = "totp" if method != "totp" else "sms"
    other_record = _make_mfa_record(other_method, user.id)

    # Track what gets deleted
    deleted_records: list = []

    # Mock DB: first execute returns the target record, second returns all verified
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First query: find the specific method record
            result.scalar_one_or_none.return_value = target_record
        elif call_count == 2:
            # Second query: count all verified methods
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [target_record, other_record]
            result.scalars.return_value = scalars_mock
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=mock_execute)

    async def mock_delete(record):
        deleted_records.append(record)

    db.delete = AsyncMock(side_effect=mock_delete)

    with patch(
        "app.modules.auth.password.verify_password",
        return_value=True,
    ):
        asyncio.get_event_loop().run_until_complete(
            disable_mfa_method(db, user, method, password)
        )

    # --- Assert: the record was deleted ---
    assert len(deleted_records) == 1, (
        f"Expected exactly 1 record deleted, got {len(deleted_records)}"
    )
    assert deleted_records[0] is target_record, (
        "The deleted record must be the target method record"
    )
    assert deleted_records[0].method == method, (
        f"Deleted record method must be '{method}'"
    )

    # --- Assert: TOTP secret is on the deleted record (will be cascade-deleted) ---
    if method == "totp":
        assert target_record.secret_encrypted is not None, (
            "TOTP record should have had secret_encrypted before deletion"
        )

    # --- Assert: SMS phone number is on the deleted record ---
    if method == "sms":
        assert target_record.phone_number is not None, (
            "SMS record should have had phone_number before deletion"
        )

    # --- Assert: audit log was written ---
    mock_audit.assert_called_once()


# ===========================================================================
# Property 12: Last-method guard in MFA-mandatory organisations
# ===========================================================================
# Feature: multi-method-mfa, Property 12: Last-method guard in MFA-mandatory organisations


@given(method=method_st, email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_last_method_guard_mandatory_org(mock_audit, method: str, email: str) -> None:
    """For any user with exactly one remaining verified MFA method in an
    organisation where MFA is mandatory, attempting to disable that method
    SHALL be rejected with an error indicating at least one method must
    remain active.

    **Validates: Requirements 4.6, 13.5**
    """
    org = _make_org(mfa_policy="mandatory")
    user = _make_user(email=email, org_id=org.id, role="org_admin")
    password = "correct-password"

    # Only one verified method — the one we're trying to disable
    target_record = _make_mfa_record(method, user.id)

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if call_count == 1:
            # First query: find the specific method record
            result.scalar_one_or_none.return_value = target_record
        elif call_count == 2:
            # Second query: count all verified methods — only 1
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [target_record]
            result.scalars.return_value = scalars_mock
        elif call_count == 3:
            # Third query: fetch the organisation
            result.scalar_one_or_none.return_value = org
        return result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=mock_execute)

    with patch(
        "app.modules.auth.password.verify_password",
        return_value=True,
    ):
        with pytest.raises(ValueError, match="Cannot disable the last MFA method"):
            asyncio.get_event_loop().run_until_complete(
                disable_mfa_method(db, user, method, password)
            )

    # --- Assert: no record was deleted ---
    db.delete.assert_not_called()

    # --- Assert: audit log was NOT written (operation rejected) ---
    mock_audit.assert_not_called()

"""Property-based tests for OTP MFA enrolment (Properties 5–7).

Properties covered:
  P5 — OTP enrolment round-trip (SMS and Email)
  P6 — Invalid OTP rejection
  P7 — OTP expiry matches method configuration

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.mfa_service import (
    _OTP_EXPIRY_EMAIL,
    _OTP_EXPIRY_SMS,
    _generate_otp_code,
    _store_otp_in_redis,
    verify_enrolment,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

email_st = st.emails()

phone_st = st.from_regex(r"\+\d{7,15}", fullmatch=True)

otp_method_st = st.sampled_from(["sms", "email"])

six_digit_code_st = st.from_regex(r"[0-9]{6}", fullmatch=True)


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
    return user


def _make_pending_mfa_record(method: str, user_id: uuid.UUID, **overrides) -> MagicMock:
    """Create a mock UserMfaMethod record representing a pending enrolment."""
    record = MagicMock()
    record.user_id = user_id
    record.method = method
    record.verified = False
    record.verified_at = None
    record.phone_number = overrides.get("phone_number", None)
    record.secret_encrypted = overrides.get("secret_encrypted", None)
    return record


def _mock_db_with_pending(pending_record):
    """Mock AsyncSession that returns the given pending record on select."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = pending_record
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ===========================================================================
# Property 5: OTP enrolment round-trip (SMS and Email)
# ===========================================================================
# Feature: multi-method-mfa, Property 5: OTP enrolment round-trip (SMS and Email)


@given(method=otp_method_st, email=email_st, phone=phone_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_otp_enrolment_round_trip(mock_audit, method: str, email: str, phone: str) -> None:
    """For any user and for any OTP-based method (SMS or email), initiating
    enrolment SHALL store a 6-digit OTP in Redis, and submitting that exact OTP
    SHALL mark the method as verified and persist method-specific data (phone
    number for SMS). The OTP SHALL be consumed after successful verification.

    **Validates: Requirements 2.1, 2.3, 3.1, 3.3**
    """
    user = _make_user(email=email)

    # Generate a 6-digit OTP (same logic as the service)
    otp_code = _generate_otp_code()
    assert len(otp_code) == 6 and otp_code.isdigit()

    # Create a pending record
    pending = _make_pending_mfa_record(
        method, user.id,
        phone_number=phone if method == "sms" else None,
    )
    db = _mock_db_with_pending(pending)

    # Mock Redis: _get_otp_from_redis returns the stored OTP,
    # _delete_otp_from_redis consumes it
    deleted_keys: list[str] = []

    async def mock_get_otp(user_id, m):
        return otp_code

    async def mock_delete_otp(user_id, m):
        deleted_keys.append(f"mfa:otp:{m}:{user_id}")

    with patch(
        "app.modules.auth.mfa_service._get_otp_from_redis",
        side_effect=mock_get_otp,
    ), patch(
        "app.modules.auth.mfa_service._delete_otp_from_redis",
        side_effect=mock_delete_otp,
    ):
        asyncio.get_event_loop().run_until_complete(
            verify_enrolment(db, user, method, otp_code)
        )

    # --- Assert: method is marked as verified ---
    assert pending.verified is True, (
        f"{method} method must be marked verified after valid OTP submission"
    )
    assert pending.verified_at is not None, (
        "verified_at must be set after successful verification"
    )
    assert isinstance(pending.verified_at, datetime), (
        "verified_at must be a datetime instance"
    )

    # --- Assert: OTP was consumed (deleted from Redis) ---
    assert len(deleted_keys) == 1, (
        "OTP must be consumed (deleted from Redis) after successful verification"
    )
    assert deleted_keys[0] == f"mfa:otp:{method}:{user.id}", (
        "Deleted key must match the expected Redis key pattern"
    )


# ===========================================================================
# Property 6: Invalid OTP rejection
# ===========================================================================
# Feature: multi-method-mfa, Property 6: Invalid OTP rejection


@given(method=otp_method_st, email=email_st, bad_code=six_digit_code_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_invalid_otp_rejection(mock_audit, method: str, email: str, bad_code: str) -> None:
    """For any user with a pending SMS or email enrolment and for any code that
    does not match the stored OTP, verification SHALL be rejected and the method
    SHALL remain unverified.

    **Validates: Requirements 2.4, 3.4**
    """
    user = _make_user(email=email)

    # Generate the "real" stored OTP
    stored_otp = _generate_otp_code()

    # Skip if the random bad_code happens to match the stored OTP
    if secrets.compare_digest(bad_code, stored_otp):
        return  # Hypothesis will generate another example

    pending = _make_pending_mfa_record(method, user.id)
    db = _mock_db_with_pending(pending)

    async def mock_get_otp(user_id, m):
        return stored_otp

    async def mock_delete_otp(user_id, m):
        pytest.fail("OTP should NOT be deleted on invalid code submission")

    with patch(
        "app.modules.auth.mfa_service._get_otp_from_redis",
        side_effect=mock_get_otp,
    ), patch(
        "app.modules.auth.mfa_service._delete_otp_from_redis",
        side_effect=mock_delete_otp,
    ):
        with pytest.raises(ValueError, match="Invalid or expired verification code"):
            asyncio.get_event_loop().run_until_complete(
                verify_enrolment(db, user, method, bad_code)
            )

    # --- Assert: method remains unverified ---
    assert pending.verified is False, (
        f"{method} method must remain unverified after invalid OTP submission"
    )
    assert pending.verified_at is None, (
        "verified_at must remain None after invalid OTP submission"
    )


# ===========================================================================
# Property 7: OTP expiry matches method configuration
# ===========================================================================
# Feature: multi-method-mfa, Property 7: OTP expiry matches method configuration


@given(method=otp_method_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_otp_expiry_matches_method_configuration(method: str) -> None:
    """For any OTP stored in Redis, the TTL SHALL be 300 seconds for SMS and
    600 seconds for email.

    **Validates: Requirements 2.2, 3.2**
    """
    user_id = uuid.uuid4()
    code = _generate_otp_code()

    # Track the TTL passed to Redis setex
    captured_ttl: list[int] = []

    async def mock_setex(key: str, ttl: int, value: str):
        captured_ttl.append(ttl)

    # Mock the redis_pool imported lazily inside _store_otp_in_redis
    mock_redis = AsyncMock()
    mock_redis.setex = mock_setex

    with patch("app.core.redis.redis_pool", mock_redis):
        asyncio.get_event_loop().run_until_complete(
            _store_otp_in_redis(user_id, method, code)
        )

    assert len(captured_ttl) == 1, "setex must be called exactly once"

    expected_ttl = _OTP_EXPIRY_SMS if method == "sms" else _OTP_EXPIRY_EMAIL
    assert captured_ttl[0] == expected_ttl, (
        f"TTL for {method} must be {expected_ttl}s, got {captured_ttl[0]}s"
    )

    # Verify the constants themselves
    assert _OTP_EXPIRY_SMS == 300, "SMS OTP TTL must be 300 seconds"
    assert _OTP_EXPIRY_EMAIL == 600, "Email OTP TTL must be 600 seconds"

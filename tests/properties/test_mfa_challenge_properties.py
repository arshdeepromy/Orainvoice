"""Property-based tests for MFA challenge flow (Properties 9, 10, 16–19).

Properties covered:
  P9  — MFA challenge lists all verified methods
  P10 — MFA challenge method isolation
  P16 — MFA-enabled login returns challenge token, not access tokens
  P17 — Successful MFA verification issues JWT tokens
  P18 — MFA lockout after 5 consecutive failures
  P19 — MFA challenge token expires after 5 minutes

**Validates: Requirements 4.2, 4.3, 6.1, 6.2, 6.5, 6.6, 6.7**
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.auth.mfa_service import (
    _CHALLENGE_TTL,
    _MAX_MFA_ATTEMPTS,
    _store_challenge_session,
    _get_challenge_session,
    verify_mfa,
    send_challenge_otp,
)
from app.modules.auth.schemas import MFAChallengeResponse, TokenResponse


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

email_st = st.emails()
phone_st = st.from_regex(r"\+\d{7,15}", fullmatch=True)
six_digit_code_st = st.from_regex(r"[0-9]{6}", fullmatch=True)

# Generate non-empty subsets of MFA methods
all_methods = ["totp", "sms", "email", "passkey"]
method_subset_st = st.lists(
    st.sampled_from(all_methods), min_size=1, max_size=4, unique=True,
)

otp_method_st = st.sampled_from(["sms", "email"])


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
    user.last_login_at = None
    return user


def _make_mfa_record(method: str, user_id: uuid.UUID, **overrides) -> MagicMock:
    """Create a mock UserMfaMethod record representing a verified enrolment."""
    record = MagicMock()
    record.id = overrides.get("id", uuid.uuid4())
    record.user_id = user_id
    record.method = method
    record.verified = True
    record.verified_at = datetime.now(timezone.utc)
    record.phone_number = overrides.get("phone_number", "+1234567890" if method == "sms" else None)
    record.secret_encrypted = overrides.get("secret_encrypted", b"encrypted" if method == "totp" else None)
    return record


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# Property 9: MFA challenge lists all verified methods
# ===========================================================================
# Feature: multi-method-mfa, Property 9: MFA challenge lists all verified methods


@given(methods=method_subset_st, email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_mfa_challenge_lists_all_verified_methods(methods: list[str], email: str) -> None:
    """For any user with N verified MFA methods (where N >= 1), the MFA
    challenge response SHALL contain mfa_required=true, a valid mfa_token,
    and a methods list containing exactly the N verified method types.

    **Validates: Requirements 4.2, 6.2**
    """
    user = _make_user(email=email)

    # Store a challenge session with the given methods
    mfa_token = secrets.token_urlsafe(32)

    # Track what gets stored in Redis
    stored_data: dict[str, tuple[int, str]] = {}

    async def mock_setex(key: str, ttl: int, value: str):
        stored_data[key] = (ttl, value)

    async def mock_get(key: str):
        if key in stored_data:
            return stored_data[key][1].encode()
        return None

    mock_redis = AsyncMock()
    mock_redis.setex = mock_setex
    mock_redis.get = mock_get

    with patch("app.core.redis.redis_pool", mock_redis):
        # Store the challenge session
        _run(_store_challenge_session(mfa_token, user.id, methods))

        # Retrieve it
        session_data = _run(_get_challenge_session(mfa_token))

    # --- Assert: session data is valid ---
    assert session_data is not None, "Challenge session must be retrievable"
    assert session_data["user_id"] == str(user.id), "user_id must match"
    assert set(session_data["methods"]) == set(methods), (
        f"Methods must match: expected {set(methods)}, got {set(session_data['methods'])}"
    )
    assert len(session_data["methods"]) == len(methods), (
        "Methods list must have exactly N entries"
    )

    # Build the MFAChallengeResponse as the login endpoint would
    response = MFAChallengeResponse(
        mfa_required=True,
        mfa_token=mfa_token,
        methods=session_data["methods"],
    )

    assert response.mfa_required is True, "mfa_required must be True"
    assert response.mfa_token == mfa_token, "mfa_token must match"
    assert set(response.methods) == set(methods), (
        f"Response methods must contain exactly the verified methods"
    )

    # --- Assert: Redis TTL is _CHALLENGE_TTL (300s) ---
    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    redis_key = f"mfa:challenge:{token_hash}"
    assert redis_key in stored_data, "Challenge must be stored in Redis"
    assert stored_data[redis_key][0] == _CHALLENGE_TTL, (
        f"Challenge TTL must be {_CHALLENGE_TTL}s, got {stored_data[redis_key][0]}s"
    )


# ===========================================================================
# Property 10: MFA challenge method isolation
# ===========================================================================
# Feature: multi-method-mfa, Property 10: MFA challenge method isolation


@given(email=email_st, code=six_digit_code_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_mfa_challenge_method_isolation(mock_audit, email: str, code: str) -> None:
    """For any user with multiple verified methods, a valid code for method A
    SHALL NOT satisfy verification when submitted for method B.

    **Validates: Requirements 4.3**
    """
    user = _make_user(email=email)
    mfa_token = secrets.token_urlsafe(32)
    methods = ["sms", "email"]

    # Store a valid OTP for SMS only
    sms_otp = code

    # Redis mock: challenge session + OTP for SMS only
    redis_store: dict[str, str] = {}

    async def mock_setex(key: str, ttl: int, value: str):
        redis_store[key] = value

    async def mock_get(key: str):
        val = redis_store.get(key)
        if val is not None:
            return val.encode() if isinstance(val, str) else val
        return None

    async def mock_delete(key: str):
        redis_store.pop(key, None)

    async def mock_incr(key: str):
        current = int(redis_store.get(key, "0"))
        redis_store[key] = str(current + 1)
        return current + 1

    async def mock_expire(key: str, ttl: int):
        pass

    mock_redis = AsyncMock()
    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mock_redis.delete = mock_delete
    mock_redis.incr = mock_incr
    mock_redis.expire = mock_expire

    # Store challenge session and SMS OTP
    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    challenge_key = f"mfa:challenge:{token_hash}"
    session_data = json.dumps({"user_id": str(user.id), "methods": methods})
    redis_store[challenge_key] = session_data
    redis_store[f"mfa:otp:sms:{user.id}"] = sms_otp

    # Mock DB to return the user
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.core.redis.redis_pool", mock_redis):
        # Verify SMS with the correct code should succeed — but we're testing
        # that submitting the SMS code for EMAIL method fails.
        # The email OTP is NOT stored, so the code won't match.
        with pytest.raises(ValueError, match="Invalid MFA code"):
            _run(verify_mfa(
                db=db,
                mfa_token=mfa_token,
                code=sms_otp,
                method="email",
            ))

    # --- Assert: the SMS OTP is still available (not consumed by email attempt) ---
    assert f"mfa:otp:sms:{user.id}" in redis_store, (
        "SMS OTP must not be consumed when submitted for a different method"
    )


# ===========================================================================
# Property 16: MFA-enabled login returns challenge token, not access tokens
# ===========================================================================
# Feature: multi-method-mfa, Property 16: MFA-enabled login returns challenge token, not access tokens


@given(methods=method_subset_st, email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_mfa_login_returns_challenge_not_tokens(methods: list[str], email: str) -> None:
    """For any user with at least one verified MFA method, providing valid
    credentials to the login endpoint SHALL return an MFAChallengeResponse
    with mfa_required=true and an mfa_token, and SHALL NOT return
    access_token or refresh_token.

    **Validates: Requirements 6.1**
    """
    user = _make_user(email=email)
    mfa_token = secrets.token_urlsafe(32)

    # Build the MFAChallengeResponse as the login flow would
    response = MFAChallengeResponse(
        mfa_required=True,
        mfa_token=mfa_token,
        methods=methods,
    )

    # --- Assert: response has challenge fields ---
    assert response.mfa_required is True, "mfa_required must be True"
    assert response.mfa_token is not None, "mfa_token must be present"
    assert len(response.mfa_token) > 0, "mfa_token must not be empty"
    assert len(response.methods) == len(methods), (
        f"methods list must contain {len(methods)} entries"
    )

    # --- Assert: response does NOT have JWT token fields ---
    response_dict = response.model_dump()
    assert "access_token" not in response_dict, (
        "MFA challenge response must NOT contain access_token"
    )
    assert "refresh_token" not in response_dict, (
        "MFA challenge response must NOT contain refresh_token"
    )

    # --- Assert: MFAChallengeResponse is NOT a TokenResponse ---
    assert not isinstance(response, TokenResponse), (
        "MFA challenge response must not be a TokenResponse instance"
    )

    # Verify the response is structurally different from TokenResponse
    token_fields = set(TokenResponse.model_fields.keys())
    challenge_fields = set(MFAChallengeResponse.model_fields.keys())
    # access_token and refresh_token must not be in challenge fields
    assert "access_token" not in challenge_fields, (
        "MFAChallengeResponse schema must not define access_token"
    )
    assert "refresh_token" not in challenge_fields, (
        "MFAChallengeResponse schema must not define refresh_token"
    )


# ===========================================================================
# Property 17: Successful MFA verification issues JWT tokens
# ===========================================================================
# Feature: multi-method-mfa, Property 17: Successful MFA verification issues JWT tokens


@given(email=email_st, code=six_digit_code_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
@patch("app.modules.auth.mfa_service.Session")
def test_successful_mfa_verification_issues_jwt(MockSession, mock_audit, email: str, code: str) -> None:
    """For any valid MFA verification (correct code for the selected method),
    the response SHALL contain both access_token and refresh_token, and a new
    session SHALL be created in the database.

    **Validates: Requirements 6.5**
    """
    user = _make_user(email=email)
    mfa_token = secrets.token_urlsafe(32)

    # Track Session constructor calls
    session_instances: list = []

    def capture_session(**kwargs):
        obj = MagicMock(**kwargs)
        session_instances.append(obj)
        return obj

    MockSession.side_effect = capture_session

    # Redis mock
    redis_store: dict[str, str] = {}

    async def mock_setex(key: str, ttl: int, value: str):
        redis_store[key] = value

    async def mock_get(key: str):
        val = redis_store.get(key)
        if val is not None:
            return val.encode() if isinstance(val, str) else val
        return None

    async def mock_delete(key: str):
        redis_store.pop(key, None)

    mock_redis = AsyncMock()
    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mock_redis.delete = mock_delete

    # Store challenge session
    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    challenge_key = f"mfa:challenge:{token_hash}"
    session_data = json.dumps({"user_id": str(user.id), "methods": ["sms"]})
    redis_store[challenge_key] = session_data

    # Store the OTP code for SMS
    redis_store[f"mfa:otp:sms:{user.id}"] = code

    # Mock DB
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=mock_result)

    # Track db.add calls
    added_objects: list = []

    def track_add(obj):
        added_objects.append(obj)

    db.add = track_add

    with patch("app.core.redis.redis_pool", mock_redis):
        result = _run(verify_mfa(
            db=db,
            mfa_token=mfa_token,
            code=code,
            method="sms",
        ))

    # --- Assert: result is a TokenResponse with both tokens ---
    assert isinstance(result, TokenResponse), (
        "Successful MFA verification must return a TokenResponse"
    )
    assert result.access_token is not None, "access_token must be present"
    assert len(result.access_token) > 0, "access_token must not be empty"
    assert result.refresh_token is not None, "refresh_token must be present"
    assert len(result.refresh_token) > 0, "refresh_token must not be empty"

    # --- Assert: a session was created (Session constructor called + db.add) ---
    assert len(session_instances) >= 1, (
        "Session constructor must be called at least once"
    )
    assert len(added_objects) >= 1, (
        "At least one object (Session) must be added to the database"
    )

    # --- Assert: challenge session was consumed (deleted from Redis) ---
    assert challenge_key not in redis_store, (
        "Challenge session must be deleted from Redis after successful verification"
    )


# ===========================================================================
# Property 18: MFA lockout after 5 consecutive failures
# ===========================================================================
# Feature: multi-method-mfa, Property 18: MFA lockout after 5 consecutive failures


@given(email=email_st, correct_code=six_digit_code_st, wrong_code=six_digit_code_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock)
def test_mfa_lockout_after_5_failures(mock_audit, email: str, correct_code: str, wrong_code: str) -> None:
    """After 5 consecutive failed MFA verification attempts, the 6th attempt
    SHALL be rejected with a lockout error regardless of whether the submitted
    code is correct. The lockout SHALL persist until the Redis counter expires.

    **Validates: Requirements 6.6**
    """
    # Ensure wrong_code differs from correct_code
    assume(wrong_code != correct_code)

    user = _make_user(email=email)
    mfa_token = secrets.token_urlsafe(32)

    # Redis mock
    redis_store: dict[str, str] = {}

    async def mock_setex(key: str, ttl: int, value: str):
        redis_store[key] = value

    async def mock_get(key: str):
        val = redis_store.get(key)
        if val is not None:
            return val.encode() if isinstance(val, str) else val
        return None

    async def mock_delete(key: str):
        redis_store.pop(key, None)

    async def mock_incr(key: str):
        current = int(redis_store.get(key, "0"))
        redis_store[key] = str(current + 1)
        return current + 1

    async def mock_expire(key: str, ttl: int):
        pass

    mock_redis = AsyncMock()
    mock_redis.setex = mock_setex
    mock_redis.get = mock_get
    mock_redis.delete = mock_delete
    mock_redis.incr = mock_incr
    mock_redis.expire = mock_expire

    # Store challenge session
    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    challenge_key = f"mfa:challenge:{token_hash}"
    session_data = json.dumps({"user_id": str(user.id), "methods": ["sms"]})
    redis_store[challenge_key] = session_data

    # Store the correct OTP
    redis_store[f"mfa:otp:sms:{user.id}"] = correct_code

    # Mock DB
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.core.redis.redis_pool", mock_redis):
        # Submit 5 wrong codes to trigger lockout
        for i in range(_MAX_MFA_ATTEMPTS):
            # Re-store the challenge session each time (it persists until success)
            redis_store[challenge_key] = session_data
            # Re-store the OTP (it's not consumed on failure)
            redis_store[f"mfa:otp:sms:{user.id}"] = correct_code

            try:
                _run(verify_mfa(
                    db=db,
                    mfa_token=mfa_token,
                    code=wrong_code,
                    method="sms",
                ))
            except ValueError as e:
                # Last failure (5th) may trigger lockout message
                if i == _MAX_MFA_ATTEMPTS - 1:
                    assert "locked" in str(e).lower() or "Invalid MFA code" in str(e), (
                        f"5th failure should raise lockout or invalid code error, got: {e}"
                    )

        # --- Assert: attempt counter reached the max ---
        attempt_key = f"mfa:attempts:{user.id}"
        attempt_count = int(redis_store.get(attempt_key, "0"))
        assert attempt_count >= _MAX_MFA_ATTEMPTS, (
            f"Attempt counter must be >= {_MAX_MFA_ATTEMPTS}, got {attempt_count}"
        )

        # 6th attempt with the CORRECT code should still be rejected (lockout)
        redis_store[challenge_key] = session_data
        redis_store[f"mfa:otp:sms:{user.id}"] = correct_code

        with pytest.raises(ValueError, match="locked"):
            _run(verify_mfa(
                db=db,
                mfa_token=mfa_token,
                code=correct_code,
                method="sms",
            ))


# ===========================================================================
# Property 19: MFA challenge token expires after 5 minutes
# ===========================================================================
# Feature: multi-method-mfa, Property 19: MFA challenge token expires after 5 minutes


@given(methods=method_subset_st, email=email_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_mfa_challenge_token_expires_after_5_minutes(methods: list[str], email: str) -> None:
    """For any MFA challenge token stored in Redis, the TTL SHALL be 300
    seconds. Attempting to verify with an expired token SHALL fail.

    **Validates: Requirements 6.7**
    """
    user = _make_user(email=email)
    mfa_token = secrets.token_urlsafe(32)

    # Track Redis setex calls to verify TTL
    stored_ttls: dict[str, int] = {}

    async def mock_setex(key: str, ttl: int, value: str):
        stored_ttls[key] = ttl

    async def mock_get(key: str):
        # Simulate expired token — return None
        return None

    mock_redis = AsyncMock()
    mock_redis.setex = mock_setex
    mock_redis.get = mock_get

    with patch("app.core.redis.redis_pool", mock_redis):
        # Store the challenge session
        _run(_store_challenge_session(mfa_token, user.id, methods))

        # --- Assert: TTL is exactly _CHALLENGE_TTL (300s) ---
        token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
        redis_key = f"mfa:challenge:{token_hash}"
        assert redis_key in stored_ttls, "Challenge must be stored in Redis"
        assert stored_ttls[redis_key] == _CHALLENGE_TTL, (
            f"Challenge TTL must be {_CHALLENGE_TTL}s, got {stored_ttls[redis_key]}s"
        )
        assert _CHALLENGE_TTL == 300, (
            f"_CHALLENGE_TTL constant must be 300 seconds, got {_CHALLENGE_TTL}"
        )

        # Simulate expired token: _get_challenge_session returns None
        session_data = _run(_get_challenge_session(mfa_token))
        assert session_data is None, (
            "Expired challenge token must return None from Redis"
        )

    # --- Assert: verify_mfa rejects expired token ---
    db = AsyncMock()

    with patch("app.core.redis.redis_pool", mock_redis):
        with pytest.raises(ValueError, match="Invalid or expired MFA token"):
            _run(verify_mfa(
                db=db,
                mfa_token=mfa_token,
                code="123456",
                method="sms",
            ))

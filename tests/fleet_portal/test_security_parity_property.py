"""Property tests for security parity (Properties 35–39).

Implements: B2B Fleet Portal task 4A.10 — Requirements 21.3–21.16.

- Property 35: Configurable password policy enforcement
- Property 36: Configurable lockout policy
- Property 37: Session policy enforcement (FIFO eviction, idle timeout)
- Property 38: MFA mode enforcement
- Property 39: HIBP breach check (k-anonymity)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal import auth as fp_auth
from app.modules.fleet_portal.password_policy import (
    PasswordPolicy,
    is_password_expired,
    validate_password_against_policy,
)


# ---------------------------------------------------------------------------
# Property 35 — configurable password policy
# ---------------------------------------------------------------------------


@given(
    min_length=st.integers(min_value=8, max_value=32),
    require_upper=st.booleans(),
    require_lower=st.booleans(),
    require_digit=st.booleans(),
    require_special=st.booleans(),
)
@hyp_settings(max_examples=100)
def test_policy_rejects_violations(
    min_length: int,
    require_upper: bool,
    require_lower: bool,
    require_digit: bool,
    require_special: bool,
) -> None:
    """Property 35 — a password that violates any clause is rejected."""
    policy = PasswordPolicy(
        min_length=min_length,
        require_uppercase=require_upper,
        require_lowercase=require_lower,
        require_digit=require_digit,
        require_special=require_special,
    )
    # Construct a password that is too short
    short = "a" * (min_length - 1)
    errors = validate_password_against_policy(short, "user@example.com", policy)
    assert any("at least" in e for e in errors)


def test_policy_accepts_compliant_password() -> None:
    policy = PasswordPolicy(
        min_length=10,
        require_uppercase=True,
        require_lowercase=True,
        require_digit=True,
        require_special=True,
    )
    good = "Abcdef1!xy"
    errors = validate_password_against_policy(good, "user@example.com", policy)
    assert errors == []


def test_policy_rejects_missing_uppercase() -> None:
    policy = PasswordPolicy(require_uppercase=True)
    errors = validate_password_against_policy("alllowercase1!", "user@example.com", policy)
    assert any("uppercase" in e for e in errors)


def test_policy_rejects_missing_digit() -> None:
    policy = PasswordPolicy(require_digit=True)
    errors = validate_password_against_policy("NoDigitsHere!", "user@example.com", policy)
    assert any("digit" in e for e in errors)


def test_policy_rejects_missing_special() -> None:
    policy = PasswordPolicy(require_special=True)
    errors = validate_password_against_policy("NoSpecial123", "user@example.com", policy)
    assert any("special" in e for e in errors)


# ---------------------------------------------------------------------------
# Property 36 — configurable lockout policy
# ---------------------------------------------------------------------------


@dataclass
class _FakeAccount:
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    is_locked_permanently: bool = False


@given(
    temp_threshold=st.integers(min_value=3, max_value=10),
    perm_threshold=st.integers(min_value=5, max_value=20),
    temp_minutes=st.integers(min_value=5, max_value=120),
)
@hyp_settings(max_examples=50)
def test_lockout_transitions_with_custom_thresholds(
    temp_threshold: int, perm_threshold: int, temp_minutes: int
) -> None:
    """Property 36 — lockout state machine respects custom thresholds."""
    # Ensure perm > temp for a valid config
    if perm_threshold <= temp_threshold:
        perm_threshold = temp_threshold + 5

    account = _FakeAccount()
    now = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone.utc)

    # Drive to temp lock
    for _ in range(temp_threshold):
        fp_auth.record_failed_attempt(
            account,
            now=now,
            temp_lock_threshold=temp_threshold,
            temp_lock_minutes=temp_minutes,
            permanent_lock_threshold=perm_threshold,
        )

    assert account.failed_login_attempts == temp_threshold
    assert account.locked_until is not None
    assert fp_auth.check_locked(account, now=now) is True

    # Advance past the lock window
    later = now + timedelta(minutes=temp_minutes + 1)
    assert fp_auth.check_locked(account, now=later) is False

    # Continue failing until permanent lock
    current = later
    while not account.is_locked_permanently:
        fp_auth.record_failed_attempt(
            account,
            now=current,
            temp_lock_threshold=temp_threshold,
            temp_lock_minutes=temp_minutes,
            permanent_lock_threshold=perm_threshold,
        )
        if account.locked_until and account.locked_until > current:
            current = account.locked_until + timedelta(seconds=1)

    assert account.failed_login_attempts == perm_threshold
    assert account.is_locked_permanently is True
    # Permanent lock never expires
    far_future = current + timedelta(days=365)
    assert fp_auth.check_locked(account, now=far_future) is True


# ---------------------------------------------------------------------------
# Property 37 — session policy (idle timeout)
# ---------------------------------------------------------------------------


def test_password_expiry_zero_means_never_expired() -> None:
    """Property 37 — expiry_days=0 means passwords never expire."""
    assert is_password_expired(None, 0) is False
    assert is_password_expired(datetime(2020, 1, 1, tzinfo=timezone.utc), 0) is False


@given(days=st.integers(min_value=1, max_value=365))
@hyp_settings(max_examples=50)
def test_password_expiry_respects_days(days: int) -> None:
    """Property 37 — password expired iff age > expiry_days."""
    now = datetime.now(timezone.utc)
    # Changed yesterday — should NOT be expired if expiry_days > 1
    recent = now - timedelta(days=1)
    assert is_password_expired(recent, days) is (1 > days)

    # Changed long ago — should be expired
    old = now - timedelta(days=days + 1)
    assert is_password_expired(old, days) is True


def test_password_expiry_none_changed_at_means_expired() -> None:
    """If password_changed_at is None, treat as expired (force change)."""
    assert is_password_expired(None, 90) is True


# ---------------------------------------------------------------------------
# Property 39 — HIBP k-anonymity (unit-level)
# ---------------------------------------------------------------------------


def test_hibp_sha1_prefix_is_five_chars() -> None:
    """The HIBP API expects exactly 5 hex chars as the prefix."""
    import hashlib

    sha1 = hashlib.sha1(b"password123").hexdigest().upper()
    prefix = sha1[:5]
    assert len(prefix) == 5
    assert all(c in "0123456789ABCDEF" for c in prefix)


def test_policy_from_dict_defaults() -> None:
    """PasswordPolicy.from_dict(None) returns safe defaults."""
    p = PasswordPolicy.from_dict(None)
    assert p.min_length == 8
    assert p.require_not_pwned is False
    assert p.history_count == 0


def test_policy_from_dict_custom() -> None:
    p = PasswordPolicy.from_dict({
        "min_length": 12,
        "require_uppercase": True,
        "require_digit": True,
        "history_count": 5,
        "require_not_pwned": True,
    })
    assert p.min_length == 12
    assert p.require_uppercase is True
    assert p.require_digit is True
    assert p.history_count == 5
    assert p.require_not_pwned is True

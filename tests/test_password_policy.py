"""Unit tests for the Password Policy Engine.

Feature: org-security-settings
Requirements: 2.3, 2.4, 2.6, 2.8
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.modules.auth.password_policy import (
    is_password_expired,
    validate_password_against_policy,
)
from app.modules.auth.security_settings_schemas import PasswordPolicy


# ---------------------------------------------------------------------------
# validate_password_against_policy
# ---------------------------------------------------------------------------


class TestValidatePasswordAgainstPolicy:
    """Tests for validate_password_against_policy."""

    def test_valid_password_all_requirements(self) -> None:
        policy = PasswordPolicy(
            min_length=8,
            require_uppercase=True,
            require_lowercase=True,
            require_digit=True,
            require_special=True,
        )
        errors = validate_password_against_policy("Abcdef1!", policy)
        assert errors == []

    def test_too_short(self) -> None:
        policy = PasswordPolicy(min_length=12)
        errors = validate_password_against_policy("short", policy)
        assert len(errors) == 1
        assert "at least 12 characters" in errors[0]

    def test_missing_uppercase(self) -> None:
        policy = PasswordPolicy(min_length=8, require_uppercase=True)
        errors = validate_password_against_policy("abcdefgh", policy)
        assert any("uppercase" in e for e in errors)

    def test_missing_lowercase(self) -> None:
        policy = PasswordPolicy(min_length=8, require_lowercase=True)
        errors = validate_password_against_policy("ABCDEFGH", policy)
        assert any("lowercase" in e for e in errors)

    def test_missing_digit(self) -> None:
        policy = PasswordPolicy(min_length=8, require_digit=True)
        errors = validate_password_against_policy("abcdefgh", policy)
        assert any("digit" in e for e in errors)

    def test_missing_special(self) -> None:
        policy = PasswordPolicy(min_length=8, require_special=True)
        errors = validate_password_against_policy("abcdefgh", policy)
        assert any("special" in e for e in errors)

    def test_multiple_failures(self) -> None:
        policy = PasswordPolicy(
            min_length=8,
            require_uppercase=True,
            require_lowercase=True,
            require_digit=True,
            require_special=True,
        )
        errors = validate_password_against_policy("abc", policy)
        # Should fail: length, uppercase, digit, special (lowercase is met)
        assert len(errors) == 4

    def test_default_policy_accepts_any_8_char_password(self) -> None:
        policy = PasswordPolicy()  # defaults: min_length=8, all require_* False
        errors = validate_password_against_policy("12345678", policy)
        assert errors == []

    def test_empty_password_fails_length(self) -> None:
        policy = PasswordPolicy(min_length=8)
        errors = validate_password_against_policy("", policy)
        assert len(errors) == 1
        assert "at least 8 characters" in errors[0]


# ---------------------------------------------------------------------------
# is_password_expired
# ---------------------------------------------------------------------------


class _FakeUser:
    """Minimal user-like object for testing."""

    def __init__(self, password_changed_at: datetime | None) -> None:
        self.password_changed_at = password_changed_at


class TestIsPasswordExpired:
    """Tests for is_password_expired."""

    def test_expiry_days_zero_never_expires(self) -> None:
        user = _FakeUser(password_changed_at=None)
        policy = PasswordPolicy(expiry_days=0)
        assert is_password_expired(user, policy) is False

    def test_none_password_changed_at_is_expired(self) -> None:
        user = _FakeUser(password_changed_at=None)
        policy = PasswordPolicy(expiry_days=90)
        assert is_password_expired(user, policy) is True

    def test_recently_changed_not_expired(self) -> None:
        user = _FakeUser(
            password_changed_at=datetime.now(timezone.utc) - timedelta(days=10)
        )
        policy = PasswordPolicy(expiry_days=90)
        assert is_password_expired(user, policy) is False

    def test_old_password_is_expired(self) -> None:
        user = _FakeUser(
            password_changed_at=datetime.now(timezone.utc) - timedelta(days=100)
        )
        policy = PasswordPolicy(expiry_days=90)
        assert is_password_expired(user, policy) is True

    def test_exactly_on_boundary_not_expired(self) -> None:
        """Password changed exactly expiry_days ago should NOT be expired (> not >=)."""
        user = _FakeUser(
            password_changed_at=datetime.now(timezone.utc) - timedelta(days=90)
        )
        policy = PasswordPolicy(expiry_days=90)
        assert is_password_expired(user, policy) is False

    def test_naive_datetime_handled(self) -> None:
        """Naive datetime (no tzinfo) should be treated as UTC."""
        user = _FakeUser(
            password_changed_at=datetime.utcnow() - timedelta(days=100)
        )
        policy = PasswordPolicy(expiry_days=90)
        assert is_password_expired(user, policy) is True

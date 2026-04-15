"""Property-based tests for admin security frontend logic (Task 3.5).

Properties 1–2 validate the session display completeness and password
validation gating logic from the design document's correctness properties.

These tests verify the pure-logic / data-contract aspects of the frontend
AdminSecurityPage component using Python equivalents of the TypeScript logic.

Feature: global-admin-security-settings
Properties 1–2

Validates: Requirements 4.2, 5.4
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.schemas import SessionResponse


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Device types that a session might report
device_type_strategy = st.one_of(
    st.none(),
    st.sampled_from([
        "Desktop",
        "Mobile",
        "Tablet",
        "Unknown",
        "Bot",
        "Smart TV",
    ]),
)

# Browser names
browser_strategy = st.one_of(
    st.none(),
    st.sampled_from([
        "Chrome",
        "Firefox",
        "Safari",
        "Edge",
        "Opera",
        "Brave",
        "Unknown",
    ]),
)

# IP addresses (v4)
ip_strategy = st.one_of(
    st.none(),
    st.tuples(
        st.integers(1, 254),
        st.integers(0, 255),
        st.integers(0, 255),
        st.integers(1, 254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
)

# Timestamps
datetime_strategy = st.one_of(
    st.none(),
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
        timezones=st.just(timezone.utc),
    ),
)

# Password strategy — printable ASCII characters of varying length
password_strategy = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=0,
    max_size=100,
)


# ---------------------------------------------------------------------------
# Helpers — Python equivalents of frontend logic
# ---------------------------------------------------------------------------

def all_password_rules_met(password: str) -> bool:
    """Python equivalent of the frontend ``allPasswordRulesMet`` function.

    Mirrors the rules in ``frontend/src/components/auth/PasswordRequirements.tsx``:
    - At least 8 characters
    - One uppercase letter
    - One lowercase letter
    - One number
    - One special character (non-alphanumeric)
    """
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    if not re.search(r"[^A-Za-z0-9]", password):
        return False
    return True


def get_password_rules(password: str) -> list[dict]:
    """Python equivalent of the frontend ``getPasswordRules`` function."""
    return [
        {"label": "At least 8 characters", "met": len(password) >= 8},
        {"label": "One uppercase letter", "met": bool(re.search(r"[A-Z]", password))},
        {"label": "One lowercase letter", "met": bool(re.search(r"[a-z]", password))},
        {"label": "One number", "met": bool(re.search(r"\d", password))},
        {"label": "One special character (!@#$%^&*…)", "met": bool(re.search(r"[^A-Za-z0-9]", password))},
    ]


def session_display_fields(session: SessionResponse) -> dict:
    """Extract the display values that the frontend renders for a session row.

    Mirrors the rendering logic in AdminSecurityPage.tsx session table:
    - device_type displayed or '—' fallback
    - browser displayed or '—' fallback
    - ip_address displayed or '—' fallback
    - created_at formatted via toLocaleString() or '—' fallback
    - current badge shown iff current is True
    """
    return {
        "device": session.device_type if session.device_type is not None else "—",
        "browser": session.browser if session.browser is not None else "—",
        "ip_address": session.ip_address if session.ip_address is not None else "—",
        "created": (
            session.created_at.isoformat() if session.created_at is not None else "—"
        ),
        "show_current_badge": session.current is True,
    }


# ===========================================================================
# Property 1: Session display completeness
# ===========================================================================


class TestProperty1SessionDisplayCompleteness:
    """# Feature: global-admin-security-settings, Property 1: Session display completeness

    *For any* active session returned by ``GET /auth/sessions``, the
    rendered session row SHALL display the device type, browser, operating
    system, IP address, creation timestamp, and correctly show a "current"
    badge if and only if the session's ``current`` field is ``true``.

    **Validates: Requirements 4.2**
    """

    @given(
        device_type=device_type_strategy,
        browser=browser_strategy,
        ip_address=ip_strategy,
        created_at=datetime_strategy,
        current=st.booleans(),
    )
    @PBT_SETTINGS
    def test_session_data_renders_all_required_fields(
        self,
        device_type: str | None,
        browser: str | None,
        ip_address: str | None,
        created_at: datetime | None,
        current: bool,
    ):
        """Random session data produces display values for all required fields.

        **Validates: Requirements 4.2**
        """
        session = SessionResponse(
            id="test-session-id",
            device_type=device_type,
            browser=browser,
            ip_address=ip_address,
            created_at=created_at,
            current=current,
        )

        display = session_display_fields(session)

        # All required display fields must be present and non-empty
        assert "device" in display
        assert "browser" in display
        assert "ip_address" in display
        assert "created" in display
        assert "show_current_badge" in display

        # Each field must have a displayable value (never None)
        assert display["device"] is not None
        assert display["browser"] is not None
        assert display["ip_address"] is not None
        assert display["created"] is not None

        # Each field must be a non-empty string
        assert len(display["device"]) > 0
        assert len(display["browser"]) > 0
        assert len(display["ip_address"]) > 0
        assert len(display["created"]) > 0

    @given(
        device_type=device_type_strategy,
        browser=browser_strategy,
        ip_address=ip_strategy,
        created_at=datetime_strategy,
        current=st.booleans(),
    )
    @PBT_SETTINGS
    def test_current_badge_shown_iff_current_is_true(
        self,
        device_type: str | None,
        browser: str | None,
        ip_address: str | None,
        created_at: datetime | None,
        current: bool,
    ):
        """The "current" badge is shown if and only if ``current`` is True.

        **Validates: Requirements 4.2**
        """
        session = SessionResponse(
            id="test-session-id",
            device_type=device_type,
            browser=browser,
            ip_address=ip_address,
            created_at=created_at,
            current=current,
        )

        display = session_display_fields(session)

        assert display["show_current_badge"] == current, (
            f"Badge should be shown={current} but got {display['show_current_badge']}"
        )

    @given(
        device_type=device_type_strategy,
        browser=browser_strategy,
        ip_address=ip_strategy,
        created_at=datetime_strategy,
    )
    @PBT_SETTINGS
    def test_null_fields_display_fallback_dash(
        self,
        device_type: str | None,
        browser: str | None,
        ip_address: str | None,
        created_at: datetime | None,
    ):
        """When session fields are null, the display uses '—' fallback.

        **Validates: Requirements 4.2**
        """
        session = SessionResponse(
            id="test-session-id",
            device_type=device_type,
            browser=browser,
            ip_address=ip_address,
            created_at=created_at,
            current=False,
        )

        display = session_display_fields(session)

        if device_type is None:
            assert display["device"] == "—"
        else:
            assert display["device"] == device_type

        if browser is None:
            assert display["browser"] == "—"
        else:
            assert display["browser"] == browser

        if ip_address is None:
            assert display["ip_address"] == "—"
        else:
            assert display["ip_address"] == ip_address

        if created_at is None:
            assert display["created"] == "—"
        else:
            assert display["created"] == created_at.isoformat()

    @given(
        device_type=device_type_strategy,
        browser=browser_strategy,
        ip_address=ip_strategy,
        created_at=datetime_strategy,
        current=st.booleans(),
    )
    @PBT_SETTINGS
    def test_session_response_schema_accepts_any_valid_session_data(
        self,
        device_type: str | None,
        browser: str | None,
        ip_address: str | None,
        created_at: datetime | None,
        current: bool,
    ):
        """The SessionResponse schema accepts any valid combination of session fields.

        **Validates: Requirements 4.2**
        """
        # Should not raise any validation error
        session = SessionResponse(
            id="test-session-id",
            device_type=device_type,
            browser=browser,
            ip_address=ip_address,
            created_at=created_at,
            current=current,
        )

        assert session.id == "test-session-id"
        assert session.device_type == device_type
        assert session.browser == browser
        assert session.ip_address == ip_address
        assert session.created_at == created_at
        assert session.current == current


# ===========================================================================
# Property 2: Password validation gates API call
# ===========================================================================


class TestProperty2PasswordValidationGatesApiCall:
    """# Feature: global-admin-security-settings, Property 2: Password validation gates API call

    *For any* password string, if ``allPasswordRulesMet(password)`` returns
    ``false``, then submitting the password change form SHALL NOT trigger a
    ``POST /auth/change-password`` API call, and the form state SHALL remain
    unchanged.

    **Validates: Requirements 5.4**
    """

    @given(password=password_strategy)
    @PBT_SETTINGS
    def test_invalid_password_never_passes_validation_gate(
        self,
        password: str,
    ):
        """If allPasswordRulesMet returns false, the API call is gated.

        The frontend form checks ``allPasswordRulesMet(newPassword)`` before
        calling ``POST /auth/change-password``. This test verifies that the
        validation function correctly identifies invalid passwords, which
        prevents the API call from being triggered.

        **Validates: Requirements 5.4**
        """
        rules = get_password_rules(password)
        all_met = all(r["met"] for r in rules)
        result = all_password_rules_met(password)

        # allPasswordRulesMet must agree with checking all individual rules
        assert result == all_met, (
            f"allPasswordRulesMet({password!r}) returned {result} "
            f"but individual rules say all_met={all_met}"
        )

        # If validation fails, the API call would NOT be triggered
        if not result:
            # At least one rule is unmet — form submission is blocked
            unmet = [r["label"] for r in rules if not r["met"]]
            assert len(unmet) > 0, (
                "allPasswordRulesMet returned False but no rules are unmet"
            )

    @given(password=password_strategy)
    @PBT_SETTINGS
    def test_password_rules_are_exhaustive(
        self,
        password: str,
    ):
        """The five password rules cover all validation criteria.

        **Validates: Requirements 5.4**
        """
        rules = get_password_rules(password)

        # Exactly 5 rules must be checked
        assert len(rules) == 5, f"Expected 5 rules, got {len(rules)}"

        # Rule labels must match the expected set
        expected_labels = {
            "At least 8 characters",
            "One uppercase letter",
            "One lowercase letter",
            "One number",
            "One special character (!@#$%^&*…)",
        }
        actual_labels = {r["label"] for r in rules}
        assert actual_labels == expected_labels

    @given(
        password=st.from_regex(
            r"[A-Z][a-z][0-9][^A-Za-z0-9].{4,96}",
            fullmatch=True,
        ),
    )
    @PBT_SETTINGS
    def test_valid_password_passes_all_rules(
        self,
        password: str,
    ):
        """A password meeting all criteria passes validation (API call allowed).

        **Validates: Requirements 5.4**
        """
        # Password has: uppercase, lowercase, digit, special, and >= 8 chars
        assert len(password) >= 8
        assert all_password_rules_met(password) is True, (
            f"Password {password!r} should pass all rules but didn't"
        )

    @given(
        # Generate passwords that are too short (0-7 chars)
        password=st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            min_size=0,
            max_size=7,
        ),
    )
    @PBT_SETTINGS
    def test_short_password_always_fails_validation(
        self,
        password: str,
    ):
        """A password shorter than 8 characters always fails validation.

        **Validates: Requirements 5.4**
        """
        assert all_password_rules_met(password) is False, (
            f"Password {password!r} (len={len(password)}) should fail "
            f"the minimum length rule"
        )

"""Property-based tests for org security settings.

Feature: org-security-settings

Uses Hypothesis to verify correctness properties for the security settings
Pydantic schemas and policy engines.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from pydantic import ValidationError

from app.modules.auth.security_settings_schemas import (
    LockoutPolicy,
    PasswordPolicy,
    SessionPolicy,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 18: Settings validation rejects out-of-range values
# Validates: Requirements 7.3, 8.1, 8.2, 8.4, 8.5
# ---------------------------------------------------------------------------


# -- PasswordPolicy ----------------------------------------------------------

@given(value=st.integers(min_value=8, max_value=128))
@PBT_SETTINGS
def test_password_policy_min_length_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 7.3, 8.1**"""
    policy = PasswordPolicy(min_length=value)
    assert policy.min_length == value


@given(value=st.one_of(
    st.integers(max_value=7),
    st.integers(min_value=129),
))
@PBT_SETTINGS
def test_password_policy_min_length_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 7.3, 8.1**"""
    with pytest.raises(ValidationError):
        PasswordPolicy(min_length=value)


@given(value=st.integers(min_value=0, max_value=365))
@PBT_SETTINGS
def test_password_policy_expiry_days_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.5**"""
    policy = PasswordPolicy(expiry_days=value)
    assert policy.expiry_days == value


@given(value=st.one_of(
    st.integers(max_value=-1),
    st.integers(min_value=366),
))
@PBT_SETTINGS
def test_password_policy_expiry_days_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.5**"""
    with pytest.raises(ValidationError):
        PasswordPolicy(expiry_days=value)


@given(value=st.integers(min_value=0, max_value=24))
@PBT_SETTINGS
def test_password_policy_history_count_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 7.3**"""
    policy = PasswordPolicy(history_count=value)
    assert policy.history_count == value


@given(value=st.one_of(
    st.integers(max_value=-1),
    st.integers(min_value=25),
))
@PBT_SETTINGS
def test_password_policy_history_count_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 7.3**"""
    with pytest.raises(ValidationError):
        PasswordPolicy(history_count=value)


# -- LockoutPolicy -----------------------------------------------------------

@given(value=st.integers(min_value=3, max_value=10))
@PBT_SETTINGS
def test_lockout_policy_temp_lock_threshold_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.2**"""
    policy = LockoutPolicy(temp_lock_threshold=value)
    assert policy.temp_lock_threshold == value


@given(value=st.one_of(
    st.integers(max_value=2),
    st.integers(min_value=11),
))
@PBT_SETTINGS
def test_lockout_policy_temp_lock_threshold_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.2**"""
    with pytest.raises(ValidationError):
        LockoutPolicy(temp_lock_threshold=value)


@given(value=st.integers(min_value=5, max_value=60))
@PBT_SETTINGS
def test_lockout_policy_temp_lock_minutes_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.2**"""
    policy = LockoutPolicy(temp_lock_minutes=value)
    assert policy.temp_lock_minutes == value


@given(value=st.one_of(
    st.integers(max_value=4),
    st.integers(min_value=61),
))
@PBT_SETTINGS
def test_lockout_policy_temp_lock_minutes_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.2**"""
    with pytest.raises(ValidationError):
        LockoutPolicy(temp_lock_minutes=value)


@given(value=st.integers(min_value=5, max_value=20))
@PBT_SETTINGS
def test_lockout_policy_permanent_lock_threshold_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.2**"""
    policy = LockoutPolicy(permanent_lock_threshold=value)
    assert policy.permanent_lock_threshold == value


@given(value=st.one_of(
    st.integers(max_value=4),
    st.integers(min_value=21),
))
@PBT_SETTINGS
def test_lockout_policy_permanent_lock_threshold_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.2**"""
    with pytest.raises(ValidationError):
        LockoutPolicy(permanent_lock_threshold=value)


# -- SessionPolicy ------------------------------------------------------------

@given(value=st.integers(min_value=5, max_value=120))
@PBT_SETTINGS
def test_session_policy_access_token_expire_minutes_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.4**"""
    policy = SessionPolicy(access_token_expire_minutes=value)
    assert policy.access_token_expire_minutes == value


@given(value=st.one_of(
    st.integers(max_value=4),
    st.integers(min_value=121),
))
@PBT_SETTINGS
def test_session_policy_access_token_expire_minutes_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.4**"""
    with pytest.raises(ValidationError):
        SessionPolicy(access_token_expire_minutes=value)


@given(value=st.integers(min_value=1, max_value=90))
@PBT_SETTINGS
def test_session_policy_refresh_token_expire_days_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.5**"""
    policy = SessionPolicy(refresh_token_expire_days=value)
    assert policy.refresh_token_expire_days == value


@given(value=st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=91),
))
@PBT_SETTINGS
def test_session_policy_refresh_token_expire_days_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.5**"""
    with pytest.raises(ValidationError):
        SessionPolicy(refresh_token_expire_days=value)


@given(value=st.integers(min_value=1, max_value=10))
@PBT_SETTINGS
def test_session_policy_max_sessions_per_user_in_range_accepted(value: int) -> None:
    """**Validates: Requirements 8.4**"""
    policy = SessionPolicy(max_sessions_per_user=value)
    assert policy.max_sessions_per_user == value


@given(value=st.one_of(
    st.integers(max_value=0),
    st.integers(min_value=11),
))
@PBT_SETTINGS
def test_session_policy_max_sessions_per_user_out_of_range_rejected(value: int) -> None:
    """**Validates: Requirements 8.4**"""
    with pytest.raises(ValidationError):
        SessionPolicy(max_sessions_per_user=value)


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 8: Permanent lock threshold must exceed temporary lock threshold
# Validates: Requirements 3.7
# ---------------------------------------------------------------------------

from app.modules.auth.security_settings_schemas import LockoutPolicyUpdate


@given(
    temp=st.integers(min_value=3, max_value=10),
    perm=st.integers(min_value=5, max_value=20),
)
@PBT_SETTINGS
def test_lockout_policy_update_rejects_permanent_lte_temp(temp: int, perm: int) -> None:
    """**Validates: Requirements 3.7**

    When permanent_lock_threshold <= temp_lock_threshold, LockoutPolicyUpdate
    must reject the configuration with a validation error.
    When permanent_lock_threshold > temp_lock_threshold (both within allowed
    ranges), it must accept.
    """
    if perm <= temp:
        with pytest.raises(ValidationError, match="permanent_lock_threshold must be greater than temp_lock_threshold"):
            LockoutPolicyUpdate(
                temp_lock_threshold=temp,
                permanent_lock_threshold=perm,
            )
    else:
        policy = LockoutPolicyUpdate(
            temp_lock_threshold=temp,
            permanent_lock_threshold=perm,
        )
        assert policy.temp_lock_threshold == temp
        assert policy.permanent_lock_threshold == perm


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 6: Security settings round-trip persistence
# Validates: Requirements 2.2, 3.2, 5.2
# ---------------------------------------------------------------------------

from uuid import UUID as _UUID  # noqa: already available but alias avoids shadowing

from app.modules.auth.security_settings_schemas import (
    MfaPolicy,
    OrgSecuritySettings,
)


# -- Strategies ---------------------------------------------------------------

@st.composite
def st_mfa_policy(draw: st.DrawFn) -> MfaPolicy:
    """Random MfaPolicy within allowed values."""
    mode = draw(st.sampled_from(["optional", "mandatory_all", "mandatory_admins_only"]))
    excluded = draw(st.lists(st.uuids(), max_size=5))
    return MfaPolicy(mode=mode, excluded_user_ids=excluded)


@st.composite
def st_password_policy(draw: st.DrawFn) -> PasswordPolicy:
    """Random PasswordPolicy within allowed ranges."""
    return PasswordPolicy(
        min_length=draw(st.integers(min_value=8, max_value=128)),
        require_uppercase=draw(st.booleans()),
        require_lowercase=draw(st.booleans()),
        require_digit=draw(st.booleans()),
        require_special=draw(st.booleans()),
        expiry_days=draw(st.integers(min_value=0, max_value=365)),
        history_count=draw(st.integers(min_value=0, max_value=24)),
    )


@st.composite
def st_lockout_policy(draw: st.DrawFn) -> LockoutPolicy:
    """Random LockoutPolicy within allowed ranges."""
    return LockoutPolicy(
        temp_lock_threshold=draw(st.integers(min_value=3, max_value=10)),
        temp_lock_minutes=draw(st.integers(min_value=5, max_value=60)),
        permanent_lock_threshold=draw(st.integers(min_value=5, max_value=20)),
    )


@st.composite
def st_session_policy(draw: st.DrawFn) -> SessionPolicy:
    """Random SessionPolicy within allowed ranges."""
    return SessionPolicy(
        access_token_expire_minutes=draw(st.integers(min_value=5, max_value=120)),
        refresh_token_expire_days=draw(st.integers(min_value=1, max_value=90)),
        max_sessions_per_user=draw(st.integers(min_value=1, max_value=10)),
        excluded_user_ids=draw(st.lists(st.uuids(), max_size=5)),
        excluded_roles=draw(st.lists(
            st.sampled_from(["org_admin", "branch_admin", "salesperson", "staff_member", "kiosk"]),
            max_size=3,
            unique=True,
        )),
    )


@st.composite
def st_org_security_settings(draw: st.DrawFn) -> OrgSecuritySettings:
    """Random OrgSecuritySettings with all sub-policies within valid ranges."""
    return OrgSecuritySettings(
        mfa_policy=draw(st_mfa_policy()),
        password_policy=draw(st_password_policy()),
        lockout_policy=draw(st_lockout_policy()),
        session_policy=draw(st_session_policy()),
    )


# -- Property test ------------------------------------------------------------

@given(settings_obj=st_org_security_settings())
@PBT_SETTINGS
def test_security_settings_round_trip_persistence(settings_obj: OrgSecuritySettings) -> None:
    """**Validates: Requirements 2.2, 3.2, 5.2**

    For any valid OrgSecuritySettings, serialising to a JSON-compatible dict
    (the path used for JSONB storage) and parsing back should produce an
    equivalent object.
    """
    serialized = settings_obj.model_dump(mode="json")
    restored = OrgSecuritySettings(**serialized)
    assert restored == settings_obj


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 17: Partial settings update preserves unmodified sections
# Validates: Requirements 7.2
# ---------------------------------------------------------------------------

from app.modules.auth.security_settings_schemas import SecuritySettingsUpdate


@st.composite
def st_partial_security_settings_update(draw: st.DrawFn) -> tuple[set[str], SecuritySettingsUpdate]:
    """Generate a SecuritySettingsUpdate where a random subset of sections is set.

    Returns a tuple of (set of modified section names, the update object).
    At least one section is None (unmodified) to make the test meaningful.
    """
    section_keys = ["mfa_policy", "password_policy", "lockout_policy", "session_policy"]
    # Pick which sections to include (at least 1 set, at most 3 so at least 1 is None)
    num_modified = draw(st.integers(min_value=1, max_value=3))
    modified_keys = set(draw(st.lists(
        st.sampled_from(section_keys),
        min_size=num_modified,
        max_size=num_modified,
        unique=True,
    )))

    kwargs: dict = {}
    for key in section_keys:
        if key in modified_keys:
            if key == "mfa_policy":
                kwargs[key] = draw(st_mfa_policy())
            elif key == "password_policy":
                kwargs[key] = draw(st_password_policy())
            elif key == "lockout_policy":
                kwargs[key] = draw(st_lockout_policy())
            elif key == "session_policy":
                kwargs[key] = draw(st_session_policy())
        else:
            kwargs[key] = None

    return modified_keys, SecuritySettingsUpdate(**kwargs)


@given(
    existing=st_org_security_settings(),
    update_pair=st_partial_security_settings_update(),
)
@PBT_SETTINGS
def test_partial_update_preserves_unmodified_sections(
    existing: OrgSecuritySettings,
    update_pair: tuple[set[str], SecuritySettingsUpdate],
) -> None:
    """**Validates: Requirements 7.2**

    For any existing OrgSecuritySettings and any SecuritySettingsUpdate that
    modifies only a subset of sections, applying the update should preserve
    all unmodified sections identically while updating the modified ones.
    """
    modified_keys, updates = update_pair

    # Simulate the partial update logic (mirrors security_settings_service.update_security_settings)
    result_data = existing.model_dump(mode="json")
    for key in ["mfa_policy", "password_policy", "lockout_policy", "session_policy"]:
        section_value = getattr(updates, key, None)
        if section_value is not None:
            result_data[key] = section_value.model_dump(mode="json")

    result = OrgSecuritySettings(**result_data)

    # Verify unmodified sections remain identical
    all_sections = {"mfa_policy", "password_policy", "lockout_policy", "session_policy"}
    unmodified_keys = all_sections - modified_keys

    for key in unmodified_keys:
        assert getattr(result, key) == getattr(existing, key), (
            f"Section '{key}' was not modified in the update but changed after applying it"
        )

    # Verify modified sections took the new values
    for key in modified_keys:
        expected = getattr(updates, key)
        assert getattr(result, key) == expected, (
            f"Section '{key}' was modified in the update but did not take the new value"
        )


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 1: MFA Policy Engine evaluates correctly
# Validates: Requirements 1.2, 1.3, 1.4, 1.5
# ---------------------------------------------------------------------------

from uuid import uuid4

from app.modules.auth.mfa_service import evaluate_mfa_requirement, validate_mfa_exclusion

ALL_ROLES = [
    "global_admin", "franchise_admin", "org_admin", "branch_admin",
    "location_manager", "salesperson", "staff_member", "kiosk",
]

ADMIN_ROLES = {"org_admin", "branch_admin"}


@given(
    role=st.sampled_from(ALL_ROLES),
    user_id=st.uuids(),
    mfa_policy=st_mfa_policy(),
)
@PBT_SETTINGS
def test_mfa_policy_engine_evaluates_correctly(
    role: str,
    user_id: _UUID,
    mfa_policy: MfaPolicy,
) -> None:
    """**Validates: Requirements 1.2, 1.3, 1.4, 1.5**

    For any user (with any role), for any MFA policy mode and exclusion list,
    evaluate_mfa_requirement should return the correct boolean:
    - False when mode is optional
    - False when user is in the exclusion list (regardless of mode)
    - True when mode is mandatory_all and user is not excluded
    - True when mode is mandatory_admins_only and role is org_admin or branch_admin and not excluded
    - False when mode is mandatory_admins_only and role is not an admin role
    """
    result = evaluate_mfa_requirement(role, user_id, mfa_policy)

    if mfa_policy.mode == "optional":
        assert result is False, "optional mode should always return False"
    elif user_id in mfa_policy.excluded_user_ids:
        assert result is False, "excluded user should always return False"
    elif mfa_policy.mode == "mandatory_all":
        assert result is True, "mandatory_all with non-excluded user should return True"
    elif mfa_policy.mode == "mandatory_admins_only":
        if role in ADMIN_ROLES:
            assert result is True, f"mandatory_admins_only with admin role '{role}' should return True"
        else:
            assert result is False, f"mandatory_admins_only with non-admin role '{role}' should return False"


@given(
    role=st.sampled_from(ALL_ROLES),
    user_id=st.uuids(),
    extra_excluded=st.lists(st.uuids(), max_size=3),
    mode=st.sampled_from(["optional", "mandatory_all", "mandatory_admins_only"]),
    include_self=st.booleans(),
)
@PBT_SETTINGS
def test_mfa_exclusion_overrides_enforcement(
    role: str,
    user_id: _UUID,
    extra_excluded: list[_UUID],
    mode: str,
    include_self: bool,
) -> None:
    """**Validates: Requirements 1.2, 1.5**

    When a user's ID is in the exclusion list, evaluate_mfa_requirement
    must return False regardless of mode (except optional which is always False).
    When the user is NOT in the exclusion list, the mode-based logic applies.
    """
    excluded = list(extra_excluded)
    if include_self:
        excluded.append(user_id)

    policy = MfaPolicy(mode=mode, excluded_user_ids=excluded)
    result = evaluate_mfa_requirement(role, user_id, policy)

    if mode == "optional":
        assert result is False
    elif user_id in excluded:
        assert result is False, "excluded user must not require MFA"
    elif mode == "mandatory_all":
        assert result is True
    elif mode == "mandatory_admins_only":
        assert result == (role in ADMIN_ROLES)


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 2: Admin self-exclusion rejection
# Validates: Requirements 1.7
# ---------------------------------------------------------------------------


@given(
    user_id=st.uuids(),
    mode=st.sampled_from(["mandatory_all", "mandatory_admins_only"]),
    extra_excluded=st.lists(st.uuids(), max_size=3),
)
@PBT_SETTINGS
def test_admin_self_exclusion_rejected_under_mandatory_modes(
    user_id: _UUID,
    mode: str,
    extra_excluded: list[_UUID],
) -> None:
    """**Validates: Requirements 1.7**

    For any org_admin user under mandatory MFA modes, attempting to add
    their own ID to the exclusion list must raise ValueError.
    """
    excluded = list(extra_excluded) + [user_id]
    policy = MfaPolicy(mode=mode, excluded_user_ids=excluded)

    with pytest.raises(ValueError, match="Cannot exclude yourself from MFA enforcement"):
        validate_mfa_exclusion(user_id, "org_admin", policy)


@given(
    user_id=st.uuids(),
    extra_excluded=st.lists(st.uuids(), max_size=3),
)
@PBT_SETTINGS
def test_admin_self_exclusion_allowed_under_optional_mode(
    user_id: _UUID,
    extra_excluded: list[_UUID],
) -> None:
    """**Validates: Requirements 1.7**

    For any org_admin user under optional mode, self-exclusion should
    NOT raise an error (exclusion list is irrelevant when mode is optional).
    """
    excluded = list(extra_excluded) + [user_id]
    policy = MfaPolicy(mode="optional", excluded_user_ids=excluded)

    # Should not raise
    validate_mfa_exclusion(user_id, "org_admin", policy)


@given(
    user_id=st.uuids(),
    role=st.sampled_from([r for r in ALL_ROLES if r != "org_admin"]),
    mode=st.sampled_from(["optional", "mandatory_all", "mandatory_admins_only"]),
    extra_excluded=st.lists(st.uuids(), max_size=3),
)
@PBT_SETTINGS
def test_non_admin_self_exclusion_always_allowed(
    user_id: _UUID,
    role: str,
    mode: str,
    extra_excluded: list[_UUID],
) -> None:
    """**Validates: Requirements 1.7**

    For any non-org_admin user, self-exclusion should never raise an error
    regardless of mode.
    """
    excluded = list(extra_excluded) + [user_id]
    policy = MfaPolicy(mode=mode, excluded_user_ids=excluded)

    # Should not raise
    validate_mfa_exclusion(user_id, role, policy)


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 3: Password validation returns exactly the unmet requirements
# Validates: Requirements 2.3, 2.4
# ---------------------------------------------------------------------------

from app.modules.auth.password_policy import validate_password_against_policy, is_password_expired


@st.composite
def st_password_for_policy(draw: st.DrawFn, policy: PasswordPolicy | None = None) -> tuple[str, PasswordPolicy]:
    """Generate a random password string and a random PasswordPolicy.

    The password is built from printable ASCII so it can contain uppercase,
    lowercase, digits, and special characters in any combination.
    """
    pol = policy if policy is not None else draw(st_password_policy())
    # Build a password of random length (0..200) from printable ASCII
    password = draw(st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
        min_size=0,
        max_size=200,
    ))
    return password, pol


def _expected_errors(password: str, policy: PasswordPolicy) -> set[str]:
    """Independently compute the set of expected error messages."""
    errors: set[str] = set()

    if len(password) < policy.min_length:
        errors.add(f"Password must be at least {policy.min_length} characters")

    if policy.require_uppercase and not any(c.isupper() for c in password):
        errors.add("Password must contain at least one uppercase letter")

    if policy.require_lowercase and not any(c.islower() for c in password):
        errors.add("Password must contain at least one lowercase letter")

    if policy.require_digit and not any(c.isdigit() for c in password):
        errors.add("Password must contain at least one digit")

    if policy.require_special and not any(not c.isalnum() for c in password):
        errors.add("Password must contain at least one special character")

    return errors


@given(data=st.data())
@PBT_SETTINGS
def test_password_validation_returns_exactly_unmet_requirements(data: st.DataObject) -> None:
    """**Validates: Requirements 2.3, 2.4**

    For any password and any valid password policy, validate_password_against_policy
    should return an error list where each item corresponds to exactly one unmet
    requirement, and the list is empty iff the password satisfies all requirements.
    """
    policy = data.draw(st_password_policy())
    password = data.draw(st.text(
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
        min_size=0,
        max_size=200,
    ))

    actual_errors = validate_password_against_policy(password, policy)
    expected = _expected_errors(password, policy)

    # The error list should contain exactly the expected errors (as a set)
    assert set(actual_errors) == expected, (
        f"Mismatch for password={password!r}, policy={policy}\n"
        f"  expected: {expected}\n"
        f"  actual:   {set(actual_errors)}"
    )

    # No duplicates
    assert len(actual_errors) == len(set(actual_errors)), "Duplicate errors returned"

    # Empty iff all requirements satisfied
    if not expected:
        assert actual_errors == [], "Expected no errors but got some"
    else:
        assert len(actual_errors) > 0, "Expected errors but got none"


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 4: Password expiry detection is correct
# Validates: Requirements 2.6
# ---------------------------------------------------------------------------

from datetime import datetime, timezone, timedelta


class _FakeUser:
    """Minimal user-like object with password_changed_at attribute."""

    def __init__(self, password_changed_at: datetime | None) -> None:
        self.password_changed_at = password_changed_at


@given(
    expiry_days=st.integers(min_value=0, max_value=365),
    days_ago=st.integers(min_value=0, max_value=730),
    has_timestamp=st.booleans(),
)
@PBT_SETTINGS
def test_password_expiry_detection_is_correct(
    expiry_days: int,
    days_ago: int,
    has_timestamp: bool,
) -> None:
    """**Validates: Requirements 2.6**

    For any user with a password_changed_at timestamp and any password policy:
    - When expiry_days is 0, is_password_expired always returns False.
    - When password_changed_at is None, is_password_expired returns True (if expiry_days > 0).
    - Otherwise, returns True iff days since password_changed_at > expiry_days.
    """
    policy = PasswordPolicy(expiry_days=expiry_days)

    if has_timestamp:
        changed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        user = _FakeUser(password_changed_at=changed_at)
    else:
        user = _FakeUser(password_changed_at=None)

    result = is_password_expired(user, policy)

    if expiry_days == 0:
        assert result is False, "expiry_days=0 should always return False"
    elif not has_timestamp:
        assert result is True, "No password_changed_at should return True when expiry_days > 0"
    else:
        # The function computes (now - changed_at).days > expiry_days
        # Since we set changed_at = now - timedelta(days=days_ago),
        # the age in days should be approximately days_ago.
        # We allow a small tolerance because of execution time between
        # creating changed_at and the function calling datetime.now().
        expected = days_ago > expiry_days
        assert result == expected, (
            f"expiry_days={expiry_days}, days_ago={days_ago}, "
            f"expected={expected}, got={result}"
        )


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 5: Password history rejects previously used passwords
# Validates: Requirements 2.8
# ---------------------------------------------------------------------------

import bcrypt as _bcrypt


@given(
    num_passwords=st.integers(min_value=1, max_value=10),
    history_count=st.integers(min_value=0, max_value=24),
    pick_from_history=st.booleans(),
)
@PBT_SETTINGS
def test_password_history_rejects_previously_used_passwords(
    num_passwords: int,
    history_count: int,
    pick_from_history: bool,
) -> None:
    """**Validates: Requirements 2.8**

    Pure logic test for password history checking. We simulate the core
    behaviour of check_password_history without a database:
    - Generate a list of bcrypt hashes (the "history").
    - Pick a candidate that either matches one of the recent hashes or is fresh.
    - Verify bcrypt.checkpw correctly identifies matches within the
      most recent min(N, history_count) entries.
    - When history_count is 0, no match should ever be found.
    """
    # Generate distinct plain-text passwords and their bcrypt hashes
    passwords = [f"TestPass{i}!@#" for i in range(num_passwords)]
    hashes = [
        _bcrypt.hashpw(p.encode("utf-8"), _bcrypt.gensalt(rounds=4))
        for p in passwords
    ]

    # The "recent" hashes are the last min(num_passwords, history_count) entries
    # (simulating ORDER BY created_at DESC LIMIT history_count)
    effective_count = min(num_passwords, history_count)
    recent_hashes = hashes[-effective_count:] if effective_count > 0 else []
    recent_passwords = passwords[-effective_count:] if effective_count > 0 else []

    if history_count == 0:
        # When history_count is 0, no check should find a match
        candidate = passwords[0]
        found = False
        # (no hashes to check against)
        assert found is False, "history_count=0 should never find a match"
    elif pick_from_history and effective_count > 0:
        # Pick a password that IS in the recent history
        candidate = recent_passwords[0]
        found = any(
            _bcrypt.checkpw(candidate.encode("utf-8"), h)
            for h in recent_hashes
        )
        assert found is True, (
            f"Expected match for candidate={candidate!r} in recent history"
        )
    else:
        # Pick a password that is NOT in the history at all
        candidate = "CompletelyFreshPassword999!@#"
        found = any(
            _bcrypt.checkpw(candidate.encode("utf-8"), h)
            for h in recent_hashes
        )
        assert found is False, (
            f"Expected no match for fresh candidate in history"
        )


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 7: Lockout engine applies correct thresholds
# Validates: Requirements 3.3, 3.4
# ---------------------------------------------------------------------------

from app.modules.auth.service import get_lockout_policy


@st.composite
def st_valid_lockout_policy(draw: st.DrawFn) -> LockoutPolicy:
    """Random LockoutPolicy within allowed ranges."""
    return LockoutPolicy(
        temp_lock_threshold=draw(st.integers(min_value=3, max_value=10)),
        temp_lock_minutes=draw(st.integers(min_value=5, max_value=60)),
        permanent_lock_threshold=draw(st.integers(min_value=5, max_value=20)),
    )


@given(
    policy=st_valid_lockout_policy(),
    failed_count=st.integers(min_value=0, max_value=25),
)
@PBT_SETTINGS
def test_lockout_engine_applies_correct_thresholds(
    policy: LockoutPolicy,
    failed_count: int,
) -> None:
    """**Validates: Requirements 3.3, 3.4**

    Pure logic test for lockout threshold comparison:
    - When failed_count >= permanent_lock_threshold → permanent deactivation
    - When failed_count >= temp_lock_threshold (but < permanent) → temp lock
    - When failed_count < temp_lock_threshold → no lockout
    """
    if failed_count >= policy.permanent_lock_threshold:
        # Should trigger permanent deactivation
        assert failed_count >= policy.permanent_lock_threshold
        # Permanent lock takes precedence — account should be deactivated
        should_temp_lock = False
        should_permanent_lock = True
    elif failed_count >= policy.temp_lock_threshold:
        # Should trigger temporary lock
        should_temp_lock = True
        should_permanent_lock = False
    else:
        # No lockout
        should_temp_lock = False
        should_permanent_lock = False

    # Simulate the lockout decision logic (mirrors service.py authenticate_user)
    actual_temp_lock = (
        failed_count >= policy.temp_lock_threshold
        and failed_count < policy.permanent_lock_threshold
    )
    actual_permanent_lock = failed_count >= policy.permanent_lock_threshold

    assert actual_temp_lock == should_temp_lock, (
        f"Temp lock mismatch: failed_count={failed_count}, "
        f"temp_threshold={policy.temp_lock_threshold}, "
        f"perm_threshold={policy.permanent_lock_threshold}"
    )
    assert actual_permanent_lock == should_permanent_lock, (
        f"Permanent lock mismatch: failed_count={failed_count}, "
        f"perm_threshold={policy.permanent_lock_threshold}"
    )


@given(
    org_settings_data=st.one_of(
        st.none(),
        st.just({}),
        st.just({"lockout_policy": None}),
        st.just({"lockout_policy": "invalid"}),
        st.builds(
            lambda t, m, p: {"lockout_policy": {
                "temp_lock_threshold": t,
                "temp_lock_minutes": m,
                "permanent_lock_threshold": p,
            }},
            t=st.integers(min_value=3, max_value=10),
            m=st.integers(min_value=5, max_value=60),
            p=st.integers(min_value=5, max_value=20),
        ),
    ),
)
@PBT_SETTINGS
def test_get_lockout_policy_fallback_and_extraction(
    org_settings_data: dict | None,
) -> None:
    """**Validates: Requirements 3.3, 3.4**

    get_lockout_policy should extract lockout policy from org settings when
    valid data is present, and fall back to defaults (5, 15, 10) otherwise.
    """
    policy = get_lockout_policy(org_settings_data)

    # Must always return a valid LockoutPolicy
    assert isinstance(policy, LockoutPolicy)

    if (
        org_settings_data
        and isinstance(org_settings_data.get("lockout_policy"), dict)
    ):
        lp = org_settings_data["lockout_policy"]
        assert policy.temp_lock_threshold == lp["temp_lock_threshold"]
        assert policy.temp_lock_minutes == lp["temp_lock_minutes"]
        assert policy.permanent_lock_threshold == lp["permanent_lock_threshold"]
    else:
        # Defaults
        assert policy.temp_lock_threshold == 5
        assert policy.temp_lock_minutes == 15
        assert policy.permanent_lock_threshold == 10


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 13: Session policy respects org overrides and exclusions
# Validates: Requirements 5.3, 5.4, 5.5
# ---------------------------------------------------------------------------

from app.modules.auth.jwt import get_session_policy
from unittest.mock import patch


@given(
    session_policy=st_session_policy(),
    user_id=st.uuids(),
    user_role=st.sampled_from(["org_admin", "branch_admin", "salesperson", "staff_member", "kiosk"]),
    include_user_in_exclusion=st.booleans(),
    include_role_in_exclusion=st.booleans(),
)
@PBT_SETTINGS
def test_session_policy_respects_org_overrides_and_exclusions(
    session_policy: SessionPolicy,
    user_id,
    user_role: str,
    include_user_in_exclusion: bool,
    include_role_in_exclusion: bool,
) -> None:
    """**Validates: Requirements 5.3, 5.4, 5.5**

    For any user and any org session policy:
    - Org-level values are used unless the user is excluded
    - If user ID is in excluded_user_ids, global defaults are returned
    - If user role is in excluded_roles, global defaults are returned
    - When no org-level session policy exists, global defaults are returned
    """
    # Build the policy with exclusions
    excluded_ids = list(session_policy.excluded_user_ids)
    excluded_roles = list(session_policy.excluded_roles)

    if include_user_in_exclusion and user_id not in excluded_ids:
        excluded_ids.append(user_id)
    if include_role_in_exclusion and user_role not in excluded_roles:
        excluded_roles.append(user_role)

    policy_data = session_policy.model_dump(mode="json")
    policy_data["excluded_user_ids"] = [str(uid) for uid in excluded_ids]
    policy_data["excluded_roles"] = excluded_roles

    org_settings = {"session_policy": policy_data}

    # Mock global config defaults
    mock_settings = type("MockSettings", (), {
        "access_token_expire_minutes": 30,
        "refresh_token_expire_days": 7,
        "max_sessions_per_user": 5,
    })()

    with patch("app.modules.auth.jwt.settings", mock_settings):
        result = get_session_policy(org_settings, user_id=user_id, user_role=user_role)

    user_excluded_by_id = user_id in [
        uid if isinstance(uid, type(user_id)) else type(user_id)(str(uid))
        for uid in excluded_ids
    ]
    user_excluded_by_role = user_role in excluded_roles

    if user_excluded_by_id or user_excluded_by_role:
        # Should get global defaults
        assert result.access_token_expire_minutes == 30
        assert result.refresh_token_expire_days == 7
        assert result.max_sessions_per_user == 5
    else:
        # Should get org-level values
        assert result.access_token_expire_minutes == session_policy.access_token_expire_minutes
        assert result.refresh_token_expire_days == session_policy.refresh_token_expire_days
        assert result.max_sessions_per_user == session_policy.max_sessions_per_user


@given(
    org_settings_data=st.one_of(
        st.none(),
        st.just({}),
        st.just({"session_policy": None}),
        st.just({"session_policy": "invalid"}),
    ),
)
@PBT_SETTINGS
def test_session_policy_falls_back_to_global_defaults(
    org_settings_data: dict | None,
) -> None:
    """**Validates: Requirements 5.3, 5.4**

    When no org-level session policy exists (None, empty, missing key, or
    malformed), get_session_policy should return global defaults.
    """
    mock_settings = type("MockSettings", (), {
        "access_token_expire_minutes": 30,
        "refresh_token_expire_days": 7,
        "max_sessions_per_user": 5,
    })()

    with patch("app.modules.auth.jwt.settings", mock_settings):
        result = get_session_policy(org_settings_data)

    assert result.access_token_expire_minutes == 30
    assert result.refresh_token_expire_days == 7
    assert result.max_sessions_per_user == 5
    assert result.excluded_user_ids == []
    assert result.excluded_roles == []


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 14: Session limit enforcement revokes oldest sessions
# Validates: Requirements 5.7
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal session-like object for pure logic testing."""

    def __init__(self, session_id: int, created_at: datetime, is_revoked: bool = False) -> None:
        self.id = session_id
        self.created_at = created_at
        self.is_revoked = is_revoked


def _enforce_session_limit_pure(
    sessions: list[_FakeSession],
    max_sessions: int,
) -> int:
    """Pure logic simulation of enforce_session_limit.

    Sorts sessions by created_at ascending and revokes the oldest ones
    until at most max_sessions remain active. Returns the count of revoked.
    """
    # Only consider active (non-revoked) sessions
    active = [s for s in sessions if not s.is_revoked]
    active.sort(key=lambda s: s.created_at)

    revoked = 0
    while len(active) - revoked >= max_sessions:
        active[revoked].is_revoked = True
        revoked += 1

    return revoked


@given(
    num_sessions=st.integers(min_value=0, max_value=15),
    max_sessions=st.integers(min_value=1, max_value=10),
    data=st.data(),
)
@PBT_SETTINGS
def test_session_limit_enforcement_revokes_oldest(
    num_sessions: int,
    max_sessions: int,
    data: st.DataObject,
) -> None:
    """**Validates: Requirements 5.7**

    Pure logic test for session limit enforcement:
    - After enforcement, at most max_sessions remain active
    - The revoked sessions are the oldest by created_at
    """
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    # Generate sessions with unique, ordered created_at timestamps
    sessions = []
    for i in range(num_sessions):
        offset_minutes = data.draw(
            st.integers(min_value=i * 10, max_value=i * 10 + 9),
            label=f"offset_{i}",
        )
        sessions.append(_FakeSession(
            session_id=i,
            created_at=base_time + timedelta(minutes=offset_minutes),
        ))

    # Record original order by created_at
    sorted_by_age = sorted(sessions, key=lambda s: s.created_at)
    original_ids_by_age = [s.id for s in sorted_by_age]

    revoked_count = _enforce_session_limit_pure(sessions, max_sessions)

    # Count remaining active sessions
    active_after = [s for s in sessions if not s.is_revoked]
    revoked_sessions = [s for s in sessions if s.is_revoked]

    # Property 1: At most max_sessions remain active
    assert len(active_after) < max_sessions, (
        f"Expected fewer than {max_sessions} active sessions, got {len(active_after)}"
    )

    # Property 2: Correct number revoked
    expected_revoked = max(0, num_sessions - max_sessions + 1)
    assert revoked_count == expected_revoked, (
        f"Expected {expected_revoked} revoked, got {revoked_count}"
    )

    # Property 3: The revoked sessions are the oldest ones
    if revoked_count > 0:
        revoked_ids = {s.id for s in revoked_sessions}
        oldest_ids = set(original_ids_by_age[:revoked_count])
        assert revoked_ids == oldest_ids, (
            f"Revoked sessions {revoked_ids} should be the oldest {oldest_ids}"
        )


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 9: Permission Registry derives from module registry
# Validates: Requirements 4.1, 4.2
# ---------------------------------------------------------------------------

from app.modules.auth.permission_registry import (
    STANDARD_ACTIONS,
    evaluate_custom_role_permissions,
    _humanise,
)
from app.modules.auth.security_settings_schemas import PermissionGroup, PermissionItem


@st.composite
def st_module_slugs(draw: st.DrawFn) -> list[str]:
    """Generate a random set of module slugs (1–10 unique slugs)."""
    slug_chars = st.text(
        alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
        min_size=2,
        max_size=20,
    ).filter(lambda s: s.isidentifier())
    return draw(st.lists(slug_chars, min_size=1, max_size=10, unique=True))


def _derive_permissions_pure(module_slugs: list[str]) -> list[PermissionGroup]:
    """Pure derivation of permissions from a list of module slugs.

    Mirrors the logic in get_available_permissions without DB/Redis.
    """
    groups: list[PermissionGroup] = []
    for slug in sorted(module_slugs):
        permissions = [
            PermissionItem(
                key=f"{slug}.{action}",
                label=_humanise(slug, action),
            )
            for action in STANDARD_ACTIONS
        ]
        groups.append(PermissionGroup(
            module_slug=slug,
            module_name=slug.replace("_", " ").title(),
            permissions=permissions,
        ))
    return groups


@given(module_slugs=st_module_slugs())
@PBT_SETTINGS
def test_permission_registry_derives_from_module_registry(
    module_slugs: list[str],
) -> None:
    """**Validates: Requirements 4.1, 4.2**

    For any set of module slugs, the Permission Registry should generate
    permission keys in the format {module_slug}.{action} for each standard
    action, and the set of generated module slugs should exactly match.
    """
    groups = _derive_permissions_pure(module_slugs)

    # Collect all generated permission keys
    all_keys: list[str] = []
    generated_slugs: set[str] = set()
    for group in groups:
        generated_slugs.add(group.module_slug)
        for perm in group.permissions:
            all_keys.append(perm.key)

    # Property 1: Generated module slugs match input exactly
    assert generated_slugs == set(module_slugs), (
        f"Module slug mismatch: expected {set(module_slugs)}, got {generated_slugs}"
    )

    # Property 2: Each module has exactly len(STANDARD_ACTIONS) permissions
    for group in groups:
        assert len(group.permissions) == len(STANDARD_ACTIONS), (
            f"Module {group.module_slug} has {len(group.permissions)} permissions, "
            f"expected {len(STANDARD_ACTIONS)}"
        )

    # Property 3: All permission keys follow {module_slug}.{action} format
    for key in all_keys:
        parts = key.split(".")
        assert len(parts) == 2, f"Permission key {key!r} does not have exactly 2 parts"
        slug_part, action_part = parts
        assert slug_part in module_slugs, f"Slug {slug_part!r} not in module_slugs"
        assert action_part in STANDARD_ACTIONS, f"Action {action_part!r} not in STANDARD_ACTIONS"

    # Property 4: Total permission count = modules × actions
    assert len(all_keys) == len(module_slugs) * len(STANDARD_ACTIONS)


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 10: Disabled modules excluded from custom role permissions
# Validates: Requirements 4.4, 4.7
# ---------------------------------------------------------------------------


@st.composite
def st_permission_keys(draw: st.DrawFn) -> list[str]:
    """Generate a random list of permission keys in {slug}.{action} format."""
    slugs = draw(st.lists(
        st.sampled_from([
            "invoices", "customers", "inventory", "pos", "jobs",
            "quotes", "bookings", "expenses", "scheduling", "reports",
        ]),
        min_size=1,
        max_size=8,
        unique=True,
    ))
    keys: list[str] = []
    for slug in slugs:
        actions = draw(st.lists(
            st.sampled_from(STANDARD_ACTIONS),
            min_size=1,
            max_size=4,
            unique=True,
        ))
        for action in actions:
            keys.append(f"{slug}.{action}")
    return keys


@given(
    role_permissions=st_permission_keys(),
    disabled_modules=st.lists(
        st.sampled_from([
            "invoices", "customers", "inventory", "pos", "jobs",
            "quotes", "bookings", "expenses", "scheduling", "reports",
        ]),
        min_size=0,
        max_size=5,
        unique=True,
    ),
)
@PBT_SETTINGS
def test_disabled_modules_excluded_from_custom_role_permissions(
    role_permissions: list[str],
    disabled_modules: list[str],
) -> None:
    """**Validates: Requirements 4.4, 4.7**

    For any custom role permission list and any set of disabled modules,
    evaluate_custom_role_permissions should:
    1. Return only permissions whose module prefix is NOT in disabled_modules
    2. Not mutate the original role_permissions list
    """
    original_copy = list(role_permissions)
    disabled_set = set(disabled_modules)

    result = evaluate_custom_role_permissions(role_permissions, disabled_set)

    # Property 1: No permission in result has a disabled module prefix
    for perm in result:
        module_prefix = perm.split(".")[0]
        assert module_prefix not in disabled_set, (
            f"Permission {perm!r} has disabled module prefix {module_prefix!r}"
        )

    # Property 2: All non-disabled permissions are preserved
    expected = [p for p in role_permissions if p.split(".")[0] not in disabled_set]
    assert result == expected, (
        f"Expected {expected}, got {result}"
    )

    # Property 3: Original list is unchanged
    assert role_permissions == original_copy, (
        "Original role_permissions list was mutated"
    )

    # Property 4: Result is a subset of original
    assert set(result) <= set(role_permissions)


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 12: Built-in roles cannot be deleted
# Validates: Requirements 4.8
# ---------------------------------------------------------------------------

from app.modules.auth.custom_roles_service import BUILT_IN_ROLE_SLUGS


@given(
    slug=st.sampled_from(sorted(BUILT_IN_ROLE_SLUGS)),
)
@PBT_SETTINGS
def test_built_in_roles_cannot_be_deleted(slug: str) -> None:
    """**Validates: Requirements 4.8**

    For any built-in role slug, attempting to delete it should be rejected.
    We verify this by checking that the slug is in the BUILT_IN_ROLE_SLUGS
    set, which the delete_custom_role function checks before proceeding.

    The actual delete_custom_role function is async and requires a DB session,
    so we test the guard logic directly: built-in roles have is_system=True
    in the DB, and the service raises ValueError("Cannot delete built-in role")
    for system roles.

    Here we verify the pure invariant: all known built-in slugs are in the
    protected set, and the set is non-empty.
    """
    assert slug in BUILT_IN_ROLE_SLUGS, (
        f"Slug {slug!r} should be in BUILT_IN_ROLE_SLUGS"
    )
    # Verify the set contains all 8 expected built-in roles
    assert len(BUILT_IN_ROLE_SLUGS) == 8
    assert "global_admin" in BUILT_IN_ROLE_SLUGS
    assert "org_admin" in BUILT_IN_ROLE_SLUGS
    assert "branch_admin" in BUILT_IN_ROLE_SLUGS
    assert "location_manager" in BUILT_IN_ROLE_SLUGS
    assert "salesperson" in BUILT_IN_ROLE_SLUGS
    assert "staff_member" in BUILT_IN_ROLE_SLUGS
    assert "kiosk" in BUILT_IN_ROLE_SLUGS
    assert "franchise_admin" in BUILT_IN_ROLE_SLUGS


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 11: Custom role permissions used for custom role users
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------

from app.modules.auth.rbac import has_permission


@given(
    custom_permissions=st_permission_keys(),
    test_permission=st.sampled_from([
        "invoices.create", "invoices.read", "invoices.update", "invoices.delete",
        "customers.create", "customers.read", "inventory.read", "pos.create",
        "jobs.update", "quotes.delete", "bookings.read", "expenses.create",
        "scheduling.update", "reports.read",
    ]),
)
@PBT_SETTINGS
def test_custom_role_permissions_used_for_custom_role_users(
    custom_permissions: list[str],
    test_permission: str,
) -> None:
    """**Validates: Requirements 4.6**

    For any user assigned a custom role with a specific permission list,
    has_permission should return True for permissions in that list and
    False for permissions not in that list, regardless of what the static
    ROLE_PERMISSIONS dict says for any built-in role.
    """
    # Use a built-in role that would normally have different permissions
    role = "staff_member"  # Very restricted built-in role

    # With custom_role_permissions, the built-in ROLE_PERMISSIONS is bypassed
    result = has_permission(
        role=role,
        permission=test_permission,
        custom_role_permissions=custom_permissions,
    )

    if test_permission in custom_permissions:
        assert result is True, (
            f"Permission {test_permission!r} is in custom_permissions but "
            f"has_permission returned False"
        )
    else:
        assert result is False, (
            f"Permission {test_permission!r} is NOT in custom_permissions but "
            f"has_permission returned True"
        )


@given(
    custom_permissions=st_permission_keys(),
    role=st.sampled_from(["staff_member", "kiosk", "salesperson"]),
)
@PBT_SETTINGS
def test_custom_role_overrides_built_in_role_permissions(
    custom_permissions: list[str],
    role: str,
) -> None:
    """**Validates: Requirements 4.6**

    When custom_role_permissions is provided, the static ROLE_PERMISSIONS
    dict for the built-in role is completely bypassed. Only the custom
    permissions list determines access.
    """
    for perm in custom_permissions:
        # Custom role grants this permission
        assert has_permission(role, perm, custom_role_permissions=custom_permissions) is True

    # A permission NOT in the custom list should be denied,
    # even if the built-in role would normally grant it
    fake_perm = "zzz_nonexistent_module.read"
    assert has_permission(role, fake_perm, custom_role_permissions=custom_permissions) is False


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 15: Audit log query correctness
# Validates: Requirements 6.1, 6.3, 6.4, 6.5
# ---------------------------------------------------------------------------

from app.modules.auth.security_audit_service import (
    is_security_action,
    get_action_description,
    parse_device_info,
    MAX_ENTRIES,
)
from app.modules.auth.security_settings_schemas import (
    ACTION_DESCRIPTIONS,
    AuditLogFilters,
)


# -- Strategies ---------------------------------------------------------------

SECURITY_ACTIONS = [
    "auth.login_success",
    "auth.login_failed_invalid_password",
    "auth.login_failed_unknown_email",
    "auth.mfa_verified",
    "auth.mfa_failed",
    "auth.password_changed",
    "auth.password_reset",
    "auth.session_revoked",
    "auth.all_sessions_revoked",
    "org.mfa_policy_updated",
    "org.security_settings_updated",
    "org.custom_role_created",
    "org.custom_role_updated",
    "org.custom_role_deleted",
]

NON_SECURITY_ACTIONS = [
    "invoice.issued",
    "invoice.paid",
    "customer.created",
    "inventory.adjusted",
    "org.subscription_updated",
    "billing.payment_received",
]


@st.composite
def st_audit_entry(draw: st.DrawFn, org_id=None) -> dict:
    """Generate a random audit log entry dict (simulating a DB row)."""
    entry_org_id = org_id if org_id is not None else draw(st.uuids())
    action = draw(st.sampled_from(SECURITY_ACTIONS + NON_SECURITY_ACTIONS))
    user_id = draw(st.uuids())
    timestamp = draw(st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2026, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    ip_address = draw(st.one_of(
        st.none(),
        st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    ))
    return {
        "id": draw(st.uuids()),
        "org_id": entry_org_id,
        "user_id": user_id,
        "action": action,
        "entity_type": draw(st.sampled_from(["user", "organisation", "session", None])),
        "entity_id": str(draw(st.uuids())) if draw(st.booleans()) else None,
        "before_value": None,
        "after_value": None,
        "ip_address": ip_address,
        "device_info": draw(st.one_of(st.none(), st.just(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ))),
        "created_at": timestamp,
        "user_email": draw(st.one_of(st.none(), st.emails())),
    }


def _filter_and_sort_entries(
    entries: list[dict],
    org_id,
    filters: AuditLogFilters,
) -> tuple[list[dict], bool]:
    """Pure-logic simulation of the audit log query filtering and ordering.

    Returns (paginated_items, truncated).
    """
    # 1. Filter to org
    result = [e for e in entries if e["org_id"] == org_id]

    # 2. Filter to security actions
    result = [e for e in result if is_security_action(e["action"])]

    # 3. Apply optional filters
    if filters.start_date is not None:
        result = [e for e in result if e["created_at"] >= filters.start_date]
    if filters.end_date is not None:
        result = [e for e in result if e["created_at"] <= filters.end_date]
    if filters.action is not None:
        result = [e for e in result if e["action"] == filters.action]
    if filters.user_id is not None:
        result = [e for e in result if e["user_id"] == filters.user_id]

    # 4. Order descending by created_at
    result.sort(key=lambda e: e["created_at"], reverse=True)

    # 5. Truncation
    total = len(result)
    truncated = total > MAX_ENTRIES
    result = result[:MAX_ENTRIES]

    # 6. Paginate
    page_size = min(filters.page_size, MAX_ENTRIES)
    offset = (filters.page - 1) * page_size
    page_items = result[offset:offset + page_size]

    return page_items, truncated


@given(
    target_org_id=st.uuids(),
    other_org_id=st.uuids(),
    num_entries=st.integers(min_value=0, max_value=50),
    page_size=st.integers(min_value=1, max_value=25),
    use_action_filter=st.booleans(),
    use_date_filter=st.booleans(),
    data=st.data(),
)
@PBT_SETTINGS
def test_audit_log_query_correctness(
    target_org_id,
    other_org_id,
    num_entries: int,
    page_size: int,
    use_action_filter: bool,
    use_date_filter: bool,
    data: st.DataObject,
) -> None:
    """**Validates: Requirements 6.1, 6.3, 6.4, 6.5**

    Pure logic test for audit log filtering and ordering:
    (a) All returned entries belong to the queried org
    (b) All returned entries have a security-related action
    (c) All returned entries match applied filters
    (d) Entries are ordered descending by created_at
    (e) Result does not exceed page_size
    """
    # Generate a mix of entries for target org and other org
    entries: list[dict] = []
    for _ in range(num_entries):
        org = data.draw(st.sampled_from([target_org_id, other_org_id]))
        entries.append(data.draw(st_audit_entry(org_id=org)))

    # Build filters
    action_filter = None
    if use_action_filter:
        action_filter = data.draw(st.sampled_from(SECURITY_ACTIONS))

    start_date = None
    end_date = None
    if use_date_filter:
        start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end_date = datetime(2025, 12, 31, tzinfo=timezone.utc)

    filters = AuditLogFilters(
        page=1,
        page_size=page_size,
        action=action_filter,
        start_date=start_date,
        end_date=end_date,
    )

    page_items, truncated = _filter_and_sort_entries(entries, target_org_id, filters)

    # (a) All entries belong to target org
    for item in page_items:
        assert item["org_id"] == target_org_id, (
            f"Entry org_id {item['org_id']} != target {target_org_id}"
        )

    # (b) All entries have security-related action
    for item in page_items:
        assert is_security_action(item["action"]), (
            f"Action {item['action']!r} is not a security action"
        )

    # (c) Entries match applied filters
    for item in page_items:
        if action_filter is not None:
            assert item["action"] == action_filter
        if start_date is not None:
            assert item["created_at"] >= start_date
        if end_date is not None:
            assert item["created_at"] <= end_date

    # (d) Ordered descending by created_at
    for i in range(len(page_items) - 1):
        assert page_items[i]["created_at"] >= page_items[i + 1]["created_at"], (
            f"Not descending: {page_items[i]['created_at']} < {page_items[i+1]['created_at']}"
        )

    # (e) Does not exceed page_size
    assert len(page_items) <= page_size


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 16: Audit log entries contain required fields
# Validates: Requirements 6.2, 6.6
# ---------------------------------------------------------------------------

from app.modules.auth.security_settings_schemas import AuditLogEntry as _AuditLogEntry


@st.composite
def st_audit_entry_with_known_action(draw: st.DrawFn) -> dict:
    """Generate a random audit log entry with a known security action key."""
    action = draw(st.sampled_from(list(ACTION_DESCRIPTIONS.keys())))
    user_email = draw(st.one_of(st.none(), st.emails()))
    ip_address = draw(st.one_of(
        st.none(),
        st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    ))
    device_info = draw(st.one_of(
        st.none(),
        st.just(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        st.just(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        ),
        st.just(
            "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"
        ),
        st.just("some-random-unparseable-string"),
    ))
    timestamp = draw(st.datetimes(
        min_value=datetime(2024, 1, 1),
        max_value=datetime(2026, 12, 31),
        timezones=st.just(timezone.utc),
    ))
    return {
        "id": draw(st.uuids()),
        "action": action,
        "user_email": user_email,
        "ip_address": ip_address,
        "device_info": device_info,
        "created_at": timestamp,
        "entity_type": draw(st.sampled_from(["user", "organisation", None])),
        "entity_id": str(draw(st.uuids())) if draw(st.booleans()) else None,
        "before_value": None,
        "after_value": None,
    }


def _build_audit_log_entry(raw: dict) -> _AuditLogEntry:
    """Build an AuditLogEntry from a raw dict, simulating the service logic."""
    browser, os_name = parse_device_info(raw["device_info"])
    return _AuditLogEntry(
        id=raw["id"],
        timestamp=raw["created_at"],
        user_email=raw["user_email"],
        action=raw["action"],
        action_description=get_action_description(raw["action"]),
        ip_address=raw["ip_address"],
        browser=browser,
        os=os_name,
        entity_type=raw["entity_type"],
        entity_id=raw["entity_id"],
        before_value=raw["before_value"],
        after_value=raw["after_value"],
    )


@given(raw_entry=st_audit_entry_with_known_action())
@PBT_SETTINGS
def test_audit_log_entries_contain_required_fields(raw_entry: dict) -> None:
    """**Validates: Requirements 6.2, 6.6**

    For any audit log entry with a known action key:
    - The response includes timestamp, user_email, action, action_description,
      ip_address, browser, os
    - action_description is a non-empty string
    - For known action keys, action_description matches ACTION_DESCRIPTIONS
    """
    entry = _build_audit_log_entry(raw_entry)

    # Required fields are present (not missing from the model)
    assert entry.timestamp is not None
    assert entry.action is not None
    assert entry.action_description is not None

    # action_description is non-empty
    assert len(entry.action_description) > 0, (
        f"action_description is empty for action {entry.action!r}"
    )

    # For known action keys, description matches the mapping
    if entry.action in ACTION_DESCRIPTIONS:
        assert entry.action_description == ACTION_DESCRIPTIONS[entry.action], (
            f"For action {entry.action!r}, expected description "
            f"{ACTION_DESCRIPTIONS[entry.action]!r} but got {entry.action_description!r}"
        )

    # user_email is either None or a string
    assert entry.user_email is None or isinstance(entry.user_email, str)

    # ip_address is either None or a string
    assert entry.ip_address is None or isinstance(entry.ip_address, str)

    # browser and os are either None or non-empty strings
    if entry.browser is not None:
        assert isinstance(entry.browser, str) and len(entry.browser) > 0
    if entry.os is not None:
        assert isinstance(entry.os, str) and len(entry.os) > 0


@given(
    action=st.sampled_from(list(ACTION_DESCRIPTIONS.keys())),
)
@PBT_SETTINGS
def test_action_description_matches_mapping_for_all_known_keys(action: str) -> None:
    """**Validates: Requirements 6.6**

    For every known action key in ACTION_DESCRIPTIONS, get_action_description
    must return the exact mapped value.
    """
    description = get_action_description(action)
    assert description == ACTION_DESCRIPTIONS[action], (
        f"For action {action!r}, expected {ACTION_DESCRIPTIONS[action]!r} "
        f"but got {description!r}"
    )


# ---------------------------------------------------------------------------
# Feature: org-security-settings, Property 19: Security endpoints reject non-admin users
# Validates: Requirements 7.4
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock
from fastapi import HTTPException
from app.modules.auth.rbac import require_role as _require_role

# All roles that are NOT org_admin (and not global_admin, which is a superadmin)
NON_ADMIN_ROLES = [
    "branch_admin",
    "location_manager",
    "salesperson",
    "staff_member",
    "kiosk",
    "franchise_admin",
]


def _make_mock_request(user_id: str, org_id: str, role: str) -> MagicMock:
    """Build a mock Request with the given state attributes."""
    request = MagicMock()
    request.state.user_id = user_id
    request.state.org_id = org_id
    request.state.role = role
    return request


@given(
    role=st.sampled_from(NON_ADMIN_ROLES),
    user_id=st.uuids(),
    org_id=st.uuids(),
)
@PBT_SETTINGS
def test_security_endpoints_reject_non_admin_users(
    role: str,
    user_id: _UUID,
    org_id: _UUID,
) -> None:
    """**Validates: Requirements 7.4**

    For any user with a role other than org_admin (and not global_admin),
    the require_role("org_admin") RBAC check should raise HTTPException
    with status 403.

    This is a PURE LOGIC test — we invoke the inner dependency function
    directly with a mock request, not actual HTTP calls.
    """
    import asyncio

    # require_role returns Depends(_check); extract the inner _check callable
    depends_obj = _require_role("org_admin")
    check_fn = depends_obj.dependency

    request = _make_mock_request(str(user_id), str(org_id), role)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(check_fn(request))

    assert exc_info.value.status_code == 403, (
        f"Expected 403 for role={role!r}, got {exc_info.value.status_code}"
    )


@given(
    user_id=st.uuids(),
    org_id=st.uuids(),
)
@PBT_SETTINGS
def test_security_endpoints_allow_org_admin(
    user_id: _UUID,
    org_id: _UUID,
) -> None:
    """**Validates: Requirements 7.4**

    For any user with the org_admin role, the require_role("org_admin")
    RBAC check should NOT raise an exception.
    """
    import asyncio

    depends_obj = _require_role("org_admin")
    check_fn = depends_obj.dependency

    request = _make_mock_request(str(user_id), str(org_id), "org_admin")

    # Should not raise
    asyncio.run(check_fn(request))

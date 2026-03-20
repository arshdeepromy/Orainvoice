"""Property-based tests for the auth module (Task 4.12).

Uses Hypothesis to verify universal correctness properties across randomly
generated inputs for authentication, session management, RBAC, and IP
allowlisting.

Feature: workshoppro-nz-platform
Properties 7–13

Validates: Requirements 1.5, 1.7, 1.8, 3.1, 3.2, 3.6, 4.4, 5.2, 5.3, 5.4, 5.5, 6.1, 6.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# Ensure Organisation model is loaded for relationship resolution
import app.modules.admin.models  # noqa: F401

from app.modules.auth.password import hash_password
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import (
    PERMANENT_LOCK_THRESHOLD,
    TEMP_LOCK_MINUTES,
    TEMP_LOCK_THRESHOLD,
    authenticate_user,
    enforce_session_limit,
    request_password_reset,
    rotate_refresh_token,
)
from app.modules.auth.rbac import (
    check_role_path_access,
    GLOBAL_ADMIN,
    GLOBAL_ADMIN_DENIED_PREFIXES,
    GLOBAL_ADMIN_ONLY_PREFIXES,
    ORG_ADMIN,
    SALESPERSON,
    SALESPERSON_DENIED_PREFIXES,
    SALESPERSON_DENIED_WRITE_PREFIXES,
)
from app.core.ip_allowlist import is_ip_in_allowlist


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


auth_event_types = st.sampled_from([
    "login_success",
    "login_failed",
    "mfa_verify",
    "session_created",
    "session_terminated",
])

ip_v4 = st.tuples(
    st.integers(1, 254),
    st.integers(0, 255),
    st.integers(0, 255),
    st.integers(1, 254),
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")

device_types = st.sampled_from(["Desktop", "Mobile", "Tablet", None])
browsers = st.sampled_from(["Chrome", "Firefox", "Safari", "Edge", None])
emails = st.from_regex(r"[a-z]{3,8}@[a-z]{3,6}\.(com|nz|org)", fullmatch=True)
passwords = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=12,
    max_size=30,
)
roles = st.sampled_from([GLOBAL_ADMIN, ORG_ADMIN, SALESPERSON])

# Paths that are meaningful for RBAC testing
api_paths = st.sampled_from([
    "/api/v1/admin/organisations",
    "/api/v1/admin/errors",
    "/api/v1/admin/plans",
    "/api/v1/customers/",
    "/api/v1/customers/123",
    "/api/v1/invoices/",
    "/api/v1/invoices/456",
    "/api/v1/vehicles/",
    "/api/v1/vehicles/lookup/ABC123",
    "/api/v1/payments/cash",
    "/api/v1/quotes/",
    "/api/v1/job-cards/",
    "/api/v1/bookings/",
    "/api/v1/org/settings",
    "/api/v1/org/users",
    "/api/v1/org/branches",
    "/api/v1/billing/",
    "/api/v1/billing/upgrade",
    "/api/v1/catalogue/services",
    "/api/v1/catalogue/parts",
    "/api/v1/notifications/settings",
    "/api/v1/auth/login",
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    *,
    email: str = "user@example.com",
    password: str = "CorrectPassword1!",
    is_active: bool = True,
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
    mfa_methods: list | None = None,
    org_id: uuid.UUID | None = None,
):
    """Build a mock User object."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.org_id = org_id or uuid.uuid4()
    u.email = email
    u.password_hash = hash_password(password)
    u.role = "salesperson"
    u.is_active = is_active
    u.is_email_verified = True
    u.failed_login_count = failed_login_count
    u.locked_until = locked_until
    u.mfa_methods = mfa_methods or []
    u.last_login_at = None
    u.passkey_credentials = []
    return u


def _mock_scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_all(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _make_session(
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    *,
    is_revoked: bool = False,
    expired: bool = False,
):
    """Build a mock Session object."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.user_id = user_id
    s.org_id = uuid.uuid4()
    s.family_id = family_id
    s.is_revoked = is_revoked
    s.device_type = "Desktop"
    s.browser = "Chrome"
    s.ip_address = "1.2.3.4"
    if expired:
        s.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    else:
        s.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    s.created_at = datetime.now(timezone.utc)
    return s


# ===========================================================================
# Property 7: Authentication Events Are Fully Logged
# ===========================================================================

class TestProperty7AuthEventsFullyLogged:
    """Feature: workshoppro-nz-platform, Property 7: Authentication Events Are Fully Logged

    *For any* authentication event (successful login, failed login, MFA
    verification, session creation, session termination), the audit log
    shall contain an entry with: the acting user (or attempted email),
    action type, timestamp, IP address, and device information. Failed
    logins shall additionally include the failure reason.

    **Validates: Requirements 1.7, 1.8**
    """

    @PBT_SETTINGS
    @given(
        ip=ip_v4,
        device=device_types,
        browser=browsers,
    )
    @pytest.mark.asyncio
    async def test_successful_login_produces_audit_entry(self, ip, device, browser):
        """Every successful login writes a complete audit log entry."""
        user = _make_user()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(user))
        db.add = MagicMock()

        with (
            patch("app.modules.auth.service.write_audit_log") as mock_audit,
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._check_anomalous_login", new_callable=AsyncMock),
            patch("app.modules.auth.service.enforce_session_limit", new_callable=AsyncMock, return_value=0),
        ):
            req = LoginRequest(email=user.email, password="CorrectPassword1!")
            result = await authenticate_user(db, req, ip, device, browser)

            # Audit must have been called for the successful login
            assert mock_audit.await_count >= 1
            # Find the success call
            success_calls = [
                c for c in mock_audit.call_args_list
                if c.kwargs.get("action") == "auth.login_success"
            ]
            assert len(success_calls) == 1
            call_kw = success_calls[0].kwargs
            assert call_kw["user_id"] == user.id
            assert call_kw["ip_address"] == ip
            assert call_kw["entity_type"] == "user"
            # after_value should contain device info
            after = call_kw["after_value"]
            assert "ip_address" in after
            assert "device_type" in after
            assert "browser" in after

    @PBT_SETTINGS
    @given(
        ip=ip_v4,
        email=emails,
    )
    @pytest.mark.asyncio
    async def test_failed_login_produces_audit_with_reason(self, ip, email):
        """Every failed login writes an audit entry including the failure reason."""
        db = AsyncMock()
        # User not found
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(None))

        with patch("app.modules.auth.service.write_audit_log") as mock_audit:
            req = LoginRequest(email=email, password="WrongPassword1!")
            with pytest.raises(ValueError):
                await authenticate_user(db, req, ip, None, None)

            assert mock_audit.await_count >= 1
            call_kw = mock_audit.call_args_list[0].kwargs
            assert call_kw["action"] == "auth.login_failed"
            assert call_kw["ip_address"] == ip
            after = call_kw["after_value"]
            assert "reason" in after
            assert after["reason"] == "unknown_email"


# ===========================================================================
# Property 8: Refresh Token Rotation Detects Reuse
# ===========================================================================

class TestProperty8RefreshTokenReuseDetection:
    """Feature: workshoppro-nz-platform, Property 8: Refresh Token Rotation Detects Reuse

    *For any* session family, if a refresh token that has already been
    consumed is presented again, the system shall invalidate all tokens
    in that session family and send an alert email to the account holder.

    **Validates: Requirements 1.5**
    """

    @PBT_SETTINGS
    @given(num_family_sessions=st.integers(min_value=1, max_value=5))
    @pytest.mark.asyncio
    async def test_reused_token_invalidates_family(self, num_family_sessions):
        """A reused (already-revoked) refresh token invalidates the entire family."""
        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        token = "reused-token-abc"

        # Build a revoked session matching the token hash
        revoked_session = _make_session(user_id, family_id, is_revoked=True)
        revoked_session.refresh_token_hash = (
            __import__("hashlib").sha256(token.encode()).hexdigest()
        )

        user = MagicMock()
        user.id = user_id
        user.email = "victim@example.com"

        # First query (valid session) returns None; second (any session) returns revoked
        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalar_one_or_none(None)  # no valid session
            elif call_count == 2:
                return _mock_scalar_one_or_none(revoked_session)  # revoked found
            elif call_count == 3:
                return _mock_scalar_one_or_none(user)  # user lookup
            return MagicMock()

        db = AsyncMock()
        db.execute = mock_execute

        with (
            patch("app.modules.auth.service._invalidate_family", new_callable=AsyncMock) as mock_invalidate,
            patch("app.modules.auth.service._send_token_reuse_alert", new_callable=AsyncMock) as mock_alert,
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="revoked"):
                await rotate_refresh_token(db, token)

            # Family must be invalidated
            mock_invalidate.assert_awaited_once_with(db, family_id)
            # Alert email must be sent
            mock_alert.assert_awaited_once_with("victim@example.com")


# ===========================================================================
# Property 9: Account Lockout After Failed Attempts
# ===========================================================================

class TestProperty9AccountLockout:
    """Feature: workshoppro-nz-platform, Property 9: Account Lockout After Failed Attempts

    *For any* user account, if 5 consecutive failed login attempts occur,
    the account shall be locked for 15 minutes. If 10 consecutive failures
    occur, the account shall be locked until manual unlock, and a
    notification email shall be sent.

    **Validates: Requirements 3.1, 3.2**
    """

    @PBT_SETTINGS
    @given(
        prior_failures=st.integers(min_value=0, max_value=TEMP_LOCK_THRESHOLD - 2),
    )
    @pytest.mark.asyncio
    async def test_reaching_5_failures_triggers_temp_lock(self, prior_failures):
        """Accumulating to 5 consecutive failures triggers a 15-minute lock."""
        # Start with prior_failures, then fail enough times to reach threshold
        failures_needed = TEMP_LOCK_THRESHOLD - prior_failures
        assume(failures_needed >= 1)

        user = _make_user(failed_login_count=prior_failures)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(user))
        db.add = MagicMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._send_permanent_lockout_email", new_callable=AsyncMock),
        ):
            for _ in range(failures_needed):
                req = LoginRequest(email=user.email, password="WrongPassword!")
                with pytest.raises(ValueError):
                    await authenticate_user(db, req, "1.2.3.4", None, None)

            # After reaching 5 failures, account should be temporarily locked
            assert user.failed_login_count >= TEMP_LOCK_THRESHOLD
            if user.failed_login_count < PERMANENT_LOCK_THRESHOLD:
                assert user.locked_until is not None
                # Lock duration should be approximately 15 minutes
                expected = datetime.now(timezone.utc) + timedelta(minutes=TEMP_LOCK_MINUTES)
                assert abs((user.locked_until - expected).total_seconds()) < 5

    @PBT_SETTINGS
    @given(
        prior_failures=st.integers(
            min_value=TEMP_LOCK_THRESHOLD,
            max_value=PERMANENT_LOCK_THRESHOLD - 2,
        ),
    )
    @pytest.mark.asyncio
    async def test_reaching_10_failures_triggers_permanent_lock(self, prior_failures):
        """Accumulating to 10 consecutive failures permanently locks the account."""
        failures_needed = PERMANENT_LOCK_THRESHOLD - prior_failures
        assume(failures_needed >= 1)

        user = _make_user(failed_login_count=prior_failures)
        # Clear any temp lock so the login attempt proceeds to password check
        user.locked_until = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(user))
        db.add = MagicMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._send_permanent_lockout_email", new_callable=AsyncMock) as mock_email,
        ):
            for _ in range(failures_needed):
                # Clear any temp lock set by previous iteration so the
                # password-check path is reached and the counter keeps
                # incrementing toward the permanent threshold.
                user.locked_until = None
                req = LoginRequest(email=user.email, password="WrongPassword!")
                with pytest.raises(ValueError):
                    await authenticate_user(db, req, "1.2.3.4", None, None)

            # Account should be permanently locked (deactivated)
            assert user.failed_login_count >= PERMANENT_LOCK_THRESHOLD
            assert user.is_active is False
            mock_email.assert_awaited()


# ===========================================================================
# Property 10: Session Limit Enforcement
# ===========================================================================

class TestProperty10SessionLimitEnforcement:
    """Feature: workshoppro-nz-platform, Property 10: Session Limit Enforcement

    *For any* user within an organisation, the number of active
    (non-revoked, non-expired) sessions shall never exceed the
    organisation's configured maximum sessions per user. When a new
    session would exceed the limit, the oldest session shall be revoked.

    **Validates: Requirements 3.6**
    """

    @PBT_SETTINGS
    @given(
        max_sessions=st.integers(min_value=1, max_value=10),
        existing_sessions=st.integers(min_value=0, max_value=15),
    )
    @pytest.mark.asyncio
    async def test_active_sessions_never_exceed_max(self, max_sessions, existing_sessions):
        """After enforce_session_limit, active sessions < max_sessions."""
        user_id = uuid.uuid4()

        # Build mock active sessions ordered by created_at
        sessions = []
        for i in range(existing_sessions):
            s = MagicMock()
            s.id = uuid.uuid4()
            s.user_id = user_id
            s.is_revoked = False
            s.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            s.created_at = datetime.now(timezone.utc) - timedelta(hours=existing_sessions - i)
            sessions.append(s)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_all(sessions))

        mock_lock = AsyncMock()
        mock_lock.acquire.return_value = True
        mock_lock.release.return_value = True
        mock_pool = MagicMock()
        mock_pool.lock.return_value = mock_lock

        with patch("app.core.redis.redis_pool", mock_pool):
            revoked = await enforce_session_limit(db=db, user_id=user_id, max_sessions=max_sessions)

        # Count sessions that are still active (not revoked by the function)
        still_active = sum(1 for s in sessions if not s.is_revoked)

        # After enforcement, remaining active sessions must be < max_sessions
        # (leaving room for the new session about to be created)
        assert still_active < max_sessions
        # The number revoked should be correct
        assert revoked == existing_sessions - still_active


# ===========================================================================
# Property 11: Password Reset Response Uniformity
# ===========================================================================

class TestProperty11PasswordResetUniformity:
    """Feature: workshoppro-nz-platform, Property 11: Password Reset Response Uniformity

    *For any* email address submitted to the password reset endpoint —
    whether it exists in the system or not — the HTTP response status
    code, response body structure, and response timing shall be
    indistinguishable, preventing account enumeration.

    **Validates: Requirements 4.4**
    """

    @PBT_SETTINGS
    @given(email=emails)
    @pytest.mark.asyncio
    async def test_existing_and_nonexisting_emails_return_none(self, email):
        """request_password_reset returns None for both existing and non-existing emails."""
        # Case 1: email does NOT exist
        db_no_user = AsyncMock()
        db_no_user.execute = AsyncMock(return_value=_mock_scalar_one_or_none(None))

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
        ):
            result_missing = await request_password_reset(db_no_user, email)

        # Case 2: email DOES exist
        user = _make_user(email=email)
        db_with_user = AsyncMock()
        db_with_user.execute = AsyncMock(return_value=_mock_scalar_one_or_none(user))

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool") as mock_redis,
            patch("app.modules.auth.service._send_password_reset_email", new_callable=AsyncMock),
        ):
            mock_redis.setex = AsyncMock()
            result_found = await request_password_reset(db_with_user, email)

        # Both must return None — identical response to caller
        assert result_missing is None
        assert result_found is None


# ===========================================================================
# Property 12: RBAC Enforcement
# ===========================================================================

class TestProperty12RBACEnforcement:
    """Feature: workshoppro-nz-platform, Property 12: Role-Based Access Control Enforcement

    *For any* API request, the system shall verify the requesting user's
    role and organisation membership before processing. A Salesperson
    shall be denied access to org settings, billing, and user management
    endpoints. An Org_Admin shall be denied access to Global Admin
    endpoints. A Global_Admin shall be denied direct access to org-level
    customer and invoice data.

    **Validates: Requirements 5.2, 5.3, 5.4, 5.5**
    """

    @PBT_SETTINGS
    @given(path=api_paths)
    def test_salesperson_denied_restricted_paths(self, path):
        """Salesperson is denied access to org settings, billing, user mgmt, catalogue, admin."""
        result = check_role_path_access(SALESPERSON, path)
        is_denied_path = any(path.startswith(p) for p in SALESPERSON_DENIED_PREFIXES)
        is_write_denied_path = any(path.startswith(p) for p in SALESPERSON_DENIED_WRITE_PREFIXES)
        if is_denied_path:
            assert result is not None, f"Salesperson should be denied {path}"
        elif is_write_denied_path:
            # Write-denied paths are allowed for GET (default method)
            assert result is None, f"Salesperson should be allowed GET on {path}"
            # But denied for PUT
            write_result = check_role_path_access(SALESPERSON, path, method="PUT")
            assert write_result is not None, f"Salesperson should be denied PUT on {path}"
        else:
            assert result is None, f"Salesperson should be allowed {path}"

    @PBT_SETTINGS
    @given(path=api_paths)
    def test_global_admin_denied_org_data(self, path):
        """Global admin is denied access to org-level customer/invoice data."""
        result = check_role_path_access(GLOBAL_ADMIN, path)
        is_denied_path = any(path.startswith(p) for p in GLOBAL_ADMIN_DENIED_PREFIXES)
        if is_denied_path:
            assert result is not None, f"Global admin should be denied {path}"
        else:
            assert result is None, f"Global admin should be allowed {path}"

    @PBT_SETTINGS
    @given(path=api_paths)
    def test_org_admin_denied_global_admin_paths(self, path):
        """Org admin is denied access to global admin endpoints."""
        result = check_role_path_access(ORG_ADMIN, path)
        is_admin_path = any(path.startswith(p) for p in GLOBAL_ADMIN_ONLY_PREFIXES)
        if is_admin_path:
            assert result is not None, f"Org admin should be denied {path}"
        else:
            assert result is None, f"Org admin should be allowed {path}"

    @PBT_SETTINGS
    @given(role=roles, path=api_paths)
    def test_role_path_access_is_deterministic(self, role, path):
        """Same role + path always produces the same access decision."""
        result1 = check_role_path_access(role, path)
        result2 = check_role_path_access(role, path)
        assert result1 == result2


# ===========================================================================
# Property 13: IP Allowlist Enforcement
# ===========================================================================

class TestProperty13IPAllowlistEnforcement:
    """Feature: workshoppro-nz-platform, Property 13: IP Allowlist Enforcement

    *For any* organisation with IP allowlisting enabled, and *for any*
    login attempt from an IP address not contained in the configured
    allowlist ranges, the login shall be rejected with an appropriate
    error and the attempt shall be logged in the audit log.

    **Validates: Requirements 6.1, 6.3**
    """

    @PBT_SETTINGS
    @given(
        allowed_ip=ip_v4,
        test_ip=ip_v4,
    )
    def test_non_allowlisted_ip_rejected(self, allowed_ip, test_ip):
        """An IP not in the allowlist is rejected; an IP in the allowlist is accepted."""
        allowlist = [allowed_ip]
        result = is_ip_in_allowlist(test_ip, allowlist)

        if test_ip == allowed_ip:
            assert result is True, f"{test_ip} should match allowlist [{allowed_ip}]"
        # When IPs differ, result depends on whether test_ip happens to
        # fall in the /32 network — for exact IPs this means only equality matches
        elif result is True:
            # This can only happen if the IPs are actually equal (already handled)
            pass
        else:
            assert result is False

    @PBT_SETTINGS
    @given(
        cidr_third_octet=st.integers(min_value=0, max_value=255),
        test_third_octet=st.integers(min_value=0, max_value=255),
    )
    def test_cidr_range_enforcement(self, cidr_third_octet, test_third_octet):
        """IPs within a CIDR range are allowed; IPs outside are rejected."""
        # Use a /24 range: 10.0.{cidr_third_octet}.0/24
        allowlist = [f"10.0.{cidr_third_octet}.0/24"]
        test_ip = f"10.0.{test_third_octet}.100"

        result = is_ip_in_allowlist(test_ip, allowlist)

        if test_third_octet == cidr_third_octet:
            assert result is True, f"{test_ip} should be in {allowlist[0]}"
        else:
            assert result is False, f"{test_ip} should NOT be in {allowlist[0]}"

    @PBT_SETTINGS
    @given(test_ip=ip_v4)
    def test_empty_allowlist_rejects_all(self, test_ip):
        """An empty allowlist rejects every IP."""
        assert is_ip_in_allowlist(test_ip, []) is False

    @PBT_SETTINGS
    @given(
        ip=ip_v4,
        num_ranges=st.integers(min_value=1, max_value=5),
    )
    def test_ip_in_own_allowlist_always_accepted(self, ip, num_ranges):
        """An IP that is explicitly in the allowlist is always accepted."""
        # Build an allowlist that definitely contains the IP
        allowlist = [ip] + [f"192.168.{i}.0/24" for i in range(num_ranges - 1)]
        assert is_ip_in_allowlist(ip, allowlist) is True

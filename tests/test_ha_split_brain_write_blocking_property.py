"""Property-based tests for split-brain write blocking consistency.

Tests Property 4 from the HA design document: split-brain write blocking
ensures that read-only methods and exempt paths are never blocked, while
write requests to non-exempt paths are blocked when the split-brain flag
is active.

**Validates: Requirements 8.1, 8.3, 8.4**
"""

from __future__ import annotations

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.ha.utils import should_block_request

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# HTTP methods — read-only methods that should always pass through.
_READ_METHODS = ["GET", "HEAD", "OPTIONS"]
# Write methods that should be blocked when split-brain blocking is active.
_WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]
# All methods combined.
_ALL_METHODS = _READ_METHODS + _WRITE_METHODS
# All node roles.
_ALL_ROLES = ["standalone", "primary", "standby"]

# Strategy for non-exempt paths (not HA, not auth).
_non_exempt_path_strategy = st.text(min_size=1, max_size=80).map(
    lambda s: "/api/v1/invoices/" + s
)

# Strategy for HA paths (always exempt).
_ha_path_strategy = st.text(min_size=0, max_size=50).map(
    lambda s: "/api/v1/ha/" + s
)

# Strategy for auth paths (always exempt).
_auth_path_strategy = st.sampled_from([
    "/api/v1/auth/login",
    "/api/v1/auth/token/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/passkey/login",
    "/api/v2/auth/login",
    "/api/v2/auth/token/refresh",
    "/api/v2/auth/logout",
])


# ============================================================================
# Property 4 — Split-brain write blocking consistency
# ============================================================================


class TestSplitBrainWriteBlockingConsistency:
    """Property: split-brain write blocking follows the same exemption rules
    as standby mode, but is triggered by the split-brain flag instead of role.

    - GET, HEAD, OPTIONS requests are NEVER blocked regardless of split-brain state
    - Paths starting with ``/api/v1/ha/`` are NEVER blocked regardless of method or state
    - Auth paths are NEVER blocked regardless of method or state
    - Write requests (POST, PUT, DELETE, PATCH) to non-exempt paths ARE blocked
      when split-brain blocking is active

    **Validates: Requirements 8.1, 8.3, 8.4**
    """

    # ------------------------------------------------------------------
    # Read-only methods are NEVER blocked
    # ------------------------------------------------------------------

    @given(
        method=st.sampled_from(_READ_METHODS),
        path=st.text(min_size=1, max_size=100).map(lambda s: "/" + s.lstrip("/")),
        role=st.sampled_from(_ALL_ROLES),
        is_split_brain_blocked=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_read_methods_never_blocked_regardless_of_split_brain(
        self, method: str, path: str, role: str, is_split_brain_blocked: bool
    ) -> None:
        assert should_block_request(method, path, role, is_split_brain_blocked) is False

    # ------------------------------------------------------------------
    # HA paths are NEVER blocked
    # ------------------------------------------------------------------

    @given(
        method=st.sampled_from(_ALL_METHODS),
        path=_ha_path_strategy,
        role=st.sampled_from(_ALL_ROLES),
        is_split_brain_blocked=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_ha_paths_never_blocked_regardless_of_split_brain(
        self, method: str, path: str, role: str, is_split_brain_blocked: bool
    ) -> None:
        assert should_block_request(method, path, role, is_split_brain_blocked) is False

    # ------------------------------------------------------------------
    # Auth paths are NEVER blocked
    # ------------------------------------------------------------------

    @given(
        method=st.sampled_from(_ALL_METHODS),
        path=_auth_path_strategy,
        role=st.sampled_from(_ALL_ROLES),
        is_split_brain_blocked=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_auth_paths_never_blocked_regardless_of_split_brain(
        self, method: str, path: str, role: str, is_split_brain_blocked: bool
    ) -> None:
        assert should_block_request(method, path, role, is_split_brain_blocked) is False

    # ------------------------------------------------------------------
    # Writes to non-exempt paths ARE blocked when split-brain is active
    # ------------------------------------------------------------------

    @given(
        method=st.sampled_from(_WRITE_METHODS),
        path=_non_exempt_path_strategy,
    )
    @h_settings(PBT_SETTINGS)
    def test_writes_blocked_when_split_brain_active(
        self, method: str, path: str
    ) -> None:
        """Non-standby role + split-brain blocked → writes are blocked."""
        assert should_block_request(method, path, "primary", is_split_brain_blocked=True) is True

    @given(
        method=st.sampled_from(_WRITE_METHODS),
        path=_non_exempt_path_strategy,
    )
    @h_settings(PBT_SETTINGS)
    def test_writes_not_blocked_when_split_brain_inactive_and_not_standby(
        self, method: str, path: str
    ) -> None:
        """Non-standby role + no split-brain → writes are allowed."""
        assert should_block_request(method, path, "primary", is_split_brain_blocked=False) is False

    # ------------------------------------------------------------------
    # Comprehensive property: blocked ⟺ (standby OR split-brain) AND write AND non-exempt
    # ------------------------------------------------------------------

    @given(
        method=st.sampled_from(_ALL_METHODS),
        path=_non_exempt_path_strategy,
        role=st.sampled_from(_ALL_ROLES),
        is_split_brain_blocked=st.booleans(),
    )
    @h_settings(PBT_SETTINGS)
    def test_comprehensive_blocking_decision(
        self, method: str, path: str, role: str, is_split_brain_blocked: bool
    ) -> None:
        """Blocked ⟺ (standby OR split-brain-blocked) AND write method AND non-exempt path.

        For non-exempt paths, the blocking decision is:
        - blocked if role is standby OR split-brain is active
        - AND the method is a write method
        """
        is_write = method not in {"GET", "HEAD", "OPTIONS"}
        should_be_blocked_by_role = role == "standby"
        should_be_blocked = (should_be_blocked_by_role or is_split_brain_blocked) and is_write

        result = should_block_request(method, path, role, is_split_brain_blocked)
        assert result is should_be_blocked

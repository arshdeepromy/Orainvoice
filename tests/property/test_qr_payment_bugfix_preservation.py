"""Preservation property tests: Kiosk RBAC Restrictions & Non-Kiosk Access Unchanged.

**Validates: Requirements 2.5, 3.1, 3.2, 3.5**

Property 2: Preservation — Kiosk RBAC Restrictions & Non-Kiosk Access Unchanged

These tests are written BEFORE implementing the fix and run on UNFIXED code.
They MUST PASS on unfixed code because they capture current correct behavior
that must remain unchanged after the fix is applied.

Observations on unfixed code:
- check_role_path_access("kiosk", "/api/v1/invoices/123", "GET")
    → "Kiosk role can only access check-in and branding endpoints"
- check_role_path_access("kiosk", "/api/v1/payments/qr-session/cs_123/expire", "POST")
    → "Kiosk role can only access check-in and branding endpoints"
- check_role_path_access("org_admin", "/api/v1/payments/qr-session/pending", "GET")
    → None
- check_role_path_access("salesperson", "/api/v1/payments/qr-session/cs_123/status", "GET")
    → None
- check_role_path_access("kiosk", "/api/v1/kiosk/checkin", "GET")
    → None
"""

from __future__ import annotations

from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.auth.rbac import (
    check_role_path_access,
    KIOSK_ALLOWED_PREFIXES,
    _matches_any_prefix,
)


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating random path segments (alphanumeric + hyphens)
path_segment = st.from_regex(r"[a-z0-9\-]{1,20}", fullmatch=True)

# Strategy for generating paths that are NOT in KIOSK_ALLOWED_PREFIXES
# and NOT starting with /api/v1/payments/qr-session
non_allowlisted_path_strategy = st.builds(
    lambda segments: "/api/v1/" + "/".join(segments),
    st.lists(path_segment, min_size=1, max_size=4),
).filter(
    lambda p: (
        not _matches_any_prefix(p, KIOSK_ALLOWED_PREFIXES)
        and not p.startswith("/api/v1/payments/qr-session")
    )
)

# Strategy for non-kiosk roles that should have unrestricted QR session access
non_kiosk_role_strategy = st.sampled_from(["org_admin", "salesperson"])

# Strategy for QR session sub-paths
session_id_strategy = st.from_regex(r"cs_[a-zA-Z0-9]{6,24}", fullmatch=True)

qr_session_path_strategy = st.one_of(
    st.just("/api/v1/payments/qr-session/pending"),
    st.builds(
        lambda sid: f"/api/v1/payments/qr-session/{sid}/status",
        session_id_strategy,
    ),
    st.builds(
        lambda sid: f"/api/v1/payments/qr-session/{sid}/expire",
        session_id_strategy,
    ),
)

# Strategy for HTTP methods that are NOT GET
non_get_method_strategy = st.sampled_from(["POST", "PUT", "DELETE", "PATCH"])

# Strategy for QR session paths (broader, for non-GET tests)
qr_session_any_path_strategy = st.one_of(
    st.just("/api/v1/payments/qr-session/pending"),
    st.builds(
        lambda sid: f"/api/v1/payments/qr-session/{sid}/status",
        session_id_strategy,
    ),
    st.builds(
        lambda sid: f"/api/v1/payments/qr-session/{sid}/expire",
        session_id_strategy,
    ),
    st.builds(
        lambda seg: f"/api/v1/payments/qr-session/{seg}",
        path_segment,
    ),
)

# Strategy for existing kiosk allowlisted paths (that should return None)
kiosk_allowlisted_path_strategy = st.one_of(
    st.just("/api/v1/kiosk/checkin"),
    st.just("/api/v1/kiosk/vehicle"),
    st.just("/api/v1/kiosk/status"),
    st.builds(
        lambda seg: f"/api/v1/kiosk/{seg}",
        path_segment,
    ),
)


# ---------------------------------------------------------------------------
# Preservation Property Tests
# ---------------------------------------------------------------------------


class TestPreservationKioskNonAllowlisted:
    """Preservation: Kiosk requests to non-allowlisted paths are denied.

    For all kiosk requests to paths NOT in KIOSK_ALLOWED_PREFIXES and NOT
    starting with /api/v1/payments/qr-session, the result must be a denial
    string (non-None).

    This behavior must be preserved after the fix.

    **Validates: Requirements 3.1, 3.5**
    """

    @given(path=non_allowlisted_path_strategy)
    @PBT_SETTINGS
    def test_kiosk_denied_non_allowlisted_paths(self, path: str) -> None:
        """Kiosk accessing paths outside the allowlist returns a denial.

        **Validates: Requirements 3.1**
        """
        result = check_role_path_access("kiosk", path, "GET")
        assert result is not None, (
            f"Expected denial for kiosk accessing non-allowlisted path '{path}', "
            f"but got None (access allowed)"
        )
        assert isinstance(result, str), (
            f"Expected denial string for kiosk at '{path}', got {type(result)}"
        )


class TestPreservationNonKioskQrAccess:
    """Preservation: Non-kiosk roles accessing QR session endpoints get None.

    For all non-kiosk roles (org_admin, salesperson) accessing QR session
    endpoints, the result is None (no denial) — these roles have unrestricted
    access to payment endpoints.

    This behavior must be preserved after the fix.

    **Validates: Requirements 3.2**
    """

    @given(role=non_kiosk_role_strategy, path=qr_session_path_strategy)
    @PBT_SETTINGS
    def test_non_kiosk_roles_access_qr_session_freely(
        self, role: str, path: str
    ) -> None:
        """org_admin and salesperson can access all QR session endpoints.

        **Validates: Requirements 3.2**
        """
        result = check_role_path_access(role, path, "GET")
        assert result is None, (
            f"Expected None (access allowed) for {role} GET '{path}', "
            f"but got denial: '{result}'"
        )

    @given(
        role=non_kiosk_role_strategy,
        path=qr_session_path_strategy,
        method=st.sampled_from(["GET", "POST", "PUT", "DELETE"]),
    )
    @PBT_SETTINGS
    def test_non_kiosk_roles_any_method_qr_session(
        self, role: str, path: str, method: str
    ) -> None:
        """org_admin and salesperson can use any HTTP method on QR session endpoints.

        **Validates: Requirements 3.2**
        """
        result = check_role_path_access(role, path, method)
        assert result is None, (
            f"Expected None for {role} {method} '{path}', "
            f"but got denial: '{result}'"
        )


class TestPreservationKioskNonGetQrSession:
    """Preservation: Kiosk non-GET requests to QR session paths are denied.

    On unfixed code, kiosk is denied ALL QR session paths because the prefix
    isn't in the allowlist at all. After the fix, kiosk POST/PUT/DELETE to
    QR session paths should STILL be denied (but for a different reason —
    the method restriction). The preservation test asserts the result is a
    non-None denial string (not checking the exact message).

    **Validates: Requirements 2.5, 3.1**
    """

    @given(path=qr_session_any_path_strategy, method=non_get_method_strategy)
    @PBT_SETTINGS
    def test_kiosk_non_get_qr_session_denied(
        self, path: str, method: str
    ) -> None:
        """Kiosk non-GET requests to /api/v1/payments/qr-session/* are denied.

        On unfixed code: denied because path not in allowlist.
        After fix: denied because kiosk has read-only access to QR sessions.
        Either way, the result must be a non-None denial string.

        **Validates: Requirements 2.5, 3.1**
        """
        result = check_role_path_access("kiosk", path, method)
        assert result is not None, (
            f"Expected denial for kiosk {method} '{path}', "
            f"but got None (access allowed). Kiosk should never have "
            f"write access to QR session endpoints."
        )
        assert isinstance(result, str), (
            f"Expected denial string for kiosk {method} at '{path}', "
            f"got {type(result)}"
        )


class TestPreservationKioskExistingAllowlist:
    """Preservation: Kiosk accessing existing allowlisted paths returns None.

    Kiosk can access paths in KIOSK_ALLOWED_PREFIXES (with appropriate
    method restrictions). This verifies the existing allowlist still works.

    **Validates: Requirements 3.5**
    """

    @given(path=kiosk_allowlisted_path_strategy)
    @PBT_SETTINGS
    def test_kiosk_allowed_paths_return_none(self, path: str) -> None:
        """Kiosk accessing /api/v1/kiosk/* paths returns None (allowed).

        **Validates: Requirements 3.5**
        """
        result = check_role_path_access("kiosk", path, "GET")
        assert result is None, (
            f"Expected None (access allowed) for kiosk GET '{path}', "
            f"but got denial: '{result}'"
        )

"""Bug condition exploration test: Kiosk QR Session RBAC Denial & Missing Endpoint.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.4**

Property 1: Bug Condition — Kiosk QR Session RBAC Denial & Missing Endpoint

This test is written BEFORE implementing the fix and run on UNFIXED code.
The test is EXPECTED TO FAIL, which confirms the bugs exist.

Bug 3: check_role_path_access("kiosk", "/api/v1/payments/qr-session/...", "GET")
returns a denial string instead of None because the path is not in
KIOSK_ALLOWED_PREFIXES.

Bug 4: POST /api/v1/payments/qr-session/existing route does not exist (404).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.auth.rbac import check_role_path_access


PBT_SETTINGS = h_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Strategy for generating valid Stripe Checkout Session IDs
session_id_strategy = st.from_regex(r"cs_[a-zA-Z0-9]{6,24}", fullmatch=True)

# Strategy for QR session GET sub-paths that kiosk should be able to access
qr_session_get_paths = st.one_of(
    st.just("/api/v1/payments/qr-session/pending"),
    st.builds(
        lambda sid: f"/api/v1/payments/qr-session/{sid}/status",
        session_id_strategy,
    ),
)


class TestBugConditionExploration:
    """Bug condition exploration: Kiosk QR Session RBAC + Missing Endpoint.

    These tests confirm the bugs exist on UNFIXED code by asserting the
    EXPECTED (correct) behavior. When they FAIL, it proves the bugs are real.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.4**
    """

    @given(path=qr_session_get_paths)
    @PBT_SETTINGS
    def test_kiosk_get_qr_session_should_be_allowed(self, path: str) -> None:
        """Bug 3: Kiosk GET requests to /api/v1/payments/qr-session/* should
        return None (no denial) from check_role_path_access.

        On UNFIXED code, this FAILS because the path is not in
        KIOSK_ALLOWED_PREFIXES, so the function returns:
        "Kiosk role can only access check-in and branding endpoints"

        **Validates: Requirements 1.1, 1.2, 2.1, 2.2**
        """
        result = check_role_path_access("kiosk", path, "GET")
        # Expected behavior: None (access allowed)
        # Bug behavior: returns denial string
        assert result is None, (
            f"Bug 3 confirmed: check_role_path_access('kiosk', '{path}', 'GET') "
            f"returned denial: '{result}' instead of None"
        )

    def test_kiosk_get_pending_should_be_allowed(self) -> None:
        """Bug 3 concrete example: Kiosk polling /qr-session/pending is denied.

        **Validates: Requirements 1.1, 2.1**
        """
        result = check_role_path_access(
            "kiosk", "/api/v1/payments/qr-session/pending", "GET"
        )
        assert result is None, (
            f"Bug 3 confirmed: kiosk GET /qr-session/pending denied with: '{result}'"
        )

    def test_kiosk_get_session_status_should_be_allowed(self) -> None:
        """Bug 3 concrete example: Kiosk polling /qr-session/{id}/status is denied.

        **Validates: Requirements 1.2, 2.2**
        """
        result = check_role_path_access(
            "kiosk", "/api/v1/payments/qr-session/cs_abc123/status", "GET"
        )
        assert result is None, (
            f"Bug 3 confirmed: kiosk GET /qr-session/cs_abc123/status denied with: '{result}'"
        )

    def test_existing_invoice_qr_endpoint_exists(self) -> None:
        """Bug 4: POST /api/v1/payments/qr-session/existing route should exist.

        On UNFIXED code, this FAILS because the route has not been created yet.
        We verify by inspecting the router source file for the route definition.

        **Validates: Requirements 1.3, 1.4, 2.4**
        """
        import ast
        import pathlib

        router_path = pathlib.Path("app/modules/payments/router.py")
        assert router_path.exists(), "payments router.py not found"

        source = router_path.read_text()

        # Check that the route decorator for /qr-session/existing exists
        # Look for the string "/qr-session/existing" in the source
        has_existing_route = "/qr-session/existing" in source

        # Also verify it's a POST route by checking for @router.post with that path
        tree = ast.parse(source)
        found_post_existing = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for router.post("/qr-session/existing", ...)
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "post"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "/qr-session/existing"
                ):
                    found_post_existing = True
                    break

        assert found_post_existing, (
            "Bug 4 confirmed: POST /qr-session/existing route does not exist in "
            "app/modules/payments/router.py. The endpoint has not been implemented yet."
        )

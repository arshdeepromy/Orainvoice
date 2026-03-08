"""Bug condition exploration tests for platform audit defects.

These tests encode the EXPECTED (correct) behavior. They are designed to
FAIL on the current unfixed code, proving the bugs exist. After fixes are
applied, these same tests should PASS.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**

Property 1: Fault Condition — Platform Audit Defects (Security, Architecture)
"""

from __future__ import annotations

import ast
import inspect
import re
import ssl
import textwrap

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# PBT settings — scoped to concrete failing cases for deterministic bugs
# ---------------------------------------------------------------------------

EXPLORATION_SETTINGS = h_settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ===================================================================
# SECURITY EXPLORATION TESTS
# ===================================================================


class TestRLSSQLInjectionExploration:
    """Req 1.1 — _set_rls_org_id uses f-string interpolation instead of
    parameterized query. Assert the SQL uses set_config() with bind params.

    **Validates: Requirements 1.1**
    """

    @given(org_id=st.uuids().map(str))
    @EXPLORATION_SETTINGS
    def test_rls_setter_uses_parameterized_query(self, org_id: str):
        """For any valid UUID, the RLS setter must use set_config() with
        bind parameters, not string interpolation."""
        import pathlib

        source = pathlib.Path("app/core/database.py").read_text()

        # Extract the _set_rls_org_id function body
        func_match = re.search(
            r"async def _set_rls_org_id\(.*?\n((?:[ \t]+.*\n)*)", source
        )
        assert func_match, "_set_rls_org_id function not found in database.py"
        func_source = func_match.group(0)

        # The fixed code should use set_config with a bind parameter
        assert "set_config(" in func_source, (
            "RLS setter should use set_config() function for parameterized queries"
        )
        # The fixed code should NOT use f-string interpolation for SQL
        assert 'f"SET LOCAL' not in func_source and "f'SET LOCAL" not in func_source, (
            f"RLS setter must not use f-string interpolation for SQL. "
            f"Found string interpolation in source for org_id={org_id}"
        )


class TestHardcodedSecretsExploration:
    """Req 1.2 — Settings allows startup with default secrets in production.
    Assert startup raises ValueError.

    **Validates: Requirements 1.2**
    """

    @given(
        env=st.sampled_from(["production", "staging"]),
    )
    @EXPLORATION_SETTINGS
    def test_settings_rejects_default_secrets_in_production(self, env: str):
        """Settings must raise ValueError when jwt_secret or encryption_master_key
        is the default placeholder in production/staging environments."""
        import pathlib

        source = pathlib.Path("app/config.py").read_text()

        # The fixed code should have a validator that checks for default secrets
        has_validator = (
            "model_validator" in source
            or "@validator" in source
            or "field_validator" in source
            or "change-me-in-production" in source.split("class Settings")[1]
            and ("ValueError" in source or "raise" in source)
        )

        # Check that there's a validation that raises on default secrets
        has_secret_check = (
            ("change-me-in-production" in source)
            and ("raise" in source or "ValueError" in source)
            and ("production" in source or "staging" in source)
        )

        # The source must contain a validator that rejects defaults in prod
        assert has_secret_check, (
            f"Settings class must validate that jwt_secret and encryption_master_key "
            f"are not 'change-me-in-production' in {env} environment. "
            f"No such validation found in app/config.py."
        )


class TestRefreshTokenStorageExploration:
    """Req 1.3 — client.ts stores refresh token in localStorage.
    Assert refresh token is NOT in localStorage.

    **Validates: Requirements 1.3**
    """

    def test_client_does_not_use_localstorage_for_refresh_token(self):
        """The API client must not store refresh tokens in localStorage."""
        import pathlib

        client_path = pathlib.Path("frontend/src/api/client.ts")
        assert client_path.exists(), "client.ts not found"
        source = client_path.read_text()

        # Check for localStorage usage with refresh_token
        has_localstorage_refresh = (
            "localStorage.getItem('refresh_token')" in source
            or 'localStorage.getItem("refresh_token")' in source
            or "localStorage.setItem('refresh_token'" in source
            or 'localStorage.setItem("refresh_token"' in source
        )
        assert not has_localstorage_refresh, (
            "client.ts must not store refresh tokens in localStorage — "
            "use httpOnly cookies instead"
        )


class TestSSLVerificationExploration:
    """Req 1.4 — DatabaseSSLConfig has check_hostname=False and
    verify_mode=CERT_NONE. Assert check_hostname=True and CERT_REQUIRED.

    **Validates: Requirements 1.4**
    """

    def test_ssl_config_enables_hostname_checking(self):
        """DatabaseSSLConfig must have check_hostname=True."""
        import pathlib

        source = pathlib.Path("app/core/security.py").read_text()

        # Extract the to_connect_args method
        method_match = re.search(
            r"def to_connect_args\(self\).*?\n((?:(?:[ \t]+.*|)\n)*)", source
        )
        assert method_match, "to_connect_args method not found"
        method_source = method_match.group(0)

        # The fixed code should set check_hostname = True
        assert "check_hostname = True" in method_source or "check_hostname=True" in method_source, (
            "SSL config must set check_hostname = True in to_connect_args"
        )
        assert "check_hostname = False" not in method_source, (
            "SSL config must not have check_hostname = False"
        )

    def test_ssl_config_requires_certificates(self):
        """DatabaseSSLConfig must have verify_mode=CERT_REQUIRED."""
        import pathlib

        source = pathlib.Path("app/core/security.py").read_text()

        # Extract the to_connect_args method
        method_match = re.search(
            r"def to_connect_args\(self\).*?\n((?:(?:[ \t]+.*|)\n)*)", source
        )
        assert method_match, "to_connect_args method not found"
        method_source = method_match.group(0)

        # The fixed code should set verify_mode = ssl.CERT_REQUIRED
        assert "CERT_REQUIRED" in method_source, (
            "SSL config must set verify_mode = ssl.CERT_REQUIRED"
        )
        assert "CERT_NONE" not in method_source, (
            "SSL config must not have verify_mode = ssl.CERT_NONE"
        )


# ===================================================================
# ARCHITECTURE EXPLORATION TESTS
# ===================================================================


class TestRouterDuplicationExploration:
    """Req 1.5 — app/main.py has duplicate router registrations.
    Assert no duplicate include_router calls for the same router.

    **Validates: Requirements 1.5**
    """

    def test_no_duplicate_router_registrations(self):
        """main.py must not register the same router object at multiple prefixes
        via duplicate include_router calls."""
        import pathlib

        main_path = pathlib.Path("app/main.py")
        assert main_path.exists(), "app/main.py not found"
        source = main_path.read_text()

        # Extract all include_router calls with their router variable names
        pattern = r"app\.include_router\(\s*(\w+)"
        matches = re.findall(pattern, source)

        # Find duplicates
        seen = {}
        duplicates = []
        for router_name in matches:
            if router_name in seen:
                duplicates.append(router_name)
            else:
                seen[router_name] = True

        assert len(duplicates) == 0, (
            f"Found duplicate include_router calls for: {set(duplicates)}. "
            f"Each router should be registered only once."
        )


class TestBlanketExceptionExploration:
    """Req 1.6 — Service-layer files use `except Exception:`.
    Assert specific exception types are caught.

    **Validates: Requirements 1.6**
    """

    def test_service_files_use_specific_exceptions(self):
        """Service-layer files must not use bare `except Exception:` patterns."""
        import pathlib

        service_files = list(pathlib.Path("app/modules").rglob("service*.py"))
        assert len(service_files) > 0, "No service files found"

        violations = []
        # Pattern matches `except Exception:` or `except Exception as ...:`
        pattern = re.compile(r"except\s+Exception\s*(as\s+\w+\s*)?:")

        for fpath in service_files:
            source = fpath.read_text()
            matches = pattern.findall(source)
            if matches:
                count = len(pattern.findall(source))
                violations.append(f"{fpath}: {count} blanket except(s)")

        assert len(violations) == 0, (
            f"Found blanket 'except Exception:' in service files:\n"
            + "\n".join(violations)
        )


class TestRateLimiterFailClosedExploration:
    """Req 1.7 — Rate limiter allows requests when Redis is unavailable.
    Assert requests are denied or throttled.

    **Validates: Requirements 1.7**
    """

    def test_rate_limiter_source_does_not_fail_open(self):
        """Rate limiter must not allow unlimited requests when Redis is down.
        The dispatch method should return 503 or apply a fallback limit,
        not just call_next when redis is None."""
        import pathlib

        rate_limit_path = pathlib.Path("app/middleware/rate_limit.py")
        assert rate_limit_path.exists(), "rate_limit.py not found"
        source = rate_limit_path.read_text()

        # The fail-open pattern: when redis is None, just call_next
        has_fail_open = (
            "if redis is None:" in source
            and "return await call_next(request)" in source
        )

        # Check for fail-open comment
        has_fail_open_comment = "fail-open" in source.lower() or "Fail-open" in source

        assert not has_fail_open, (
            "Rate limiter must not fail-open when Redis is unavailable. "
            "Should return 503 or apply a conservative fallback limit."
        )
        assert not has_fail_open_comment, (
            "Rate limiter contains fail-open comment — must be changed to fail-closed."
        )

"""Tests for Task 38.1 — Data encryption at rest and security hardening.

Verifies:
  - Security headers are present on all responses (Requirement 52.3)
  - TLS configuration enforces TLS 1.3 minimum (Requirement 52.2)
  - Database SSL mode is enforced in production (Requirement 52.1)
  - Security headers verification utility works correctly
"""

from __future__ import annotations

import ssl
from unittest.mock import patch

import pytest

from app.core.security import (
    REQUIRED_SECURITY_HEADERS,
    DatabaseSSLConfig,
    HeaderVerificationResult,
    create_tls_context,
    get_database_ssl_config,
    get_tls_min_version,
    verify_security_headers,
)


# ---------------------------------------------------------------------------
# TLS configuration tests (Requirement 52.2)
# ---------------------------------------------------------------------------

class TestTLSConfiguration:
    """Verify TLS 1.3 enforcement."""

    def test_tls_min_version_is_1_3(self):
        assert get_tls_min_version() == "TLSv1.3"

    def test_create_tls_context_enforces_tls_1_3(self):
        ctx = create_tls_context(purpose=ssl.Purpose.SERVER_AUTH)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_create_tls_context_disables_old_protocols(self):
        ctx = create_tls_context(purpose=ssl.Purpose.SERVER_AUTH)
        # TLS 1.3 minimum means older protocols are implicitly disabled
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3
        assert ctx.maximum_version == ssl.TLSVersion.MAXIMUM_SUPPORTED


# ---------------------------------------------------------------------------
# Database SSL configuration tests (Requirement 52.1)
# ---------------------------------------------------------------------------

class TestDatabaseSSLConfig:
    """Verify PostgreSQL SSL connection enforcement."""

    def test_production_requires_ssl(self):
        config = get_database_ssl_config("production")
        assert config.ssl_mode == "require"
        assert config.ssl_min_protocol_version == "TLSv1.3"

    def test_staging_requires_ssl(self):
        config = get_database_ssl_config("staging")
        assert config.ssl_mode == "require"
        assert config.ssl_min_protocol_version == "TLSv1.3"

    def test_development_prefers_ssl(self):
        config = get_database_ssl_config("development")
        assert config.ssl_mode == "prefer"
        assert config.ssl_min_protocol_version == "TLSv1.3"

    def test_to_connect_args_returns_ssl_context(self):
        config = DatabaseSSLConfig()
        args = config.to_connect_args()
        assert "ssl" in args
        ctx = args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_to_engine_kwargs_wraps_connect_args(self):
        config = DatabaseSSLConfig()
        kwargs = config.to_engine_kwargs()
        assert "connect_args" in kwargs
        assert "ssl" in kwargs["connect_args"]


# ---------------------------------------------------------------------------
# Security headers verification tests (Requirement 52.3)
# ---------------------------------------------------------------------------

class TestSecurityHeadersVerification:
    """Verify the security headers verification utility."""

    def test_all_required_headers_defined(self):
        """Ensure all Req 52.3 headers are in the required set."""
        required_names = {h.lower() for h in REQUIRED_SECURITY_HEADERS}
        assert "content-security-policy" in required_names
        assert "x-frame-options" in required_names
        assert "x-content-type-options" in required_names
        assert "strict-transport-security" in required_names
        assert "referrer-policy" in required_names

    def test_compliant_headers_pass(self):
        result = verify_security_headers(dict(REQUIRED_SECURITY_HEADERS))
        assert result.is_compliant is True
        assert result.missing_headers == []
        assert result.incorrect_headers == {}

    def test_missing_header_detected(self):
        headers = dict(REQUIRED_SECURITY_HEADERS)
        del headers["X-Frame-Options"]
        result = verify_security_headers(headers)
        assert result.is_compliant is False
        assert "X-Frame-Options" in result.missing_headers

    def test_incorrect_header_value_detected(self):
        headers = dict(REQUIRED_SECURITY_HEADERS)
        headers["X-Frame-Options"] = "SAMEORIGIN"
        result = verify_security_headers(headers)
        assert result.is_compliant is False
        assert "X-Frame-Options" in result.incorrect_headers
        assert result.incorrect_headers["X-Frame-Options"]["expected"] == "DENY"
        assert result.incorrect_headers["X-Frame-Options"]["actual"] == "SAMEORIGIN"

    def test_case_insensitive_header_matching(self):
        headers = {k.lower(): v for k, v in REQUIRED_SECURITY_HEADERS.items()}
        result = verify_security_headers(headers)
        assert result.is_compliant is True

    def test_empty_headers_all_missing(self):
        result = verify_security_headers({})
        assert result.is_compliant is False
        assert len(result.missing_headers) == len(REQUIRED_SECURITY_HEADERS)

    def test_multiple_missing_headers(self):
        headers = dict(REQUIRED_SECURITY_HEADERS)
        del headers["X-Frame-Options"]
        del headers["X-Content-Type-Options"]
        result = verify_security_headers(headers)
        assert result.is_compliant is False
        assert "X-Frame-Options" in result.missing_headers
        assert "X-Content-Type-Options" in result.missing_headers


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware integration test (Requirement 52.3)
# ---------------------------------------------------------------------------

class TestSecurityHeadersMiddleware:
    """Verify the middleware applies all required headers to responses."""

    @pytest.fixture
    def app(self):
        """Create a minimal FastAPI app with the security headers middleware."""
        from fastapi import FastAPI
        from app.middleware.security_headers import SecurityHeadersMiddleware

        test_app = FastAPI()
        test_app.add_middleware(SecurityHeadersMiddleware)

        @test_app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}

        @test_app.post("/test-post")
        async def test_post_endpoint():
            return {"status": "created"}

        return test_app

    @pytest.fixture
    def client(self, app):
        from starlette.testclient import TestClient
        return TestClient(app)

    def test_get_response_has_all_required_headers(self, client):
        response = client.get("/test")
        assert response.status_code == 200
        for header_name in REQUIRED_SECURITY_HEADERS:
            assert header_name.lower() in {
                k.lower() for k in response.headers.keys()
            }, f"Missing header: {header_name}"

    def test_get_response_header_values_correct(self, client):
        response = client.get("/test")
        for header_name, expected_value in REQUIRED_SECURITY_HEADERS.items():
            actual = response.headers.get(header_name)
            assert actual == expected_value, (
                f"Header {header_name}: expected {expected_value!r}, got {actual!r}"
            )

    def test_csp_header_present(self, client):
        response = client.get("/test")
        csp = response.headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp

    def test_hsts_header_present(self, client):
        response = client.get("/test")
        hsts = response.headers.get("strict-transport-security")
        assert hsts is not None
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts

    def test_x_frame_options_deny(self, client):
        response = client.get("/test")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options_nosniff(self, client):
        response = client.get("/test")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_referrer_policy_present(self, client):
        response = client.get("/test")
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_additional_hardening_headers(self, client):
        """X-XSS-Protection and Permissions-Policy are bonus hardening."""
        response = client.get("/test")
        assert response.headers.get("x-xss-protection") == "1; mode=block"
        assert "camera=()" in response.headers.get("permissions-policy", "")

    def test_headers_on_post_with_bearer(self, client):
        """Security headers should be present on POST responses too."""
        response = client.post(
            "/test-post",
            headers={"Authorization": "Bearer fake-token"},
        )
        for header_name in REQUIRED_SECURITY_HEADERS:
            assert header_name.lower() in {
                k.lower() for k in response.headers.keys()
            }, f"Missing header on POST: {header_name}"


# ---------------------------------------------------------------------------
# Database engine SSL integration test
# ---------------------------------------------------------------------------

class TestDatabaseEngineSSL:
    """Verify database.py applies SSL config in production."""

    def test_production_engine_has_ssl_connect_args(self):
        """In production, the engine should include SSL connect_args."""
        config = get_database_ssl_config("production")
        kwargs = config.to_engine_kwargs()
        ssl_ctx = kwargs["connect_args"]["ssl"]
        assert isinstance(ssl_ctx, ssl.SSLContext)
        assert ssl_ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_development_engine_ssl_still_configured(self):
        """Even in dev, SSL config should specify TLS 1.3 minimum."""
        config = get_database_ssl_config("development")
        kwargs = config.to_engine_kwargs()
        ssl_ctx = kwargs["connect_args"]["ssl"]
        assert ssl_ctx.minimum_version == ssl.TLSVersion.TLSv1_3

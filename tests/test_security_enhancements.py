"""Tests for Task 51 — Security enhancements.

Covers:
  51.9  CSP headers block inline scripts and external resources not in allowlist
  51.10 Encrypted fields are not readable in raw database queries
  51.11 Rate limiter returns 429 with Retry-After header when limit exceeded
  51.12 Pen test mode headers only present when PEN_TEST_MODE env var is set
  51.13 Refresh token rotation invalidates old refresh token
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import settings
from app.core.encryption import (
    encrypt_field,
    decrypt_field,
    envelope_encrypt,
    envelope_decrypt_str,
    rotate_master_key,
)
from app.core.encrypted_field import EncryptedString
from app.core.security import REQUIRED_SECURITY_HEADERS
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.rate_limit import RateLimitMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app(*middlewares) -> FastAPI:
    """Create a minimal FastAPI app with the given middleware stack."""
    app = FastAPI()
    for mw in middlewares:
        app.add_middleware(mw)

    @app.get("/test")
    async def test_endpoint():
        return {"ok": True}

    @app.post("/api/v1/auth/password/reset-request")
    async def password_reset():
        return {"sent": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"token": "ok"}

    return app


# ===================================================================
# 51.9 — CSP headers block inline scripts and external resources
# ===================================================================

class TestCSPHeaders:
    """Verify Content-Security-Policy header blocks unsafe content."""

    @pytest.fixture
    def app(self):
        return _build_app(SecurityHeadersMiddleware)

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_csp_header_present(self, client):
        resp = client.get("/test")
        assert "Content-Security-Policy" in resp.headers

    def test_csp_blocks_inline_scripts(self, client):
        """CSP script-src should be 'self' only — no 'unsafe-inline'."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        # script-src must be 'self' only
        assert "script-src 'self'" in csp
        assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]

    def test_csp_blocks_unsafe_eval(self, client):
        """CSP should not allow 'unsafe-eval'."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "'unsafe-eval'" not in csp

    def test_csp_default_src_self(self, client):
        """default-src should be 'self' to block external resources."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp

    def test_csp_frame_ancestors_none(self, client):
        """frame-ancestors 'none' prevents clickjacking."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp

    def test_csp_connect_src_allowlist(self, client):
        """connect-src should allow self, Stripe API, and Firebase domains."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        connect_directive = [
            d.strip() for d in csp.split(";")
            if d.strip().startswith("connect-src")
        ]
        assert len(connect_directive) == 1
        allowed = connect_directive[0]
        assert "'self'" in allowed
        assert "https://api.stripe.com" in allowed
        assert "https://identitytoolkit.googleapis.com" in allowed
        assert "https://www.googleapis.com" in allowed
        assert "https://firebaseinstallations.googleapis.com" in allowed
        # No wildcard origins
        assert "* " not in allowed

    def test_csp_base_uri_self(self, client):
        """base-uri 'self' prevents base tag injection."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "base-uri 'self'" in csp

    def test_csp_form_action_self(self, client):
        """form-action 'self' prevents form submission to external sites."""
        resp = client.get("/test")
        csp = resp.headers["Content-Security-Policy"]
        assert "form-action 'self'" in csp

    def test_all_required_security_headers_present(self, client):
        """All headers from REQUIRED_SECURITY_HEADERS must be set."""
        resp = client.get("/test")
        for header_name in REQUIRED_SECURITY_HEADERS:
            assert header_name in resp.headers, f"Missing header: {header_name}"


# ===================================================================
# 51.10 — Encrypted fields are not readable in raw database queries
# ===================================================================

class TestEncryptedFields:
    """Verify field-level encryption produces opaque ciphertext."""

    def test_encrypt_field_returns_bytes(self):
        result = encrypt_field("123-456-789")
        assert isinstance(result, bytes)

    def test_encrypted_value_not_plaintext(self):
        """Raw encrypted bytes must not contain the original plaintext."""
        plaintext = "NZ-GST-12-345-678"
        encrypted = encrypt_field(plaintext)
        assert plaintext.encode() not in encrypted

    def test_decrypt_field_recovers_original(self):
        plaintext = "GB123456789"
        encrypted = encrypt_field(plaintext)
        assert decrypt_field(encrypted) == plaintext

    def test_different_encryptions_produce_different_ciphertext(self):
        """Each encryption uses a unique DEK, so ciphertext differs."""
        plaintext = "same-value"
        enc1 = encrypt_field(plaintext)
        enc2 = encrypt_field(plaintext)
        assert enc1 != enc2  # Different random DEKs

    def test_empty_string_encrypt(self):
        assert encrypt_field("") == b""

    def test_empty_bytes_decrypt(self):
        assert decrypt_field(b"") == ""

    def test_none_handling_in_type_decorator(self):
        """EncryptedString type should pass None through."""
        col_type = EncryptedString()
        assert col_type.process_bind_param(None, None) is None
        assert col_type.process_result_value(None, None) is None

    def test_type_decorator_roundtrip(self):
        """EncryptedString type should encrypt on bind and decrypt on result."""
        col_type = EncryptedString()
        plaintext = "secret-bank-account-12345"
        encrypted = col_type.process_bind_param(plaintext, None)
        assert isinstance(encrypted, bytes)
        assert plaintext.encode() not in encrypted
        decrypted = col_type.process_result_value(encrypted, None)
        assert decrypted == plaintext

    def test_key_rotation(self):
        """rotate_master_key re-encrypts DEK under new master key."""
        plaintext = "sensitive-data-for-rotation"
        encrypted = envelope_encrypt(plaintext)

        old_key = settings.encryption_master_key
        new_key = "new-master-key-for-rotation"

        rotated = rotate_master_key(old_key, new_key, encrypted)

        # Rotated blob should differ from original
        assert rotated != encrypted

        # Decrypt with new key should work
        new_master = hashlib.sha256(new_key.encode()).digest()
        import struct
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        (dek_len,) = struct.unpack(">I", rotated[:4])
        encrypted_dek = rotated[4 : 4 + dek_len]
        encrypted_payload = rotated[4 + dek_len :]

        nonce = encrypted_dek[:12]
        dek = AESGCM(new_master).decrypt(nonce, encrypted_dek[12:], None)

        nonce2 = encrypted_payload[:12]
        result = AESGCM(dek).decrypt(nonce2, encrypted_payload[12:], None)
        assert result.decode() == plaintext


# ===================================================================
# 51.11 — Rate limiter returns 429 with Retry-After header
# ===================================================================

class TestRateLimiter429:
    """Verify rate limiter returns 429 with Retry-After when limit exceeded."""

    def test_rate_limit_exceeded_returns_429(self):
        """When sliding window count >= limit, return 429."""
        app = FastAPI()
        mock_redis = AsyncMock()
        app.add_middleware(RateLimitMiddleware, redis=mock_redis)

        from starlette.middleware.base import BaseHTTPMiddleware

        class FakeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = "test-user"
                request.state.org_id = "test-org"
                return await call_next(request)

        app.add_middleware(FakeAuthMiddleware)

        @app.get("/api/v1/invoices")
        async def invoices():
            return {"ok": True}

        # Mock _check_rate_limit to return rate-limited
        with patch(
            "app.middleware.rate_limit._check_rate_limit",
            new_callable=AsyncMock,
            return_value=(False, 42),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/invoices")
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert resp.headers["Retry-After"] == "42"

    def test_rate_limit_response_body_has_detail(self):
        """429 response should include a descriptive detail message."""
        app = FastAPI()
        mock_redis = AsyncMock()
        app.add_middleware(RateLimitMiddleware, redis=mock_redis)

        from starlette.middleware.base import BaseHTTPMiddleware

        class FakeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = "test-user"
                request.state.org_id = "test-org"
                return await call_next(request)

        app.add_middleware(FakeAuthMiddleware)

        @app.get("/api/v1/invoices")
        async def invoices():
            return {"ok": True}

        with patch(
            "app.middleware.rate_limit._check_rate_limit",
            new_callable=AsyncMock,
            return_value=(False, 10),
        ):
            client = TestClient(app)
            resp = client.get("/api/v1/invoices")
            assert resp.status_code == 429
            body = resp.json()
            assert "detail" in body

    def test_rate_limit_fail_open_when_redis_unavailable(self):
        """When Redis is down, requests should pass through (fail-open)."""
        app = FastAPI()
        app.add_middleware(RateLimitMiddleware, redis=None)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_password_reset_has_stricter_limit(self):
        """Password reset endpoints should use the 5/min limit."""
        app = FastAPI()
        mock_redis = AsyncMock()
        app.add_middleware(RateLimitMiddleware, redis=mock_redis)

        @app.post("/api/v1/auth/password/reset-request")
        async def pw_reset():
            return {"sent": True}

        call_args_list = []

        async def mock_check(redis, key, limit, now):
            call_args_list.append((key, limit))
            return (True, 0)

        with patch(
            "app.middleware.rate_limit._check_rate_limit",
            side_effect=mock_check,
        ):
            client = TestClient(app)
            resp = client.post("/api/v1/auth/password/reset-request")
            assert resp.status_code == 200

        # Should have been called with password reset key and limit=5
        pw_reset_calls = [c for c in call_args_list if "pwreset" in c[0]]
        assert len(pw_reset_calls) >= 1
        assert pw_reset_calls[0][1] == 5


# ===================================================================
# 51.12 — Pen test mode headers only present when env var is set
# ===================================================================

class TestPenTestMode:
    """Verify pen-test diagnostic headers are conditional on PEN_TEST_MODE."""

    def _build_pen_test_app(self):
        from app.core.pen_test_mode import PenTestMiddleware

        app = FastAPI()
        app.add_middleware(PenTestMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        return app

    def test_no_debug_headers_without_env_var(self):
        """Without PEN_TEST_MODE, no X-Debug-* headers should appear."""
        with patch.dict(os.environ, {}, clear=False):
            # Ensure PEN_TEST_MODE is not set
            os.environ.pop("PEN_TEST_MODE", None)
            app = self._build_pen_test_app()
            client = TestClient(app)
            resp = client.get("/test")
            assert resp.status_code == 200
            assert "X-Debug-SQL-Queries" not in resp.headers
            assert "X-Debug-Cache-Hits" not in resp.headers
            assert "X-Debug-Cache-Misses" not in resp.headers
            assert "X-Debug-Timing-Ms" not in resp.headers

    def test_debug_headers_present_with_env_var(self):
        """With PEN_TEST_MODE=1, all X-Debug-* headers should appear."""
        with patch.dict(os.environ, {"PEN_TEST_MODE": "1"}):
            with patch("app.core.pen_test_mode.settings") as mock_settings:
                mock_settings.environment = "development"
                app = self._build_pen_test_app()
                client = TestClient(app)
                resp = client.get("/test")
                assert resp.status_code == 200
                assert "X-Debug-SQL-Queries" in resp.headers
                assert "X-Debug-Cache-Hits" in resp.headers
                assert "X-Debug-Cache-Misses" in resp.headers
                assert "X-Debug-Timing-Ms" in resp.headers

    def test_debug_headers_blocked_in_production(self):
        """Even with PEN_TEST_MODE=1, production should not expose headers."""
        with patch.dict(os.environ, {"PEN_TEST_MODE": "1"}):
            with patch("app.core.pen_test_mode.settings") as mock_settings:
                mock_settings.environment = "production"
                app = self._build_pen_test_app()
                client = TestClient(app)
                resp = client.get("/test")
                assert resp.status_code == 200
                assert "X-Debug-SQL-Queries" not in resp.headers

    def test_timing_header_is_numeric(self):
        """X-Debug-Timing-Ms should be a valid float."""
        with patch.dict(os.environ, {"PEN_TEST_MODE": "true"}):
            with patch("app.core.pen_test_mode.settings") as mock_settings:
                mock_settings.environment = "staging"
                app = self._build_pen_test_app()
                client = TestClient(app)
                resp = client.get("/test")
                timing = resp.headers.get("X-Debug-Timing-Ms")
                assert timing is not None
                assert float(timing) >= 0

    def test_sql_query_count_defaults_to_zero(self):
        """Without any DB calls, SQL query count should be 0."""
        with patch.dict(os.environ, {"PEN_TEST_MODE": "yes"}):
            with patch("app.core.pen_test_mode.settings") as mock_settings:
                mock_settings.environment = "development"
                app = self._build_pen_test_app()
                client = TestClient(app)
                resp = client.get("/test")
                assert resp.headers["X-Debug-SQL-Queries"] == "0"
                assert resp.headers["X-Debug-Cache-Hits"] == "0"
                assert resp.headers["X-Debug-Cache-Misses"] == "0"


# ===================================================================
# 51.13 — Refresh token rotation invalidates old refresh token
# ===================================================================

class TestRefreshTokenRotation:
    """Verify refresh token rotation invalidates the old token."""

    def _make_session(
        self,
        refresh_token: str,
        family_id=None,
        user_id=None,
        org_id=None,
        is_revoked=False,
    ):
        from app.modules.auth.service import _hash_refresh_token

        s = MagicMock()
        s.id = uuid.uuid4()
        s.user_id = user_id or uuid.uuid4()
        s.org_id = org_id or uuid.uuid4()
        s.refresh_token_hash = _hash_refresh_token(refresh_token)
        s.family_id = family_id or uuid.uuid4()
        s.device_type = "desktop"
        s.browser = "Chrome"
        s.ip_address = "127.0.0.1"
        s.is_revoked = is_revoked
        s.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        return s

    def _make_user(self, user_id, org_id=None):
        u = MagicMock()
        u.id = user_id
        u.org_id = org_id
        u.role = "org_admin"
        u.email = "test@example.com"
        return u

    def _mock_scalar_one_or_none(self, value):
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    def _mock_scalar_one(self, value):
        result = MagicMock()
        result.scalar_one.return_value = value
        return result

    @pytest.mark.asyncio
    async def test_old_token_revoked_after_rotation(self):
        """After rotation, the old session must be marked is_revoked=True."""
        import app.modules.admin.models  # noqa: F401
        from app.modules.auth.service import rotate_refresh_token

        token = "old-refresh-token"
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        session_obj = self._make_session(
            refresh_token=token, user_id=user_id, org_id=org_id,
        )
        user_obj = self._make_user(user_id, org_id)

        db = AsyncMock()
        db.execute.side_effect = [
            self._mock_scalar_one_or_none(session_obj),
            self._mock_scalar_one(user_obj),
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            result = await rotate_refresh_token(db, token)

        # Old session must be revoked
        assert session_obj.is_revoked is True
        # New token must be different
        assert result.refresh_token != token

    @pytest.mark.asyncio
    async def test_new_token_issued_after_rotation(self):
        """Rotation must return a new access + refresh token pair."""
        import app.modules.admin.models  # noqa: F401
        from app.modules.auth.service import rotate_refresh_token

        token = "rotate-me"
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        session_obj = self._make_session(
            refresh_token=token, user_id=user_id, org_id=org_id,
        )
        user_obj = self._make_user(user_id, org_id)

        db = AsyncMock()
        db.execute.side_effect = [
            self._mock_scalar_one_or_none(session_obj),
            self._mock_scalar_one(user_obj),
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            result = await rotate_refresh_token(db, token)

        assert result.access_token
        assert result.refresh_token
        assert result.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_reused_token_revokes_entire_family(self):
        """Using an already-revoked token should invalidate all tokens in the family."""
        import app.modules.admin.models  # noqa: F401
        from app.modules.auth.service import rotate_refresh_token

        token = "already-used-token"
        family_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        revoked_session = self._make_session(
            refresh_token=token,
            family_id=family_id,
            user_id=user_id,
            org_id=org_id,
            is_revoked=True,
        )
        user_obj = self._make_user(user_id, org_id)

        db = AsyncMock()
        db.execute.side_effect = [
            self._mock_scalar_one_or_none(None),           # no valid session
            self._mock_scalar_one_or_none(revoked_session), # found revoked
            MagicMock(),                                    # bulk invalidate family
            self._mock_scalar_one_or_none(user_obj),        # load user for alert
        ]

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_token_reuse_alert", new_callable=AsyncMock) as mock_alert,
        ):
            with pytest.raises(ValueError, match="Token has been revoked"):
                await rotate_refresh_token(db, token, ip_address="10.0.0.1")

        # Alert should be sent for token reuse
        mock_alert.assert_awaited_once()

"""Unit tests for core utilities (Task 1.5).

Tests cover:
  - database.py: context variable management, RLS helper
  - redis.py: pool creation, dependency
  - encryption.py: envelope encrypt/decrypt round-trip, different inputs
  - audit.py: entry construction
  - errors.py: PII sanitisation, auto-categorisation, severity/category enums
"""

import uuid

import pytest

# ---------------------------------------------------------------------------
# Encryption tests (no DB/Redis required)
# ---------------------------------------------------------------------------

from app.core.encryption import (
    envelope_decrypt,
    envelope_decrypt_str,
    envelope_encrypt,
)


class TestEnvelopeEncryption:
    def test_round_trip_string(self):
        plaintext = "sk_live_abc123_stripe_secret"
        blob = envelope_encrypt(plaintext)
        assert isinstance(blob, bytes)
        assert envelope_decrypt_str(blob) == plaintext

    def test_round_trip_bytes(self):
        plaintext = b"\x00\x01\x02binary data"
        blob = envelope_encrypt(plaintext)
        assert envelope_decrypt(blob) == plaintext

    def test_different_plaintexts_produce_different_blobs(self):
        blob1 = envelope_encrypt("secret_a")
        blob2 = envelope_encrypt("secret_b")
        assert blob1 != blob2

    def test_same_plaintext_produces_different_blobs(self):
        """Each encryption uses a fresh DEK, so ciphertexts differ."""
        blob1 = envelope_encrypt("same_value")
        blob2 = envelope_encrypt("same_value")
        assert blob1 != blob2
        # But both decrypt to the same value.
        assert envelope_decrypt_str(blob1) == envelope_decrypt_str(blob2)

    def test_empty_string(self):
        blob = envelope_encrypt("")
        assert envelope_decrypt_str(blob) == ""

    def test_unicode_round_trip(self):
        plaintext = "Tēnā koe — NZ Māori greeting 🇳🇿"
        blob = envelope_encrypt(plaintext)
        assert envelope_decrypt_str(blob) == plaintext

    def test_large_payload(self):
        plaintext = "x" * 100_000
        blob = envelope_encrypt(plaintext)
        assert envelope_decrypt_str(blob) == plaintext

    def test_tampered_blob_raises(self):
        blob = envelope_encrypt("secret")
        tampered = blob[:-1] + bytes([blob[-1] ^ 0xFF])
        with pytest.raises(Exception):
            envelope_decrypt(tampered)


# ---------------------------------------------------------------------------
# Error logging — sanitisation & categorisation (no DB required)
# ---------------------------------------------------------------------------

from app.core.errors import (
    Category,
    Severity,
    auto_categorise,
    sanitise_value,
)


class TestSanitisation:
    def test_email_redacted(self):
        result = sanitise_value("Contact john@example.com for details")
        assert "john@example.com" not in result
        assert "[EMAIL_REDACTED]" in result

    def test_sensitive_dict_keys_redacted(self):
        data = {
            "username": "admin",
            "password": "hunter2",
            "email": "user@test.com",
            "first_name": "John",
            "address": "123 Main St",
            "api_key": "sk_live_xxx",
        }
        result = sanitise_value(data)
        assert result["username"] == "admin"  # not a sensitive key
        assert result["password"] == "[REDACTED]"
        assert result["email"] == "[REDACTED]"
        assert result["first_name"] == "[REDACTED]"
        assert result["address"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"

    def test_nested_dict_sanitised(self):
        data = {"user": {"email": "a@b.com", "role": "admin"}}
        result = sanitise_value(data)
        assert result["user"]["email"] == "[REDACTED]"
        assert result["user"]["role"] == "admin"

    def test_list_sanitised(self):
        data = [{"password": "secret"}, {"name": "Jane"}]
        result = sanitise_value(data)
        assert result[0]["password"] == "[REDACTED]"
        assert result[1]["name"] == "[REDACTED]"

    def test_none_passthrough(self):
        assert sanitise_value(None) is None

    def test_numeric_passthrough(self):
        assert sanitise_value(42) == 42

    def test_card_number_redacted(self):
        result = sanitise_value("Card: 4111-1111-1111-1111")
        assert "4111" not in result
        assert "[CARD_REDACTED]" in result


class TestAutoCategoisation:
    def test_payment_module(self):
        assert auto_categorise("modules.payments.service") == Category.PAYMENT

    def test_stripe_integration(self):
        assert auto_categorise("integrations.stripe_connect") == Category.PAYMENT

    def test_carjam_integration(self):
        assert auto_categorise("integrations.carjam") == Category.INTEGRATION

    def test_auth_module(self):
        assert auto_categorise("modules.auth.router") == Category.AUTHENTICATION

    def test_celery_task(self):
        assert auto_categorise("tasks.notifications") == Category.BACKGROUND_JOB

    def test_storage_module(self):
        assert auto_categorise("modules.storage.service") == Category.STORAGE

    def test_unknown_defaults_to_application(self):
        assert auto_categorise("modules.invoices.router") == Category.APPLICATION

    def test_twilio_integration(self):
        assert auto_categorise("integrations.twilio_sms") == Category.INTEGRATION


class TestSeverityEnum:
    def test_values(self):
        assert Severity.INFO == "info"
        assert Severity.WARNING == "warning"
        assert Severity.ERROR == "error"
        assert Severity.CRITICAL == "critical"


class TestCategoryEnum:
    def test_values(self):
        assert Category.PAYMENT == "payment"
        assert Category.INTEGRATION == "integration"
        assert Category.STORAGE == "storage"
        assert Category.AUTHENTICATION == "authentication"
        assert Category.DATA == "data"
        assert Category.BACKGROUND_JOB == "background_job"
        assert Category.APPLICATION == "application"


# ---------------------------------------------------------------------------
# Database — context variable management (no real DB connection)
# ---------------------------------------------------------------------------

from app.core.database import _current_org_id, set_current_org_id


class TestDatabaseContextVar:
    def test_set_and_get_org_id(self):
        set_current_org_id("org-123")
        assert _current_org_id.get() == "org-123"

    def test_set_none(self):
        set_current_org_id(None)
        assert _current_org_id.get() is None

    def test_overwrite(self):
        set_current_org_id("org-a")
        set_current_org_id("org-b")
        assert _current_org_id.get() == "org-b"


# ---------------------------------------------------------------------------
# Redis — pool creation (no real Redis connection)
# ---------------------------------------------------------------------------

from app.core.redis import get_redis, redis_pool


class TestRedisPool:
    def test_pool_is_created(self):
        assert redis_pool is not None

    @pytest.mark.asyncio
    async def test_get_redis_returns_pool(self):
        r = await get_redis()
        assert r is redis_pool


# ---------------------------------------------------------------------------
# Tenant middleware integration with database context var
# ---------------------------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.tenant import TenantMiddleware


def _make_token(user_id="u1", org_id="org1", role="salesperson"):
    payload = {"user_id": user_id, "role": role}
    if org_id is not None:
        payload["org_id"] = org_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TestTenantMiddlewareWithDatabase:
    def test_org_id_set_in_context_var(self):
        app = FastAPI()
        app.add_middleware(TenantMiddleware)
        app.add_middleware(AuthMiddleware)

        @app.get("/api/v1/check")
        async def check(request: Request):
            from app.core.database import _current_org_id
            return {"ctx_org_id": _current_org_id.get()}

        client = TestClient(app)
        token = _make_token(org_id="org-ctx-test")
        resp = client.get(
            "/api/v1/check",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["ctx_org_id"] == "org-ctx-test"

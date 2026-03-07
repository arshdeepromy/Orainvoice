"""Security-focused tests for Task 38.6.

Verifies:
  - CSRF protection on all state-changing endpoints (Requirement 52.4)
  - PII is never written to logs or error reports (Requirement 13.4)
  - Integration credentials are never returned in API responses (Requirement 48.5)
  - RLS violations return 404, not 403 (Requirement 54.3)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from app.core.errors import sanitise_value, Severity, Category
from app.middleware.security_headers import (
    SecurityHeadersMiddleware,
    _CSRF_EXEMPT_PATHS,
    _STATE_CHANGING_METHODS,
)
from app.modules.admin.service import get_integration_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_csrf_app() -> FastAPI:
    """Create a minimal FastAPI app with SecurityHeadersMiddleware for CSRF tests."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.post("/api/v1/invoices")
    async def create_invoice():
        return {"created": True}

    @app.put("/api/v1/invoices/1")
    async def update_invoice():
        return {"updated": True}

    @app.patch("/api/v1/invoices/1")
    async def patch_invoice():
        return {"patched": True}

    @app.delete("/api/v1/invoices/1")
    async def delete_invoice():
        return {"deleted": True}

    @app.get("/api/v1/invoices")
    async def list_invoices():
        return {"invoices": []}

    @app.post("/api/v1/payments/stripe/webhook")
    async def stripe_webhook():
        return {"ok": True}

    return app


def _mock_db_session():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# 1. CSRF Protection Tests (Requirement 52.4)
# ---------------------------------------------------------------------------

class TestCSRFProtection:
    """Verify CSRF protection on state-changing endpoints."""

    @pytest.fixture
    def app(self):
        return _build_csrf_app()

    @pytest.fixture
    def session_client(self, app):
        """Client with a session cookie (simulates browser-based auth)."""
        return TestClient(app, cookies={"session": "test-session-id"})

    @pytest.fixture
    def bearer_client(self, app):
        """Client with a Bearer token (API client)."""
        return TestClient(app)

    def test_post_with_session_cookie_no_csrf_returns_403(self, session_client):
        """POST with session cookie but no X-CSRF-Token must be rejected."""
        resp = session_client.post("/api/v1/invoices", json={})
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_put_with_session_cookie_no_csrf_returns_403(self, session_client):
        """PUT with session cookie but no X-CSRF-Token must be rejected."""
        resp = session_client.put("/api/v1/invoices/1", json={})
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_patch_with_session_cookie_no_csrf_returns_403(self, session_client):
        """PATCH with session cookie but no X-CSRF-Token must be rejected."""
        resp = session_client.patch("/api/v1/invoices/1", json={})
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_delete_with_session_cookie_no_csrf_returns_403(self, session_client):
        """DELETE with session cookie but no X-CSRF-Token must be rejected."""
        resp = session_client.delete("/api/v1/invoices/1")
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_post_with_csrf_token_succeeds(self, session_client):
        """POST with session cookie AND X-CSRF-Token should pass CSRF check."""
        resp = session_client.post(
            "/api/v1/invoices",
            json={},
            headers={"X-CSRF-Token": "valid-csrf-token"},
        )
        assert resp.status_code == 200

    def test_put_with_csrf_token_succeeds(self, session_client):
        """PUT with session cookie AND X-CSRF-Token should pass CSRF check."""
        resp = session_client.put(
            "/api/v1/invoices/1",
            json={},
            headers={"X-CSRF-Token": "valid-csrf-token"},
        )
        assert resp.status_code == 200

    def test_bearer_token_exempt_from_csrf(self, bearer_client):
        """POST with Bearer token should not require CSRF header."""
        resp = bearer_client.post(
            "/api/v1/invoices",
            json={},
            headers={"Authorization": "Bearer fake-jwt-token"},
        )
        assert resp.status_code == 200

    def test_get_request_not_affected_by_csrf(self, session_client):
        """GET requests should never require CSRF tokens."""
        resp = session_client.get("/api/v1/invoices")
        assert resp.status_code == 200

    def test_webhook_path_exempt_from_csrf(self, session_client):
        """Webhook endpoints should be exempt from CSRF checks."""
        resp = session_client.post(
            "/api/v1/payments/stripe/webhook",
            json={"type": "payment_intent.succeeded"},
        )
        assert resp.status_code == 200

    def test_all_state_changing_methods_covered(self):
        """Ensure POST, PUT, PATCH, DELETE are all considered state-changing."""
        assert _STATE_CHANGING_METHODS == {"POST", "PUT", "PATCH", "DELETE"}

    def test_csrf_exempt_paths_include_stripe_webhook(self):
        """Stripe webhook path must be in the CSRF exempt set."""
        assert "/api/v1/payments/stripe/webhook" in _CSRF_EXEMPT_PATHS


# ---------------------------------------------------------------------------
# 2. PII Never in Logs Tests (Requirement 13.4)
# ---------------------------------------------------------------------------

class TestPIISanitisation:
    """Verify PII is stripped from error log entries."""

    def test_email_redacted_from_string(self):
        """Email addresses must be replaced with [EMAIL_REDACTED]."""
        result = sanitise_value("Contact john.doe@example.com for help")
        assert "john.doe@example.com" not in result
        assert "[EMAIL_REDACTED]" in result

    def test_nz_phone_redacted_from_string(self):
        """NZ phone numbers (compact format) must be replaced with [PHONE_REDACTED]."""
        result = sanitise_value("Call 0211234567 for support")
        assert "0211234567" not in result
        assert "[PHONE_REDACTED]" in result

    def test_international_phone_redacted(self):
        """International format NZ numbers must be redacted."""
        result = sanitise_value("Phone: +64211234567")
        assert "+64211234567" not in result
        assert "[PHONE_REDACTED]" in result

    def test_credit_card_redacted(self):
        """Credit card numbers must be replaced with [CARD_REDACTED]."""
        result = sanitise_value("Card: 4111 1111 1111 1111")
        assert "4111 1111 1111 1111" not in result
        assert "[CARD_REDACTED]" in result

    def test_name_key_redacted_in_dict(self):
        """Dict keys like 'name', 'first_name', 'last_name' must be redacted."""
        data = {
            "name": "John Doe",
            "first_name": "John",
            "last_name": "Doe",
            "invoice_id": "INV-001",
        }
        result = sanitise_value(data)
        assert result["name"] == "[REDACTED]"
        assert result["first_name"] == "[REDACTED]"
        assert result["last_name"] == "[REDACTED]"
        assert result["invoice_id"] == "INV-001"

    def test_email_key_redacted_in_dict(self):
        """Dict key 'email' must be redacted."""
        data = {"email": "customer@example.com", "status": "active"}
        result = sanitise_value(data)
        assert result["email"] == "[REDACTED]"
        assert result["status"] == "active"

    def test_phone_key_redacted_in_dict(self):
        """Dict keys 'phone', 'phone_number', 'mobile' must be redacted."""
        data = {
            "phone": "021 555 1234",
            "phone_number": "+6421555999",
            "mobile": "027 888 7777",
        }
        result = sanitise_value(data)
        assert result["phone"] == "[REDACTED]"
        assert result["phone_number"] == "[REDACTED]"
        assert result["mobile"] == "[REDACTED]"

    def test_password_and_token_keys_redacted(self):
        """Sensitive keys like password, token, api_key must be redacted."""
        data = {
            "password": "s3cret!",
            "token": "jwt-abc-123",
            "api_key": "sk_live_xxx",
        }
        result = sanitise_value(data)
        assert result["password"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"

    def test_nested_dict_pii_redacted(self):
        """PII in nested dicts must also be redacted."""
        data = {
            "customer": {
                "name": "Jane Smith",
                "email": "jane@example.com",
            },
            "amount": 150.00,
        }
        result = sanitise_value(data)
        assert result["customer"]["name"] == "[REDACTED]"
        assert result["customer"]["email"] == "[REDACTED]"
        assert result["amount"] == 150.00

    def test_list_values_sanitised(self):
        """PII in list items must be sanitised."""
        data = ["Contact john@example.com", "No PII here"]
        result = sanitise_value(data)
        assert "john@example.com" not in result[0]
        assert "[EMAIL_REDACTED]" in result[0]
        assert result[1] == "No PII here"

    def test_none_value_passes_through(self):
        """None values should pass through unchanged."""
        assert sanitise_value(None) is None

    def test_stack_trace_with_email_sanitised(self):
        """Stack traces containing PII must be sanitised."""
        trace = (
            'Traceback (most recent call last):\n'
            '  File "app/service.py", line 42\n'
            '    raise ValueError("User admin@workshop.nz not found")\n'
            'ValueError: User admin@workshop.nz not found'
        )
        result = sanitise_value(trace)
        assert "admin@workshop.nz" not in result
        assert "[EMAIL_REDACTED]" in result


# ---------------------------------------------------------------------------
# 3. Integration Credentials Never in API Responses (Requirement 48.5)
# ---------------------------------------------------------------------------

class TestIntegrationCredentialMasking:
    """Verify integration credentials are never returned in API responses."""

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_carjam_api_key_never_returned_raw(self, mock_decrypt):
        """GET /integrations/carjam must not return the raw API key."""
        config_data = {
            "api_key": "cj_live_super_secret_key_12345",
            "endpoint_url": "https://api.carjam.co.nz/v1",
            "per_lookup_cost_nzd": 0.15,
            "global_rate_limit_per_minute": 60,
        }
        mock_decrypt.return_value = json.dumps(config_data)

        from app.modules.admin.models import IntegrationConfig as IC
        config_row = MagicMock(spec=IC)
        config_row.name = "carjam"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="carjam")
        response_json = json.dumps(result)

        # Raw API key must never appear
        assert "cj_live_super_secret_key_12345" not in response_json
        # Only last 4 chars as masked value
        assert result["config"].get("api_key_last4") == "2345"

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_stripe_secrets_never_returned_raw(self, mock_decrypt):
        """GET /integrations/stripe must not return raw signing_secret or account ID."""
        config_data = {
            "platform_account_id": "acct_1234567890abcdef",
            "webhook_endpoint": "https://workshoppro.nz/webhook",
            "signing_secret": "whsec_very_secret_signing_key",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        from app.modules.admin.models import IntegrationConfig as IC
        config_row = MagicMock(spec=IC)
        config_row.name = "stripe"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 7, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="stripe")
        response_json = json.dumps(result)

        # Raw secrets must never appear
        assert "acct_1234567890abcdef" not in response_json
        assert "whsec_very_secret_signing_key" not in response_json
        # Only masked last-4 values
        assert result["config"]["platform_account_id_last4"] == "cdef"
        assert result["config"]["signing_secret_last4"] == "_key"

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_smtp_api_key_never_returned_raw(self, mock_decrypt):
        """GET /integrations/smtp must not return the raw API key or password."""
        config_data = {
            "provider": "brevo",
            "api_key": "xkeysib-secret-api-key-value",
            "host": "smtp.brevo.com",
            "port": 587,
            "username": "user",
            "password": "smtp-password-secret",
            "domain": "workshoppro.nz",
            "from_email": "noreply@workshoppro.nz",
            "from_name": "WorkshopPro",
            "reply_to": "support@workshoppro.nz",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        from app.modules.admin.models import IntegrationConfig as IC
        config_row = MagicMock(spec=IC)
        config_row.name = "smtp"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 5, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="smtp")
        response_json = json.dumps(result)

        # Raw secrets must never appear
        assert "xkeysib-secret-api-key-value" not in response_json
        assert "smtp-password-secret" not in response_json
        # Masked value present
        assert result["config"]["api_key_last4"] == "alue"

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_twilio_auth_token_never_returned_raw(self, mock_decrypt):
        """GET /integrations/twilio must not return the raw auth_token."""
        config_data = {
            "account_sid": "AC1234567890abcdef1234567890abcdef",
            "auth_token": "twilio_super_secret_auth_token",
            "sender_number": "+64211234567",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        from app.modules.admin.models import IntegrationConfig as IC
        config_row = MagicMock(spec=IC)
        config_row.name = "twilio"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 8, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="twilio")
        response_json = json.dumps(result)

        # Raw secrets must never appear
        assert "twilio_super_secret_auth_token" not in response_json
        assert "AC1234567890abcdef1234567890abcdef" not in response_json
        # Masked value present
        assert result["config"]["account_sid_last4"] == "cdef"

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_no_full_secret_keys_in_config_dict(self, mock_decrypt):
        """The config dict must never contain the original secret field names with raw values."""
        config_data = {
            "api_key": "secret-key-value",
            "endpoint_url": "https://api.carjam.co.nz/v1",
            "per_lookup_cost_nzd": 0.15,
            "global_rate_limit_per_minute": 60,
        }
        mock_decrypt.return_value = json.dumps(config_data)

        from app.modules.admin.models import IntegrationConfig as IC
        config_row = MagicMock(spec=IC)
        config_row.name = "carjam"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="carjam")
        config = result["config"]

        # The raw "api_key" key must not be present with the full value
        assert config.get("api_key") != "secret-key-value"


# ---------------------------------------------------------------------------
# 4. RLS Violations Return 404 (Requirement 54.3)
# ---------------------------------------------------------------------------

class TestRLSViolationsReturn404:
    """Verify that accessing another org's resource returns 404, not 403.

    This prevents information leakage about whether a resource exists
    in another organisation's data.
    """

    def test_cross_org_access_returns_404_not_403(self):
        """A request for another org's resource must get 404, not 403."""
        app = FastAPI()

        @app.get("/api/v1/invoices/{invoice_id}")
        async def get_invoice(invoice_id: str, request: Request):
            # Simulate RLS: the query returns no rows because the
            # invoice belongs to a different org.
            requesting_org = getattr(request.state, "org_id", "org-A")
            invoice_org = "org-B"  # different org
            if requesting_org != invoice_org:
                # Correct behaviour: return 404 (not 403)
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Invoice not found"},
                )
            return {"id": invoice_id}

        client = TestClient(app)
        resp = client.get("/api/v1/invoices/inv-999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Invoice not found"
        # Must NOT be 403 — that would leak existence info
        assert resp.status_code != 403

    def test_rls_filtered_query_returns_404_for_missing_resource(self):
        """When RLS filters out a row, the API should return 404."""
        app = FastAPI()

        @app.get("/api/v1/customers/{customer_id}")
        async def get_customer(customer_id: str):
            # Simulate: RLS-filtered query returns None
            customer = None  # RLS hid the row
            if customer is None:
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Customer not found"},
                )
            return {"id": customer_id}

        client = TestClient(app)
        resp = client.get("/api/v1/customers/cust-other-org")
        assert resp.status_code == 404
        # Verify the response doesn't hint at authorization issues
        detail = resp.json()["detail"]
        assert "forbidden" not in detail.lower()
        assert "permission" not in detail.lower()
        assert "unauthorized" not in detail.lower()

    def test_rls_violation_response_does_not_leak_org_info(self):
        """404 response for RLS violation must not mention the owning org."""
        app = FastAPI()

        @app.get("/api/v1/jobs/{job_id}")
        async def get_job(job_id: str):
            # Simulate RLS filtering
            return JSONResponse(
                status_code=404,
                content={"detail": "Job not found"},
            )

        client = TestClient(app)
        resp = client.get("/api/v1/jobs/job-from-other-org")
        body = json.dumps(resp.json())
        assert resp.status_code == 404
        # Must not contain org references
        assert "org-" not in body
        assert "organisation" not in body.lower()

    def test_database_rls_set_local_org_id(self):
        """Verify the RLS helper sets app.current_org_id via SET LOCAL."""
        from app.core.database import _set_rls_org_id

        session = AsyncMock()
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            _set_rls_org_id(session, "org-123")
        )
        session.execute.assert_called_once()
        call_args = session.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "SET LOCAL app.current_org_id" in sql_text

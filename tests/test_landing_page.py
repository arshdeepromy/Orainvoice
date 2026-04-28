"""Unit and integration tests for the landing page endpoints.

Tests cover:
  - POST /api/v1/public/demo-request: valid submission, missing fields,
    invalid email, honeypot rejection, rate limiting
  - GET /api/v1/public/privacy-policy: null content when no policy saved,
    content returned after save
  - PUT /api/v1/admin/privacy-policy: global_admin role required (403 for
    org_admin), saves content and returns timestamp, content length validation

Requirements: 18.5, 18.6, 18.7, 18.8, 18.11, 21.3, 21.4, 21.9
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.landing.schemas import (
    DemoRequestPayload,
    DemoRequestResponse,
    PrivacyPolicyResponse,
    PrivacyPolicyUpdatePayload,
    PrivacyPolicyUpdateResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    """Create a mock async DB session with common operations."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _mock_redis():
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    return redis


def _make_execute_result(rows=None, scalar_value=None):
    """Create a mock execute result."""
    result = MagicMock()
    result.first.return_value = rows[0] if rows else None
    result.scalar_one_or_none.return_value = scalar_value
    result.scalar_one.return_value = scalar_value
    result.scalars.return_value.all.return_value = rows or []
    return result


def _make_email_provider(
    provider_key="smtp-default",
    smtp_host="smtp.example.com",
    smtp_port=587,
    priority=1,
):
    """Create a mock EmailProvider."""
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.smtp_host = smtp_host
    provider.smtp_port = smtp_port
    provider.smtp_encryption = "tls"
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted"
    provider.config = {"from_email": "noreply@example.com", "from_name": "OraInvoice"}
    provider.priority = priority
    return provider


def _make_request(client_ip="127.0.0.1", user_id=None, role=None):
    """Create a mock FastAPI Request object."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = client_ip
    request.state = MagicMock()
    request.state.user_id = user_id
    request.state.client_ip = client_ip
    request.state.role = role
    return request


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestDemoRequestSchemas:
    """Validate DemoRequestPayload Pydantic schema."""

    def test_valid_payload(self):
        payload = DemoRequestPayload(
            full_name="John Smith",
            business_name="Smith Auto",
            email="john@smithauto.co.nz",
        )
        assert payload.full_name == "John Smith"
        assert payload.business_name == "Smith Auto"
        assert payload.email == "john@smithauto.co.nz"
        assert payload.phone is None
        assert payload.message is None
        assert payload.website is None

    def test_valid_payload_all_fields(self):
        payload = DemoRequestPayload(
            full_name="Jane Doe",
            business_name="Doe Motors",
            email="jane@doemotors.co.nz",
            phone="+6421234567",
            message="Interested in a demo for our workshop.",
            website=None,
        )
        assert payload.phone == "+6421234567"
        assert payload.message == "Interested in a demo for our workshop."

    def test_missing_full_name_rejected(self):
        with pytest.raises(Exception):
            DemoRequestPayload(
                full_name="",
                business_name="Test",
                email="a@b.com",
            )

    def test_missing_business_name_rejected(self):
        with pytest.raises(Exception):
            DemoRequestPayload(
                full_name="Test",
                business_name="",
                email="a@b.com",
            )

    def test_invalid_email_rejected(self):
        with pytest.raises(Exception):
            DemoRequestPayload(
                full_name="Test",
                business_name="Test",
                email="not-an-email",
            )

    def test_full_name_max_length(self):
        with pytest.raises(Exception):
            DemoRequestPayload(
                full_name="A" * 201,
                business_name="Test",
                email="a@b.com",
            )

    def test_business_name_max_length(self):
        with pytest.raises(Exception):
            DemoRequestPayload(
                full_name="Test",
                business_name="B" * 201,
                email="a@b.com",
            )

    def test_message_max_length(self):
        with pytest.raises(Exception):
            DemoRequestPayload(
                full_name="Test",
                business_name="Test",
                email="a@b.com",
                message="M" * 2001,
            )


class TestPrivacyPolicySchemas:
    """Validate privacy policy Pydantic schemas."""

    def test_response_defaults(self):
        resp = PrivacyPolicyResponse()
        assert resp.content is None
        assert resp.last_updated is None

    def test_response_with_data(self):
        resp = PrivacyPolicyResponse(
            content="# Privacy Policy\nSome content.",
            last_updated="2025-06-01T00:00:00+00:00",
        )
        assert resp.content == "# Privacy Policy\nSome content."
        assert resp.last_updated == "2025-06-01T00:00:00+00:00"

    def test_update_payload_valid(self):
        payload = PrivacyPolicyUpdatePayload(content="New policy content")
        assert payload.content == "New policy content"

    def test_update_payload_empty_rejected(self):
        with pytest.raises(Exception):
            PrivacyPolicyUpdatePayload(content="")

    def test_update_payload_exceeds_max_length(self):
        with pytest.raises(Exception):
            PrivacyPolicyUpdatePayload(content="X" * 100001)

    def test_update_response(self):
        resp = PrivacyPolicyUpdateResponse(
            success=True,
            last_updated="2025-06-01T12:00:00+00:00",
        )
        assert resp.success is True
        assert resp.last_updated == "2025-06-01T12:00:00+00:00"


# ---------------------------------------------------------------------------
# POST /api/v1/public/demo-request — endpoint tests
# ---------------------------------------------------------------------------

class TestDemoRequestEndpoint:
    """Test the submit_demo_request endpoint function."""

    @pytest.mark.asyncio
    @patch("app.modules.landing.router.envelope_decrypt_str")
    @patch("app.modules.landing.router.smtplib")
    async def test_valid_submission_returns_200(self, mock_smtplib, mock_decrypt):
        """Valid demo request with active email provider returns 200."""
        from app.modules.landing.router import submit_demo_request

        mock_decrypt.return_value = json.dumps({
            "username": "user@example.com",
            "password": "secret",
        })
        mock_smtp_instance = MagicMock()
        mock_smtplib.SMTP.return_value = mock_smtp_instance

        provider = _make_email_provider()
        db = _mock_db()
        provider_result = _make_execute_result()
        provider_result.scalars.return_value.all.return_value = [provider]
        db.execute = AsyncMock(return_value=provider_result)

        redis = _mock_redis()
        request = _make_request()

        payload = DemoRequestPayload(
            full_name="John Smith",
            business_name="Smith Auto",
            email="john@smithauto.co.nz",
            phone="+6421234567",
            message="Interested in a demo.",
        )

        result = await submit_demo_request(payload, request, db, redis)

        assert isinstance(result, DemoRequestResponse)
        assert result.success is True
        assert "24 hours" in result.message
        mock_smtp_instance.sendmail.assert_called_once()

    @pytest.mark.asyncio
    async def test_honeypot_returns_200_without_email(self):
        """Non-empty honeypot field returns 200 without sending email.

        Validates: Requirement 18.11
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()

        payload = DemoRequestPayload(
            full_name="Bot User",
            business_name="Bot Corp",
            email="bot@spam.com",
            website="http://spam.example.com",  # honeypot filled
        )

        result = await submit_demo_request(payload, request, db, redis)

        assert isinstance(result, DemoRequestResponse)
        assert result.success is True
        # DB should NOT have been queried for email providers
        db.execute.assert_not_called()
        # Redis rate limit should NOT have been checked
        redis.incr.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limiting_returns_429(self):
        """6th request within 1 hour returns 429.

        Validates: Requirement 18.8
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        # Simulate 6th request (exceeds RATE_LIMIT_MAX of 5)
        redis.incr = AsyncMock(return_value=6)
        request = _make_request()

        payload = DemoRequestPayload(
            full_name="Frequent User",
            business_name="Frequent Corp",
            email="freq@example.com",
        )

        result = await submit_demo_request(payload, request, db, redis)

        # Should be a JSONResponse with 429
        assert result.status_code == 429
        body = json.loads(result.body)
        assert body["success"] is False
        assert "Too many requests" in body["message"]

    @pytest.mark.asyncio
    async def test_fifth_request_still_allowed(self):
        """5th request within 1 hour is still allowed (limit is 5).

        Validates: Requirement 18.8
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        # Return empty providers so we get a 500 (but not a 429)
        provider_result = _make_execute_result()
        provider_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=provider_result)

        redis = _mock_redis()
        redis.incr = AsyncMock(return_value=5)
        request = _make_request()

        payload = DemoRequestPayload(
            full_name="User",
            business_name="Corp",
            email="user@example.com",
        )

        result = await submit_demo_request(payload, request, db, redis)

        # Should NOT be 429 — 5th request is within the limit
        # It will be 500 because no providers, but that's fine — not rate limited
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_no_email_providers_returns_500(self):
        """No active email providers returns 500."""
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        provider_result = _make_execute_result()
        provider_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=provider_result)

        redis = _mock_redis()
        request = _make_request()

        payload = DemoRequestPayload(
            full_name="User",
            business_name="Corp",
            email="user@example.com",
        )

        result = await submit_demo_request(payload, request, db, redis)

        assert result.status_code == 500
        body = json.loads(result.body)
        assert body["success"] is False

    @pytest.mark.asyncio
    async def test_redis_unavailable_fails_open(self):
        """When Redis is unavailable, rate limiting is skipped (fail-open)."""
        from app.modules.landing.router import _check_rate_limit

        redis = _mock_redis()
        redis.incr = AsyncMock(side_effect=Exception("Connection refused"))

        result = await _check_rate_limit(redis, "192.168.1.1")

        # Should return False (not rate limited) — fail open
        assert result is False


# ---------------------------------------------------------------------------
# GET /api/v1/public/privacy-policy — endpoint tests
# ---------------------------------------------------------------------------

class TestGetPrivacyPolicyEndpoint:
    """Test the get_privacy_policy endpoint function."""

    @pytest.mark.asyncio
    async def test_no_custom_policy_returns_null(self):
        """When no custom policy saved, returns null content.

        Validates: Requirement 21.4
        """
        from app.modules.landing.router import get_privacy_policy

        db = _mock_db()
        result = _make_execute_result()
        result.first.return_value = None
        db.execute = AsyncMock(return_value=result)

        response = await get_privacy_policy(db)

        assert isinstance(response, PrivacyPolicyResponse)
        assert response.content is None
        assert response.last_updated is None

    @pytest.mark.asyncio
    async def test_returns_content_after_save(self):
        """When custom policy exists, returns content and timestamp.

        Validates: Requirements 21.4, 21.9
        """
        from app.modules.landing.router import get_privacy_policy

        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        stored_value = {"content": "# Custom Privacy Policy\n\nThis is custom.", "updated_by": str(uuid.uuid4())}

        db = _mock_db()
        result = _make_execute_result()
        result.first.return_value = (stored_value, now)
        db.execute = AsyncMock(return_value=result)

        response = await get_privacy_policy(db)

        assert isinstance(response, PrivacyPolicyResponse)
        assert response.content == "# Custom Privacy Policy\n\nThis is custom."
        assert response.last_updated == now.isoformat()

    @pytest.mark.asyncio
    async def test_returns_content_from_json_string(self):
        """When value is stored as JSON string (not dict), it is parsed correctly."""
        from app.modules.landing.router import get_privacy_policy

        now = datetime(2025, 7, 15, 8, 30, 0, tzinfo=timezone.utc)
        stored_value = json.dumps({"content": "Markdown content here", "updated_by": "user-123"})

        db = _mock_db()
        result = _make_execute_result()
        result.first.return_value = (stored_value, now)
        db.execute = AsyncMock(return_value=result)

        response = await get_privacy_policy(db)

        assert response.content == "Markdown content here"
        assert response.last_updated == now.isoformat()


# ---------------------------------------------------------------------------
# PUT /api/v1/admin/privacy-policy — endpoint tests
# ---------------------------------------------------------------------------

class TestUpdatePrivacyPolicyEndpoint:
    """Test the update_privacy_policy endpoint function."""

    @pytest.mark.asyncio
    @patch("app.modules.landing.router.write_audit_log", new_callable=AsyncMock)
    async def test_saves_content_and_returns_timestamp(self, mock_audit):
        """Global admin can save privacy policy content.

        Validates: Requirement 21.3
        """
        from app.modules.landing.router import update_privacy_policy

        user_id = str(uuid.uuid4())
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

        db = _mock_db()
        # First execute: SELECT FOR UPDATE — no existing row
        select_result = _make_execute_result()
        select_result.first.return_value = None
        # Second execute: INSERT
        insert_result = MagicMock()
        # Third execute: SELECT updated_at
        ts_result = _make_execute_result(scalar_value=now)
        db.execute = AsyncMock(side_effect=[select_result, insert_result, ts_result])

        request = _make_request(user_id=user_id, role="global_admin")

        payload = PrivacyPolicyUpdatePayload(content="# New Privacy Policy\n\nUpdated content.")

        response = await update_privacy_policy(payload, request, db)

        assert isinstance(response, PrivacyPolicyUpdateResponse)
        assert response.success is True
        assert response.last_updated == now.isoformat()
        mock_audit.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.landing.router.write_audit_log", new_callable=AsyncMock)
    async def test_updates_existing_content(self, mock_audit):
        """Updating existing privacy policy increments version."""
        from app.modules.landing.router import update_privacy_policy

        user_id = str(uuid.uuid4())
        now = datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc)

        db = _mock_db()
        # First execute: SELECT FOR UPDATE — existing row
        existing_value = json.dumps({"content": "Old content", "updated_by": "old-user"})
        select_result = _make_execute_result()
        select_result.first.return_value = (existing_value, 2)
        # Second execute: UPDATE
        update_result = MagicMock()
        # Third execute: SELECT updated_at
        ts_result = _make_execute_result(scalar_value=now)
        db.execute = AsyncMock(side_effect=[select_result, update_result, ts_result])

        request = _make_request(user_id=user_id, role="global_admin")
        payload = PrivacyPolicyUpdatePayload(content="# Updated Policy")

        response = await update_privacy_policy(payload, request, db)

        assert response.success is True
        assert response.last_updated == now.isoformat()

        # Verify the UPDATE call used version 3 (old was 2)
        update_call = db.execute.call_args_list[1]
        params = update_call[0][1]
        assert params["ver"] == 3


# ---------------------------------------------------------------------------
# Role-based access control tests (admin endpoint)
# ---------------------------------------------------------------------------

class TestPrivacyPolicyRBAC:
    """Test that PUT /api/v1/admin/privacy-policy requires global_admin role.

    Uses the same pattern as test_rbac.py — builds a minimal FastAPI app
    with the auth middleware and the admin router to test role enforcement.
    """

    def test_org_admin_gets_403(self):
        """org_admin role is denied access to PUT /api/v1/admin/privacy-policy.

        Validates: Requirement 21.3 (global_admin only)
        """
        import jwt
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.middleware.auth import AuthMiddleware
        from app.modules.landing.router import admin_router

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")
        app.add_middleware(AuthMiddleware)

        client = TestClient(app)

        token = jwt.encode(
            {"user_id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "role": "org_admin"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        resp = client.put(
            "/api/v1/admin/privacy-policy",
            json={"content": "Some policy content"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403

    def test_global_admin_is_allowed(self):
        """global_admin role is allowed access to PUT /api/v1/admin/privacy-policy.

        Mocks the DB and audit log to isolate the role check.
        """
        import jwt
        from unittest.mock import AsyncMock, MagicMock, patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.core.database import get_db_session
        from app.core.redis import get_redis
        from app.middleware.auth import AuthMiddleware
        from app.modules.landing.router import admin_router

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")
        app.add_middleware(AuthMiddleware)

        # Mock DB session to avoid hitting real database
        mock_db = AsyncMock()
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        select_result = MagicMock()
        select_result.first.return_value = None
        insert_result = MagicMock()
        ts_result = MagicMock()
        ts_result.scalar_one.return_value = now
        mock_db.execute = AsyncMock(side_effect=[select_result, insert_result, ts_result])
        mock_db.flush = AsyncMock()

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db_session] = _override_db

        client = TestClient(app)

        token = jwt.encode(
            {"user_id": str(uuid.uuid4()), "role": "global_admin"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        with patch("app.modules.landing.router.write_audit_log", new_callable=AsyncMock):
            resp = client.put(
                "/api/v1/admin/privacy-policy",
                json={"content": "Some policy content"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Should NOT be 401 or 403 — role check passes
        assert resp.status_code not in (401, 403)
        # With mocked DB, should actually succeed
        assert resp.status_code == 200

    def test_salesperson_gets_403(self):
        """salesperson role is denied access to PUT /api/v1/admin/privacy-policy."""
        import jwt
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.middleware.auth import AuthMiddleware
        from app.modules.landing.router import admin_router

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")
        app.add_middleware(AuthMiddleware)

        client = TestClient(app)

        token = jwt.encode(
            {"user_id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "role": "salesperson"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        resp = client.put(
            "/api/v1/admin/privacy-policy",
            json={"content": "Some policy content"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 403

    def test_unauthenticated_gets_401(self):
        """Unauthenticated request gets 401."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.middleware.auth import AuthMiddleware
        from app.modules.landing.router import admin_router

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")
        app.add_middleware(AuthMiddleware)

        client = TestClient(app)

        resp = client.put(
            "/api/v1/admin/privacy-policy",
            json={"content": "Some policy content"},
        )

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pydantic validation tests (422 responses)
# ---------------------------------------------------------------------------

class TestDemoRequestValidation:
    """Test that invalid demo request payloads are rejected with 422.

    Uses a minimal FastAPI app with the public router to test Pydantic
    validation at the HTTP level.
    """

    @pytest.fixture
    def public_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.core.database import get_db_session
        from app.core.redis import get_redis
        from app.modules.landing.router import public_router

        app = FastAPI()
        app.include_router(public_router, prefix="/api/v1/public")

        # Override DB and Redis to avoid hitting real services
        async def _override_db():
            yield _mock_db()

        app.dependency_overrides[get_db_session] = _override_db
        app.dependency_overrides[get_redis] = lambda: _mock_redis()

        return TestClient(app)

    def test_missing_required_fields_returns_422(self, public_client):
        """POST with missing required fields returns 422.

        Validates: Requirement 18.5
        """
        # Missing all required fields
        resp = public_client.post("/api/v1/public/demo-request", json={})
        assert resp.status_code == 422

    def test_missing_email_returns_422(self, public_client):
        """POST with missing email returns 422."""
        resp = public_client.post(
            "/api/v1/public/demo-request",
            json={"full_name": "Test", "business_name": "Test"},
        )
        assert resp.status_code == 422

    def test_missing_full_name_returns_422(self, public_client):
        """POST with missing full_name returns 422."""
        resp = public_client.post(
            "/api/v1/public/demo-request",
            json={"business_name": "Test", "email": "a@b.com"},
        )
        assert resp.status_code == 422

    def test_missing_business_name_returns_422(self, public_client):
        """POST with missing business_name returns 422."""
        resp = public_client.post(
            "/api/v1/public/demo-request",
            json={"full_name": "Test", "email": "a@b.com"},
        )
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, public_client):
        """POST with invalid email format returns 422.

        Validates: Requirement 18.5
        """
        resp = public_client.post(
            "/api/v1/public/demo-request",
            json={
                "full_name": "Test User",
                "business_name": "Test Corp",
                "email": "not-a-valid-email",
            },
        )
        assert resp.status_code == 422

    def test_empty_full_name_returns_422(self, public_client):
        """POST with empty full_name returns 422."""
        resp = public_client.post(
            "/api/v1/public/demo-request",
            json={
                "full_name": "",
                "business_name": "Test Corp",
                "email": "a@b.com",
            },
        )
        assert resp.status_code == 422

    def test_empty_business_name_returns_422(self, public_client):
        """POST with empty business_name returns 422."""
        resp = public_client.post(
            "/api/v1/public/demo-request",
            json={
                "full_name": "Test",
                "business_name": "",
                "email": "a@b.com",
            },
        )
        assert resp.status_code == 422


class TestPrivacyPolicyUpdateValidation:
    """Test that invalid privacy policy update payloads are rejected with 422."""

    @pytest.fixture
    def admin_client(self):
        import jwt
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.core.database import get_db_session
        from app.middleware.auth import AuthMiddleware
        from app.modules.landing.router import admin_router

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")
        app.add_middleware(AuthMiddleware)

        # Override DB to avoid hitting real database
        async def _override_db():
            yield _mock_db()

        app.dependency_overrides[get_db_session] = _override_db

        token = jwt.encode(
            {"user_id": str(uuid.uuid4()), "role": "global_admin"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        client = TestClient(app)
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    def test_content_exceeding_100000_chars_returns_422(self, admin_client):
        """PUT with content exceeding 100000 characters returns 422.

        Validates: Requirement 21.3
        """
        resp = admin_client.put(
            "/api/v1/admin/privacy-policy",
            json={"content": "X" * 100001},
        )
        assert resp.status_code == 422

    def test_empty_content_returns_422(self, admin_client):
        """PUT with empty content returns 422."""
        resp = admin_client.put(
            "/api/v1/admin/privacy-policy",
            json={"content": ""},
        )
        assert resp.status_code == 422

    def test_missing_content_returns_422(self, admin_client):
        """PUT with missing content field returns 422."""
        resp = admin_client.put(
            "/api/v1/admin/privacy-policy",
            json={},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Public path registration test
# ---------------------------------------------------------------------------

class TestPublicPathRegistration:
    """Verify landing page public endpoints are accessible without auth."""

    def test_public_prefix_includes_public_routes(self):
        """The /api/v1/public/ prefix is registered as a public path prefix."""
        from app.middleware.auth import PUBLIC_PREFIXES

        assert any(
            "/api/v1/public/" == prefix or "/api/v1/public/".startswith(prefix)
            for prefix in PUBLIC_PREFIXES
        )


# ---------------------------------------------------------------------------
# Property-Based Tests (Hypothesis)
# ---------------------------------------------------------------------------

from hypothesis import given, settings as hyp_settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies for valid demo request form data
# ---------------------------------------------------------------------------

# Non-empty names (1–200 chars) using printable characters
_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "M", "N", "P", "Z")),
    min_size=1,
    max_size=200,
).filter(lambda s: len(s.strip()) > 0)

# Valid email addresses: local@domain.tld
_email_strategy = st.from_regex(
    r"[a-z][a-z0-9]{0,19}@[a-z]{2,10}\.[a-z]{2,5}",
    fullmatch=True,
)

# Optional phone numbers
_phone_strategy = st.one_of(
    st.none(),
    st.from_regex(r"\+?[0-9]{6,15}", fullmatch=True),
)

# Optional messages (up to 2000 chars)
_message_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "M", "N", "P", "Z")),
        min_size=1,
        max_size=500,
    ),
)


PBT_SETTINGS = hyp_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


class TestProperty4DemoFormSubmissionWithValidData:
    """# Feature: landing-page, Property 4: Demo form submission with valid data

    *For any* valid demo request form data (non-empty name, non-empty business
    name, valid email), submitting the form SHALL result in a 200 response with
    ``success: true``.

    **Validates: Requirements 18.5**
    """

    @given(
        full_name=_name_strategy,
        business_name=_name_strategy,
        email=_email_strategy,
        phone=_phone_strategy,
        message=_message_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_valid_demo_request_returns_200_success(
        self,
        full_name: str,
        business_name: str,
        email: str,
        phone: str | None,
        message: str | None,
    ):
        """Any valid form payload returns 200 with success=True.

        **Validates: Requirements 18.5**
        """
        from app.modules.landing.router import submit_demo_request

        payload = DemoRequestPayload(
            full_name=full_name,
            business_name=business_name,
            email=email,
            phone=phone,
            message=message,
            website=None,  # no honeypot — real submission
        )

        # Mock SMTP so no actual emails are sent
        mock_smtp_instance = MagicMock()
        mock_decrypt_value = json.dumps({
            "username": "user@example.com",
            "password": "secret",
        })

        provider = _make_email_provider()
        db = _mock_db()
        provider_result = _make_execute_result()
        provider_result.scalars.return_value.all.return_value = [provider]
        db.execute = AsyncMock(return_value=provider_result)

        # Mock Redis so rate limiting doesn't interfere
        redis = _mock_redis()
        request = _make_request()

        with patch("app.modules.landing.router.envelope_decrypt_str", return_value=mock_decrypt_value), \
             patch("app.modules.landing.router.smtplib") as mock_smtplib:
            mock_smtplib.SMTP.return_value = mock_smtp_instance
            result = await submit_demo_request(payload, request, db, redis)

        assert isinstance(result, DemoRequestResponse), (
            f"Expected DemoRequestResponse, got {type(result).__name__} "
            f"for payload: name={full_name!r}, business={business_name!r}, email={email!r}"
        )
        assert result.success is True, (
            f"Expected success=True for valid payload: "
            f"name={full_name!r}, business={business_name!r}, email={email!r}"
        )


class TestProperty5DemoRequestRateLimiting:
    """# Feature: landing-page, Property 5: Demo request rate limiting

    *For any* IP address, after 5 successful demo request submissions within a
    1-hour window, subsequent requests from that IP SHALL be rejected (rate
    limited).

    Generate sequences of N requests (N drawn from 1–20) from the same IP.
    Verify first 5 succeed, all subsequent return True (rate limited).

    **Validates: Requirements 18.8**
    """

    @given(n=st.integers(min_value=1, max_value=20))
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_rate_limit_kicks_in_after_5_requests(self, n: int):
        """For N requests from the same IP, first 5 pass and rest are blocked.

        **Validates: Requirements 18.8**
        """
        from app.modules.landing.router import _check_rate_limit, RATE_LIMIT_MAX

        # Track the call count to simulate Redis INCR returning 1, 2, 3, ...
        call_count = 0

        async def _mock_incr(key: str) -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        redis = _mock_redis()
        redis.incr = _mock_incr
        redis.expire = AsyncMock()

        client_ip = "192.168.1.100"

        for i in range(1, n + 1):
            result = await _check_rate_limit(redis, client_ip)

            if i <= RATE_LIMIT_MAX:
                assert result is False, (
                    f"Request {i} of {n} should NOT be rate limited "
                    f"(limit is {RATE_LIMIT_MAX}), but got rate_limited=True"
                )
            else:
                assert result is True, (
                    f"Request {i} of {n} SHOULD be rate limited "
                    f"(limit is {RATE_LIMIT_MAX}), but got rate_limited=False"
                )


class TestProperty6HoneypotBotRejection:
    """# Feature: landing-page, Property 6: Honeypot bot rejection

    *For any* demo request submission where the honeypot field (``website``) is
    non-empty, the backend SHALL return a 200 success response without sending
    an email, silently discarding the submission.

    **Validates: Requirements 18.11**
    """

    @given(
        honeypot_value=st.text(min_size=1, max_size=500).filter(lambda s: len(s.strip()) > 0),
        full_name=_name_strategy,
        business_name=_name_strategy,
        email=_email_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_honeypot_filled_returns_success_without_side_effects(
        self,
        honeypot_value: str,
        full_name: str,
        business_name: str,
        email: str,
    ):
        """Any non-empty honeypot value silently accepts without email or rate-limit.

        **Validates: Requirements 18.11**
        """
        from app.modules.landing.router import submit_demo_request

        payload = DemoRequestPayload(
            full_name=full_name,
            business_name=business_name,
            email=email,
            website=honeypot_value,  # honeypot filled — bot detected
        )

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()

        result = await submit_demo_request(payload, request, db, redis)

        # Must return a DemoRequestResponse (not a JSONResponse error)
        assert isinstance(result, DemoRequestResponse), (
            f"Expected DemoRequestResponse, got {type(result).__name__} "
            f"for honeypot={honeypot_value!r}"
        )
        assert result.success is True, (
            f"Expected success=True for honeypot submission, "
            f"got success={result.success} for honeypot={honeypot_value!r}"
        )

        # DB should NOT have been queried (no email provider lookup)
        db.execute.assert_not_called()

        # Redis should NOT have been called (no rate limit check)
        redis.incr.assert_not_called()
        redis.expire.assert_not_called()


class TestProperty8PrivacyPolicyContentRoundTrip:
    """# Feature: landing-page, Property 8: Privacy policy content round-trip

    *For any* valid Markdown string saved via ``PUT /api/v1/admin/privacy-policy``,
    subsequently fetching via ``GET /api/v1/public/privacy-policy`` SHALL return
    the same content string and a non-null ``last_updated`` timestamp.

    **Validates: Requirements 21.3**
    """

    @given(
        content=st.text(
            alphabet=st.characters(whitelist_categories=("L", "M", "N", "P", "Z", "S")),
            min_size=1,
            max_size=10000,
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_privacy_policy_round_trip_preserves_content(self, content: str):
        """Save content via update_privacy_policy, fetch via get_privacy_policy,
        verify exact match and non-null last_updated.

        **Validates: Requirements 21.3**
        """
        from app.modules.landing.router import update_privacy_policy, get_privacy_policy

        user_id = str(uuid.uuid4())
        now = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)

        # --- PUT: save the content ---
        put_db = _mock_db()
        # First execute: SELECT FOR UPDATE — no existing row
        select_result = _make_execute_result()
        select_result.first.return_value = None
        # Second execute: INSERT
        insert_result = MagicMock()
        # Third execute: SELECT updated_at
        ts_result = _make_execute_result(scalar_value=now)
        put_db.execute = AsyncMock(side_effect=[select_result, insert_result, ts_result])

        request = _make_request(user_id=user_id, role="global_admin")
        payload = PrivacyPolicyUpdatePayload(content=content)

        with patch("app.modules.landing.router.write_audit_log", new_callable=AsyncMock):
            put_response = await update_privacy_policy(payload, request, put_db)

        assert isinstance(put_response, PrivacyPolicyUpdateResponse), (
            f"Expected PrivacyPolicyUpdateResponse, got {type(put_response).__name__}"
        )
        assert put_response.success is True
        assert put_response.last_updated is not None, (
            "last_updated must be non-null after saving privacy policy"
        )

        # --- GET: fetch the content back ---
        # Simulate the DB returning exactly what was saved
        stored_value = {"content": content, "updated_by": user_id}
        get_db = _mock_db()
        get_result = _make_execute_result()
        get_result.first.return_value = (stored_value, now)
        get_db.execute = AsyncMock(return_value=get_result)

        get_response = await get_privacy_policy(get_db)

        assert isinstance(get_response, PrivacyPolicyResponse), (
            f"Expected PrivacyPolicyResponse, got {type(get_response).__name__}"
        )
        assert get_response.content == content, (
            f"Content mismatch: saved {content!r:.100} but got {get_response.content!r:.100}"
        )
        assert get_response.last_updated is not None, (
            "last_updated must be non-null when a custom policy exists"
        )

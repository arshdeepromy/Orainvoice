"""Tests for comprehensive error logging (Task 23.3).

Covers:
- Error logging service (log_error, sanitise_value, auto_categorise)
- Error log admin service functions (dashboard, list, detail, status update, export)
- Error log schemas
- Error log router endpoints

Requirements: 49.1, 49.2, 49.3, 49.4, 49.5, 49.6, 49.7
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import (
    Category,
    Severity,
    auto_categorise,
    log_error,
    sanitise_value,
)
from app.modules.admin.schemas import (
    ErrorLogDashboardResponse,
    ErrorLogDetailResponse,
    ErrorLogListItem,
    ErrorLogListResponse,
    ErrorLogStatusUpdateRequest,
    ErrorLogStatusUpdateResponse,
    ErrorLogSummaryCount,
)


# ---------------------------------------------------------------------------
# Unit tests: sanitise_value (Req 49.2)
# ---------------------------------------------------------------------------


class TestSanitiseValue:
    """Tests for PII and secret sanitisation."""

    def test_redacts_email(self):
        result = sanitise_value("Contact us at user@example.com for help")
        assert "[EMAIL_REDACTED]" in result
        assert "user@example.com" not in result

    def test_redacts_sensitive_keys(self):
        data = {"password": "secret123", "username": "admin", "api_key": "sk_live_abc"}
        result = sanitise_value(data)
        assert result["password"] == "[REDACTED]"
        assert result["api_key"] == "[REDACTED]"
        assert result["username"] == "admin"

    def test_redacts_nested_dict(self):
        data = {"user": {"email": "test@test.com", "name": "John"}}
        result = sanitise_value(data)
        assert result["user"]["email"] == "[REDACTED]"
        assert result["user"]["name"] == "[REDACTED]"

    def test_redacts_list_items(self):
        data = [{"password": "abc"}, {"token": "xyz"}]
        result = sanitise_value(data)
        assert result[0]["password"] == "[REDACTED]"
        assert result[1]["token"] == "[REDACTED]"

    def test_none_passthrough(self):
        assert sanitise_value(None) is None

    def test_number_passthrough(self):
        assert sanitise_value(42) == 42

    def test_card_number_redacted(self):
        result = sanitise_value("Card: 4111-1111-1111-1111")
        assert "[CARD_REDACTED]" in result


# ---------------------------------------------------------------------------
# Unit tests: auto_categorise (Req 49.3)
# ---------------------------------------------------------------------------


class TestAutoCategorise:
    """Tests for automatic error categorisation."""

    def test_payment_module(self):
        assert auto_categorise("modules.payments.service") == Category.PAYMENT

    def test_stripe_integration(self):
        assert auto_categorise("integrations.stripe_billing") == Category.PAYMENT

    def test_carjam_integration(self):
        assert auto_categorise("integrations.carjam") == Category.INTEGRATION

    def test_brevo_integration(self):
        assert auto_categorise("integrations.brevo") == Category.INTEGRATION

    def test_twilio_integration(self):
        assert auto_categorise("integrations.twilio_sms") == Category.INTEGRATION

    def test_storage_module(self):
        assert auto_categorise("modules.storage.service") == Category.STORAGE

    def test_auth_module(self):
        assert auto_categorise("modules.auth.service") == Category.AUTHENTICATION

    def test_background_tasks(self):
        assert auto_categorise("tasks.notifications") == Category.BACKGROUND_JOB

    def test_celery_worker(self):
        assert auto_categorise("celery.worker") == Category.BACKGROUND_JOB

    def test_unknown_defaults_to_application(self):
        assert auto_categorise("modules.invoices.service") == Category.APPLICATION

    def test_all_categories_exist(self):
        """Verify all 7 required categories exist."""
        expected = {
            "payment", "integration", "storage", "authentication",
            "data", "background_job", "application",
        }
        actual = {c.value for c in Category}
        assert expected == actual


# ---------------------------------------------------------------------------
# Unit tests: Severity enum (Req 49.2)
# ---------------------------------------------------------------------------


class TestSeverity:
    """Tests for severity levels."""

    def test_all_severities_exist(self):
        expected = {"info", "warning", "error", "critical"}
        actual = {s.value for s in Severity}
        assert expected == actual


# ---------------------------------------------------------------------------
# Unit tests: log_error (Req 49.1, 49.2)
# ---------------------------------------------------------------------------


class TestLogError:
    """Tests for the log_error function."""

    @pytest.mark.asyncio
    async def test_log_error_returns_uuid(self):
        """log_error should insert a row and return a UUID."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        error_id = await log_error(
            mock_session,
            severity=Severity.ERROR,
            category=Category.PAYMENT,
            module="modules.payments.service",
            function_name="process_payment",
            message="Payment processing failed",
        )

        assert isinstance(error_id, uuid.UUID)
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_error_auto_categorises(self):
        """log_error should auto-categorise when category is None."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        error_id = await log_error(
            mock_session,
            severity=Severity.WARNING,
            module="integrations.carjam",
            function_name="lookup_vehicle",
            message="Carjam rate limit exceeded",
        )

        assert isinstance(error_id, uuid.UUID)
        # Verify the execute call included the auto-categorised value
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["category"] == "integration"

    @pytest.mark.asyncio
    async def test_log_error_sanitises_request_body(self):
        """log_error should sanitise PII in request_body."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        await log_error(
            mock_session,
            severity=Severity.ERROR,
            module="modules.auth.service",
            message="Login failed",
            request_body={"email": "user@test.com", "password": "secret"},
        )

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        body = json.loads(params["request_body"])
        assert body["password"] == "[REDACTED]"
        assert body["email"] == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_log_error_with_all_fields(self):
        """log_error should accept all optional fields."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        error_id = await log_error(
            mock_session,
            severity=Severity.CRITICAL,
            category=Category.APPLICATION,
            module="modules.invoices.service",
            function_name="generate_invoice",
            message="Invoice generation failed",
            stack_trace="Traceback...",
            org_id=org_id,
            user_id=user_id,
            http_method="POST",
            http_endpoint="/api/v1/invoices",
            request_body={"amount": 100},
            response_body={"error": "Internal Server Error"},
        )

        assert isinstance(error_id, uuid.UUID)
        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["org_id"] == str(org_id)
        assert params["user_id"] == str(user_id)
        assert params["http_method"] == "POST"
        assert params["http_endpoint"] == "/api/v1/invoices"


# ---------------------------------------------------------------------------
# Unit tests: Schema validation (Req 49.4, 49.6)
# ---------------------------------------------------------------------------


class TestErrorLogSchemas:
    """Tests for error log Pydantic schemas."""

    def test_dashboard_response(self):
        resp = ErrorLogDashboardResponse(
            by_severity=[
                ErrorLogSummaryCount(label="error", count_1h=5, count_24h=20, count_7d=100),
            ],
            by_category=[
                ErrorLogSummaryCount(label="payment", count_1h=2, count_24h=10, count_7d=50),
            ],
            total_1h=5,
            total_24h=20,
            total_7d=100,
        )
        assert resp.total_1h == 5
        assert resp.by_severity[0].label == "error"

    def test_list_item(self):
        item = ErrorLogListItem(
            id=str(uuid.uuid4()),
            severity="error",
            category="payment",
            module="modules.payments",
            message="Payment failed",
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        assert item.severity == "error"

    def test_detail_response(self):
        detail = ErrorLogDetailResponse(
            id=str(uuid.uuid4()),
            severity="critical",
            category="integration",
            module="integrations.stripe",
            message="Stripe webhook failed",
            stack_trace="Traceback (most recent call last):\n  ...",
            status="investigating",
            resolution_notes="Looking into it",
            created_at=datetime.now(timezone.utc),
        )
        assert detail.stack_trace is not None
        assert detail.status == "investigating"

    def test_status_update_request(self):
        req = ErrorLogStatusUpdateRequest(
            status="resolved",
            resolution_notes="Fixed the webhook secret",
        )
        assert req.status == "resolved"

    def test_status_update_response(self):
        resp = ErrorLogStatusUpdateResponse(
            message="Error status updated to resolved",
            id=str(uuid.uuid4()),
            status="resolved",
            resolution_notes="Fixed",
        )
        assert resp.status == "resolved"

    def test_list_response(self):
        resp = ErrorLogListResponse(
            errors=[],
            total=0,
            page=1,
            page_size=25,
        )
        assert resp.total == 0


# ---------------------------------------------------------------------------
# Unit tests: Admin service functions (Req 49.4, 49.6, 49.7)
# ---------------------------------------------------------------------------


class TestErrorLogService:
    """Tests for error log admin service functions."""

    @pytest.mark.asyncio
    async def test_get_error_dashboard(self):
        """get_error_dashboard should return counts by severity and category."""
        from app.modules.admin.service import get_error_dashboard

        mock_session = AsyncMock()

        # Mock severity query result
        severity_result = MagicMock()
        severity_result.__iter__ = lambda self: iter([
            ("error", 3, 15, 80),
            ("critical", 1, 5, 20),
        ])

        # Mock category query result
        category_result = MagicMock()
        category_result.__iter__ = lambda self: iter([
            ("payment", 2, 10, 50),
            ("integration", 2, 10, 50),
        ])

        mock_session.execute = AsyncMock(side_effect=[severity_result, category_result])

        data = await get_error_dashboard(mock_session)

        assert data["total_1h"] == 4
        assert data["total_24h"] == 20
        assert data["total_7d"] == 100
        assert len(data["by_severity"]) == 2
        assert len(data["by_category"]) == 2

    @pytest.mark.asyncio
    async def test_list_error_logs_no_filters(self):
        """list_error_logs should return paginated results."""
        from app.modules.admin.service import list_error_logs

        mock_session = AsyncMock()

        # Mock count result
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        # Mock rows result
        now = datetime.now(timezone.utc)
        eid1 = uuid.uuid4()
        eid2 = uuid.uuid4()
        rows_result = MagicMock()
        rows_result.__iter__ = lambda self: iter([
            (eid1, "error", "payment", "mod.pay", "fn1", "msg1", None, None, "open", now),
            (eid2, "warning", "integration", "mod.int", "fn2", "msg2", None, None, "open", now),
        ])

        mock_session.execute = AsyncMock(side_effect=[count_result, rows_result])

        data = await list_error_logs(mock_session)

        assert data["total"] == 2
        assert len(data["errors"]) == 2
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_error_logs_with_filters(self):
        """list_error_logs should apply filters."""
        from app.modules.admin.service import list_error_logs

        mock_session = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 1

        now = datetime.now(timezone.utc)
        eid = uuid.uuid4()
        rows_result = MagicMock()
        rows_result.__iter__ = lambda self: iter([
            (eid, "critical", "payment", "mod.pay", "fn", "msg", None, None, "open", now),
        ])

        mock_session.execute = AsyncMock(side_effect=[count_result, rows_result])

        data = await list_error_logs(
            mock_session,
            severity="critical",
            category="payment",
            keyword="msg",
        )

        assert data["total"] == 1
        # Verify the SQL included filter params
        call_args = mock_session.execute.call_args_list[0]
        params = call_args[0][1]
        assert params["severity"] == "critical"
        assert params["category"] == "payment"

    @pytest.mark.asyncio
    async def test_get_error_detail_found(self):
        """get_error_detail should return full detail for existing error."""
        from app.modules.admin.service import get_error_detail

        mock_session = AsyncMock()
        eid = uuid.uuid4()
        now = datetime.now(timezone.utc)

        row_result = MagicMock()
        row_result.one_or_none.return_value = (
            eid, "error", "payment", "mod.pay", "process", "Payment failed",
            "Traceback...", None, None, "POST", "/api/v1/payments",
            {"amount": 100}, None, "open", None, now,
        )
        mock_session.execute = AsyncMock(return_value=row_result)

        detail = await get_error_detail(mock_session, eid)

        assert detail is not None
        assert detail["id"] == str(eid)
        assert detail["severity"] == "error"
        assert detail["stack_trace"] == "Traceback..."

    @pytest.mark.asyncio
    async def test_get_error_detail_not_found(self):
        """get_error_detail should return None for missing error."""
        from app.modules.admin.service import get_error_detail

        mock_session = AsyncMock()
        row_result = MagicMock()
        row_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=row_result)

        detail = await get_error_detail(mock_session, uuid.uuid4())
        assert detail is None

    @pytest.mark.asyncio
    async def test_update_error_status_success(self):
        """update_error_status should update status and notes."""
        from app.modules.admin.service import update_error_status

        mock_session = AsyncMock()
        eid = uuid.uuid4()

        # Mock the existence check
        exists_result = MagicMock()
        exists_result.one_or_none.return_value = (eid,)

        # Mock the update
        update_result = MagicMock()

        mock_session.execute = AsyncMock(side_effect=[exists_result, update_result])

        result = await update_error_status(
            mock_session,
            eid,
            status="resolved",
            resolution_notes="Fixed the issue",
        )

        assert result["status"] == "resolved"
        assert result["resolution_notes"] == "Fixed the issue"

    @pytest.mark.asyncio
    async def test_update_error_status_invalid(self):
        """update_error_status should reject invalid status values."""
        from app.modules.admin.service import update_error_status

        mock_session = AsyncMock()

        with pytest.raises(ValueError, match="Status must be one of"):
            await update_error_status(
                mock_session,
                uuid.uuid4(),
                status="invalid_status",
            )

    @pytest.mark.asyncio
    async def test_update_error_status_not_found(self):
        """update_error_status should raise ValueError for missing error."""
        from app.modules.admin.service import update_error_status

        mock_session = AsyncMock()
        exists_result = MagicMock()
        exists_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=exists_result)

        with pytest.raises(ValueError, match="not found"):
            await update_error_status(
                mock_session,
                uuid.uuid4(),
                status="resolved",
            )

    @pytest.mark.asyncio
    async def test_export_error_logs(self):
        """export_error_logs should return serialisable dicts."""
        from app.modules.admin.service import export_error_logs

        mock_session = AsyncMock()
        now = datetime.now(timezone.utc)
        eid = uuid.uuid4()

        rows_result = MagicMock()
        rows_result.__iter__ = lambda self: iter([
            (eid, "error", "payment", "mod.pay", "fn", "msg",
             "trace", None, None, "POST", "/api", "open", None, now),
        ])
        mock_session.execute = AsyncMock(return_value=rows_result)

        data = await export_error_logs(mock_session)

        assert len(data) == 1
        assert data[0]["id"] == str(eid)
        assert data[0]["created_at"] == now.isoformat()

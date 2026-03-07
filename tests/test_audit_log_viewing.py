"""Tests for audit log viewing endpoints (Task 23.5).

Covers:
- AuditLogEntry, AuditLogListParams, AuditLogListResponse schemas
- list_audit_logs service function (global + org-scoped, filters, pagination)
- GET /api/v1/admin/audit-log (Global_Admin)
- GET /api/v1/org/audit-log (Org_Admin)

Requirements: 51.1, 51.2, 51.4
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.schemas import (
    AuditLogEntry,
    AuditLogListParams,
    AuditLogListResponse,
)


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------


class TestAuditLogSchemas:
    """Validate Pydantic schema construction and defaults."""

    def test_audit_log_entry_full(self):
        entry = AuditLogEntry(
            id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            action="invoice.issued",
            entity_type="invoice",
            entity_id=str(uuid.uuid4()),
            before_value={"status": "draft"},
            after_value={"status": "issued"},
            ip_address="192.168.1.1",
            device_info="Mozilla/5.0",
            created_at="2024-01-15T10:30:00+00:00",
        )
        assert entry.action == "invoice.issued"
        assert entry.before_value == {"status": "draft"}
        assert entry.after_value == {"status": "issued"}

    def test_audit_log_entry_minimal(self):
        entry = AuditLogEntry(
            id=str(uuid.uuid4()),
            action="auth.login_success",
            entity_type="user",
            created_at="2024-01-15T10:30:00+00:00",
        )
        assert entry.org_id is None
        assert entry.before_value is None
        assert entry.ip_address is None

    def test_audit_log_list_params_defaults(self):
        params = AuditLogListParams()
        assert params.page == 1
        assert params.page_size == 50
        assert params.action is None
        assert params.entity_type is None

    def test_audit_log_list_params_custom(self):
        params = AuditLogListParams(
            page=3,
            page_size=25,
            action="invoice",
            entity_type="invoice",
            user_id=str(uuid.uuid4()),
            date_from="2024-01-01",
            date_to="2024-01-31",
        )
        assert params.page == 3
        assert params.page_size == 25
        assert params.action == "invoice"

    def test_audit_log_list_response(self):
        entry = AuditLogEntry(
            id=str(uuid.uuid4()),
            action="auth.login_success",
            entity_type="user",
            created_at="2024-01-15T10:30:00+00:00",
        )
        resp = AuditLogListResponse(
            entries=[entry],
            total=1,
            page=1,
            page_size=50,
        )
        assert resp.total == 1
        assert len(resp.entries) == 1
        assert resp.entries[0].action == "auth.login_success"



# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


def _make_audit_row(
    *,
    org_id=None,
    user_id=None,
    action="test.action",
    entity_type="test",
    entity_id=None,
    before_value=None,
    after_value=None,
    ip_address=None,
    device_info=None,
    created_at=None,
):
    """Build a fake DB row tuple matching the SELECT column order."""
    return (
        uuid.uuid4(),                                       # id
        uuid.UUID(org_id) if org_id else None,              # org_id
        uuid.UUID(user_id) if user_id else None,            # user_id
        action,                                              # action
        entity_type,                                         # entity_type
        uuid.UUID(entity_id) if entity_id else None,        # entity_id
        json.dumps(before_value) if before_value else None,  # before_value
        json.dumps(after_value) if after_value else None,    # after_value
        ip_address,                                          # ip_address
        device_info,                                         # device_info
        created_at or datetime.now(timezone.utc),            # created_at
    )


class TestListAuditLogs:
    """Tests for the list_audit_logs service function."""

    @pytest.mark.asyncio
    async def test_global_view_no_filters(self):
        """Global admin view returns all entries without org filter."""
        from app.modules.admin.service import list_audit_logs

        org1 = str(uuid.uuid4())
        org2 = str(uuid.uuid4())
        rows = [
            _make_audit_row(org_id=org1, action="invoice.issued", entity_type="invoice"),
            _make_audit_row(org_id=org2, action="auth.login_success", entity_type="user"),
        ]

        mock_db = AsyncMock()
        # First call: count query
        count_result = MagicMock()
        count_result.scalar.return_value = 2
        # Second call: data query
        data_result = MagicMock()
        data_result.__iter__ = lambda self: iter(rows)
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await list_audit_logs(mock_db, org_id=None, page=1, page_size=50)

        assert result["total"] == 2
        assert len(result["entries"]) == 2
        assert result["page"] == 1
        assert result["page_size"] == 50

    @pytest.mark.asyncio
    async def test_org_scoped_view(self):
        """Org admin view filters by org_id."""
        from app.modules.admin.service import list_audit_logs

        org_id = uuid.uuid4()
        rows = [
            _make_audit_row(
                org_id=str(org_id),
                action="customer.created",
                entity_type="customer",
                ip_address="10.0.0.1",
                device_info="Chrome/120",
            ),
        ]

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.__iter__ = lambda self: iter(rows)
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await list_audit_logs(mock_db, org_id=org_id, page=1, page_size=50)

        assert result["total"] == 1
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["action"] == "customer.created"
        assert entry["ip_address"] == "10.0.0.1"
        assert entry["device_info"] == "Chrome/120"

        # Verify org_id was passed in the SQL params
        call_args = mock_db.execute.call_args_list[0]
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("params", {})
        assert params.get("org_id") == str(org_id)

    @pytest.mark.asyncio
    async def test_filters_applied(self):
        """Verify action, entity_type, user_id, date filters are passed."""
        from app.modules.admin.service import list_audit_logs

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.__iter__ = lambda self: iter([])
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        uid = str(uuid.uuid4())
        result = await list_audit_logs(
            mock_db,
            org_id=None,
            action="invoice",
            entity_type="invoice",
            user_id=uid,
            date_from="2024-01-01",
            date_to="2024-01-31",
            page=2,
            page_size=10,
        )

        assert result["total"] == 0
        assert result["page"] == 2
        assert result["page_size"] == 10

        # Check that the count query received all filter params
        call_args = mock_db.execute.call_args_list[0]
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert params.get("action") == "%invoice%"
        assert params.get("entity_type") == "%invoice%"
        assert params.get("user_id") == uid
        assert params.get("date_from") == "2024-01-01"
        assert params.get("date_to") == "2024-01-31"

    @pytest.mark.asyncio
    async def test_pagination_offset(self):
        """Page 3 with page_size 10 should offset by 20."""
        from app.modules.admin.service import list_audit_logs

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 50
        data_result = MagicMock()
        data_result.__iter__ = lambda self: iter([])
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await list_audit_logs(mock_db, org_id=None, page=3, page_size=10)

        assert result["total"] == 50
        # Check offset in the data query params
        call_args = mock_db.execute.call_args_list[1]
        params = call_args[0][1] if len(call_args[0]) > 1 else {}
        assert params.get("offset") == 20
        assert params.get("limit") == 10

    @pytest.mark.asyncio
    async def test_entry_fields_complete(self):
        """Each entry should contain all audit log fields."""
        from app.modules.admin.service import list_audit_logs

        eid = str(uuid.uuid4())
        uid = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        rows = [
            _make_audit_row(
                org_id=oid,
                user_id=uid,
                action="plan.updated",
                entity_type="plan",
                entity_id=eid,
                before_value={"name": "Basic"},
                after_value={"name": "Pro"},
                ip_address="203.0.113.5",
                device_info="Safari/17",
                created_at=ts,
            ),
        ]

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.__iter__ = lambda self: iter(rows)
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await list_audit_logs(mock_db, org_id=None)
        entry = result["entries"][0]

        assert entry["org_id"] == oid
        assert entry["user_id"] == uid
        assert entry["action"] == "plan.updated"
        assert entry["entity_type"] == "plan"
        assert entry["entity_id"] == eid
        assert entry["before_value"] == {"name": "Basic"}
        assert entry["after_value"] == {"name": "Pro"}
        assert entry["ip_address"] == "203.0.113.5"
        assert entry["device_info"] == "Safari/17"
        assert "2024-06-15" in entry["created_at"]

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """Empty audit log returns zero entries."""
        from app.modules.admin.service import list_audit_logs

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.__iter__ = lambda self: iter([])
        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await list_audit_logs(mock_db, org_id=None)
        assert result["total"] == 0
        assert result["entries"] == []

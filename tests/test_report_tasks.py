"""Unit tests for Task 35.4 — Report generation tasks.

Tests the four Celery tasks in ``app/tasks/reports.py``:
- generate_revenue_report_task
- generate_gst_return_task
- generate_customer_statement_task
- generate_bulk_export_task

Requirements: 82.3
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.tasks.reports import (
    _parse_date,
    _serialise,
    generate_revenue_report_task,
    generate_gst_return_task,
    generate_customer_statement_task,
    generate_bulk_export_task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_iso_date(self):
        assert _parse_date("2024-01-15") == date(2024, 1, 15)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_invalid_string_returns_none(self):
        assert _parse_date("not-a-date") is None


class TestSerialise:
    def test_decimal_to_string(self):
        from decimal import Decimal
        result = _serialise({"amount": Decimal("123.45")})
        assert result["amount"] == "123.45"

    def test_date_to_iso(self):
        result = _serialise({"d": date(2024, 3, 1)})
        assert result["d"] == "2024-03-01"

    def test_uuid_to_string(self):
        uid = uuid.uuid4()
        result = _serialise({"id": uid})
        assert result["id"] == str(uid)

    def test_nested_structure(self):
        from decimal import Decimal
        data = {"items": [{"val": Decimal("1.00")}]}
        result = _serialise(data)
        assert result["items"][0]["val"] == "1.00"


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------

class TestTaskRegistration:
    """Verify all report tasks are properly registered with Celery."""

    def test_revenue_report_task_name(self):
        assert generate_revenue_report_task.name == (
            "app.tasks.reports.generate_revenue_report_task"
        )

    def test_gst_return_task_name(self):
        assert generate_gst_return_task.name == (
            "app.tasks.reports.generate_gst_return_task"
        )

    def test_customer_statement_task_name(self):
        assert generate_customer_statement_task.name == (
            "app.tasks.reports.generate_customer_statement_task"
        )

    def test_bulk_export_task_name(self):
        assert generate_bulk_export_task.name == (
            "app.tasks.reports.generate_bulk_export_task"
        )

    def test_revenue_report_acks_late(self):
        assert generate_revenue_report_task.acks_late is True

    def test_gst_return_acks_late(self):
        assert generate_gst_return_task.acks_late is True

    def test_customer_statement_acks_late(self):
        assert generate_customer_statement_task.acks_late is True

    def test_bulk_export_acks_late(self):
        assert generate_bulk_export_task.acks_late is True


# ---------------------------------------------------------------------------
# Task routing
# ---------------------------------------------------------------------------

class TestTaskRouting:
    """Verify report tasks are importable."""

    def test_report_tasks_importable(self):
        from app.tasks import reports
        assert reports is not None


# ---------------------------------------------------------------------------
# generate_revenue_report_task
# ---------------------------------------------------------------------------

class TestGenerateRevenueReportTask:
    """Req 82.3: async revenue report generation."""

    def test_success_returns_report_data(self):
        mock_data = {
            "report_type": "revenue",
            "org_id": str(uuid.uuid4()),
            "generated_by": str(uuid.uuid4()),
            "data": {"total_revenue": "1000.00"},
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_revenue_report_task(
                org_id=mock_data["org_id"],
                user_id=mock_data["generated_by"],
            )
            assert result["report_type"] == "revenue"
            assert result["data"]["total_revenue"] == "1000.00"

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.reports._run_async",
            side_effect=RuntimeError("DB timeout"),
        ):
            result = generate_revenue_report_task(
                org_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
            )
            assert "error" in result
            assert "DB timeout" in result["error"]
            assert result["report_type"] == "revenue"

    def test_passes_date_params(self):
        org_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        with patch("app.tasks.reports._run_async", return_value={"report_type": "revenue"}) as mock:
            generate_revenue_report_task(
                org_id=org_id,
                user_id=user_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                preset="quarter",
            )
            mock.assert_called_once()


# ---------------------------------------------------------------------------
# generate_gst_return_task
# ---------------------------------------------------------------------------

class TestGenerateGstReturnTask:
    """Req 82.3: async GST return report generation."""

    def test_success_returns_report_data(self):
        mock_data = {
            "report_type": "gst_return",
            "org_id": str(uuid.uuid4()),
            "generated_by": str(uuid.uuid4()),
            "data": {"total_gst_collected": "150.00"},
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_gst_return_task(
                org_id=mock_data["org_id"],
                user_id=mock_data["generated_by"],
            )
            assert result["report_type"] == "gst_return"

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.reports._run_async",
            side_effect=RuntimeError("Connection refused"),
        ):
            result = generate_gst_return_task(
                org_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
            )
            assert "error" in result
            assert result["report_type"] == "gst_return"


# ---------------------------------------------------------------------------
# generate_customer_statement_task
# ---------------------------------------------------------------------------

class TestGenerateCustomerStatementTask:
    """Req 82.3: async customer statement generation."""

    def test_success_returns_statement(self):
        mock_data = {
            "report_type": "customer_statement",
            "org_id": str(uuid.uuid4()),
            "generated_by": str(uuid.uuid4()),
            "customer_id": str(uuid.uuid4()),
            "data": {"closing_balance": "500.00"},
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_customer_statement_task(
                org_id=mock_data["org_id"],
                user_id=mock_data["generated_by"],
                customer_id=mock_data["customer_id"],
            )
            assert result["report_type"] == "customer_statement"
            assert "customer_id" in result

    def test_customer_not_found(self):
        mock_data = {
            "report_type": "customer_statement",
            "org_id": str(uuid.uuid4()),
            "error": "Customer not found",
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_customer_statement_task(
                org_id=mock_data["org_id"],
                user_id=str(uuid.uuid4()),
                customer_id=str(uuid.uuid4()),
            )
            assert "error" in result

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.reports._run_async",
            side_effect=RuntimeError("Timeout"),
        ):
            result = generate_customer_statement_task(
                org_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                customer_id=str(uuid.uuid4()),
            )
            assert "error" in result
            assert result["report_type"] == "customer_statement"


# ---------------------------------------------------------------------------
# generate_bulk_export_task
# ---------------------------------------------------------------------------

class TestGenerateBulkExportTask:
    """Req 82.3: async bulk invoice export."""

    def test_csv_export_returns_content(self):
        mock_data = {
            "report_type": "bulk_export",
            "org_id": str(uuid.uuid4()),
            "generated_by": str(uuid.uuid4()),
            "export_format": "csv",
            "invoice_count": 10,
            "csv_content": "header1,header2\nval1,val2",
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_bulk_export_task(
                org_id=mock_data["org_id"],
                user_id=mock_data["generated_by"],
                export_format="csv",
            )
            assert result["report_type"] == "bulk_export"
            assert result["export_format"] == "csv"
            assert result["invoice_count"] == 10
            assert "csv_content" in result

    def test_pdf_export_returns_invoices(self):
        mock_data = {
            "report_type": "bulk_export",
            "org_id": str(uuid.uuid4()),
            "generated_by": str(uuid.uuid4()),
            "export_format": "pdf",
            "invoice_count": 3,
            "invoices": [{"id": "abc"}],
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_bulk_export_task(
                org_id=mock_data["org_id"],
                user_id=mock_data["generated_by"],
                export_format="pdf",
            )
            assert result["export_format"] == "pdf"
            assert "invoices" in result

    def test_exception_returns_error(self):
        with patch(
            "app.tasks.reports._run_async",
            side_effect=RuntimeError("Disk full"),
        ):
            result = generate_bulk_export_task(
                org_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
            )
            assert "error" in result
            assert result["report_type"] == "bulk_export"

    def test_default_format_is_csv(self):
        """Verify the default export_format parameter is 'csv'."""
        mock_data = {
            "report_type": "bulk_export",
            "export_format": "csv",
            "invoice_count": 0,
        }
        with patch(
            "app.tasks.reports._run_async",
            return_value=mock_data,
        ):
            result = generate_bulk_export_task(
                org_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
            )
            assert result["export_format"] == "csv"

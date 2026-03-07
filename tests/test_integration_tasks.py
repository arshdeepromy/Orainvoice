"""Unit tests for Task 35.5 — Accounting sync integration tasks.

Tests the four Celery tasks in ``app/tasks/integrations.py``:
- sync_invoice_to_accounting_task
- sync_payment_to_accounting_task
- sync_credit_note_to_accounting_task
- retry_failed_sync_task

Requirements: 68.3, 68.4, 68.5, 68.6
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.tasks.integrations import (
    VALID_PROVIDERS,
    sync_invoice_to_accounting_task,
    sync_payment_to_accounting_task,
    sync_credit_note_to_accounting_task,
    retry_failed_sync_task,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_ID = str(uuid.uuid4())
ENTITY_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


class TestTaskRegistration:
    """Verify all integration tasks are properly registered with Celery."""

    def test_sync_invoice_task_name(self):
        assert sync_invoice_to_accounting_task.name == (
            "app.tasks.integrations.sync_invoice_to_accounting_task"
        )

    def test_sync_payment_task_name(self):
        assert sync_payment_to_accounting_task.name == (
            "app.tasks.integrations.sync_payment_to_accounting_task"
        )

    def test_sync_credit_note_task_name(self):
        assert sync_credit_note_to_accounting_task.name == (
            "app.tasks.integrations.sync_credit_note_to_accounting_task"
        )

    def test_retry_failed_sync_task_name(self):
        assert retry_failed_sync_task.name == (
            "app.tasks.integrations.retry_failed_sync_task"
        )

    def test_sync_invoice_acks_late(self):
        assert sync_invoice_to_accounting_task.acks_late is True

    def test_sync_payment_acks_late(self):
        assert sync_payment_to_accounting_task.acks_late is True

    def test_sync_credit_note_acks_late(self):
        assert sync_credit_note_to_accounting_task.acks_late is True

    def test_retry_failed_sync_acks_late(self):
        assert retry_failed_sync_task.acks_late is True


# ---------------------------------------------------------------------------
# Task routing
# ---------------------------------------------------------------------------


class TestTaskRouting:
    """Verify integration tasks route to the 'integrations' queue."""

    def test_integrations_queue_exists(self):
        from app.tasks import QUEUE_NAMES
        assert "integrations" in QUEUE_NAMES

    def test_integrations_route_configured(self):
        from app.tasks import TASK_ROUTES
        assert "app.tasks.integrations.*" in TASK_ROUTES
        assert TASK_ROUTES["app.tasks.integrations.*"]["queue"] == "integrations"


# ---------------------------------------------------------------------------
# Valid providers
# ---------------------------------------------------------------------------


class TestValidProviders:
    def test_xero_is_valid(self):
        assert "xero" in VALID_PROVIDERS

    def test_myob_is_valid(self):
        assert "myob" in VALID_PROVIDERS


# ---------------------------------------------------------------------------
# sync_invoice_to_accounting_task (Req 68.3)
# ---------------------------------------------------------------------------


class TestSyncInvoiceTask:
    """Req 68.3: sync invoice to Xero or MYOB."""

    def test_invalid_provider_returns_error(self):
        result = sync_invoice_to_accounting_task(
            org_id=ORG_ID, entity_id=ENTITY_ID, provider="quickbooks",
        )
        assert "error" in result
        assert "Invalid provider" in result["error"]

    def test_success_xero(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "xero",
            "entity_type": "invoice",
            "entity_id": ENTITY_ID,
            "status": "synced",
            "external_id": "xero-inv-123",
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_invoice_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="xero",
            )
            assert result["status"] == "synced"
            assert result["provider"] == "xero"
            assert result["entity_type"] == "invoice"

    def test_success_myob(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "myob",
            "entity_type": "invoice",
            "entity_id": ENTITY_ID,
            "status": "synced",
            "external_id": "myob-loc-123",
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_invoice_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="myob",
            )
            assert result["status"] == "synced"
            assert result["provider"] == "myob"

    def test_sync_failure_logged(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "xero",
            "entity_type": "invoice",
            "entity_id": ENTITY_ID,
            "status": "failed",
            "external_id": None,
            "error_message": "No active xero connection",
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_invoice_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="xero",
            )
            assert result["status"] == "failed"
            assert result["error_message"] is not None

    def test_passes_invoice_data(self):
        mock_result = {"status": "synced", "entity_type": "invoice"}
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ) as mock_run:
            sync_invoice_to_accounting_task(
                org_id=ORG_ID,
                entity_id=ENTITY_ID,
                provider="xero",
                invoice_data={"customer_name": "Test Co"},
            )
            mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# sync_payment_to_accounting_task (Req 68.4)
# ---------------------------------------------------------------------------


class TestSyncPaymentTask:
    """Req 68.4: sync payment to Xero or MYOB."""

    def test_invalid_provider_returns_error(self):
        result = sync_payment_to_accounting_task(
            org_id=ORG_ID, entity_id=ENTITY_ID, provider="sage",
        )
        assert "error" in result

    def test_success_xero(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "xero",
            "entity_type": "payment",
            "entity_id": ENTITY_ID,
            "status": "synced",
            "external_id": "xero-pay-456",
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_payment_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="xero",
            )
            assert result["status"] == "synced"
            assert result["entity_type"] == "payment"

    def test_success_myob(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "myob",
            "entity_type": "payment",
            "entity_id": ENTITY_ID,
            "status": "synced",
            "external_id": None,
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_payment_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="myob",
            )
            assert result["status"] == "synced"

    def test_sync_failure_returns_failed_status(self):
        mock_result = {
            "status": "failed",
            "error_message": "Token expired",
            "entity_type": "payment",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_payment_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="xero",
            )
            assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# sync_credit_note_to_accounting_task (Req 68.5)
# ---------------------------------------------------------------------------


class TestSyncCreditNoteTask:
    """Req 68.5: sync credit note to Xero or MYOB."""

    def test_invalid_provider_returns_error(self):
        result = sync_credit_note_to_accounting_task(
            org_id=ORG_ID, entity_id=ENTITY_ID, provider="invalid",
        )
        assert "error" in result

    def test_success_xero(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "xero",
            "entity_type": "credit_note",
            "entity_id": ENTITY_ID,
            "status": "synced",
            "external_id": "xero-cn-789",
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_credit_note_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="xero",
            )
            assert result["status"] == "synced"
            assert result["entity_type"] == "credit_note"

    def test_success_myob(self):
        mock_result = {
            "id": str(uuid.uuid4()),
            "provider": "myob",
            "entity_type": "credit_note",
            "entity_id": ENTITY_ID,
            "status": "synced",
            "external_id": None,
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_credit_note_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="myob",
            )
            assert result["status"] == "synced"

    def test_sync_failure_returns_failed_status(self):
        mock_result = {
            "status": "failed",
            "error_message": "Connection refused",
            "entity_type": "credit_note",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = sync_credit_note_to_accounting_task(
                org_id=ORG_ID, entity_id=ENTITY_ID, provider="myob",
            )
            assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# retry_failed_sync_task (Req 68.6)
# ---------------------------------------------------------------------------


class TestRetryFailedSyncTask:
    """Req 68.6: retry failed sync operations."""

    def test_invalid_provider_returns_error(self):
        result = retry_failed_sync_task(
            org_id=ORG_ID, provider="invalid",
        )
        assert "error" in result

    def test_success_xero(self):
        mock_result = {
            "provider": "xero",
            "synced": 3,
            "failed": 1,
            "message": "Retried 4 failed syncs: 3 succeeded, 1 failed",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = retry_failed_sync_task(
                org_id=ORG_ID, provider="xero",
            )
            assert result["synced"] == 3
            assert result["failed"] == 1

    def test_success_myob(self):
        mock_result = {
            "provider": "myob",
            "synced": 0,
            "failed": 0,
            "message": "Retried 0 failed syncs: 0 succeeded, 0 failed",
        }
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = retry_failed_sync_task(
                org_id=ORG_ID, provider="myob",
            )
            assert result["synced"] == 0
            assert result["failed"] == 0

    def test_no_failed_entries(self):
        mock_result = {"provider": "xero", "synced": 0, "failed": 0, "message": ""}
        with patch(
            "app.tasks.integrations._run_async",
            return_value=mock_result,
        ):
            result = retry_failed_sync_task(
                org_id=ORG_ID, provider="xero",
            )
            assert result["synced"] == 0

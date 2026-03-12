"""Unit tests for accounting sync integration tasks.

Tests the four async tasks in ``app/tasks/integrations.py``.

Requirements: 68.3, 68.4, 68.5, 68.6
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.integrations import (
    VALID_PROVIDERS,
    sync_invoice_to_accounting_task,
    sync_payment_to_accounting_task,
    sync_credit_note_to_accounting_task,
    retry_failed_sync_task,
)

ORG_ID = str(uuid.uuid4())
ENTITY_ID = str(uuid.uuid4())


class TestTaskImportability:
    def test_sync_invoice_task_callable(self):
        assert callable(sync_invoice_to_accounting_task)

    def test_sync_payment_task_callable(self):
        assert callable(sync_payment_to_accounting_task)

    def test_sync_credit_note_task_callable(self):
        assert callable(sync_credit_note_to_accounting_task)

    def test_retry_failed_sync_task_callable(self):
        assert callable(retry_failed_sync_task)


class TestTaskRouting:
    def test_integration_tasks_importable(self):
        from app.tasks import integrations
        assert integrations is not None


class TestValidProviders:
    def test_xero_is_valid(self):
        assert "xero" in VALID_PROVIDERS

    def test_myob_is_valid(self):
        assert "myob" in VALID_PROVIDERS

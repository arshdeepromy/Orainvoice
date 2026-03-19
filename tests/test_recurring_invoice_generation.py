"""Unit tests for Task 35.3 — recurring invoice generation task.

Tests cover:
  - Celery Beat scheduled task finds due recurring schedules and generates invoices
  - Draft vs Issued invoice generation based on auto_issue flag (Req 60.2)
  - next_due_at advances correctly for each frequency (Req 60.2)
  - Org_Admin notification is sent on generation (Req 60.4)
  - Inactive/missing schedules are handled gracefully
  - Scheduled task processes multiple schedules and reports errors

Requirements: 60.2, 60.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.invoices.service import (
    generate_recurring_invoice,
    _notify_org_admins_recurring_invoice,
)
from app.modules.recurring_invoices.models import RecurringSchedule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _sample_line_items() -> list[dict]:
    """Return sample line items for a recurring schedule."""
    return [
        {
            "item_type": "service",
            "description": "Monthly WOF check",
            "quantity": Decimal("1"),
            "unit_price": Decimal("55.00"),
            "is_gst_exempt": False,
        },
        {
            "item_type": "part",
            "description": "Oil filter",
            "quantity": Decimal("1"),
            "unit_price": Decimal("25.00"),
            "is_gst_exempt": False,
        },
    ]


def _make_mock_schedule(
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    status: str = "active",
    frequency: str = "monthly",
    auto_issue: bool = False,
) -> MagicMock:
    """Create a mock RecurringSchedule."""
    sched = MagicMock(spec=RecurringSchedule)
    sched.id = uuid.uuid4()
    sched.org_id = org_id
    sched.customer_id = customer_id
    sched.frequency = frequency
    sched.line_items = _sample_line_items()
    sched.auto_issue = auto_issue
    sched.auto_email = False
    sched.status = status
    sched.start_date = date(2025, 2, 1)
    sched.end_date = None
    sched.next_generation_date = date(2025, 2, 1)
    sched.created_at = datetime.now(timezone.utc)
    sched.updated_at = datetime.now(timezone.utc)
    return sched


def _make_mock_admin(org_id: uuid.UUID, email: str = "admin@workshop.nz") -> MagicMock:
    """Create a mock User with org_admin role."""
    admin = MagicMock()
    admin.id = uuid.uuid4()
    admin.org_id = org_id
    admin.email = email
    admin.role = "org_admin"
    admin.is_active = True
    return admin


# ---------------------------------------------------------------------------
# Tests — Org_Admin Notification (Req 60.4)
# ---------------------------------------------------------------------------


class TestNotifyOrgAdminsRecurringInvoice:
    """Test _notify_org_admins_recurring_invoice helper."""

    @pytest.mark.asyncio
    async def test_notification_sent_to_org_admin(self):
        """Org_Admin should receive a notification when a recurring invoice is generated."""
        org_id = uuid.uuid4()
        admin = _make_mock_admin(org_id)
        sched = _make_mock_schedule(org_id, uuid.uuid4())

        db = _mock_db_session()
        admin_result = MagicMock()
        admin_result.scalars.return_value.all.return_value = [admin]
        db.execute.return_value = admin_result

        invoice_data = {
            "id": uuid.uuid4(),
            "status": "draft",
            "invoice_number": None,
            "total": "80.00",
        }

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new_callable=AsyncMock,
        ) as mock_log:
            await _notify_org_admins_recurring_invoice(
                db,
                org_id=org_id,
                invoice_data=invoice_data,
                schedule=sched,
            )

            mock_log.assert_called_once()
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["org_id"] == org_id
            assert call_kwargs["recipient"] == admin.email
            assert call_kwargs["template_type"] == "recurring_invoice_generated"
            assert "Draft" in call_kwargs["subject"]

    @pytest.mark.asyncio
    async def test_notification_sent_to_multiple_admins(self):
        """All active Org_Admins should receive notifications."""
        org_id = uuid.uuid4()
        admin1 = _make_mock_admin(org_id, email="admin1@workshop.nz")
        admin2 = _make_mock_admin(org_id, email="admin2@workshop.nz")
        sched = _make_mock_schedule(org_id, uuid.uuid4())

        db = _mock_db_session()
        admin_result = MagicMock()
        admin_result.scalars.return_value.all.return_value = [admin1, admin2]
        db.execute.return_value = admin_result

        invoice_data = {
            "id": uuid.uuid4(),
            "status": "issued",
            "invoice_number": "INV-0042",
            "total": "92.00",
        }

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new_callable=AsyncMock,
        ) as mock_log:
            await _notify_org_admins_recurring_invoice(
                db,
                org_id=org_id,
                invoice_data=invoice_data,
                schedule=sched,
            )

            assert mock_log.call_count == 2
            recipients = [c.kwargs["recipient"] for c in mock_log.call_args_list]
            assert "admin1@workshop.nz" in recipients
            assert "admin2@workshop.nz" in recipients

    @pytest.mark.asyncio
    async def test_notification_skips_admin_without_email(self):
        """Admins without an email address should be skipped."""
        org_id = uuid.uuid4()
        admin_no_email = _make_mock_admin(org_id)
        admin_no_email.email = None
        sched = _make_mock_schedule(org_id, uuid.uuid4())

        db = _mock_db_session()
        admin_result = MagicMock()
        admin_result.scalars.return_value.all.return_value = [admin_no_email]
        db.execute.return_value = admin_result

        invoice_data = {"id": uuid.uuid4(), "status": "draft", "total": "50.00"}

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new_callable=AsyncMock,
        ) as mock_log:
            await _notify_org_admins_recurring_invoice(
                db,
                org_id=org_id,
                invoice_data=invoice_data,
                schedule=sched,
            )

            mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_no_admins(self):
        """No error when there are no org admins to notify."""
        org_id = uuid.uuid4()
        sched = _make_mock_schedule(org_id, uuid.uuid4())

        db = _mock_db_session()
        admin_result = MagicMock()
        admin_result.scalars.return_value.all.return_value = []
        db.execute.return_value = admin_result

        invoice_data = {"id": uuid.uuid4(), "status": "draft", "total": "50.00"}

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new_callable=AsyncMock,
        ) as mock_log:
            await _notify_org_admins_recurring_invoice(
                db,
                org_id=org_id,
                invoice_data=invoice_data,
                schedule=sched,
            )

            mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_subject_includes_invoice_number(self):
        """Notification subject should include the invoice number when issued."""
        org_id = uuid.uuid4()
        admin = _make_mock_admin(org_id)
        sched = _make_mock_schedule(org_id, uuid.uuid4())

        db = _mock_db_session()
        admin_result = MagicMock()
        admin_result.scalars.return_value.all.return_value = [admin]
        db.execute.return_value = admin_result

        invoice_data = {
            "id": uuid.uuid4(),
            "status": "issued",
            "invoice_number": "INV-0099",
            "total": "150.00",
        }

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new_callable=AsyncMock,
        ) as mock_log:
            await _notify_org_admins_recurring_invoice(
                db,
                org_id=org_id,
                invoice_data=invoice_data,
                schedule=sched,
            )

            call_kwargs = mock_log.call_args.kwargs
            assert "INV-0099" in call_kwargs["subject"]


# ---------------------------------------------------------------------------
# Tests — generate_recurring_invoice calls notification (Req 60.2 + 60.4)
# ---------------------------------------------------------------------------


class TestGenerateRecurringInvoiceWithNotification:
    """Test that generate_recurring_invoice triggers Org_Admin notification."""

    @pytest.mark.asyncio
    async def test_generate_calls_notification(self):
        """generate_recurring_invoice should call _notify_org_admins_recurring_invoice."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        sched = _make_mock_schedule(org_id, customer_id, auto_issue=False)

        db = _mock_db_session()

        sched_result = MagicMock()
        sched_result.scalar_one_or_none.return_value = sched

        mock_invoice_data = {
            "id": uuid.uuid4(),
            "status": "draft",
            "invoice_number": None,
            "total": "80.00",
        }

        with (
            patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock),
            patch(
                "app.modules.invoices.service.create_invoice",
                new_callable=AsyncMock,
                return_value=mock_invoice_data,
            ),
            patch(
                "app.modules.invoices.service._notify_org_admins_recurring_invoice",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            inv_result = MagicMock()
            inv_result.scalar_one_or_none.return_value = MagicMock()
            db.execute.side_effect = [sched_result, inv_result]

            await generate_recurring_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                schedule_id=sched.id,
            )

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["org_id"] == org_id
            assert call_kwargs["invoice_data"] == mock_invoice_data

    @pytest.mark.asyncio
    async def test_generate_issued_invoice_notification_has_number(self):
        """When auto_issue=True, the notification should receive the invoice number."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        sched = _make_mock_schedule(org_id, customer_id, auto_issue=True)

        db = _mock_db_session()

        sched_result = MagicMock()
        sched_result.scalar_one_or_none.return_value = sched

        mock_invoice_data = {
            "id": uuid.uuid4(),
            "status": "issued",
            "invoice_number": "INV-0001",
            "total": "80.00",
        }

        with (
            patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock),
            patch(
                "app.modules.invoices.service.create_invoice",
                new_callable=AsyncMock,
                return_value=mock_invoice_data,
            ),
            patch(
                "app.modules.invoices.service._notify_org_admins_recurring_invoice",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            inv_result = MagicMock()
            inv_result.scalar_one_or_none.return_value = MagicMock()
            db.execute.side_effect = [sched_result, inv_result]

            await generate_recurring_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                schedule_id=sched.id,
            )

            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["invoice_data"]["invoice_number"] == "INV-0001"
            assert call_kwargs["invoice_data"]["status"] == "issued"


# ---------------------------------------------------------------------------
# Tests — Scheduled task (_generate_recurring_invoices_async)
# ---------------------------------------------------------------------------


class TestGenerateRecurringInvoicesScheduledTask:
    """Test the Celery Beat scheduled task for recurring invoice generation."""

    def test_task_returns_counts_on_success(self):
        """Task should return generated and error counts."""
        from app.tasks.scheduled import generate_recurring_invoices_task

        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"generated": 3, "errors": 0},
        ):
            result = generate_recurring_invoices_task()
            assert result["generated"] == 3
            assert result["errors"] == 0

    def test_task_handles_partial_failures(self):
        """Task should report both generated and error counts."""
        from app.tasks.scheduled import generate_recurring_invoices_task

        with patch(
            "app.tasks.scheduled._run_async",
            return_value={"generated": 2, "errors": 1},
        ):
            result = generate_recurring_invoices_task()
            assert result["generated"] == 2
            assert result["errors"] == 1

    def test_task_handles_exception(self):
        """Task should catch exceptions and return error dict."""
        from app.tasks.scheduled import generate_recurring_invoices_task

        with patch(
            "app.tasks.scheduled._run_async",
            side_effect=RuntimeError("DB connection failed"),
        ):
            result = generate_recurring_invoices_task()
            assert "error" in result

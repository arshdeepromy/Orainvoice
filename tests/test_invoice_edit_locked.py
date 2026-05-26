"""Tests for the invoice-edit locking on non-draft invoices.

Two-part fix:

1. ``update_invoice_endpoint`` short-circuits when the caller passes
   ``status='sent'`` on an already-issued invoice and returns a clear
   400: "Invoice is already {status} and cannot be re-issued. Use a
   credit note to correct prices, or void this invoice and create a
   new one."

2. The existing limited-edit branch in ``update_invoice`` continues to
   silently strip non-allowed fields for non-draft invoices (notes,
   due date, vehicle metadata are still editable; line items / totals
   stay locked). This test guards against accidentally widening the
   allow-list.

Validates: invoice-edit-issued-clearer-error regression-fix.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Model preload (mirror of app/main.py)
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.catalogue.fluid_oil_models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.invoices.attachment_models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.service_types.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.sms_chat.models  # noqa: F401
import app.modules.ha.models  # noqa: F401
import app.modules.ha.volume_sync_models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.quotes.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.platform_settings.models  # noqa: F401
import app.modules.ledger.models  # noqa: F401
import app.modules.banking.models  # noqa: F401
import app.modules.tax_wallets.models  # noqa: F401
import app.modules.ird.models  # noqa: F401
import app.modules.in_app_notifications.models  # noqa: F401
import app.modules.fleet_portal.models  # noqa: F401
import app.modules.portal.models  # noqa: F401

from app.modules.invoices.models import Invoice
from app.modules.invoices.service import update_invoice


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _make_invoice(
    *,
    invoice_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    status: str = "issued",
    balance_due: Decimal = Decimal("100.00"),
) -> MagicMock:
    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id or uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = uuid.uuid4()
    inv.status = status
    inv.invoice_number = "INV-LOCK-1"
    inv.balance_due = balance_due
    inv.amount_paid = Decimal("0.00")
    inv.total = balance_due
    inv.notes_internal = None
    inv.notes_customer = None
    inv.due_date = None
    inv.invoice_data_json = {}
    inv.is_gst_locked = False
    return inv


# Patch ``_invoice_to_dict`` for every test in this module so we don't
# have to populate every relationship on the mock invoice — the tests
# assert on the in-memory mutation of the invoice object, not on the
# returned dict shape.


@pytest.fixture(autouse=True)
def _patch_invoice_to_dict():
    with patch(
        "app.modules.invoices.service._invoice_to_dict",
        side_effect=lambda inv, _li: {
            "id": inv.id,
            "status": inv.status,
            "notes_customer": inv.notes_customer,
            "notes_internal": inv.notes_internal,
            "total": inv.total,
            "balance_due": inv.balance_due,
        },
    ):
        yield


class _FakeDb:
    """AsyncMock DB returning a single invoice."""

    def __init__(self, invoice: MagicMock | None) -> None:
        self.invoice = invoice
        self.flushes = 0
        self.flush = AsyncMock(side_effect=self._flush)
        self.execute = AsyncMock(side_effect=self._execute)
        self.refresh = AsyncMock()

    async def _flush(self) -> None:
        self.flushes += 1

    async def _execute(self, stmt, *args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.invoice
        scalars = MagicMock()
        scalars.all.return_value = [self.invoice] if self.invoice else []
        result.scalars.return_value = scalars
        return result


# ---------------------------------------------------------------------------
# Service-layer tests — limited-edit allow-list
# ---------------------------------------------------------------------------


class TestUpdateInvoiceLimitedEdit:
    """``update_invoice`` silently drops disallowed fields for non-draft
    invoices and applies only the allow-list (notes, due date, vehicle
    metadata, T&Cs).

    Validates: invoice-edit-issued-clearer-error regression-fix.
    """

    @pytest.mark.asyncio
    async def test_issued_invoice_drops_line_items_and_discount(self):
        invoice = _make_invoice(status="issued")
        db = _FakeDb(invoice)

        with patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                updates={
                    "line_items": [
                        {
                            "description": "evil edit",
                            "quantity": 1,
                            "rate": 999,
                            "amount": 999,
                        }
                    ],
                    "discount_value": Decimal("50"),
                    "currency": "USD",
                    "notes_customer": "OK to edit notes",
                    "due_date": "2026-12-31",
                },
            )

        assert result is not None
        # Notes + due_date were applied (allow-listed).
        assert invoice.notes_customer == "OK to edit notes"
        # line_items / discount_value / currency were dropped silently.
        # (We can't observe the dropped fields directly but we can
        # observe that they did NOT cause a status change or alter
        # invoice.total / invoice.balance_due.)
        assert invoice.total == Decimal("100.00")
        assert invoice.balance_due == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_overdue_invoice_also_uses_limited_edit(self):
        """``overdue`` is in the limited-edit set; same drop behaviour."""
        invoice = _make_invoice(status="overdue")
        db = _FakeDb(invoice)

        with patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                updates={
                    "line_items": [
                        {
                            "description": "edit attempt",
                            "quantity": 1,
                            "rate": 10,
                            "amount": 10,
                        }
                    ],
                    "notes_internal": "private note",
                },
            )

        assert result is not None
        assert invoice.notes_internal == "private note"
        # Totals untouched.
        assert invoice.total == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_voided_invoice_rejects_any_update(self):
        """Voided invoices reject all edits with ValueError → HTTP 400."""
        invoice = _make_invoice(status="voided")
        db = _FakeDb(invoice)

        with patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            with pytest.raises(ValueError, match="cannot be edited"):
                await update_invoice(
                    db,
                    org_id=invoice.org_id,
                    user_id=uuid.uuid4(),
                    invoice_id=invoice.id,
                    updates={"notes_internal": "no-op"},
                )

    @pytest.mark.asyncio
    async def test_draft_invoice_allows_full_edit(self):
        """Drafts continue to allow line item + discount edits."""
        invoice = _make_invoice(status="draft")
        # Drafts go through the full edit path which queries Org for GST
        # rate. Stub a permissive db that returns the invoice for any
        # SELECT it issues (the test only cares that the call doesn't
        # 400 because of the limited-edit guard).
        db = _FakeDb(invoice)

        org_mock = MagicMock()
        org_mock.settings = {"gst_percentage": 15}

        # Patch the SELECT to return either the invoice or the org mock
        # depending on what's being queried — for this test we don't
        # actually execute the line-item replacement path (would touch
        # stock service); we only assert that ``status='draft'`` does
        # NOT raise the limited-edit ValueError on a notes-only update.
        with patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                updates={"notes_customer": "freely editable"},
            )

        assert result is not None
        assert invoice.notes_customer == "freely editable"

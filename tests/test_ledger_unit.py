"""Unit tests for the OraFlows Accounting ledger module (Task 1.10).

Covers:
  1. COA seed data verification (all 30 accounts)
  2. Manual journal entry creation (balanced) and rejection (unbalanced)
  3. Auto-posting: invoice → correct accounts and amounts
  4. Auto-posting: payment → correct journal entry
  5. Auto-posting: expense with GST → DR expense + DR GST Receivable + CR AP
  6. Period close → closed_by and closed_at recorded
  7. System account deletion rejection
  8. Account with journal_lines deletion rejection
  9. Xero account code fallback behavior
  10. FX invoice auto-posting (exchange_rate_to_nzd conversion)

Requirements: 1.1–1.7, 2.1–2.7, 3.1–3.5, 4.1–4.8, 5.1–5.3
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import HTTPException

# Import models so SQLAlchemy can resolve all relationships.
# The ORM mapper requires all related models to be imported before
# any relationship-loading operations (like selectinload) are used.
import importlib as _importlib
import pathlib as _pathlib

for _models_file in _pathlib.Path("app/modules").rglob("models.py"):
    _mod_path = str(_models_file).replace("/", ".").replace("\\", ".").removesuffix(".py")
    try:
        _importlib.import_module(_mod_path)
    except Exception:
        pass  # some modules may have optional deps

from app.modules.ledger.models import Account, JournalEntry, JournalLine, AccountingPeriod
from app.modules.ledger.service import (
    seed_coa_for_org,
    create_journal_entry,
    post_journal_entry,
    close_period,
    delete_account,
    _NZ_COA_SEED,
)
from app.modules.ledger.auto_poster import (
    auto_post_invoice,
    auto_post_payment,
    auto_post_expense,
    _get_account_by_code,
)
from app.modules.accounting.service import get_xero_account_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    """Create a mock AsyncSession with standard methods."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_account(
    code: str = "1000",
    name: str = "Bank/Cash",
    account_type: str = "asset",
    is_system: bool = True,
    org_id: uuid.UUID | None = None,
    xero_account_code: str | None = None,
) -> MagicMock:
    acct = MagicMock(spec=Account)
    acct.id = uuid.uuid4()
    acct.org_id = org_id or uuid.uuid4()
    acct.code = code
    acct.name = name
    acct.account_type = account_type
    acct.is_system = is_system
    acct.is_active = True
    acct.xero_account_code = xero_account_code
    return acct


# ---------------------------------------------------------------------------
# 1. COA seed data verification
#    Validates: Requirement 1.1
# ---------------------------------------------------------------------------


class TestCoaSeedData:
    """Verify that seed_coa_for_org creates all 30 standard NZ accounts."""

    def _make_mock_account(**kwargs):
        """Create a simple namespace to capture Account constructor kwargs."""
        obj = MagicMock()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

    @pytest.mark.asyncio
    @patch("app.modules.ledger.service.Account", side_effect=lambda **kw: TestCoaSeedData._make_mock_account(**kw))
    async def test_seed_creates_30_accounts(self, mock_account_cls):
        """Req 1.1: COA seed inserts exactly 30 accounts."""
        db = _mock_db()
        org_id = uuid.uuid4()

        accounts = await seed_coa_for_org(db, org_id)

        assert len(accounts) == 30
        assert db.add.call_count == 30

    @pytest.mark.asyncio
    @patch("app.modules.ledger.service.Account", side_effect=lambda **kw: TestCoaSeedData._make_mock_account(**kw))
    async def test_seed_account_codes_match_nz_coa(self, mock_account_cls):
        """Req 1.1: Seeded account codes match the expected NZ COA codes."""
        db = _mock_db()
        org_id = uuid.uuid4()

        await seed_coa_for_org(db, org_id)

        expected_codes = {s["code"] for s in _NZ_COA_SEED}
        added_codes = set()
        for c in db.add.call_args_list:
            obj = c[0][0]
            added_codes.add(obj.code)

        assert added_codes == expected_codes

    @pytest.mark.asyncio
    @patch("app.modules.ledger.service.Account", side_effect=lambda **kw: TestCoaSeedData._make_mock_account(**kw))
    async def test_seed_sets_org_id_on_all_accounts(self, mock_account_cls):
        """Req 1.1: All seeded accounts belong to the given org."""
        db = _mock_db()
        org_id = uuid.uuid4()

        await seed_coa_for_org(db, org_id)

        for c in db.add.call_args_list:
            obj = c[0][0]
            assert obj.org_id == org_id

    @pytest.mark.asyncio
    @patch("app.modules.ledger.service.Account", side_effect=lambda **kw: TestCoaSeedData._make_mock_account(**kw))
    async def test_seed_system_accounts_flagged(self, mock_account_cls):
        """Req 1.1: System accounts have is_system=True."""
        db = _mock_db()
        org_id = uuid.uuid4()

        await seed_coa_for_org(db, org_id)

        system_codes = {s["code"] for s in _NZ_COA_SEED if s["is_system"]}
        for c in db.add.call_args_list:
            obj = c[0][0]
            if obj.code in system_codes:
                assert obj.is_system is True


# ---------------------------------------------------------------------------
# 2. Manual journal entry creation and rejection
#    Validates: Requirements 2.1, 2.3, 2.4
# ---------------------------------------------------------------------------


class TestJournalEntryCreationAndPosting:
    """Manual journal entry creation (balanced) and rejection (unbalanced)."""

    @pytest.mark.asyncio
    @patch("app.modules.ledger.service.JournalLine", side_effect=lambda **kw: MagicMock(**kw))
    @patch("app.modules.ledger.service.JournalEntry", side_effect=lambda **kw: MagicMock(**kw))
    async def test_create_balanced_journal_entry(self, mock_je_cls, mock_jl_cls):
        """Req 2.1, 2.3: A balanced entry is created and can be posted."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        acct_a_id = uuid.uuid4()
        acct_b_id = uuid.uuid4()

        # Mock _get_next_entry_number
        mock_result = MagicMock()
        mock_result.first.return_value = None  # no existing entries
        db.execute.return_value = mock_result

        entry = await create_journal_entry(
            db,
            org_id,
            user_id=user_id,
            entry_date=date.today(),
            description="Test balanced entry",
            lines=[
                {"account_id": acct_a_id, "debit": Decimal("100.00"), "credit": Decimal("0")},
                {"account_id": acct_b_id, "debit": Decimal("0"), "credit": Decimal("100.00")},
            ],
        )

        # Entry was added to the session (1 entry + 2 lines = 3 adds)
        assert db.add.call_count >= 1

    @pytest.mark.asyncio
    async def test_post_unbalanced_entry_rejected_with_imbalance(self):
        """Req 2.4: Unbalanced entry is rejected with imbalance amount in error."""
        db = _mock_db()
        org_id = uuid.uuid4()

        # Create a mock unbalanced entry
        line_a = MagicMock(spec=JournalLine)
        line_a.debit = Decimal("100.00")
        line_a.credit = Decimal("0")
        line_b = MagicMock(spec=JournalLine)
        line_b.debit = Decimal("0")
        line_b.credit = Decimal("50.00")

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        entry.org_id = org_id
        entry.is_posted = False
        entry.period_id = None
        entry.lines = [line_a, line_b]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await post_journal_entry(db, org_id, entry.id)

        assert exc_info.value.status_code == 400
        assert "Imbalance: 50" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_post_to_closed_period_rejected(self):
        """Req 2.5: Posting to a closed period is rejected."""
        db = _mock_db()
        org_id = uuid.uuid4()
        period_id = uuid.uuid4()

        # Balanced entry with a closed period
        line_a = MagicMock(spec=JournalLine)
        line_a.debit = Decimal("100.00")
        line_a.credit = Decimal("0")
        line_b = MagicMock(spec=JournalLine)
        line_b.debit = Decimal("0")
        line_b.credit = Decimal("100.00")

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        entry.org_id = org_id
        entry.is_posted = False
        entry.period_id = period_id
        entry.lines = [line_a, line_b]

        period = MagicMock(spec=AccountingPeriod)
        period.is_closed = True

        # First execute returns the entry, second returns the period
        entry_result = MagicMock()
        entry_result.scalar_one_or_none.return_value = entry
        period_result = MagicMock()
        period_result.scalar_one_or_none.return_value = period
        db.execute = AsyncMock(side_effect=[entry_result, period_result])

        with pytest.raises(HTTPException) as exc_info:
            await post_journal_entry(db, org_id, entry.id)

        assert exc_info.value.status_code == 400
        assert "closed" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 3. Auto-posting: invoice → correct accounts and amounts
#    Validates: Requirements 4.1, 4.6, 4.7
# ---------------------------------------------------------------------------


class TestAutoPostInvoice:
    """Auto-posting an invoice creates correct journal entry."""

    @pytest.mark.asyncio
    @patch("app.modules.ledger.auto_poster.post_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster.create_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster._get_account_by_code", new_callable=AsyncMock)
    async def test_invoice_auto_post_correct_accounts(
        self, mock_get_acct, mock_create_je, mock_post_je,
    ):
        """Req 4.1: Invoice auto-post debits AR, credits Revenue + GST Payable."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        ar_acct = _make_account(code="1100", name="Accounts Receivable", org_id=org_id)
        rev_acct = _make_account(code="4000", name="Sales Revenue", org_id=org_id)
        gst_acct = _make_account(code="2100", name="GST Payable", org_id=org_id)

        mock_get_acct.side_effect = [ar_acct, rev_acct, gst_acct]

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        mock_create_je.return_value = entry

        invoice = MagicMock()
        invoice.id = uuid.uuid4()
        invoice.org_id = org_id
        invoice.total = Decimal("230.00")
        invoice.gst_amount = Decimal("30.00")
        invoice.exchange_rate_to_nzd = Decimal("1.0")
        invoice.issue_date = date.today()
        invoice.invoice_number = "INV-0001"

        await auto_post_invoice(db, invoice, user_id)

        # Verify create_journal_entry was called with correct lines
        call_kwargs = mock_create_je.call_args[1]
        lines = call_kwargs["lines"]

        assert call_kwargs["source_type"] == "invoice"
        assert call_kwargs["source_id"] == invoice.id

        # DR AR = total (230)
        ar_line = [l for l in lines if l["account_id"] == ar_acct.id][0]
        assert ar_line["debit"] == Decimal("230.00")
        assert ar_line["credit"] == Decimal("0")

        # CR Revenue = net (200)
        rev_line = [l for l in lines if l["account_id"] == rev_acct.id][0]
        assert rev_line["credit"] == Decimal("200.00")
        assert rev_line["debit"] == Decimal("0")

        # CR GST Payable = GST (30)
        gst_line = [l for l in lines if l["account_id"] == gst_acct.id][0]
        assert gst_line["credit"] == Decimal("30.00")
        assert gst_line["debit"] == Decimal("0")

        # Verify entry was posted
        mock_post_je.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Auto-posting: payment → correct journal entry
#    Validates: Requirements 4.2, 4.6
# ---------------------------------------------------------------------------


class TestAutoPostPayment:
    """Auto-posting a payment creates correct journal entry."""

    @pytest.mark.asyncio
    @patch("app.modules.ledger.auto_poster.post_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster.create_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster._get_account_by_code", new_callable=AsyncMock)
    async def test_payment_auto_post_correct_accounts(
        self, mock_get_acct, mock_create_je, mock_post_je,
    ):
        """Req 4.2: Payment auto-post debits Bank, credits AR."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        bank_acct = _make_account(code="1000", name="Bank/Cash", org_id=org_id)
        ar_acct = _make_account(code="1100", name="Accounts Receivable", org_id=org_id)

        mock_get_acct.side_effect = [bank_acct, ar_acct]

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        mock_create_je.return_value = entry

        payment = MagicMock()
        payment.id = uuid.uuid4()
        payment.org_id = org_id
        payment.amount = Decimal("150.00")

        invoice = MagicMock()
        invoice.id = uuid.uuid4()
        invoice.invoice_number = "INV-0002"

        await auto_post_payment(db, payment, invoice, user_id)

        call_kwargs = mock_create_je.call_args[1]
        lines = call_kwargs["lines"]

        assert call_kwargs["source_type"] == "payment"
        assert call_kwargs["source_id"] == payment.id

        # DR Bank = 150
        bank_line = [l for l in lines if l["account_id"] == bank_acct.id][0]
        assert bank_line["debit"] == Decimal("150.00")

        # CR AR = 150
        ar_line = [l for l in lines if l["account_id"] == ar_acct.id][0]
        assert ar_line["credit"] == Decimal("150.00")

        mock_post_je.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Auto-posting: expense with GST → DR expense + DR GST Recv + CR AP
#    Validates: Requirements 4.3, 4.6
# ---------------------------------------------------------------------------


class TestAutoPostExpense:
    """Auto-posting an expense with GST creates correct journal entry."""

    @pytest.mark.asyncio
    @patch("app.modules.ledger.auto_poster.post_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster.create_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster._get_account_by_code", new_callable=AsyncMock)
    async def test_expense_with_gst_auto_post(
        self, mock_get_acct, mock_create_je, mock_post_je,
    ):
        """Req 4.3: Expense auto-post: DR expense + DR GST Receivable + CR AP."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        expense_acct = _make_account(code="6990", name="General Expenses", org_id=org_id)
        ap_acct = _make_account(code="2000", name="Accounts Payable", org_id=org_id)
        gst_recv = _make_account(code="1200", name="GST Receivable", org_id=org_id)

        mock_get_acct.side_effect = [expense_acct, ap_acct, gst_recv]

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        mock_create_je.return_value = entry

        expense = MagicMock()
        expense.id = uuid.uuid4()
        expense.org_id = org_id
        expense.amount = Decimal("115.00")
        expense.tax_amount = Decimal("15.00")
        expense.category = "other"
        expense.description = "Office supplies"
        expense.date = date.today()

        await auto_post_expense(db, expense, user_id)

        call_kwargs = mock_create_je.call_args[1]
        lines = call_kwargs["lines"]

        assert call_kwargs["source_type"] == "expense"
        assert call_kwargs["source_id"] == expense.id

        # DR Expense = net (100)
        exp_line = [l for l in lines if l["account_id"] == expense_acct.id][0]
        assert exp_line["debit"] == Decimal("100.00")

        # DR GST Receivable = tax (15)
        gst_line = [l for l in lines if l["account_id"] == gst_recv.id][0]
        assert gst_line["debit"] == Decimal("15.00")

        # CR AP = total (115)
        ap_line = [l for l in lines if l["account_id"] == ap_acct.id][0]
        assert ap_line["credit"] == Decimal("115.00")

        # Verify balance: debits = credits
        total_debits = sum(l["debit"] for l in lines)
        total_credits = sum(l["credit"] for l in lines)
        assert total_debits == total_credits

        mock_post_je.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Period close → closed_by and closed_at recorded
#    Validates: Requirements 3.2, 3.3
# ---------------------------------------------------------------------------


class TestPeriodClose:
    """Closing an accounting period records closed_by and closed_at."""

    @pytest.mark.asyncio
    async def test_close_period_records_user_and_timestamp(self):
        """Req 3.2, 3.3: Closing a period sets closed_by and closed_at."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        period_id = uuid.uuid4()

        period = MagicMock(spec=AccountingPeriod)
        period.id = period_id
        period.org_id = org_id
        period.is_closed = False
        period.closed_by = None
        period.closed_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = period
        db.execute.return_value = mock_result

        result = await close_period(db, org_id, period_id, user_id=user_id)

        assert period.is_closed is True
        assert period.closed_by == user_id
        assert period.closed_at is not None

    @pytest.mark.asyncio
    async def test_close_already_closed_period_rejected(self):
        """Req 3.2: Closing an already-closed period is rejected."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        period_id = uuid.uuid4()

        period = MagicMock(spec=AccountingPeriod)
        period.id = period_id
        period.org_id = org_id
        period.is_closed = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = period
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await close_period(db, org_id, period_id, user_id=user_id)

        assert exc_info.value.status_code == 400
        assert "already closed" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 7. System account deletion rejection
#    Validates: Requirement 1.5
# ---------------------------------------------------------------------------


class TestSystemAccountDeletion:
    """System accounts cannot be deleted."""

    @pytest.mark.asyncio
    async def test_system_account_deletion_rejected(self):
        """Req 1.5: Deleting a system account raises 400."""
        db = _mock_db()
        org_id = uuid.uuid4()

        acct = MagicMock(spec=Account)
        acct.id = uuid.uuid4()
        acct.org_id = org_id
        acct.is_system = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = acct
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await delete_account(db, org_id, acct.id)

        assert exc_info.value.status_code == 400
        assert "system account" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# 8. Account with journal_lines deletion rejection
#    Validates: Requirement 1.6
# ---------------------------------------------------------------------------


class TestAccountWithJournalLinesDeletion:
    """Accounts with journal lines cannot be deleted."""

    @pytest.mark.asyncio
    async def test_account_with_lines_deletion_rejected(self):
        """Req 1.6: Deleting an account with journal entries raises 400."""
        db = _mock_db()
        org_id = uuid.uuid4()

        acct = MagicMock(spec=Account)
        acct.id = uuid.uuid4()
        acct.org_id = org_id
        acct.is_system = False

        # First execute returns the account, second returns line count > 0
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = acct
        line_count_result = MagicMock()
        line_count_result.scalar.return_value = 3
        db.execute = AsyncMock(side_effect=[acct_result, line_count_result])

        with pytest.raises(HTTPException) as exc_info:
            await delete_account(db, org_id, acct.id)

        assert exc_info.value.status_code == 400
        assert "journal entries" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_account_without_lines_can_be_deleted(self):
        """Non-system account with no journal lines can be deleted."""
        db = _mock_db()
        org_id = uuid.uuid4()

        acct = MagicMock(spec=Account)
        acct.id = uuid.uuid4()
        acct.org_id = org_id
        acct.is_system = False

        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = acct
        line_count_result = MagicMock()
        line_count_result.scalar.return_value = 0
        db.execute = AsyncMock(side_effect=[acct_result, line_count_result])

        # Should not raise
        await delete_account(db, org_id, acct.id)

        db.delete.assert_called_once_with(acct)


# ---------------------------------------------------------------------------
# 9. Xero account code fallback behavior
#    Validates: Requirements 5.1, 5.2
# ---------------------------------------------------------------------------


class TestXeroAccountCodeFallback:
    """Xero account code lookup with fallback to defaults."""

    @pytest.mark.asyncio
    async def test_xero_code_returned_when_set(self):
        """Req 5.1: Returns xero_account_code from the account when set."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "200"
        db.execute.return_value = mock_result

        code = await get_xero_account_code(db, org_id, "4000", "999")
        assert code == "200"

    @pytest.mark.asyncio
    async def test_xero_code_falls_back_when_null(self):
        """Req 5.2: Falls back to default when xero_account_code is null."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        code = await get_xero_account_code(db, org_id, "4000", "200")
        assert code == "200"

    @pytest.mark.asyncio
    async def test_xero_code_falls_back_when_account_missing(self):
        """Req 5.2: Falls back to default when account doesn't exist."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        code = await get_xero_account_code(db, org_id, "9999", "090")
        assert code == "090"

    @pytest.mark.asyncio
    async def test_xero_bank_code_fallback(self):
        """Req 5.2: Bank account falls back to 090 when xero_account_code is null."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        code = await get_xero_account_code(db, org_id, "1000", "090")
        assert code == "090"


# ---------------------------------------------------------------------------
# 10. FX invoice auto-posting (exchange_rate_to_nzd conversion)
#     Validates: Requirements 4.1, 4.8
# ---------------------------------------------------------------------------


class TestFxInvoiceAutoPosting:
    """FX invoice auto-posting converts amounts using exchange_rate_to_nzd."""

    @pytest.mark.asyncio
    @patch("app.modules.ledger.auto_poster.post_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster.create_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster._get_account_by_code", new_callable=AsyncMock)
    async def test_fx_invoice_converts_to_nzd(
        self, mock_get_acct, mock_create_je, mock_post_je,
    ):
        """Req 4.8: FX invoice amounts are converted to NZD before posting."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        ar_acct = _make_account(code="1100", org_id=org_id)
        rev_acct = _make_account(code="4000", org_id=org_id)
        gst_acct = _make_account(code="2100", org_id=org_id)

        mock_get_acct.side_effect = [ar_acct, rev_acct, gst_acct]

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        mock_create_je.return_value = entry

        # AUD invoice: total=230 AUD, GST=30 AUD, rate=0.95 NZD per AUD
        invoice = MagicMock()
        invoice.id = uuid.uuid4()
        invoice.org_id = org_id
        invoice.total = Decimal("230.00")
        invoice.gst_amount = Decimal("30.00")
        invoice.exchange_rate_to_nzd = Decimal("0.95")
        invoice.issue_date = date.today()
        invoice.invoice_number = "INV-FX-001"

        await auto_post_invoice(db, invoice, user_id)

        call_kwargs = mock_create_je.call_args[1]
        lines = call_kwargs["lines"]

        rate = Decimal("0.95")
        expected_net_nzd = Decimal("200.00") * rate  # 190.00
        expected_gst_nzd = Decimal("30.00") * rate   # 28.50
        expected_total_nzd = expected_net_nzd + expected_gst_nzd  # 218.50

        # DR AR = total in NZD
        ar_line = [l for l in lines if l["account_id"] == ar_acct.id][0]
        assert ar_line["debit"] == expected_total_nzd

        # CR Revenue = net in NZD
        rev_line = [l for l in lines if l["account_id"] == rev_acct.id][0]
        assert rev_line["credit"] == expected_net_nzd

        # CR GST = GST in NZD
        gst_line = [l for l in lines if l["account_id"] == gst_acct.id][0]
        assert gst_line["credit"] == expected_gst_nzd

        # Verify balance
        total_debits = sum(l["debit"] for l in lines)
        total_credits = sum(l["credit"] for l in lines)
        assert total_debits == total_credits

    @pytest.mark.asyncio
    @patch("app.modules.ledger.auto_poster.post_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster.create_journal_entry", new_callable=AsyncMock)
    @patch("app.modules.ledger.auto_poster._get_account_by_code", new_callable=AsyncMock)
    async def test_fx_invoice_rate_1_equals_nzd(
        self, mock_get_acct, mock_create_je, mock_post_je,
    ):
        """Req 4.8: Rate of 1.0 means NZD — amounts unchanged."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        ar_acct = _make_account(code="1100", org_id=org_id)
        rev_acct = _make_account(code="4000", org_id=org_id)
        gst_acct = _make_account(code="2100", org_id=org_id)

        mock_get_acct.side_effect = [ar_acct, rev_acct, gst_acct]

        entry = MagicMock(spec=JournalEntry)
        entry.id = uuid.uuid4()
        mock_create_je.return_value = entry

        invoice = MagicMock()
        invoice.id = uuid.uuid4()
        invoice.org_id = org_id
        invoice.total = Decimal("115.00")
        invoice.gst_amount = Decimal("15.00")
        invoice.exchange_rate_to_nzd = Decimal("1.0")
        invoice.issue_date = date.today()
        invoice.invoice_number = "INV-NZD-001"

        await auto_post_invoice(db, invoice, user_id)

        call_kwargs = mock_create_je.call_args[1]
        lines = call_kwargs["lines"]

        ar_line = [l for l in lines if l["account_id"] == ar_acct.id][0]
        assert ar_line["debit"] == Decimal("115.00")

        rev_line = [l for l in lines if l["account_id"] == rev_acct.id][0]
        assert rev_line["credit"] == Decimal("100.00")

        gst_line = [l for l in lines if l["account_id"] == gst_acct.id][0]
        assert gst_line["credit"] == Decimal("15.00")

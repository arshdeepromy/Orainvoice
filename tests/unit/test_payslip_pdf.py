"""Unit tests for ``app.modules.payslips.pdf`` (B5 + E1).

Covers the verify list under task B5 + E1 in
``.kiro/specs/staff-management-p4/tasks.md``:

  - **G1** — masked bank account string ``**-****-****NN-**`` shown
    on the rendered PDF; full IRD never appears in the output.
  - **G2** — public-holiday band rendered with hours × rate as its
    own row.
  - **G18** — allowance rows render quantity / unit / amount for
    shift+km units.
  - **N18** — staff with NULL bank account shows the cash-payment
    fallback string.
  - **P4-N25** — PDF YTD figures: PAYE / KiwiSaver-employee /
    KiwiSaver-employer YTD computed at render time from
    ``payslip_deductions``. Two prior finalised payslips with PAYE
    $200 + $300 → render third payslip → ``paye_ytd`` shows $500.

We stub WeasyPrint via :func:`unittest.mock.patch` so the test runs
in any environment (no native dependencies). The Jinja template is
the real one — we render it and assert the resulting HTML contains
every required substring. This is faster than parsing PDF binary
and produces clearer failure messages.

**Validates: Requirements R7, R7.5, R4a, R5, R6, P4-N25 — Staff
Management Phase 4 task B5 + E1.**
"""

from __future__ import annotations

# Resolve mappers eagerly — pdf.py imports Organisation transitively.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# WeasyPrint native deps (libpango, etc.) may not be installed in
# every environment. The PDF module does ``from weasyprint import
# HTML`` inside its function body, so we install a stub module
# globally before any test runs — every ``HTML`` call from the
# render path goes through the stub. The stub captures the rendered
# string and returns dummy bytes from ``write_pdf()``.
if "weasyprint" not in sys.modules:
    _stub = ModuleType("weasyprint")

    class _StubHTML:  # noqa: D401 — stand-in only.
        last_string: str = ""

        def __init__(self, *, string=None, **_kwargs):
            type(self).last_string = string or ""

        def write_pdf(self):
            return b"%PDF-1.4 (mocked)"

    _stub.HTML = _StubHTML
    sys.modules["weasyprint"] = _stub


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class _Result:
    def __init__(
        self,
        *,
        all_rows=None,
        scalar=None,
        scalars_list=None,
    ):
        self._all = list(all_rows or [])
        self._scalar = scalar
        self._scalars_list = scalars_list

    def all(self):
        return list(self._all)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        proxy = MagicMock()
        proxy.all.return_value = list(self._scalars_list or [])
        return proxy


@dataclass
class _Script:
    queue: list[_Result] = field(default_factory=list)

    def push(self, result: _Result) -> None:
        self.queue.append(result)

    def pop(self) -> _Result:
        if not self.queue:
            return _Result()
        return self.queue.pop(0)


class _FakeSession:
    def __init__(self) -> None:
        self._gets: dict[tuple[str, Any], Any] = {}
        self._scripts: dict[str, _Script] = {}

    def add_get(self, model_name: str, key: Any, value: Any) -> None:
        self._gets[(model_name, key)] = value

    def script(self, key: str) -> _Script:
        if key not in self._scripts:
            self._scripts[key] = _Script()
        return self._scripts[key]

    async def get(self, model, key):
        return self._gets.get((model.__name__, key))

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        for key, script in self._scripts.items():
            if key.lower() in sql:
                return script.pop()
        return _Result()

    @asynccontextmanager
    async def begin(self):
        yield self


# ---------------------------------------------------------------------------
# Builders for ORM-shaped rows
# ---------------------------------------------------------------------------


def _make_payslip_row(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    pay_period_id: uuid.UUID,
    public_holiday_hours: Decimal = Decimal("0.00"),
    public_holiday_rate: Decimal | None = None,
    overtime_hours: Decimal = Decimal("0.00"),
    overtime_rate: Decimal | None = None,
    ordinary_hours: Decimal = Decimal("40.00"),
    ordinary_rate: Decimal = Decimal("25.00"),
    gross_pay: Decimal = Decimal("1000.00"),
    gross_ytd: Decimal = Decimal("1000.00"),
    net_pay: Decimal = Decimal("800.00"),
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        pay_period_id=pay_period_id,
        status="finalised",
        ordinary_hours=ordinary_hours,
        overtime_hours=overtime_hours,
        public_holiday_hours=public_holiday_hours,
        ordinary_rate=ordinary_rate,
        overtime_rate=overtime_rate,
        public_holiday_rate=public_holiday_rate,
        gross_pay=gross_pay,
        gross_ytd=gross_ytd,
        net_pay=net_pay,
        notes=None,
    )


def _make_staff_row(
    *,
    org_id: uuid.UUID,
    bank_account_encrypted: bytes | None = b"fake-encrypted-bank",
    ird_encrypted: bytes | None = b"fake-encrypted-ird",
    tax_code: str = "M",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        name="Jane Doe",
        first_name="Jane",
        tax_code=tax_code,
        ird_number_encrypted=ird_encrypted,
        bank_account_number_encrypted=bank_account_encrypted,
    )


def _make_period_row(
    *,
    org_id: uuid.UUID,
    start_date: date = date(2026, 6, 1),
    end_date: date = date(2026, 6, 14),
    pay_date: date = date(2026, 6, 17),
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        start_date=start_date,
        end_date=end_date,
        pay_date=pay_date,
    )


def _make_org_row():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Acme Workshops",
        income_tax_year_end=date(2026, 3, 31),
    )


def _allowance(label, *, quantity, unit, amount, taxable=True, atype_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        payslip_id=uuid.uuid4(),
        allowance_type_id=atype_id,
        label=label,
        quantity=Decimal(str(quantity)),
        unit=unit,
        amount=Decimal(str(amount)),
        taxable=taxable,
    )


def _deduction(kind, *, amount, label=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        payslip_id=uuid.uuid4(),
        kind=kind,
        label=label or kind.replace("_", " ").title(),
        amount=Decimal(str(amount)),
    )


def _reimbursement(label, *, amount):
    return SimpleNamespace(
        id=uuid.uuid4(),
        payslip_id=uuid.uuid4(),
        label=label,
        amount=Decimal(str(amount)),
    )


# ---------------------------------------------------------------------------
# Common patch context — captures the rendered HTML
# ---------------------------------------------------------------------------


def _patch_weasyprint_capture():
    """Return a context manager and a mutable dict. The manager
    patches ``weasyprint.HTML(string=...).write_pdf()`` so the
    method records the string and returns dummy bytes.
    """
    captured: dict[str, str] = {}

    class _CaptureHTML:
        def __init__(self, *, string=None, **_kwargs):
            captured["html"] = string or ""

        def write_pdf(self):
            return b"%PDF-1.4 (mocked)"

    cm = patch.object(sys.modules["weasyprint"], "HTML", _CaptureHTML)
    return cm, captured


def _patch_decryption(plain_ird="123456789", plain_bank="01-1234-1234567-00"):
    """Patch ``envelope_decrypt_str`` to return deterministic plain
    strings without doing real KMS work.
    """
    counter = {"n": 0}

    def _decrypt(blob):
        # First call: IRD; second call: bank. The pdf module calls
        # IRD first then bank (see ``_mask_staff_pii``).
        counter["n"] += 1
        if counter["n"] == 1:
            return plain_ird
        return plain_bank

    return patch(
        "app.modules.payslips.pdf.envelope_decrypt_str",
        side_effect=_decrypt,
    )


# ===========================================================================
# 1. G1 + G2 + G18 — Rendered HTML contains required substrings
# ===========================================================================


class TestRenderHtmlSubstrings:
    """A "happy path" rendered payslip contains every documented
    field the auditors and IRD compliance need.
    """

    @pytest.mark.asyncio
    async def test_full_payslip_renders_all_required_fields(self):
        """G1 + G2 + G18 — verify the rendered HTML includes:

          - tax_code (M)
          - masked IRD (***789)
          - masked bank account (**-****-****67-**)
          - all hour bands incl. public_holiday_rate
          - gross
          - all deductions including KiwiSaver employer
          - net
          - leave_taken (one row)
          - every accruing leave balance
          - YTD totals (gross/PAYE/KS-employee/KS-employer)
          - per-allowance quantity × unit × amount for shift/km units
        """
        from app.modules.payslips.pdf import render_pdf

        org = _make_org_row()
        period = _make_period_row(org_id=org.id)
        staff = _make_staff_row(org_id=org.id)
        payslip = _make_payslip_row(
            org_id=org.id,
            staff_id=staff.id,
            pay_period_id=period.id,
            ordinary_hours=Decimal("40.00"),
            ordinary_rate=Decimal("25.00"),
            overtime_hours=Decimal("4.00"),
            overtime_rate=Decimal("37.50"),
            public_holiday_hours=Decimal("8.00"),
            public_holiday_rate=Decimal("37.50"),
            gross_pay=Decimal("1450.00"),
            gross_ytd=Decimal("5800.00"),
            net_pay=Decimal("1100.00"),
        )

        # Three allowances: shift, km, period.
        allowances = [
            _allowance("Tool allowance", quantity="5", unit="shift", amount="50.00"),
            _allowance(
                "Vehicle km", quantity="120", unit="km", amount="102.00",
                taxable=False,
            ),
            _allowance(
                "Meal allowance", quantity="1", unit="period", amount="25.00",
            ),
        ]
        deductions = [
            _deduction("paye", amount="200.00", label="PAYE"),
            _deduction(
                "kiwisaver_employee", amount="43.50",
                label="KiwiSaver employee contribution",
            ),
            _deduction(
                "kiwisaver_employer", amount="43.50",
                label="KiwiSaver employer contribution (informational)",
            ),
        ]
        reimbursements = [
            _reimbursement("Fuel claim", amount="35.00"),
        ]
        leave_lines_rows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                leave_type_id=uuid.uuid4(),
                hours=Decimal("8.00"),
                rate=Decimal("25.00"),
                amount=Decimal("200.00"),
                balance_after=Decimal("72.00"),
                leave_type_code="annual_leave",
                leave_type_name="Annual leave",
            ),
        ]
        leave_balance_rows = [
            SimpleNamespace(
                code="annual_leave",
                name="Annual leave",
                accrued_hours=Decimal("80.00"),
                used_hours=Decimal("8.00"),
            ),
            SimpleNamespace(
                code="sick_leave",
                name="Sick leave",
                accrued_hours=Decimal("80.00"),
                used_hours=Decimal("0.00"),
            ),
        ]

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)
        db.add_get("StaffMember", staff.id, staff)
        db.add_get("PayPeriod", period.id, period)
        db.add_get("Organisation", payslip.org_id, org)

        # PDF helper SQL paths:
        # 1. SELECT PayslipAllowance / Deduction / Reimbursement.
        db.script("from payslip_allowances").push(
            _Result(scalars_list=allowances),
        )
        db.script("from payslip_deductions").push(
            _Result(scalars_list=deductions),
        )
        db.script("from payslip_reimbursements").push(
            _Result(scalars_list=reimbursements),
        )
        # 2. SELECT PayslipLeaveLine joined on LeaveType (ORM tuple).
        db.script("from payslip_leave_lines").push(
            _Result(all_rows=leave_lines_rows),
        )
        # 3. SELECT remaining LeaveBalance × LeaveType for the s130A
        # balances block.
        db.script("from leave_types").push(
            _Result(all_rows=leave_balance_rows),
        )
        # 4. YTD deductions (paye / KS-employee / KS-employer).
        db.script("from payslip_deductions").push(_Result(all_rows=[]))
        # 5. Anniversary date lookup (best-effort).
        db.script("from leave_balances").push(
            _Result(scalar=date(2024, 6, 1)),
        )

        cm, captured = _patch_weasyprint_capture()
        with cm, _patch_decryption():
            await render_pdf(db, payslip.id)

        html = captured["html"]

        # ---- Tax code (G1) ----
        assert "M" in html
        # "Tax code" label rendered.
        assert "Tax code" in html

        # ---- Masked IRD (G1). Plain "123456789" → mask = ***789. ----
        assert "***789" in html
        # Full plaintext IRD must NOT leak.
        assert "123456789" not in html

        # ---- Masked bank account (G1). Plain "01-1234-1234567-00" →
        # digits "011234123456700" (15 chars), digits[-4:-2] = "67".
        # Mask format = **-****-****NN-**.
        assert "**-****-****67-**" in html
        # Full plain bank account must NOT leak.
        assert "01-1234-1234567-00" not in html

        # ---- Hour bands (G2). Public-holiday band as its own row. ----
        assert "Public holiday (Holidays Act s50)" in html
        # Public-holiday rate visible ($37.50).
        assert "$37.50" in html

        # ---- Per-allowance quantity × unit × amount (G18). ----
        assert "Tool allowance" in html
        assert "5.00" in html  # quantity for shift
        assert "shift" in html
        assert "$50.00" in html  # amount
        assert "Vehicle km" in html
        assert "120.00" in html
        assert "km" in html
        assert "$102.00" in html
        # Period unit shows "—" placeholder for quantity per template.
        assert "Meal allowance" in html
        # Period amount.
        assert "$25.00" in html

        # ---- Gross + Net + Deductions ----
        assert "$1,450.00" in html  # gross_pay
        assert "$1,100.00" in html  # net_pay
        # KiwiSaver employer flagged as informational on the line.
        assert "informational" in html.lower()

        # ---- Leave taken + balances (s130A) ----
        assert "Leave taken" in html
        assert "Annual leave" in html
        assert "Remaining leave balances" in html
        assert "Sick leave" in html

        # ---- YTD totals (P4-N25) ----
        assert "Year-to-date" in html
        assert "Gross YTD" in html
        assert "PAYE YTD" in html
        assert "KiwiSaver employee YTD" in html
        assert "KiwiSaver employer YTD" in html
        # Gross YTD value displayed.
        assert "$5,800.00" in html


# ===========================================================================
# 2. N18 — Cash-payment fallback string
# ===========================================================================


class TestCashPaymentFallback:
    """N18 — when the staff has no encrypted bank account on file,
    the PDF surfaces the literal cash-payment fallback string.
    """

    @pytest.mark.asyncio
    async def test_null_bank_account_shows_cash_fallback(self):
        from app.modules.payslips.pdf import render_pdf

        org = _make_org_row()
        period = _make_period_row(org_id=org.id)
        staff = _make_staff_row(
            org_id=org.id,
            bank_account_encrypted=None,
            ird_encrypted=b"fake-encrypted-ird",
        )
        payslip = _make_payslip_row(
            org_id=org.id,
            staff_id=staff.id,
            pay_period_id=period.id,
        )

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)
        db.add_get("StaffMember", staff.id, staff)
        db.add_get("PayPeriod", period.id, period)
        db.add_get("Organisation", org.id, org)

        # Empty line lists for this test — we only care about the
        # bank-account substring.
        db.script("from payslip_allowances").push(_Result(scalars_list=[]))
        db.script("from payslip_deductions").push(_Result(scalars_list=[]))
        db.script("from payslip_reimbursements").push(
            _Result(scalars_list=[]),
        )
        db.script("from payslip_leave_lines").push(_Result(all_rows=[]))
        db.script("from leave_types").push(_Result(all_rows=[]))
        db.script("from payslip_deductions").push(_Result(all_rows=[]))
        db.script("from leave_balances").push(_Result(scalar=None))

        cm, captured = _patch_weasyprint_capture()

        # Only IRD decryption happens here (bank is NULL → no
        # decrypt call). Patch envelope_decrypt_str to return the IRD
        # plaintext.
        with cm, patch(
            "app.modules.payslips.pdf.envelope_decrypt_str",
            return_value="123456789",
        ):
            await render_pdf(db, payslip.id)

        html = captured["html"]
        assert "Cash payment / no bank account on file" in html
        # And no masked-bank string appears (the cash fallback
        # replaces it entirely).
        assert "**-****-****" not in html


# ===========================================================================
# 3. P4-N25 — YTD deductions sum across the tax year
# ===========================================================================


class TestYtdDeductionAggregation:
    """P4-N25 — PAYE / KiwiSaver-employee / KiwiSaver-employer YTD
    figures are computed at render time by summing
    ``payslip_deductions`` joined to finalised ``payslips`` × the
    NZ tax-year window.

    Rather than driving the full ``render_pdf`` flow, we exercise
    the helper directly: feed three simulated rows (the SUMs
    materialised by the SQL — Postgres returns one row per kind),
    and assert the helper's return shape is correct.
    """

    @pytest.mark.asyncio
    async def test_paye_ytd_is_sum_of_two_prior_payslips_paye(self):
        """Two prior finalised payslips with PAYE $200 + $300 in the
        same tax year → ``paye_ytd`` reads $500. The fake session
        returns the SQL SUM rows pre-aggregated, which is what
        Postgres would produce.
        """
        from app.modules.payslips.pdf import _compute_ytd_deductions

        # Postgres returns one row per kind in the GROUP BY.
        ytd_rows = [
            SimpleNamespace(kind="paye", total=Decimal("500.00")),
            SimpleNamespace(
                kind="kiwisaver_employee", total=Decimal("87.00"),
            ),
            SimpleNamespace(
                kind="kiwisaver_employer", total=Decimal("87.00"),
            ),
        ]

        db = _FakeSession()
        db.script("from payslip_deductions").push(_Result(all_rows=ytd_rows))

        result = await _compute_ytd_deductions(
            db,
            staff_id=uuid.uuid4(),
            pay_date=date(2026, 6, 17),
            tax_year_end=date(2026, 3, 31),
        )

        assert result["paye_ytd"] == Decimal("500.00")
        assert result["kiwisaver_employee_ytd"] == Decimal("87.00")
        assert result["kiwisaver_employer_ytd"] == Decimal("87.00")

    @pytest.mark.asyncio
    async def test_missing_kinds_default_to_zero(self):
        """When a staff has no PAYE rows yet, the helper still
        returns the three keys with zero values.
        """
        from app.modules.payslips.pdf import _compute_ytd_deductions

        db = _FakeSession()
        db.script("from payslip_deductions").push(_Result(all_rows=[]))

        result = await _compute_ytd_deductions(
            db,
            staff_id=uuid.uuid4(),
            pay_date=date(2026, 6, 17),
            tax_year_end=date(2026, 3, 31),
        )

        assert result["paye_ytd"] == Decimal("0.00")
        assert result["kiwisaver_employee_ytd"] == Decimal("0.00")
        assert result["kiwisaver_employer_ytd"] == Decimal("0.00")

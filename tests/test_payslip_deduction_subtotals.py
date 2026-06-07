"""Tests for per-payslip deduction subtotals.

Feature: payroll-deduction-subtotals

Covers:
  - ``PayslipDeductionSubtotals`` schema: zero defaults, computed ``total``,
    decimal-as-string serialisation, and tolerance of unexpected keys.
  - ``service.deduction_subtotals_for``: result shaping from grouped rows,
    the empty-ids short-circuit (no query), and per-payslip grouping.

These follow the module's existing mock-based test convention (the payslips
suite uses in-memory / mocked ``AsyncSession`` stand-ins rather than a live
DB — see ``tests/property/test_payslip_invariants.py``).
"""

from __future__ import annotations

# Configure the ORM mappers (calc/service import order needs these).
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.payslips import service as payslips_service
from app.modules.payslips.schemas import PayslipDeductionSubtotals


# ---------------------------------------------------------------------------
# Schema — PayslipDeductionSubtotals
# ---------------------------------------------------------------------------


def test_empty_default_is_all_zeros_with_zero_total():
    s = PayslipDeductionSubtotals()
    dumped = s.model_dump(mode="json")
    for kind in (
        "paye",
        "acc_levy",
        "kiwisaver_employee",
        "kiwisaver_employer",
        "student_loan",
        "child_support",
        "voluntary",
    ):
        assert dumped[kind] == "0"
    assert dumped["total"] == "0"


def test_total_is_sum_of_the_seven_kinds():
    s = PayslipDeductionSubtotals(
        paye=Decimal("724.00"),
        kiwisaver_employee=Decimal("102.50"),
        kiwisaver_employer=Decimal("120.00"),
        acc_levy=Decimal("30.00"),
        voluntary=Decimal("15.00"),
    )
    assert s.total == Decimal("991.50")


def test_absent_kinds_default_to_zero_when_constructed_from_partial_dict():
    s = PayslipDeductionSubtotals(**{"paye": Decimal("10.00")})
    assert s.paye == Decimal("10.00")
    assert s.student_loan == Decimal("0")
    assert s.total == Decimal("10.00")


def test_decimal_serialised_as_string():
    s = PayslipDeductionSubtotals(paye=Decimal("12.34"))
    assert s.model_dump(mode="json")["paye"] == "12.34"


def test_unexpected_kind_is_ignored_not_an_error():
    # CHECK constraint guarantees only the seven kinds, but the router builds
    # via **kwargs — an unexpected key must never raise (extra='ignore').
    s = PayslipDeductionSubtotals(**{"paye": Decimal("5"), "bogus": Decimal("9")})
    assert s.paye == Decimal("5")
    assert s.total == Decimal("5")


# ---------------------------------------------------------------------------
# Service — deduction_subtotals_for
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ids_short_circuits_without_query():
    db = AsyncMock()
    result = await payslips_service.deduction_subtotals_for(db, [])
    assert result == {}
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_groups_rows_by_payslip_and_kind():
    p1 = uuid.uuid4()
    p2 = uuid.uuid4()
    rows = [
        (p1, "paye", Decimal("724.00")),
        (p1, "kiwisaver_employee", Decimal("102.50")),
        (p1, "acc_levy", Decimal("30.00")),
        (p2, "paye", Decimal("558.00")),
    ]
    execute_result = MagicMock()
    execute_result.all.return_value = rows
    db = AsyncMock()
    db.execute.return_value = execute_result

    out = await payslips_service.deduction_subtotals_for(db, [p1, p2])

    assert out[p1] == {
        "paye": Decimal("724.00"),
        "kiwisaver_employee": Decimal("102.50"),
        "acc_levy": Decimal("30.00"),
    }
    assert out[p2] == {"paye": Decimal("558.00")}
    # Each grouped row maps straight onto the schema (absent kinds → 0).
    sub1 = PayslipDeductionSubtotals(**out[p1])
    assert sub1.total == Decimal("856.50")
    assert sub1.student_loan == Decimal("0")


@pytest.mark.asyncio
async def test_null_sum_coerced_to_zero():
    p1 = uuid.uuid4()
    execute_result = MagicMock()
    execute_result.all.return_value = [(p1, "voluntary", None)]
    db = AsyncMock()
    db.execute.return_value = execute_result

    out = await payslips_service.deduction_subtotals_for(db, [p1])
    assert out[p1]["voluntary"] == Decimal("0")

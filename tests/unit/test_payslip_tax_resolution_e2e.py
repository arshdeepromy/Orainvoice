"""End-to-end test: tax-config resolution flows into payslip numbers (task 9.2).

Covers the wiring added in task 9.1 — ``compute_payslip`` calls
``resolve_tax_config(db, staff.org_id)`` and hands the resolved
:class:`~app.modules.timesheets.paye.ResolvedTaxConfig` to ``compute_paye`` — and
asserts the two behaviours that wiring guarantees end-to-end, at the payslip
level:

  - **Req 2.5** — a change to the **Platform_Tax_Default** flows through
    resolution into a generated payslip's statutory numbers (PAYE / student
    loan) for an organisation that has **no** overrides.
  - **Req 3.3** — an organisation **override** changes only that organisation's
    payslip; a second organisation with no override (same platform default,
    same gross) is unaffected, and the non-overridden fields stay identical
    across both orgs.

Test strategy
-------------
This exercises the real ``compute_payslip`` orchestrator — including the real
``resolve_tax_config`` resolution layer and the real ``compute_paye`` engine —
against an in-memory session double that serves exactly the queries the calc
path makes. This mirrors the established calc-test pattern
(``tests/unit/test_payslip_calc.py``), which uses an in-memory ``_FakeSession``
rather than seeding real ``staff_members`` / ``pay_periods`` / timesheet rows
(those tables carry FK chains + RLS that make a two-org payslip seed heavy).
The only rows that are faked are the two stored tax-configuration rows
(``platform_tax_default`` and ``org_tax_settings``); everything the resolution
precedence and PAYE math do with them is the production code path.

Each example feeds a configurable platform ``config`` document and an optional
org ``overrides`` document, plus a fixed block of ordinary hours so the payslip
has a non-zero gross to tax. Numeric tax values are carried as **strings** so
they round-trip losslessly through the resolver's ``Decimal(str(...))``
coercion, exactly as JSONB storage would.

**Validates: Requirements 2.5, 3.3 — Payroll Tax Settings.**
"""

from __future__ import annotations

# Import dependent ORM modules eagerly so SQLAlchemy can resolve mappers before
# the calc layer compiles any ``select(...)`` (mirrors test_payslip_calc.py).
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.payroll_tax.models  # noqa: F401
import app.modules.timesheets.models  # noqa: F401

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.modules.payslips.calc import compute_payslip
from app.modules.timesheets.paye import SAFETY_NET


# ---------------------------------------------------------------------------
# Stored-row doubles + session double
# ---------------------------------------------------------------------------


class _FakePlatformRow:
    """Stand-in for a ``platform_tax_default`` row (config JSONB + label)."""

    def __init__(self, config: dict[str, Any], tax_year_label: str):
        self.config = config
        self.tax_year_label = tax_year_label


class _FakeOrgRow:
    """Stand-in for an ``org_tax_settings`` row (sparse overrides JSONB)."""

    def __init__(self, overrides: dict[str, Any]):
        self.overrides = overrides


class _Result:
    """Mimic the shape returned by ``AsyncSession.execute()``."""

    def __init__(
        self,
        *,
        all_rows: list | None = None,
        scalar: Any = None,
        one_or_none_row: Any = None,
    ):
        self._all = list(all_rows or [])
        self._scalar = scalar
        self._one_or_none = one_or_none_row

    def all(self):
        return list(self._all)

    def one_or_none(self):
        return self._one_or_none

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        proxy = MagicMock()
        proxy.all.return_value = list(self._all)
        return proxy


class _FakeTaxSession:
    """In-memory ``AsyncSession`` double for the resolution-into-payslip path.

    Routes ``execute()`` by inspecting the compiled SQL text:

      - legacy ``timesheet_approvals`` hours aggregation → the configured
        ordinary/overtime/public-holiday minutes (so gross is non-zero);
      - ``platform_tax_default`` SELECT → the configured fake platform row
        (or ``None`` to model "no platform row");
      - ``org_tax_settings`` SELECT → the configured fake org row (or ``None``
        to model "org inherits everything");
      - the ``timesheets`` ORM SELECT (Timesheet lookup) → ``None`` so the calc
        falls through to the legacy hours path;
      - the ``compute_gross_ytd`` join → empty;
      - anything else → empty.
    """

    def __init__(
        self,
        *,
        platform_row: _FakePlatformRow | None,
        org_row: _FakeOrgRow | None,
        ordinary_minutes: int = 0,
        overtime_minutes: int = 0,
        public_holiday_minutes: int = 0,
    ):
        self.platform_row = platform_row
        self.org_row = org_row
        self.ordinary_minutes = ordinary_minutes
        self.overtime_minutes = overtime_minutes
        self.public_holiday_minutes = public_holiday_minutes

    async def get(self, model, key):
        # The calc only ever calls ``db.get(Organisation, org_id)`` for the
        # tax-year window; ``None`` → the default 1 Apr / 31 Mar boundary.
        return None

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()

        # 1. Legacy hours aggregation (raw SQL on timesheet_approvals).
        if "timesheet_approvals" in sql:
            row = SimpleNamespace(
                ordinary_minutes=self.ordinary_minutes,
                overtime_minutes=self.overtime_minutes,
                public_holiday_minutes=self.public_holiday_minutes,
            )
            return _Result(one_or_none_row=row)

        # 2. Platform tax default singleton.
        if "platform_tax_default" in sql:
            return _Result(scalar=self.platform_row)

        # 3. Org tax settings overrides row.
        if "org_tax_settings" in sql:
            return _Result(scalar=self.org_row)

        # 4. compute_gross_ytd ORM join (payslips × pay_periods).
        if "gross_pay" in sql and "pay_periods" in sql:
            return _Result(all_rows=[])

        # 5. Timesheet ORM SELECT → no row, so the calc uses the legacy path.
        if "from timesheets" in sql:
            return _Result(scalar=None)

        # Default — empty.
        return _Result(all_rows=[])


# ---------------------------------------------------------------------------
# Config-document helpers
# ---------------------------------------------------------------------------


def _safety_net_document() -> dict[str, Any]:
    """The full platform ``config`` document equal to :data:`SAFETY_NET`.

    Every numeric value is a string so it round-trips losslessly through the
    resolver's ``Decimal(str(...))`` coercion, exactly as JSONB storage does.
    """
    return {
        "paye_brackets": [
            {
                "upper_limit": (None if b.upper_limit is None else str(b.upper_limit)),
                "rate": str(b.rate),
            }
            for b in SAFETY_NET.paye_brackets
        ],
        "secondary_rates": {k: str(v) for k, v in SAFETY_NET.secondary_rates.items()},
        "acc_levy_rate": str(SAFETY_NET.acc_levy_rate),
        "acc_max_liable_earnings": str(SAFETY_NET.acc_max_liable_earnings),
        "student_loan_rate": str(SAFETY_NET.student_loan_rate),
        "student_loan_threshold": str(SAFETY_NET.student_loan_threshold),
        "ietc": {
            "amount": str(SAFETY_NET.ietc.amount),
            "lower": str(SAFETY_NET.ietc.lower),
            "abatement_start": str(SAFETY_NET.ietc.abatement_start),
            "abatement_rate": str(SAFETY_NET.ietc.abatement_rate),
            "upper": str(SAFETY_NET.ietc.upper),
        },
        "default_kiwisaver_employee_rate": str(
            SAFETY_NET.default_kiwisaver_employee_rate
        ),
        "default_kiwisaver_employer_rate": str(
            SAFETY_NET.default_kiwisaver_employer_rate
        ),
    }


def _bump_all_bracket_rates(brackets: list[dict[str, Any]], delta: str) -> list[dict[str, Any]]:
    """Return a copy of ``brackets`` with every marginal ``rate`` raised by ``delta``."""
    inc = Decimal(delta)
    return [
        {"upper_limit": b["upper_limit"], "rate": str(Decimal(b["rate"]) + inc)}
        for b in brackets
    ]


def _make_staff(org_id: uuid.UUID):
    """A duck-typed primary-code, student-loan staff member on $40/h."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        name="Pat Worker",
        first_name="Pat",
        hourly_rate=Decimal("40.00"),
        overtime_rate=None,
        employment_type="permanent",
        kiwisaver_enrolled=False,
        kiwisaver_employee_rate=None,
        kiwisaver_employer_rate=None,
        tax_code="M",
        student_loan=True,
        working_arrangement="variable",
    )


def _make_period():
    """A standard fortnightly pay period (14 inclusive days)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 14),
        pay_date=date(2026, 6, 17),
    )


#: 80 ordinary hours over the fortnight (× $40 → $3,200 gross to tax).
_FORTNIGHT_ORDINARY_MINUTES = 80 * 60


async def _run_payslip(
    *,
    platform_doc: dict[str, Any] | None,
    org_overrides: dict[str, Any] | None,
):
    """Compute one payslip for a fresh org under the given stored tax rows."""
    org_id = uuid.uuid4()
    staff = _make_staff(org_id)
    period = _make_period()
    platform_row = (
        _FakePlatformRow(config=platform_doc, tax_year_label="2024/25")
        if platform_doc is not None
        else None
    )
    org_row = _FakeOrgRow(overrides=org_overrides) if org_overrides is not None else None
    db = _FakeTaxSession(
        platform_row=platform_row,
        org_row=org_row,
        ordinary_minutes=_FORTNIGHT_ORDINARY_MINUTES,
    )
    return await compute_payslip(db, staff, period, payslip=None)


# ===========================================================================
# Req 2.5 — platform rate change flows through to a non-overriding org
# ===========================================================================


class TestPlatformChangeFlowsIntoPayslip:
    """Req 2.5 — a Platform_Tax_Default change reaches the payslip numbers of an
    organisation that has no overrides."""

    @pytest.mark.asyncio
    async def test_platform_rate_change_moves_non_overriding_org_payslip(self):
        # Baseline platform config (the seeded 2024/25 values).
        platform_v1 = _safety_net_document()
        calc_v1 = await _run_payslip(platform_doc=platform_v1, org_overrides=None)

        # Sanity — the payslip has a non-zero gross and non-zero statutory
        # numbers so a rate change can demonstrably move them.
        assert calc_v1.gross == Decimal("3200.00")
        assert calc_v1.paye > Decimal("0.00")
        assert calc_v1.student_loan > Decimal("0.00")

        # The Global_Admin raises the student-loan rate (0.12 → 0.20) and every
        # PAYE bracket rate (+0.05) on the platform default. The org still has
        # NO override, so resolution must surface the new platform values.
        platform_v2 = _safety_net_document()
        platform_v2["student_loan_rate"] = "0.20"
        platform_v2["paye_brackets"] = _bump_all_bracket_rates(
            platform_v2["paye_brackets"], "0.05"
        )
        calc_v2 = await _run_payslip(platform_doc=platform_v2, org_overrides=None)

        # Same gross, but the new platform rates flowed through into the payslip.
        assert calc_v2.gross == calc_v1.gross
        assert calc_v2.student_loan > calc_v1.student_loan, (
            "raising the platform student-loan rate must increase the "
            "non-overriding org's payslip student-loan deduction"
        )
        assert calc_v2.paye > calc_v1.paye, (
            "raising the platform PAYE bracket rates must increase the "
            "non-overriding org's payslip PAYE"
        )

    @pytest.mark.asyncio
    async def test_no_platform_row_falls_back_to_safety_net_numbers(self):
        """With no platform row at all, the payslip still computes against the
        Safety_Net — identical to the seeded 2024/25 document."""
        calc_safety = await _run_payslip(platform_doc=None, org_overrides=None)
        calc_seeded = await _run_payslip(
            platform_doc=_safety_net_document(), org_overrides=None
        )
        assert calc_safety.paye == calc_seeded.paye
        assert calc_safety.student_loan == calc_seeded.student_loan
        assert calc_safety.acc_levy == calc_seeded.acc_levy


# ===========================================================================
# Req 3.3 — an org override changes only that org's payslip
# ===========================================================================


class TestOrgOverrideIsolation:
    """Req 3.3 — an organisation override changes only that organisation's
    payslip; another org on the same platform default is unaffected."""

    @pytest.mark.asyncio
    async def test_override_changes_only_that_orgs_payslip(self):
        platform_doc = _safety_net_document()

        # Org A overrides only the student-loan rate (0.12 → 0.25).
        calc_a = await _run_payslip(
            platform_doc=platform_doc,
            org_overrides={"student_loan_rate": "0.25"},
        )
        # Org B has no override — it inherits the platform default.
        calc_b = await _run_payslip(platform_doc=platform_doc, org_overrides=None)
        # An independent no-override baseline (same platform, same gross).
        calc_baseline = await _run_payslip(
            platform_doc=platform_doc, org_overrides=None
        )

        # Same gross for everyone.
        assert calc_a.gross == calc_b.gross == calc_baseline.gross == Decimal("3200.00")

        # Org A's overridden field moved its payslip's student loan up.
        assert calc_a.student_loan > calc_b.student_loan, (
            "org A's student-loan override must raise org A's payslip "
            "student-loan deduction"
        )

        # Org B (no override) is unaffected by org A's override — it equals the
        # independent no-override baseline.
        assert calc_b.student_loan == calc_baseline.student_loan, (
            "org B must be unaffected by org A's override"
        )

        # And the override is confined to the overridden field: PAYE (driven by
        # the unchanged platform brackets) is identical for A and B.
        assert calc_a.paye == calc_b.paye, (
            "a student-loan override must not change PAYE — only the "
            "overridden field differs between the orgs"
        )
        assert calc_a.acc_levy == calc_b.acc_levy

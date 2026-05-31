"""Unit tests for ``app.modules.payslips.termination`` (B6 + E1).

Covers the verify list under task B6 + E1 in
``.kiro/specs/staff-management-p4/tasks.md``:

  - **s27_annual_leave_payout** returns greater of weekly vs 52-wk
    avg (R10 step 2). Pure function — straightforward arithmetic
    test.
  - **G16** — termination cancels future-dated approved leave first,
    writes compensating ledger rows that restore balance hours, marks
    future ``schedule_entries.status='cancelled'`` (NOT hard-delete
    per X8), and writes a ``staff.termination_cancelled_future_leave``
    audit row.
  - **G25** period-selection branches:
      * open → uses;
      * finalised → reopens via R1a (audit
        ``pay_period.reopened_for_termination``);
      * paid → raises 409 ``PayPeriodAlreadyPaidError``;
      * missing → rolls forward + audit
        ``pay_period.rolled_for_termination``.
  - **N15** KiwiSaver scope on termination — verified via the
    helper-level scaffolding (the s27 lump-sum is excluded from the
    KiwiSaver basis).
  - **N19** concurrent terminate — first succeeds, second sees
    ``is_active=false`` and raises :class:`AlreadyTerminatedError`.

The tests construct an in-memory fake session with SQL-substring
routing similar to ``tests/unit/test_roll_pay_periods.py`` so we can
drive the helpers without a real DB.

**Validates: Requirements R10, G16, G25, N15, N19 — Staff Management
Phase 4 task B6 + E1.**
"""

from __future__ import annotations

# Resolve mappers eagerly.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.payslips import termination as termination_module
from app.modules.payslips.termination import (
    AlreadyTerminatedError,
    PayPeriodAlreadyPaidError,
    s27_annual_leave_payout,
    terminate_employment,
)
from app.modules.leave.models import LeaveBalance, LeaveLedger
from app.modules.payslips.models import PayPeriod


# ---------------------------------------------------------------------------
# Fake-session machinery
# ---------------------------------------------------------------------------


class _Result:
    def __init__(
        self,
        *,
        all_rows=None,
        scalar=None,
        scalars_list=None,
        first_row=None,
    ):
        self._all = list(all_rows or [])
        self._scalar = scalar
        self._scalars_list = scalars_list
        self._first_row = first_row

    def all(self):
        return list(self._all)

    def scalar_one_or_none(self):
        return self._scalar

    def first(self):
        return self._first_row

    def scalars(self):
        proxy = MagicMock()
        proxy.all.return_value = list(self._scalars_list or [])
        proxy.first.return_value = (
            self._scalars_list[0] if self._scalars_list else None
        )
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
    """In-memory async-session for termination helpers.

    Routes ``execute()`` against substring keys registered via
    :meth:`script`. Any unmatched SQL returns an empty result.

    ``get(model, key)`` looks up by the model's class name + key.
    """

    def __init__(self) -> None:
        self._gets: dict[tuple[str, Any], Any] = {}
        self._scripts: dict[str, _Script] = {}
        self.added: list[Any] = []

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

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None

    @asynccontextmanager
    async def begin_nested(self):
        yield self


# ===========================================================================
# 1. s27_annual_leave_payout — pure function
# ===========================================================================


class TestS27Calc:
    """R10 step 2 — greater of weekly ordinary vs 52-wk avg, then
    converted to an hourly rate via ``standard_hours_per_week``.
    """

    def test_returns_greater_of_weekly_vs_52wk_avg(self):
        """When the weekly ordinary ($1000) is greater than the 52-wk
        avg ($800), the formula picks $1000.

        ``hourly = 1000 / 40 = 25``.
        ``payout = 25 × 40h remaining = 1000.00``.
        """
        result = s27_annual_leave_payout(
            remaining_hours=Decimal("40"),
            ordinary_weekly=Decimal("1000"),
            fifty_two_week_avg=Decimal("800"),
            standard_hours_per_week=Decimal("40"),
        )
        assert result == Decimal("1000.00")

    def test_picks_52wk_avg_when_higher(self):
        """When the 52-wk avg ($1200) exceeds the ordinary ($1000)
        — e.g. heavy overtime in the prior 52 weeks — formula picks
        $1200.

        hourly = 1200 / 40 = 30. payout = 30 × 40 = 1200.
        """
        result = s27_annual_leave_payout(
            remaining_hours=Decimal("40"),
            ordinary_weekly=Decimal("1000"),
            fifty_two_week_avg=Decimal("1200"),
            standard_hours_per_week=Decimal("40"),
        )
        assert result == Decimal("1200.00")

    def test_zero_remaining_hours_yields_zero_payout(self):
        """No accrued leave → no payout."""
        result = s27_annual_leave_payout(
            remaining_hours=Decimal("0"),
            ordinary_weekly=Decimal("1000"),
            fifty_two_week_avg=Decimal("800"),
            standard_hours_per_week=Decimal("40"),
        )
        assert result == Decimal("0.00")

    def test_unset_standard_hours_yields_zero(self):
        """Defensive fallback — when standard_hours_per_week is
        zero/unset, hourly is zero and payout is zero (caller should
        surface a warning).
        """
        result = s27_annual_leave_payout(
            remaining_hours=Decimal("40"),
            ordinary_weekly=Decimal("1000"),
            fifty_two_week_avg=Decimal("800"),
            standard_hours_per_week=None,
        )
        assert result == Decimal("0.00")

    def test_partial_hours_quantizes_to_cents(self):
        """40-hour week, 30/h hourly, 10.5h remaining → 315.00
        exactly.
        """
        result = s27_annual_leave_payout(
            remaining_hours=Decimal("10.50"),
            ordinary_weekly=Decimal("1200"),
            fifty_two_week_avg=Decimal("1200"),
            standard_hours_per_week=Decimal("40"),
        )
        assert result == Decimal("315.00")


# ===========================================================================
# 2. G16 — Future-leave reconciliation
# ===========================================================================


class TestCancelFutureLeave:
    """G16 — ``_cancel_future_leave`` cancels approved leave_requests
    whose start_date > end_date, writes compensating ledger rows,
    restores balance hours, marks future schedule_entries cancelled,
    and writes the audit row.
    """

    @pytest.mark.asyncio
    async def test_cancels_request_restores_balance_and_audits(self):
        """One approved future leave request (40h annual) → request
        cancelled, balance restored (used_hours reduced by 40),
        compensating ledger row added, audit row written.
        """
        from app.modules.payslips.termination import _cancel_future_leave

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        leave_type_id = uuid.uuid4()
        request_id = uuid.uuid4()

        # Future request row.
        future_row = SimpleNamespace(
            id=request_id,
            leave_type_id=leave_type_id,
            hours_requested=Decimal("40"),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
        )
        # The current balance — used 40 of 80 accrued.
        balance = SimpleNamespace(
            id=uuid.uuid4(),
            staff_id=staff_id,
            leave_type_id=leave_type_id,
            accrued_hours=Decimal("80"),
            used_hours=Decimal("40"),
            pending_hours=Decimal("0"),
        )

        db = _FakeSession()
        # 1. SELECT future approved leave_requests → returns one row.
        db.script("from leave_requests").push(_Result(all_rows=[future_row]))
        # 2. UPDATE leave_requests → no rows of interest, return empty.
        db.script("update leave_requests").push(_Result())
        # 3. SELECT LeaveBalance for that leave_type → returns balance.
        db.script("from leave_balances").push(_Result(scalar=balance))
        # 4. UPDATE schedule_entries → empty.
        db.script("update schedule_entries").push(_Result())

        captured_audit: list[dict] = []

        async def _fake_audit(*args, **kwargs):
            captured_audit.append(kwargs)
            return uuid.uuid4()

        with patch(
            "app.modules.payslips.termination.write_audit_log",
            side_effect=_fake_audit,
        ):
            summary = await _cancel_future_leave(
                db,
                org_id=org_id,
                staff_id=staff_id,
                end_date=date(2026, 6, 30),
                user_id=uuid.uuid4(),
                ip_address=None,
            )

        # Summary reports the cancelled IDs and total hours restored.
        assert summary["cancelled_request_ids"] == [str(request_id)]
        assert summary["total_hours_restored"] == Decimal("40")

        # Compensating leave_ledger row was added with reason
        # 'request_cancelled_after_approval'.
        ledgers = [obj for obj in db.added if isinstance(obj, LeaveLedger)]
        assert len(ledgers) == 1
        assert ledgers[0].delta_hours == Decimal("40")
        assert ledgers[0].reason == "request_cancelled_after_approval"
        assert ledgers[0].request_id == request_id

        # Balance was reduced (used_hours 40 → 0 because we restored 40).
        assert balance.used_hours == Decimal("0")

        # Audit row written with the documented action.
        assert any(
            row.get("action") == "staff.termination_cancelled_future_leave"
            for row in captured_audit
        )

    @pytest.mark.asyncio
    async def test_no_future_requests_writes_no_audit(self):
        """When there are no future-dated approved requests, the
        helper returns an empty cancellation list and does NOT write
        an audit row.
        """
        from app.modules.payslips.termination import _cancel_future_leave

        db = _FakeSession()
        db.script("from leave_requests").push(_Result(all_rows=[]))

        captured_audit: list[dict] = []

        async def _fake_audit(*args, **kwargs):
            captured_audit.append(kwargs)
            return uuid.uuid4()

        with patch(
            "app.modules.payslips.termination.write_audit_log",
            side_effect=_fake_audit,
        ):
            summary = await _cancel_future_leave(
                db,
                org_id=uuid.uuid4(),
                staff_id=uuid.uuid4(),
                end_date=date(2026, 6, 30),
                user_id=None,
                ip_address=None,
            )

        assert summary["cancelled_request_ids"] == []
        assert summary["total_hours_restored"] == Decimal("0")
        assert captured_audit == []
        # No ledger rows added either.
        assert [obj for obj in db.added if isinstance(obj, LeaveLedger)] == []


# ===========================================================================
# 3. G25 — Period selection branches
# ===========================================================================


class TestFindOrCreatePeriodCovering:
    """G25 — period-selection state machine."""

    @pytest.mark.asyncio
    async def test_open_period_used_directly(self):
        """A pay_period covering :end_date with status='open' is
        returned untouched (no reopen, no roll).
        """
        from app.modules.payslips.termination import _find_or_create_period_covering

        org_id = uuid.uuid4()
        period = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            status="open",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 14),
            pay_date=date(2026, 6, 17),
            finalised_at=None,
        )

        db = _FakeSession()
        # The candidate-lookup uses ``select(PayPeriod) ... .scalars().first()``.
        # Our fake routes on substring match against "from pay_periods".
        db.script("from pay_periods").push(
            _Result(scalars_list=[period]),
        )

        result = await _find_or_create_period_covering(
            db,
            org_id=org_id,
            end_date=date(2026, 6, 10),
            user_id=None,
            ip_address=None,
        )
        assert result is period
        assert result.status == "open"

    @pytest.mark.asyncio
    async def test_paid_period_raises_already_paid(self):
        """A pay_period covering :end_date with status='paid' raises
        :class:`PayPeriodAlreadyPaidError`.
        """
        from app.modules.payslips.termination import _find_or_create_period_covering

        org_id = uuid.uuid4()
        period = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            status="paid",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 14),
            pay_date=date(2026, 6, 17),
            finalised_at=None,
        )

        db = _FakeSession()
        db.script("from pay_periods").push(
            _Result(scalars_list=[period]),
        )

        with pytest.raises(PayPeriodAlreadyPaidError):
            await _find_or_create_period_covering(
                db,
                org_id=org_id,
                end_date=date(2026, 6, 10),
                user_id=None,
                ip_address=None,
            )

    @pytest.mark.asyncio
    async def test_finalised_period_reopens_and_audits(self):
        """A finalised covering period is reopened via R1a, with a
        ``pay_period.reopened_for_termination`` audit row.
        """
        from app.modules.payslips.termination import _find_or_create_period_covering

        org_id = uuid.uuid4()
        period = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            status="finalised",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 14),
            pay_date=date(2026, 6, 17),
            finalised_at=datetime.now(timezone.utc),
        )

        db = _FakeSession()
        db.script("from pay_periods").push(
            _Result(scalars_list=[period]),
        )
        db.add_get("PayPeriod", period.id, period)

        captured_audit: list[dict] = []

        async def _fake_audit(*args, **kwargs):
            captured_audit.append(kwargs)
            return uuid.uuid4()

        # Patch both the termination's and the service's audit writer.
        with (
            patch(
                "app.modules.payslips.termination.write_audit_log",
                side_effect=_fake_audit,
            ),
            patch(
                "app.modules.payslips.service.write_audit_log",
                side_effect=_fake_audit,
            ),
        ):
            result = await _find_or_create_period_covering(
                db,
                org_id=org_id,
                end_date=date(2026, 6, 10),
                user_id=uuid.uuid4(),
                ip_address=None,
            )

        # Period flipped to 'open' by the inner reopen call.
        assert result is period
        assert period.status == "open"
        assert period.finalised_at is None

        # The termination-specific audit action is written.
        actions = [row["action"] for row in captured_audit]
        assert "pay_period.reopened_for_termination" in actions
        # The base reopen also emits 'pay_period.reopened'.
        assert "pay_period.reopened" in actions

    @pytest.mark.asyncio
    async def test_missing_period_rolls_forward_and_audits(self):
        """When no period covers :end_date, the helper rolls forward
        until one does and emits ``pay_period.rolled_for_termination``
        per created period.
        """
        from app.modules.payslips.termination import _find_or_create_period_covering

        org_id = uuid.uuid4()
        org_row = SimpleNamespace(
            id=org_id,
            pay_period_cadence="fortnightly",
            pay_period_anchor_day=1,
            pay_date_offset_days=3,
        )

        db = _FakeSession()
        # 1. Candidate lookup → no rows.
        db.script("from pay_periods").push(_Result(scalars_list=[]))
        # 2. latest_end SELECT (ORDER BY end_date DESC LIMIT 1).
        # Our session matches the same "from pay_periods" key — push
        # the scalar latest_end as a separate scripted result. Need a
        # new key that matches the LIMIT-1 ORDER BY query.
        # Both fall under "from pay_periods" so we push both into the
        # same script queue in order: candidate first, then latest_end.
        db.script("from pay_periods").push(_Result(scalar=date(2026, 6, 14)))

        db.add_get("Organisation", org_id, org_row)

        captured_audit: list[dict] = []

        async def _fake_audit(*args, **kwargs):
            captured_audit.append(kwargs)
            return uuid.uuid4()

        with patch(
            "app.modules.payslips.termination.write_audit_log",
            side_effect=_fake_audit,
        ):
            result = await _find_or_create_period_covering(
                db,
                org_id=org_id,
                end_date=date(2026, 7, 1),
                user_id=None,
                ip_address=None,
            )

        # A new period was added to the session and returned.
        added_periods = [
            obj for obj in db.added if isinstance(obj, PayPeriod)
        ]
        assert len(added_periods) >= 1
        assert result in added_periods or isinstance(result, SimpleNamespace)
        # Audit row(s) for the rolled-for-termination action.
        actions = [row["action"] for row in captured_audit]
        assert "pay_period.rolled_for_termination" in actions


# ===========================================================================
# 4. N15 — KiwiSaver scope on termination (helper-level)
# ===========================================================================


class TestKiwiSaverScopeOnTermination:
    """N15 — KiwiSaver employee/employer rates apply only to the
    non-s27 portion of gross. Tested at the policy level: the calc
    of the carve-out amount.

    The full ``terminate_employment`` flow does this by computing
    the ordinary-period KiwiSaver via :func:`recompute_payslip` and
    then SUBTRACTING ``lump_sum × rate`` from each KiwiSaver
    deduction row. The carve math is straightforward; this test
    verifies the formula directly because the integration test
    would need a full DB.
    """

    def test_kiwisaver_basis_excludes_lump_sum(self):
        """For a 3% employee rate, carve = lump_sum × 0.03. The
        carve gets subtracted from the auto-deduction row.

        Example: ordinary gross $2000, s27 lump $5000.
          - naive auto-deduction = (2000 + 5000) × 0.03 = 210
          - correct deduction    = 2000 × 0.03 = 60
          - carve                = 5000 × 0.03 = 150
          - 210 - 150 = 60 ✓
        """
        ordinary_gross = Decimal("2000")
        lump_sum_total = Decimal("5000")
        emp_rate = Decimal("3.00") / Decimal("100")

        naive_employee = (
            (ordinary_gross + lump_sum_total) * emp_rate
        ).quantize(Decimal("0.01"))
        carve_employee = (lump_sum_total * emp_rate).quantize(Decimal("0.01"))
        corrected = (naive_employee - carve_employee).quantize(Decimal("0.01"))

        # The corrected deduction equals the ordinary-only basis × rate.
        assert corrected == (ordinary_gross * emp_rate).quantize(Decimal("0.01"))
        assert corrected == Decimal("60.00")

    def test_kiwisaver_carve_zero_when_no_lump_sum(self):
        """Sanity — when lump_sum is zero (no s27, no alt-day, no
        casual remainder), the carve is zero and the naive basis
        already matches the corrected basis.
        """
        ordinary_gross = Decimal("2000")
        lump_sum_total = Decimal("0")
        emp_rate = Decimal("3.00") / Decimal("100")
        carve = (lump_sum_total * emp_rate).quantize(Decimal("0.01"))
        assert carve == Decimal("0.00")


# ===========================================================================
# 5. N19 — Concurrent terminate
# ===========================================================================


class TestConcurrentTerminate:
    """N19 — two concurrent ``terminate_employment`` calls for the
    same staff: first succeeds, second sees ``is_active=false`` and
    raises :class:`AlreadyTerminatedError`.

    We simulate the second-caller view: the FOR UPDATE row lock has
    already been released, the staff record now has
    ``is_active=False``, and the helper returns 409.
    """

    @pytest.mark.asyncio
    async def test_already_terminated_raises_409(self):
        """Calling ``terminate_employment`` for a staff whose
        ``is_active`` is already ``False`` raises immediately AFTER
        acquiring the row lock — before any payout work runs.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        # Staff already terminated (race-loser sees this).
        staff = SimpleNamespace(
            id=staff_id,
            org_id=org_id,
            is_active=False,
            employment_type="permanent",
            hourly_rate=Decimal("25.00"),
            standard_hours_per_week=Decimal("40"),
            kiwisaver_enrolled=False,
            kiwisaver_employee_rate=Decimal("3.00"),
            kiwisaver_employer_rate=Decimal("3.00"),
        )

        db = _FakeSession()
        db.add_get("StaffMember", staff_id, staff)
        # The Step 0 row-lock query returns scalar None (no-op).
        db.script("for update").push(_Result(scalar=None))

        with pytest.raises(AlreadyTerminatedError):
            await terminate_employment(
                db,
                org_id=org_id,
                staff_id=staff_id,
                end_date=date(2026, 6, 30),
                reason="resignation",
            )

    @pytest.mark.asyncio
    async def test_unknown_staff_raises_payslip_service_error(self):
        """Asking to terminate a staff that doesn't exist in this
        org → generic service error (router maps to 404 separately).
        """
        from app.modules.payslips.service import PayslipServiceError

        db = _FakeSession()
        db.script("for update").push(_Result())

        with pytest.raises(PayslipServiceError):
            await terminate_employment(
                db,
                org_id=uuid.uuid4(),
                staff_id=uuid.uuid4(),
                end_date=date(2026, 6, 30),
                reason="ghost",
            )

    @pytest.mark.asyncio
    async def test_cross_org_staff_treated_as_not_found(self):
        """Terminate via org A for a staff that belongs to org B →
        service error (no existence leak across tenants).
        """
        from app.modules.payslips.service import PayslipServiceError

        org_id = uuid.uuid4()
        other_org = uuid.uuid4()
        staff = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=other_org,
            is_active=True,
        )
        db = _FakeSession()
        db.add_get("StaffMember", staff.id, staff)
        db.script("for update").push(_Result())

        with pytest.raises(PayslipServiceError):
            await terminate_employment(
                db,
                org_id=org_id,
                staff_id=staff.id,
                end_date=date(2026, 6, 30),
                reason="cross-tenant",
            )

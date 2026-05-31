"""Unit tests for ``app.modules.payslips.service`` (B4 + E1).

Covers the verify list under task B4 + E1 in
``.kiro/specs/staff-management-p4/tasks.md``:

  - **G4 recurring-allowance auto-attach** —
    ``_auto_attach_recurring_allowances`` looks up active rules and
    inserts one ``payslip_allowances`` row per match using the
    overrides-or-defaults / unit-aware quantity logic.
  - **G21 reopen_pay_period** — finalised → open succeeds; paid →
    409; open → 422.
  - ``finalise_payslip`` on a finalised payslip → 409
    ``PayslipImmutableError``.
  - ``void_payslip`` on a draft inside an open period → status flips
    to ``'voided'``.
  - ``update_payslip_fields`` on a finalised payslip with
    non-``emailed_at`` columns → 409 (P4-N26 column allowlist).

We avoid spinning up Postgres by driving the service functions
against an in-memory fake session that captures ``db.add`` calls and
serves duck-typed objects from ``db.get``. Every test patches
``write_audit_log`` so the SQL ``INSERT INTO audit_log`` never runs.

**Validates: Requirements R3, R4, R8, R9, R1a — Staff Management
Phase 4 task B4 + E1.**
"""

from __future__ import annotations

# Eager imports so SQLAlchemy can resolve mappers transitively.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.payslips import service as payslips_service
from app.modules.payslips.models import (
    AllowanceType,
    PayPeriod,
    Payslip,
    PayslipAllowance,
    StaffRecurringAllowance,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Result:
    """Minimal stand-in for ``AsyncSession.execute()`` return value."""

    def __init__(
        self,
        *,
        all_rows: list | None = None,
        scalar=None,
        scalars_list: list | None = None,
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
class _SelectScript:
    """A queue of pre-canned ``execute()`` return values for tests
    that need to drive a sequence of selects (e.g.
    ``_auto_attach_recurring_allowances`` runs three selects in order).
    """

    queue: list[_Result] = field(default_factory=list)

    def push(self, result: _Result) -> None:
        self.queue.append(result)

    def pop(self) -> _Result:
        if not self.queue:
            return _Result()  # default empty
        return self.queue.pop(0)


class _FakeSession:
    """In-memory async-session stand-in.

    The fake supports:

      - ``get(model, key)`` — returns from a per-model dict registered
        via :meth:`add_get`.
      - ``execute(stmt, params=None)`` — pops the next pre-scripted
        result if a script was registered, else returns an empty
        result.
      - ``add(obj)`` — appends to ``self.added``.
      - ``flush`` / ``refresh`` — no-ops (refresh is a no-op against
        in-memory test doubles per the project conventions).
      - ``begin_nested`` — yields self so the caller's ``async with``
        works without spinning up a real SAVEPOINT.
    """

    def __init__(self) -> None:
        self._gets: dict[tuple[str, Any], Any] = {}
        self.added: list[Any] = []
        self.deleted_filters: list[Any] = []
        self._scripts: dict[str, _SelectScript] = {}

    def add_get(self, model_name: str, key: Any, value: Any) -> None:
        self._gets[(model_name, key)] = value

    def script(self, key: str) -> _SelectScript:
        if key not in self._scripts:
            self._scripts[key] = _SelectScript()
        return self._scripts[key]

    async def get(self, model, key):
        return self._gets.get((model.__name__, key))

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        # Match any pre-registered substring script in registration
        # order.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_period(*, status: str = "open"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        status=status,
        finalised_at=(
            datetime.now(timezone.utc) if status == "finalised" else None
        ),
        start_date=None,
        end_date=None,
        pay_date=None,
    )


def _make_staff(
    *,
    org_id: uuid.UUID | None = None,
    is_active: bool = True,
    employment_type: str = "permanent",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        is_active=is_active,
        hourly_rate=Decimal("25.00"),
        overtime_rate=None,
        kiwisaver_enrolled=False,
        kiwisaver_employee_rate=Decimal("3.00"),
        kiwisaver_employer_rate=Decimal("3.00"),
        employment_type=employment_type,
        standard_hours_per_week=Decimal("40.00"),
        first_name="Jane",
        name="Jane Doe",
        email="jane@example.com",
    )


def _make_payslip(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID | None = None,
    pay_period_id: uuid.UUID | None = None,
    status: str = "draft",
    public_holiday_rate: Decimal | None = None,
    pdf_file_key: str | None = None,
    emailed_at=None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id or uuid.uuid4(),
        pay_period_id=pay_period_id or uuid.uuid4(),
        status=status,
        public_holiday_rate=public_holiday_rate,
        pdf_file_key=pdf_file_key,
        emailed_at=emailed_at,
        finalised_at=None,
        notes=None,
        ordinary_hours=Decimal("0"),
        overtime_hours=Decimal("0"),
        public_holiday_hours=Decimal("0"),
        ordinary_rate=Decimal("25.00"),
        overtime_rate=None,
        gross_pay=Decimal("0"),
        gross_ytd=Decimal("0"),
        net_pay=Decimal("0"),
    )


# ===========================================================================
# G4 — Recurring allowance auto-attach
# ===========================================================================


class TestRecurringAllowanceAutoAttach:
    """G4 — ``_auto_attach_recurring_allowances`` inserts one
    ``payslip_allowances`` row per active recurring rule, using the
    rule's override or the catalogue default, and copies the unit at
    attach time.
    """

    @pytest.mark.asyncio
    async def test_auto_attach_inserts_one_payslip_allowance_per_rule(self):
        """One active rule → one ``PayslipAllowance`` row added with
        the rule's override amount, the catalogue's unit, the
        catalogue's name as label.
        """
        from app.modules.payslips.service import _auto_attach_recurring_allowances

        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        period = _make_period()
        period.start_date = __import__("datetime").date(2026, 6, 1)
        period.end_date = __import__("datetime").date(2026, 6, 14)
        payslip = _make_payslip(
            org_id=org_id, staff_id=staff.id, pay_period_id=period.id,
        )

        atype_id = uuid.uuid4()
        atype = SimpleNamespace(
            id=atype_id,
            org_id=org_id,
            code="meal_allowance",
            name="Meal allowance",
            taxable=True,
            default_amount=Decimal("25.00"),
            unit="period",
            active=True,
        )
        rule = SimpleNamespace(
            id=uuid.uuid4(),
            staff_id=staff.id,
            allowance_type_id=atype_id,
            amount=Decimal("50.00"),  # override
            quantity=None,
            active=True,
        )

        db = _FakeSession()
        # Script the three selects the helper makes:
        # 1. SELECT recurring rules → returns [rule]
        db.script("staff_recurring_allowances").push(
            _Result(scalars_list=[rule]),
        )
        # 2. SELECT allowance_types IN type_ids → returns [atype]
        db.script("from allowance_types").push(
            _Result(scalars_list=[atype]),
        )
        # 3. SELECT existing allowance_type_ids on payslip → []
        db.script("payslip_allowances").push(_Result(all_rows=[]))

        await _auto_attach_recurring_allowances(
            db, payslip=payslip, staff=staff, period=period,
        )

        # One row inserted.
        added_allowances = [
            obj for obj in db.added if isinstance(obj, PayslipAllowance)
        ]
        assert len(added_allowances) == 1
        line = added_allowances[0]
        assert line.payslip_id == payslip.id
        assert line.allowance_type_id == atype_id
        assert line.label == "Meal allowance"
        assert line.amount == Decimal("50.00")  # override beats default
        assert line.quantity == Decimal("1")  # unit='period'
        assert line.unit == "period"  # copied from the catalogue
        assert line.taxable is True

    @pytest.mark.asyncio
    async def test_no_active_rules_no_lines_attached(self):
        """When the staff has no recurring rules, the helper does
        nothing (no inserts, no errors).
        """
        from app.modules.payslips.service import _auto_attach_recurring_allowances

        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        period = _make_period()
        period.start_date = __import__("datetime").date(2026, 6, 1)
        period.end_date = __import__("datetime").date(2026, 6, 14)
        payslip = _make_payslip(
            org_id=org_id, staff_id=staff.id, pay_period_id=period.id,
        )

        db = _FakeSession()
        # Empty rule list.
        db.script("staff_recurring_allowances").push(
            _Result(scalars_list=[]),
        )

        await _auto_attach_recurring_allowances(
            db, payslip=payslip, staff=staff, period=period,
        )

        added_allowances = [
            obj for obj in db.added if isinstance(obj, PayslipAllowance)
        ]
        assert added_allowances == []

    @pytest.mark.asyncio
    async def test_skips_rule_when_existing_line_for_same_type(self):
        """If the payslip already has a line for the rule's
        allowance_type, the helper does NOT add a duplicate.
        """
        from app.modules.payslips.service import _auto_attach_recurring_allowances

        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        period = _make_period()
        period.start_date = __import__("datetime").date(2026, 6, 1)
        period.end_date = __import__("datetime").date(2026, 6, 14)
        payslip = _make_payslip(
            org_id=org_id, staff_id=staff.id, pay_period_id=period.id,
        )

        atype_id = uuid.uuid4()
        atype = SimpleNamespace(
            id=atype_id,
            unit="period",
            default_amount=Decimal("10.00"),
            name="Tool",
            taxable=True,
            active=True,
        )
        rule = SimpleNamespace(
            id=uuid.uuid4(),
            staff_id=staff.id,
            allowance_type_id=atype_id,
            amount=None,
            quantity=None,
            active=True,
        )

        db = _FakeSession()
        db.script("staff_recurring_allowances").push(
            _Result(scalars_list=[rule]),
        )
        db.script("from allowance_types").push(
            _Result(scalars_list=[atype]),
        )
        # Existing payslip_allowance row already references this type.
        db.script("payslip_allowances").push(
            _Result(all_rows=[SimpleNamespace(allowance_type_id=atype_id)]),
        )

        await _auto_attach_recurring_allowances(
            db, payslip=payslip, staff=staff, period=period,
        )

        added_allowances = [
            obj for obj in db.added if isinstance(obj, PayslipAllowance)
        ]
        assert added_allowances == []


# ===========================================================================
# G21 — reopen_pay_period state machine
# ===========================================================================


class TestReopenPayPeriod:
    """G21 — finalised → open succeeds; paid → 409; open → 422."""

    @pytest.mark.asyncio
    async def test_finalised_period_reopens_to_open(self):
        org_id = uuid.uuid4()
        period = _make_period(status="finalised")
        period.org_id = org_id
        period.finalised_at = datetime.now(timezone.utc)

        db = _FakeSession()
        db.add_get("PayPeriod", period.id, period)

        async def _fake_audit(*args, **kwargs):
            return uuid.uuid4()

        with patch(
            "app.modules.payslips.service.write_audit_log",
            side_effect=_fake_audit,
        ):
            result = await payslips_service.reopen_pay_period(
                db,
                org_id=org_id,
                period_id=period.id,
                reason="found a bug in payslip 12",
                user_id=uuid.uuid4(),
            )

        assert result is period
        assert period.status == "open"
        assert period.finalised_at is None

    @pytest.mark.asyncio
    async def test_paid_period_refuses_with_period_already_paid(self):
        org_id = uuid.uuid4()
        period = _make_period(status="paid")
        period.org_id = org_id

        db = _FakeSession()
        db.add_get("PayPeriod", period.id, period)

        with pytest.raises(payslips_service.PeriodAlreadyPaidError):
            await payslips_service.reopen_pay_period(
                db,
                org_id=org_id,
                period_id=period.id,
                reason="cant",
            )
        # Period unchanged.
        assert period.status == "paid"

    @pytest.mark.asyncio
    async def test_open_period_refuses_with_period_already_open(self):
        org_id = uuid.uuid4()
        period = _make_period(status="open")
        period.org_id = org_id

        db = _FakeSession()
        db.add_get("PayPeriod", period.id, period)

        with pytest.raises(payslips_service.PeriodAlreadyOpenError):
            await payslips_service.reopen_pay_period(
                db,
                org_id=org_id,
                period_id=period.id,
                reason="redundant",
            )
        assert period.status == "open"

    @pytest.mark.asyncio
    async def test_unknown_period_raises_pay_period_not_found(self):
        org_id = uuid.uuid4()
        db = _FakeSession()
        # No period registered.

        with pytest.raises(payslips_service.PayPeriodNotFoundError):
            await payslips_service.reopen_pay_period(
                db,
                org_id=org_id,
                period_id=uuid.uuid4(),
                reason="ghost",
            )

    @pytest.mark.asyncio
    async def test_cross_tenant_period_returns_not_found(self):
        """Period from a different org is treated as not-found
        (no existence leak).
        """
        org_id = uuid.uuid4()
        other_org = uuid.uuid4()
        period = _make_period(status="finalised")
        period.org_id = other_org

        db = _FakeSession()
        db.add_get("PayPeriod", period.id, period)

        with pytest.raises(payslips_service.PayPeriodNotFoundError):
            await payslips_service.reopen_pay_period(
                db,
                org_id=org_id,
                period_id=period.id,
                reason="cross-tenant",
            )


# ===========================================================================
# finalise_payslip on finalised → 409
# ===========================================================================


class TestFinalisePayslip:
    @pytest.mark.asyncio
    async def test_finalising_already_finalised_raises_immutable(self):
        """``PayslipImmutableError`` (409) — re-finalising is refused."""
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="finalised")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        with pytest.raises(payslips_service.PayslipImmutableError):
            await payslips_service.finalise_payslip(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
            )

    @pytest.mark.asyncio
    async def test_finalising_voided_raises_immutable(self):
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="voided")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        with pytest.raises(payslips_service.PayslipImmutableError):
            await payslips_service.finalise_payslip(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
            )

    @pytest.mark.asyncio
    async def test_unknown_payslip_raises_not_found(self):
        org_id = uuid.uuid4()
        db = _FakeSession()
        with pytest.raises(payslips_service.PayslipNotFoundError):
            await payslips_service.finalise_payslip(
                db,
                org_id=org_id,
                payslip_id=uuid.uuid4(),
            )


# ===========================================================================
# void_payslip on draft → status='voided'
# ===========================================================================


class TestVoidPayslip:
    @pytest.mark.asyncio
    async def test_voiding_draft_in_open_period_succeeds(self):
        org_id = uuid.uuid4()
        period = _make_period(status="open")
        period.org_id = org_id
        payslip = _make_payslip(
            org_id=org_id,
            status="draft",
            pay_period_id=period.id,
        )

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)
        db.add_get("PayPeriod", period.id, period)

        async def _fake_audit(*args, **kwargs):
            return uuid.uuid4()

        with patch(
            "app.modules.payslips.service.write_audit_log",
            side_effect=_fake_audit,
        ):
            result = await payslips_service.void_payslip(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                reason="duplicate from re-generation",
            )

        assert result is payslip
        assert payslip.status == "voided"

    @pytest.mark.asyncio
    async def test_voiding_when_period_finalised_refuses(self):
        org_id = uuid.uuid4()
        period = _make_period(status="finalised")
        period.org_id = org_id
        payslip = _make_payslip(
            org_id=org_id,
            status="draft",
            pay_period_id=period.id,
        )

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)
        db.add_get("PayPeriod", period.id, period)

        with pytest.raises(payslips_service.PeriodFinalisedError):
            await payslips_service.void_payslip(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                reason="cant",
            )
        assert payslip.status == "draft"

    @pytest.mark.asyncio
    async def test_voiding_when_period_paid_refuses(self):
        org_id = uuid.uuid4()
        period = _make_period(status="paid")
        period.org_id = org_id
        payslip = _make_payslip(
            org_id=org_id,
            status="draft",
            pay_period_id=period.id,
        )

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)
        db.add_get("PayPeriod", period.id, period)

        with pytest.raises(payslips_service.PeriodAlreadyPaidError):
            await payslips_service.void_payslip(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                reason="paid",
            )
        assert payslip.status == "draft"


# ===========================================================================
# update_payslip_fields — column allowlist (P4-N26)
# ===========================================================================


class TestUpdatePayslipFieldsAllowlist:
    """P4-N26 — finalised payslips ONLY allow ``emailed_at`` updates;
    every other column refused with ``PayslipImmutableError`` (409).
    """

    @pytest.mark.asyncio
    async def test_finalised_payslip_with_non_allowlist_field_raises_409(self):
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="finalised")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        with pytest.raises(payslips_service.PayslipImmutableError):
            await payslips_service.update_payslip_fields(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                fields={"ordinary_hours": Decimal("10")},
            )

    @pytest.mark.asyncio
    async def test_finalised_payslip_with_emailed_at_succeeds(self):
        """Sanity — the allowlist permits ``emailed_at``."""
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="finalised")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        # No audit row is written for status='finalised' updates.
        ts = datetime.now(timezone.utc)
        result = await payslips_service.update_payslip_fields(
            db,
            org_id=org_id,
            payslip_id=payslip.id,
            fields={"emailed_at": ts},
        )
        assert result is payslip
        assert payslip.emailed_at == ts

    @pytest.mark.asyncio
    async def test_voided_payslip_is_fully_immutable(self):
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="voided")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        with pytest.raises(payslips_service.PayslipImmutableError):
            await payslips_service.update_payslip_fields(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                fields={"emailed_at": datetime.now(timezone.utc)},
            )

    @pytest.mark.asyncio
    async def test_draft_payslip_accepts_documented_edit_fields(self):
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="draft")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        async def _fake_audit(*args, **kwargs):
            return uuid.uuid4()

        with patch(
            "app.modules.payslips.service.write_audit_log",
            side_effect=_fake_audit,
        ):
            result = await payslips_service.update_payslip_fields(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                fields={"public_holiday_rate": Decimal("40.00")},
            )

        assert result is payslip
        assert payslip.public_holiday_rate == Decimal("40.00")

    @pytest.mark.asyncio
    async def test_draft_payslip_rejects_non_allowlist_field(self):
        """Even on a draft, a non-allowlist column (e.g. ``status``)
        is refused.
        """
        org_id = uuid.uuid4()
        payslip = _make_payslip(org_id=org_id, status="draft")

        db = _FakeSession()
        db.add_get("Payslip", payslip.id, payslip)

        with pytest.raises(payslips_service.PayslipImmutableError):
            await payslips_service.update_payslip_fields(
                db,
                org_id=org_id,
                payslip_id=payslip.id,
                fields={"status": "finalised"},
            )

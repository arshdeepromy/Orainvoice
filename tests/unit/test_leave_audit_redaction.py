"""Audit-redaction lint test (P2-N6).

This test enforces a narrow but important contract: when the leave
service writes an audit row for a confidential leave type
(``leave_type.confidential_visibility=True``), the ``after_value`` dict
must NOT contain any of:

    {'reason', 'decision_notes', 'relationship_to_subject',
     'attachment_upload_id'}

We verify this two ways for defence in depth:

1. **Static (AST-level) check** — parse
   ``app/modules/leave/service.py`` and confirm every
   ``write_audit_log(...)`` call site computes its ``after_value``
   through the central ``_audit_after_value(...)`` helper. This is the
   single redaction control point so any future call site that tries
   to write an unredacted dict literal would fail this assertion.

2. **Runtime check** — drive ``submit_request`` against a confidential
   (``family_violence``) leave type, capture the actual call to
   ``write_audit_log``, and assert the captured ``after_value`` dict
   is missing the four redacted keys. This guards the runtime shape
   independently of the AST check.

Together: a future contributor cannot weaken redaction without one of
these tests failing.

**Validates: Requirements R4.6, R15, P2-N6 — Staff Phase 2 task B3**
"""

from __future__ import annotations

import ast
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.leave.models import LeaveBalance, LeaveRequest, LeaveType
from app.modules.leave.service import submit_request
from app.modules.staff.models import StaffMember


# ---------------------------------------------------------------------------
# 1. Static AST check
# ---------------------------------------------------------------------------


REDACTED_KEYS = frozenset(
    {"reason", "decision_notes", "relationship_to_subject", "attachment_upload_id"}
)


def _service_source_path() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "modules" / "leave" / "service.py"


def _collect_write_audit_log_calls(tree: ast.AST) -> list[ast.Call]:
    """Find every ``write_audit_log(...)`` call site in the AST."""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match ``write_audit_log(...)`` (direct name) and ``app.core.audit.write_audit_log(...)``.
        if isinstance(func, ast.Name) and func.id == "write_audit_log":
            calls.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == "write_audit_log":
            calls.append(node)
    return calls


def _resolve_after_value_kwarg(call: ast.Call) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == "after_value":
            return kw.value
    return None


class TestAstAuditCalls:
    """Every ``write_audit_log`` call routes ``after_value`` through the
    central redaction helper, guaranteeing the redaction rule cannot be
    bypassed by a future inline dict literal.
    """

    def test_leave_request_audit_calls_use_redaction_helper(self):
        source = _service_source_path().read_text()
        tree = ast.parse(source)
        calls = _collect_write_audit_log_calls(tree)
        assert calls, "expected at least one write_audit_log call"

        leave_request_calls = []
        for call in calls:
            for kw in call.keywords:
                if kw.arg == "action" and isinstance(kw.value, ast.Constant):
                    if str(kw.value.value).startswith("leave_request."):
                        leave_request_calls.append(call)
                        break

        assert leave_request_calls, (
            "expected at least one leave_request.* audit call"
        )

        for call in leave_request_calls:
            after_value = _resolve_after_value_kwarg(call)
            assert after_value is not None, (
                "every leave_request audit call must pass after_value"
            )
            # The after_value MUST be a call to ``_audit_after_value(...)``
            # — this is the single chokepoint that applies the redaction
            # rule.
            assert isinstance(after_value, ast.Call), (
                "leave_request audit calls must compute after_value via "
                "the _audit_after_value() helper, not via a dict literal"
            )
            func = after_value.func
            func_name = (
                func.id if isinstance(func, ast.Name)
                else getattr(func, "attr", None)
            )
            assert func_name == "_audit_after_value", (
                f"leave_request audit call uses {func_name!r} for "
                f"after_value; must use _audit_after_value() so the "
                f"P2-N6 redaction rule cannot be bypassed."
            )


# ---------------------------------------------------------------------------
# 2. Runtime check — confidential family_violence submit
# ---------------------------------------------------------------------------


def _make_staff() -> StaffMember:
    return StaffMember(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Confidential Subject",
        first_name="Conf",
        last_name="Subject",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        standard_hours_per_week=Decimal("40.00"),
        shift_start="09:00",
        shift_end="17:00",
        employment_type="permanent",
    )


def _make_fv_leave_type(org_id: uuid.UUID) -> LeaveType:
    return LeaveType(
        id=uuid.uuid4(),
        org_id=org_id,
        code="family_violence",
        name="Family violence leave",
        is_paid=True,
        accrual_method="per_period",
        accrual_amount=Decimal("80"),
        accrual_unit="hours",
        carry_over_max=Decimal("80"),
        is_statutory=True,
        requires_doctor_note=False,
        confidential_visibility=True,
        active=True,
        display_order=4,
    )


def _make_db_for_submit(staff, leave_type, balance) -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db._added: list = []

    def _fake_add(obj):
        db._added.append(obj)
        if isinstance(obj, LeaveRequest):
            if obj.id is None:
                obj.id = uuid.uuid4()

    db.add.side_effect = _fake_add

    async def _fake_get(model, key):
        if model is StaffMember:
            return staff if key == staff.id else None
        if model is LeaveType:
            return leave_type if key == leave_type.id else None
        return None

    db.get = AsyncMock(side_effect=_fake_get)

    async def _fake_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = balance
        result.scalar.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db


class TestRuntimeAuditRedaction:
    """Driving submit_request with a confidential leave type produces an
    audit ``after_value`` that strips the four redacted keys.
    """

    @pytest.mark.asyncio
    async def test_confidential_submit_after_value_omits_redacted_keys(self):
        org_id = uuid.uuid4()
        staff = _make_staff()
        # Override staff.org_id to match.
        staff.org_id = org_id
        leave_type = _make_fv_leave_type(org_id)
        balance = LeaveBalance(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=leave_type.id,
            accrued_hours=Decimal("80"),
            used_hours=Decimal("0"),
            pending_hours=Decimal("0"),
        )
        db = _make_db_for_submit(staff, leave_type, balance)

        captured: list[dict] = []

        async def _fake_audit(session, **kwargs):
            captured.append(kwargs)
            return uuid.uuid4()

        payload = SimpleNamespace(
            leave_type_id=leave_type.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
            reason="HIGHLY-CONFIDENTIAL-FREE-TEXT",
            relationship_to_subject=None,  # FV is not bereavement
            partial_day_start_time=None,
            attachment_upload_id=uuid.uuid4(),
        )

        with patch(
            "app.modules.leave.service.write_audit_log",
            side_effect=_fake_audit,
        ):
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )

        assert len(captured) == 1
        after = captured[0]["after_value"]
        # The confidential redaction rule strips ALL four keys, even
        # though the inbound payload supplied them.
        for key in REDACTED_KEYS:
            assert key not in after, (
                f"confidential audit row leaked redacted key {key!r}: "
                f"{after!r}"
            )
        # And the safe keys are still present so the audit row is useful.
        assert after["leave_type_code"] == "family_violence"
        assert after["staff_id"] == str(staff.id)
        assert after["status"] == "pending"
        assert after["start_date"] == "2026-06-01"
        assert after["end_date"] == "2026-06-01"

    @pytest.mark.asyncio
    async def test_non_confidential_submit_includes_full_payload(self):
        """Sanity check the redactor only applies to confidential types
        — annual-leave audit rows still carry the reason field.
        """
        org_id = uuid.uuid4()
        staff = _make_staff()
        staff.org_id = org_id
        leave_type = LeaveType(
            id=uuid.uuid4(),
            org_id=org_id,
            code="annual",
            name="Annual leave",
            is_paid=True,
            accrual_method="anniversary",
            accrual_amount=None,
            accrual_unit="hours",
            carry_over_max=None,
            is_statutory=True,
            requires_doctor_note=False,
            confidential_visibility=False,
            active=True,
            display_order=1,
        )
        balance = LeaveBalance(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=leave_type.id,
            accrued_hours=Decimal("80"),
            used_hours=Decimal("0"),
            pending_hours=Decimal("0"),
        )
        db = _make_db_for_submit(staff, leave_type, balance)

        captured: list[dict] = []

        async def _fake_audit(session, **kwargs):
            captured.append(kwargs)
            return uuid.uuid4()

        payload = SimpleNamespace(
            leave_type_id=leave_type.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            hours_requested=Decimal("40"),
            reason="Family trip",
            relationship_to_subject=None,
            partial_day_start_time=None,
            attachment_upload_id=None,
        )

        with patch(
            "app.modules.leave.service.write_audit_log",
            side_effect=_fake_audit,
        ):
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )

        assert len(captured) == 1
        after = captured[0]["after_value"]
        # Non-confidential → reason is present in the audit row.
        assert after["reason"] == "Family trip"

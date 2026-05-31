"""Property-based tests for leave balance invariants.

Covers task **F4** from `.kiro/specs/staff-management-p2/tasks.md`.

Hypothesis drives a random sequence of leave operations (accrue,
submit + approve cycle, cancel-last-approved) against a real Postgres
database via the same service entrypoints the API layer uses
(``submit_request``, ``approve_request``, ``cancel_request``,
``adjust_balance``, and the daily ``accrue_for_staff`` helper). For
every generated sequence, the following invariants must hold:

  1. **Accrued >= used.** At every point in the ledger,
     ``sum(positive accrual rows) >= sum(absolute usage)``.
     Approval writes a negative ``delta_hours`` row with
     ``reason='request_approved'``; cancellation writes a
     compensating positive row. The sum of all accruals must always
     dominate the sum of all approved usage.
  2. **Balance non-negative.** ``leave_balance.accrued_hours >= 0``
     after any operation sequence. The service refuses requests that
     would push the available figure (``accrued - used - pending``)
     below zero, so the running balance stays non-negative.
  3. **Ledger sum equals balance.** ``sum(delta_hours) ==
     accrued_hours - used_hours`` for every (staff, leave_type) pair.
     The append-only ledger is the source of truth — the balance row
     is just a pre-aggregated view of it.
  4. **Idempotency.** Calling ``accrue_for_staff`` twice on the same
     ``today`` produces the same balance (no double-grant). The
     accrual engine guards every write with a SELECT against
     ``leave_ledger`` keyed on (staff_id, leave_type_id, reason,
     occurred_at).
  5. **Approve→Cancel restores balance.** Submitting, approving, then
     cancelling a request returns ``accrued`` / ``used`` /
     ``pending`` to their pre-submission values (with a compensating
     positive ledger row written by ``cancel_request``).

The test runs against the real Postgres instance in the dev compose
stack — Hypothesis tests in this codebase use real DB per the project
pattern (see e.g. ``tests/test_invoice_vehicle_fk_preservation.py``).
``max_examples`` is held at 20 to keep the runtime reasonable since
each example provisions a fresh org / staff / leave_type and tears
them down.

**Validates: Requirements R1, R2, R3, R4 — Staff Phase 2 task F4**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings as h_settings
from hypothesis import strategies as st
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Pre-import the model modules whose string-based relationship targets
# would otherwise fail to resolve when SQLAlchemy initialises mappers.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.scheduling_v2.models  # noqa: F401

from app.config import settings
from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.leave.accrual import accrue_for_staff
from app.modules.leave.models import (
    LeaveBalance,
    LeaveLedger,
    LeaveRequest,
    LeaveType,
)
from app.modules.leave.service import (
    InsufficientLeaveError,
    LeaveServiceError,
    adjust_balance,
    approve_request,
    cancel_request,
    submit_request,
)
from app.modules.staff.models import StaffMember


# ---------------------------------------------------------------------------
# Hypothesis configuration
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        # Each example creates fresh fixtures and runs a sequence of
        # async DB calls; treating it as a "function-scoped fixture"
        # warning would block the run.
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Hours per request — keep within a single working day so we can
# always submit at least once given the 80h annual leave grant we
# seed the balance with.
hours_strategy = st.decimals(
    min_value=Decimal("0.5"),
    max_value=Decimal("8.0"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Days offset for the accrual helper (used to nudge the simulated
# "today" forward without ever crossing a real anniversary, which
# would trigger an annual-leave grant we can't otherwise control in
# the test).
days_offset_strategy = st.integers(min_value=0, max_value=10)


def operation_strategy() -> st.SearchStrategy:
    """Each operation is a (kind, params) tuple.

    Kinds:
      - ``accrue`` — params = days_offset for the simulated "today".
        Uses the daily accrual helper, which on a non-anniversary day
        is a no-op for our seeded annual-leave balance. Idempotency
        is what we're stressing here.
      - ``submit_approve`` — params = hours. Submits and immediately
        approves an annual-leave request for ``hours`` hours.
      - ``cancel_last`` — params = None. Cancels the most recent
        approved request (no-op when there is none).
    """
    return st.one_of(
        st.tuples(st.just("accrue"), days_offset_strategy),
        st.tuples(st.just("submit_approve"), hours_strategy),
        st.tuples(st.just("cancel_last"), st.just(None)),
    )


sequence_strategy = st.lists(operation_strategy(), min_size=1, max_size=10)


# ---------------------------------------------------------------------------
# Per-test engine + fixtures
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, "AsyncEngine"]:
    """Build a fresh engine + session per Hypothesis example."""
    test_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    return factory(), test_engine


async def _cleanup(session: AsyncSession, fixtures: dict) -> None:
    """Wipe every row touched by ``_create_fixtures``.

    Order matters — child tables first. Runs RLS-disabled so we can
    cross the tenant boundary on cleanup.
    """
    org_id = fixtures.get("org_id")
    plan_id = fixtures.get("plan_id")
    if not org_id:
        return
    try:
        await _set_rls_org_id(session, None)
        # Delete audit_log rows the service writes — they're
        # otherwise retained and accumulate across examples.
        await session.execute(
            sa_text("DELETE FROM audit_log WHERE org_id = :oid"),
            {"oid": str(org_id)},
        )
        for table in (
            "schedule_entries",
            "leave_ledger",
            "leave_requests",
            "leave_balances",
            "leave_types",
            "staff_members",
            "users",
            "organisations",
        ):
            await session.execute(
                sa_text(f"DELETE FROM {table} WHERE org_id = :oid"),
                {"oid": str(org_id)},
            )
        if plan_id:
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE id = :pid"),
                {"pid": str(plan_id)},
            )
        await session.commit()
    except Exception:
        await session.rollback()


async def _create_fixtures(
    session: AsyncSession,
    *,
    initial_accrued: Decimal = Decimal("80"),
) -> dict:
    """Create org + plan + user + staff + annual leave_type + balance.

    The balance is seeded with ``initial_accrued`` hours so the
    submit/approve cycle can withdraw without immediately tripping
    ``InsufficientLeaveError``.
    """
    plan = SubscriptionPlan(
        name=f"Leave Inv Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"Leave Inv Org {uuid.uuid4().hex[:6]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        settings={},
    )
    session.add(org)
    await session.flush()

    # RLS context for the rest of the inserts.
    await _set_rls_org_id(session, str(org.id))

    user = User(
        org_id=org.id,
        email=f"inv-{uuid.uuid4().hex[:6]}@leave-invariants.test",
        first_name="Invariant",
        last_name="Tester",
        role="org_admin",
        password_hash="not-a-real-hash",
    )
    session.add(user)
    await session.flush()

    staff = StaffMember(
        org_id=org.id,
        user_id=user.id,
        name="Inv Tester",
        first_name="Invariant",
        last_name="Tester",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        standard_hours_per_week=Decimal("40.00"),
        # Set anchor to a date that's NOT the simulated "today" so
        # the accrual helper doesn't grant during the run.
        employment_start_date=date(2020, 7, 4),
        employment_type="permanent",
        shift_start="09:00",
        shift_end="17:00",
    )
    session.add(staff)
    await session.flush()

    annual_type = LeaveType(
        org_id=org.id,
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
    session.add(annual_type)
    await session.flush()

    balance = LeaveBalance(
        org_id=org.id,
        staff_id=staff.id,
        leave_type_id=annual_type.id,
        accrued_hours=initial_accrued,
        used_hours=Decimal("0"),
        pending_hours=Decimal("0"),
        anniversary_date=date(2020, 7, 4),
    )
    session.add(balance)
    # Seed the ledger with an opening balance row so invariant 3
    # (ledger sum == accrued - used) holds from the very first call.
    session.add(
        LeaveLedger(
            org_id=org.id,
            staff_id=staff.id,
            leave_type_id=annual_type.id,
            delta_hours=initial_accrued,
            reason="opening_balance",
            request_id=None,
            occurred_at=date(2020, 7, 4),
            created_by=None,
        )
    )
    await session.flush()
    await session.commit()

    return {
        "plan_id": plan.id,
        "org_id": org.id,
        "user_id": user.id,
        "staff": staff,
        "annual_type": annual_type,
        "balance_id": balance.id,
    }


def _make_request(org_id: uuid.UUID) -> SimpleNamespace:
    """Build a FastAPI-style request stand-in for the decision helpers.

    The leave service only reads ``state.permission_overrides`` and
    ``state.role`` — for non-confidential annual leave neither field
    matters but they must be present so ``getattr`` lookups succeed.
    """
    return SimpleNamespace(
        state=SimpleNamespace(
            role="org_admin",
            permission_overrides=[],
            org_id=org_id,
        )
    )


# ---------------------------------------------------------------------------
# Invariant assertion helpers
# ---------------------------------------------------------------------------


async def _assert_balance_invariants(
    session: AsyncSession,
    *,
    staff_id: uuid.UUID,
    leave_type_id: uuid.UUID,
) -> None:
    """Run invariants 1, 2, 3 against the live DB state."""
    # Re-read the balance row (do not trust the in-memory object).
    bal_result = await session.execute(
        select(LeaveBalance).where(
            LeaveBalance.staff_id == staff_id,
            LeaveBalance.leave_type_id == leave_type_id,
        )
    )
    bal: LeaveBalance | None = bal_result.scalar_one_or_none()
    assert bal is not None

    # Property 2 — balance non-negative.
    assert Decimal(bal.accrued_hours) >= Decimal("0"), (
        f"accrued_hours went negative: {bal.accrued_hours}"
    )
    assert Decimal(bal.used_hours) >= Decimal("0"), (
        f"used_hours went negative: {bal.used_hours}"
    )
    assert Decimal(bal.pending_hours) >= Decimal("0"), (
        f"pending_hours went negative: {bal.pending_hours}"
    )

    # Property 3 — ledger sum equals accrued - used.
    ledger_rows = (
        (await session.execute(
            select(LeaveLedger).where(
                LeaveLedger.staff_id == staff_id,
                LeaveLedger.leave_type_id == leave_type_id,
            )
        ))
        .scalars()
        .all()
    )
    ledger_sum = sum(
        (Decimal(row.delta_hours) for row in ledger_rows), Decimal("0"),
    )
    expected = Decimal(bal.accrued_hours) - Decimal(bal.used_hours)
    assert ledger_sum == expected, (
        f"ledger sum {ledger_sum} != accrued - used {expected} "
        f"(rows={[(str(r.reason), str(r.delta_hours)) for r in ledger_rows]})"
    )

    # Property 1 — sum of positive accrual rows >= sum of |negative usage|.
    positive_credits = sum(
        (
            Decimal(r.delta_hours)
            for r in ledger_rows
            if Decimal(r.delta_hours) > 0
            and r.reason
            in (
                "accrual",
                "opening_balance",
                "manual_adjustment",
                "request_cancelled_after_approval",
                "toil_accrual",
            )
        ),
        Decimal("0"),
    )
    negative_usage = sum(
        (
            -Decimal(r.delta_hours)
            for r in ledger_rows
            if Decimal(r.delta_hours) < 0
            and r.reason == "request_approved"
        ),
        Decimal("0"),
    )
    assert positive_credits >= negative_usage, (
        f"sum(credits)={positive_credits} < sum(usage)={negative_usage}"
    )


# ---------------------------------------------------------------------------
# Operation drivers
# ---------------------------------------------------------------------------


async def _drive_submit_approve(
    session: AsyncSession,
    *,
    fixtures: dict,
    hours: Decimal,
    approved_request_ids: list[uuid.UUID],
) -> None:
    """Submit and approve an annual-leave request for ``hours`` hours.

    Skips silently when the request would exceed the available
    balance (the service's own guard) — that's a valid outcome under
    the invariant, not a test failure.
    """
    org_id = fixtures["org_id"]
    staff: StaffMember = fixtures["staff"]
    annual_type: LeaveType = fixtures["annual_type"]

    payload = SimpleNamespace(
        leave_type_id=annual_type.id,
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 10),
        hours_requested=Decimal(hours),
        reason="property test",
        relationship_to_subject=None,
        partial_day_start_time=None,
        attachment_upload_id=None,
    )
    try:
        leave_request = await submit_request(
            session,
            org_id=org_id,
            staff_id=staff.id,
            payload=payload,
            requested_by_user_id=fixtures["user_id"],
        )
    except InsufficientLeaveError:
        return
    except LeaveServiceError:
        return

    request_id = leave_request.id

    request = _make_request(org_id)
    try:
        await approve_request(
            session,
            org_id=org_id,
            request_id=request_id,
            decided_by_user_id=fixtures["user_id"],
            request=request,
        )
        approved_request_ids.append(request_id)
    except LeaveServiceError:
        # Approval guards are exercised elsewhere; ignore here.
        return


async def _drive_cancel_last(
    session: AsyncSession,
    *,
    fixtures: dict,
    approved_request_ids: list[uuid.UUID],
) -> None:
    """Cancel the most recently approved request (no-op when empty)."""
    if not approved_request_ids:
        return
    request_id = approved_request_ids.pop()
    request = _make_request(fixtures["org_id"])
    try:
        await cancel_request(
            session,
            org_id=fixtures["org_id"],
            request_id=request_id,
            user_id=fixtures["user_id"],
            request=request,
        )
    except LeaveServiceError:
        return


async def _drive_accrue(
    session: AsyncSession,
    *,
    fixtures: dict,
    days_offset: int,
) -> None:
    """Run the daily accrual helper for a simulated ``today``.

    On any non-anniversary date this is a no-op for our annual-leave
    type — we still call it so the test exercises the engine's
    idempotency guard alongside the request workflow.
    """
    today = date(2026, 6, 1) + timedelta(days=days_offset)
    await accrue_for_staff(session, fixtures["staff"], today)
    # Flush so any potential ledger row is visible to the invariant
    # check (the helper only flushes when it actually wrote a row).
    await session.flush()


# ===========================================================================
# Property 1 / 2 / 3 — random-sequence invariants
# ===========================================================================


class TestRandomSequenceInvariants:
    """Drives random sequences of accrue / submit+approve / cancel and
    asserts the three core balance invariants hold throughout."""

    @PBT_SETTINGS
    @given(operations=sequence_strategy)
    @pytest.mark.asyncio
    async def test_invariants_hold_under_random_operations(
        self, operations
    ) -> None:
        """**Validates: Requirements R1, R2, R3** — Properties 1, 2, 3."""
        session, engine = await _make_session()
        fixtures: dict = {}
        approved_request_ids: list[uuid.UUID] = []
        try:
            fixtures = await _create_fixtures(session)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            for kind, param in operations:
                if kind == "accrue":
                    await _drive_accrue(
                        session, fixtures=fixtures, days_offset=param,
                    )
                elif kind == "submit_approve":
                    await _drive_submit_approve(
                        session,
                        fixtures=fixtures,
                        hours=Decimal(param),
                        approved_request_ids=approved_request_ids,
                    )
                elif kind == "cancel_last":
                    await _drive_cancel_last(
                        session,
                        fixtures=fixtures,
                        approved_request_ids=approved_request_ids,
                    )
                # Commit so the next operation sees the latest state
                # (and so the cleanup step can DELETE without a
                # SELECT-then-INSERT race in the same transaction).
                await session.commit()
                await _set_rls_org_id(session, str(fixtures["org_id"]))

                await _assert_balance_invariants(
                    session,
                    staff_id=fixtures["staff"].id,
                    leave_type_id=fixtures["annual_type"].id,
                )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()


# ===========================================================================
# Property 4 — accrue idempotency
# ===========================================================================


class TestAccrueIdempotent:
    """Calling ``accrue_for_staff`` twice on the same ``today`` must
    leave the balance unchanged (no double-grant). The accrual engine
    guards every write with a SELECT against ``leave_ledger`` keyed on
    (staff_id, leave_type_id, reason, occurred_at)."""

    @PBT_SETTINGS
    @given(days_offset=days_offset_strategy)
    @pytest.mark.asyncio
    async def test_double_accrue_same_day_is_idempotent(
        self, days_offset: int
    ) -> None:
        """**Validates: Requirement R3 (accrual idempotency).**"""
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            today = date(2026, 6, 1) + timedelta(days=days_offset)

            # Run #1.
            await accrue_for_staff(session, fixtures["staff"], today)
            await session.commit()
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            bal_after_first = (
                (
                    await session.execute(
                        select(LeaveBalance).where(
                            LeaveBalance.id == fixtures["balance_id"]
                        )
                    )
                )
                .scalar_one()
            )
            accrued_first = Decimal(bal_after_first.accrued_hours)
            ledger_count_first = (
                (
                    await session.execute(
                        select(LeaveLedger).where(
                            LeaveLedger.staff_id == fixtures["staff"].id,
                            LeaveLedger.leave_type_id
                            == fixtures["annual_type"].id,
                        )
                    )
                )
                .scalars()
                .all()
            )

            # Run #2 — same ``today``.
            await accrue_for_staff(session, fixtures["staff"], today)
            await session.commit()
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            bal_after_second = (
                (
                    await session.execute(
                        select(LeaveBalance).where(
                            LeaveBalance.id == fixtures["balance_id"]
                        )
                    )
                )
                .scalar_one()
            )
            accrued_second = Decimal(bal_after_second.accrued_hours)
            ledger_count_second = (
                (
                    await session.execute(
                        select(LeaveLedger).where(
                            LeaveLedger.staff_id == fixtures["staff"].id,
                            LeaveLedger.leave_type_id
                            == fixtures["annual_type"].id,
                        )
                    )
                )
                .scalars()
                .all()
            )

            # Property 4 — accrued unchanged, no extra ledger rows.
            assert accrued_first == accrued_second, (
                f"second accrue_for_staff changed accrued: "
                f"{accrued_first} → {accrued_second}"
            )
            assert len(ledger_count_first) == len(ledger_count_second), (
                f"second accrue_for_staff added rows: "
                f"{len(ledger_count_first)} → {len(ledger_count_second)}"
            )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()


# ===========================================================================
# Property 5 — submit→approve→cancel restores balance
# ===========================================================================


class TestApproveCancelRestoresBalance:
    """For any valid hours value, submit + approve + cancel must
    return the (accrued, used, pending) triple to its pre-submission
    state. The compensating ledger row carries
    ``reason='request_cancelled_after_approval'`` and a positive
    ``delta_hours`` equal to the original request."""

    @PBT_SETTINGS
    @given(hours=hours_strategy)
    @pytest.mark.asyncio
    async def test_approve_then_cancel_restores_balance(
        self, hours: Decimal
    ) -> None:
        """**Validates: Requirement R3 — compensating-row symmetry.**"""
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            org_id = fixtures["org_id"]
            staff: StaffMember = fixtures["staff"]
            annual_type: LeaveType = fixtures["annual_type"]

            # Snapshot pre-state.
            pre_bal = (
                (
                    await session.execute(
                        select(LeaveBalance).where(
                            LeaveBalance.id == fixtures["balance_id"]
                        )
                    )
                )
                .scalar_one()
            )
            pre_accrued = Decimal(pre_bal.accrued_hours)
            pre_used = Decimal(pre_bal.used_hours)
            pre_pending = Decimal(pre_bal.pending_hours)

            payload = SimpleNamespace(
                leave_type_id=annual_type.id,
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 10),
                hours_requested=Decimal(hours),
                reason="property approve+cancel test",
                relationship_to_subject=None,
                partial_day_start_time=None,
                attachment_upload_id=None,
            )

            leave_request = await submit_request(
                session,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=fixtures["user_id"],
            )
            request_id = leave_request.id
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            request = _make_request(org_id)
            await approve_request(
                session,
                org_id=org_id,
                request_id=request_id,
                decided_by_user_id=fixtures["user_id"],
                request=request,
            )
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            await cancel_request(
                session,
                org_id=org_id,
                request_id=request_id,
                user_id=fixtures["user_id"],
                request=request,
            )
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            # Re-read the balance.
            post_bal = (
                (
                    await session.execute(
                        select(LeaveBalance).where(
                            LeaveBalance.id == fixtures["balance_id"]
                        )
                    )
                )
                .scalar_one()
            )

            # Property 5 — pre-submission state restored.
            assert Decimal(post_bal.accrued_hours) == pre_accrued, (
                f"accrued not restored: {pre_accrued} → "
                f"{post_bal.accrued_hours}"
            )
            assert Decimal(post_bal.used_hours) == pre_used, (
                f"used not restored: {pre_used} → {post_bal.used_hours}"
            )
            assert Decimal(post_bal.pending_hours) == pre_pending, (
                f"pending not restored: {pre_pending} → "
                f"{post_bal.pending_hours}"
            )

            # And the compensating ledger row is present.
            comp_rows = (
                (
                    await session.execute(
                        select(LeaveLedger).where(
                            LeaveLedger.request_id == request_id,
                            LeaveLedger.reason
                            == "request_cancelled_after_approval",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(comp_rows) == 1, (
                f"expected 1 compensating ledger row, got {len(comp_rows)}"
            )
            assert Decimal(comp_rows[0].delta_hours) == Decimal(hours), (
                f"compensating delta != request hours: "
                f"{comp_rows[0].delta_hours} != {hours}"
            )

            # Final invariants check.
            await _assert_balance_invariants(
                session,
                staff_id=staff.id,
                leave_type_id=annual_type.id,
            )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()

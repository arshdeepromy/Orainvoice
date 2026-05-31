"""Unit tests for ``app.modules.leave.visibility._apply_confidential_filter``.

Covers task **F3a** from `.kiro/specs/staff-management-p2/tasks.md` and
the contract documented in design §4.4.

The filter restricts confidential leave-type rows so that:

  (a) Users without ``leave.fv_view`` can NEVER see another staff
      member's confidential request.
  (b) The SUBJECT of a confidential request always sees their own row,
      even when a manager submitted it on their behalf
      (``LeaveRequest.requested_by != current user`` but
      ``LeaveRequest.staff_id == current user's staff record``).
      This is the **P2-N12** regression — the earlier draft of the
      filter keyed self-service on ``requested_by`` and would have
      hidden the row from the very subject the feature protects.
  (c) Users WITH ``leave.fv_view`` see every confidential row in the
      org, regardless of subject or submitter.
  (d) Revocation propagates immediately — the filter consumes
      ``request.state.permission_overrides`` directly so toggling the
      list takes effect on the next call (no DB lookup, no cache
      separate from the existing 60s RBAC cache).

The filter is **synchronous** and reads from ``request.state``. We
build a ``SimpleNamespace`` request stand-in (only
``state.permission_overrides`` and ``state.org_id`` matter) and run the
returned ``Select`` against a real Postgres database so the
``staff_id`` subquery + the ``leave_type_id`` NOT IN clause both
exercise their full SQL paths.

**Validates: Requirements R4.6, R4.9, P2-N12 — Staff Phase 2 task F3a**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Pre-import the model modules whose string-based relationship targets
# would otherwise fail to resolve when SQLAlchemy initialises mappers.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.staff.models  # noqa: F401

from app.config import settings
from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.leave.models import LeaveRequest, LeaveType
from app.modules.leave.visibility import (
    FV_LEAVE_VIEW_PERMISSION,
    _apply_confidential_filter,
)
from app.modules.staff.models import StaffMember


# ---------------------------------------------------------------------------
# Per-test engine + fixture helpers
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, "AsyncEngine"]:
    """Build a fresh engine + session per test.

    Pattern mirrors ``tests/test_invoice_vehicle_fk_preservation.py``
    so RLS context can be set per-session and cleanup runs in a
    finally block.
    """
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
    """Delete every row touched by ``_create_fixtures``.

    Runs RLS-disabled (``app.current_org_id = NULL``) so we can wipe
    rows across the org boundary. Order matters — child tables first.
    """
    org_id = fixtures.get("org_id")
    plan_id = fixtures.get("plan_id")
    if not org_id:
        return
    try:
        await _set_rls_org_id(session, None)
        # Children first.
        for table in (
            "leave_requests",
            "leave_balances",
            "leave_ledger",
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


async def _create_fixtures(session: AsyncSession) -> dict:
    """Create org + plan + users + staff + leave_types for the suite.

    Layout:

      * ``user_a``, ``staff_a`` — a regular employee.
      * ``user_b``, ``staff_b`` — another employee whose FV request
        should be HIDDEN from user_a.
      * ``user_m``, ``staff_m`` — a manager who will submit on behalf
        of user_s as a proxy (P2-N12 regression).
      * ``user_s``, ``staff_s`` — the SUBJECT of the proxy submission.
      * ``user_p`` — a permitted approver (no staff record needed for
        the filter; just exercises the override branch).

    Plus a confidential leave type (``family_violence``) and a
    non-confidential one (``annual``) for the row mix.
    """
    plan = SubscriptionPlan(
        name=f"FV Filter Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"FV Filter Org {uuid.uuid4().hex[:6]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        settings={},
    )
    session.add(org)
    await session.flush()

    # RLS context for the rest of the inserts (leave_types, staff,
    # leave_requests are all RLS-protected).
    await _set_rls_org_id(session, str(org.id))

    def _user(label: str, role: str = "salesperson") -> User:
        u = User(
            org_id=org.id,
            email=f"{label}-{uuid.uuid4().hex[:6]}@fvfilter.test",
            first_name=label.title(),
            last_name="Tester",
            role=role,
            password_hash="not-a-real-hash",
        )
        session.add(u)
        return u

    user_a = _user("user-a", role="salesperson")
    user_b = _user("user-b", role="salesperson")
    user_m = _user("user-m", role="org_admin")  # manager / proxy submitter
    user_s = _user("user-s", role="salesperson")  # subject
    user_p = _user("user-p", role="org_admin")  # permitted approver
    await session.flush()

    def _staff(user: User, name: str) -> StaffMember:
        s = StaffMember(
            org_id=org.id,
            user_id=user.id,
            name=name,
            first_name=name.split()[0],
            last_name=name.split()[-1],
            role_type="employee",
            is_active=True,
            availability_schedule={},
            skills=[],
            standard_hours_per_week=Decimal("40.00"),
            employment_type="permanent",
        )
        session.add(s)
        return s

    staff_a = _staff(user_a, "Alice Anderson")
    staff_b = _staff(user_b, "Bob Brown")
    staff_m = _staff(user_m, "Mia Manager")
    staff_s = _staff(user_s, "Sam Subject")
    await session.flush()

    fv_type = LeaveType(
        org_id=org.id,
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
    session.add_all([fv_type, annual_type])
    await session.flush()

    def _request(
        *,
        staff: StaffMember,
        leave_type: LeaveType,
        requested_by: User,
        start: date = date(2026, 6, 1),
        end: date = date(2026, 6, 1),
        hours: Decimal = Decimal("8"),
    ) -> LeaveRequest:
        r = LeaveRequest(
            org_id=org.id,
            staff_id=staff.id,
            leave_type_id=leave_type.id,
            start_date=start,
            end_date=end,
            hours_requested=hours,
            status="pending",
            requested_by=requested_by.id,
        )
        session.add(r)
        return r

    # Row mix:
    #   r_annual_a — non-confidential; A's own annual leave.
    #   r_annual_b — non-confidential; B's annual leave.
    #   r_fv_a    — confidential; A's own FV request (subject = A).
    #   r_fv_b    — confidential; B's own FV request (subject = B).
    #   r_fv_proxy — confidential; M submitted on behalf of S
    #                (requested_by=user_m, staff_id=staff_s).
    r_annual_a = _request(
        staff=staff_a, leave_type=annual_type, requested_by=user_a,
    )
    r_annual_b = _request(
        staff=staff_b, leave_type=annual_type, requested_by=user_b,
    )
    r_fv_a = _request(
        staff=staff_a, leave_type=fv_type, requested_by=user_a,
    )
    r_fv_b = _request(
        staff=staff_b, leave_type=fv_type, requested_by=user_b,
    )
    r_fv_proxy = _request(
        staff=staff_s, leave_type=fv_type, requested_by=user_m,
    )
    await session.flush()
    await session.commit()

    return {
        "plan_id": plan.id,
        "org_id": org.id,
        "user_a": user_a,
        "user_b": user_b,
        "user_m": user_m,
        "user_s": user_s,
        "user_p": user_p,
        "staff_a": staff_a,
        "staff_b": staff_b,
        "staff_m": staff_m,
        "staff_s": staff_s,
        "fv_type": fv_type,
        "annual_type": annual_type,
        "r_annual_a": r_annual_a,
        "r_annual_b": r_annual_b,
        "r_fv_a": r_fv_a,
        "r_fv_b": r_fv_b,
        "r_fv_proxy": r_fv_proxy,
    }


def _make_request(
    *,
    org_id: uuid.UUID,
    has_fv_view: bool = False,
):
    """Build a FastAPI-style request stand-in.

    The filter only reads ``state.permission_overrides`` and
    ``state.org_id``. A ``SimpleNamespace`` is enough — no need for
    ``MagicMock(spec=Request)``.
    """
    overrides: list[dict] = []
    if has_fv_view:
        overrides.append({
            "permission_key": FV_LEAVE_VIEW_PERMISSION,
            "is_granted": True,
        })
    return SimpleNamespace(
        state=SimpleNamespace(
            permission_overrides=overrides,
            org_id=org_id,
        )
    )


async def _run_filter(
    session: AsyncSession,
    *,
    request,
    user_id: uuid.UUID,
    user_role: str,
) -> list[LeaveRequest]:
    """Build a ``select(LeaveRequest)`` query, apply the filter,
    execute it, and return the resulting rows."""
    base = select(LeaveRequest).where(
        LeaveRequest.org_id == request.state.org_id
    )
    filtered = _apply_confidential_filter(
        base, request, user_id, user_role,
    )
    result = await session.execute(filtered)
    return list(result.scalars().all())


# ===========================================================================
# 1. Non-permitted user cannot see other staff's FV requests
# ===========================================================================


class TestNonPermittedUserHidesOtherFvRequests:
    """User without ``leave.fv_view`` sees:
       (a) all non-confidential rows in the org, and
       (b) only their OWN confidential rows (subject branch via
           staff_id == current user's staff_id).
    """

    @pytest.mark.asyncio
    async def test_user_a_sees_own_fv_and_all_annual_but_not_others_fv(self):
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            req = _make_request(org_id=fixtures["org_id"], has_fv_view=False)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            rows = await _run_filter(
                session,
                request=req,
                user_id=fixtures["user_a"].id,
                user_role="salesperson",
            )
            row_ids = {r.id for r in rows}

            # Annual leave: both A's and B's are visible (non-confidential).
            assert fixtures["r_annual_a"].id in row_ids
            assert fixtures["r_annual_b"].id in row_ids
            # A's own FV request: visible via the subject branch.
            assert fixtures["r_fv_a"].id in row_ids
            # B's FV request and the proxy FV request (subject = S):
            # both confidential and A is neither subject nor permitted.
            assert fixtures["r_fv_b"].id not in row_ids
            assert fixtures["r_fv_proxy"].id not in row_ids
            # Total visible = 3 (2 annual + 1 own FV).
            assert len(row_ids) == 3
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()


# ===========================================================================
# 2. Subject of a confidential request sees their own row
# ===========================================================================


class TestSubjectSeesOwnFvRequest:
    """The subject branch — ``LeaveRequest.staff_id ==
    select(StaffMember.id).where(user_id == current_user)`` — keeps
    self-service visibility intact.
    """

    @pytest.mark.asyncio
    async def test_user_a_sees_own_fv_request(self):
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            req = _make_request(org_id=fixtures["org_id"], has_fv_view=False)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            rows = await _run_filter(
                session,
                request=req,
                user_id=fixtures["user_a"].id,
                user_role="salesperson",
            )

            # Locate A's own FV request in the result.
            own_fv = [r for r in rows if r.id == fixtures["r_fv_a"].id]
            assert len(own_fv) == 1
            assert own_fv[0].staff_id == fixtures["staff_a"].id
            assert own_fv[0].requested_by == fixtures["user_a"].id
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()


# ===========================================================================
# 3. User with leave.fv_view sees every confidential row
# ===========================================================================


class TestPermittedUserSeesAllFvRequests:
    """Override list contains ``leave.fv_view`` is_granted=True →
    filter returns the query unchanged → every row in the org is
    returned.
    """

    @pytest.mark.asyncio
    async def test_permitted_user_sees_all_5_rows(self):
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            req = _make_request(org_id=fixtures["org_id"], has_fv_view=True)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            rows = await _run_filter(
                session,
                request=req,
                user_id=fixtures["user_p"].id,
                user_role="org_admin",
            )
            row_ids = {r.id for r in rows}

            # All five rows visible.
            assert fixtures["r_annual_a"].id in row_ids
            assert fixtures["r_annual_b"].id in row_ids
            assert fixtures["r_fv_a"].id in row_ids
            assert fixtures["r_fv_b"].id in row_ids
            assert fixtures["r_fv_proxy"].id in row_ids
            assert len(row_ids) == 5
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()


# ===========================================================================
# 4. Revocation takes effect on the next call
# ===========================================================================


class TestRevocationTakesEffect:
    """After revoking the override, the same user no longer sees other
    staff's confidential requests on the next call. The filter is
    synchronous and consumes ``request.state.permission_overrides``
    directly, so toggling the list is enough — no DB or cache replay.
    """

    @pytest.mark.asyncio
    async def test_revoke_hides_other_staff_fv_on_next_call(self):
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            # Step 1 — granted: every row visible.
            req_granted = _make_request(
                org_id=fixtures["org_id"], has_fv_view=True,
            )
            rows_before = await _run_filter(
                session,
                request=req_granted,
                user_id=fixtures["user_p"].id,
                user_role="org_admin",
            )
            assert len(rows_before) == 5

            # Step 2 — simulate revocation by toggling the same
            # request object's override list to empty (mirrors what
            # the RBAC cache miss + DB DELETE produces 60s after a
            # revoke).
            req_granted.state.permission_overrides = []

            rows_after = await _run_filter(
                session,
                request=req_granted,
                user_id=fixtures["user_p"].id,
                user_role="org_admin",
            )
            row_ids_after = {r.id for r in rows_after}

            # ``user_p`` has no staff record, so the subject branch
            # never matches — every confidential row is hidden.
            assert fixtures["r_fv_a"].id not in row_ids_after
            assert fixtures["r_fv_b"].id not in row_ids_after
            assert fixtures["r_fv_proxy"].id not in row_ids_after
            # Non-confidential rows still visible.
            assert fixtures["r_annual_a"].id in row_ids_after
            assert fixtures["r_annual_b"].id in row_ids_after
            assert len(row_ids_after) == 2
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()


# ===========================================================================
# 5. P2-N12 — subject-vs-proxy regression
# ===========================================================================


class TestProxySubmissionSubjectControlsVisibility:
    """When a manager submits an FV request on behalf of a staff
    member, the SUBJECT (whose ``staff_id`` is on the row) controls
    visibility — not the proxy submitter.

    This is the **P2-N12** fix. The earlier draft of the filter used
    ``LeaveRequest.requested_by == user_id`` for the self-service
    branch, which would have:
      * HIDDEN the request from the very subject the feature protects
        (because ``requested_by != subject.user_id``), and
      * SHOWN it to the manager even after the fact (because they
        submitted it).
    Both outcomes are wrong. The fixed filter joins on ``staff_id``
    so the subject sees the row and the proxy does not (unless they
    independently hold ``leave.fv_view``).
    """

    @pytest.mark.asyncio
    async def test_subject_sees_proxy_submitted_fv_request(self):
        """Subject ``S`` sees the FV request even though it was
        submitted by manager ``M``."""
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            # Sanity check: the proxy row has the expected shape.
            assert fixtures["r_fv_proxy"].requested_by == fixtures["user_m"].id
            assert fixtures["r_fv_proxy"].staff_id == fixtures["staff_s"].id
            assert fixtures["r_fv_proxy"].requested_by != fixtures["user_s"].id

            req = _make_request(org_id=fixtures["org_id"], has_fv_view=False)
            rows = await _run_filter(
                session,
                request=req,
                user_id=fixtures["user_s"].id,
                user_role="salesperson",
            )
            row_ids = {r.id for r in rows}

            # Subject sees their own confidential request via the
            # staff_id branch even though they didn't submit it.
            assert fixtures["r_fv_proxy"].id in row_ids
            # And does NOT see other staff's confidential requests.
            assert fixtures["r_fv_a"].id not in row_ids
            assert fixtures["r_fv_b"].id not in row_ids
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_proxy_submitter_does_not_see_request_after_the_fact(self):
        """Manager ``M`` (without ``leave.fv_view``) does NOT see the
        FV request they submitted on behalf of ``S``.

        ``M`` IS a staff member (``staff_m`` exists) — so the subject
        branch could fire — but the row's ``staff_id`` resolves to
        ``staff_s``, not ``staff_m``, so the branch correctly skips
        ``M``.
        """
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            await _set_rls_org_id(session, str(fixtures["org_id"]))

            req = _make_request(org_id=fixtures["org_id"], has_fv_view=False)
            rows = await _run_filter(
                session,
                request=req,
                user_id=fixtures["user_m"].id,
                user_role="org_admin",
            )
            row_ids = {r.id for r in rows}

            # Proxy submitter does NOT see the request — staff_id is
            # the subject's, not the proxy's, and the proxy lacks the
            # permission override.
            assert fixtures["r_fv_proxy"].id not in row_ids
            # And does not see other staff's FV requests either.
            assert fixtures["r_fv_a"].id not in row_ids
            assert fixtures["r_fv_b"].id not in row_ids
            # Annual leave still visible (non-confidential).
            assert fixtures["r_annual_a"].id in row_ids
            assert fixtures["r_annual_b"].id in row_ids
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()

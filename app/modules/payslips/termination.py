"""Termination workflow + Holidays Act s27 final payslip.

Implements task B6 from ``.kiro/specs/staff-management-p4/tasks.md``.
The flow runs as a single DB transaction (the caller — usually the
router via :func:`get_db_session` — owns ``session.begin()``):

  Step 0 — Concurrency guard (N19): row lock with
           ``SELECT 1 FROM staff_members WHERE id=:id FOR UPDATE``.
           Two concurrent terminate calls serialise; the second sees
           ``is_active=false`` and raises 409 ``already_terminated``.

  Step 1 — Reconcile future-dated approved leave (G16 + cross-phase
           X8): cancel each approved leave_request whose start_date >
           end_date; restore hours via leave_ledger; mark future
           schedule_entries.status='cancelled' (NOT hard-delete —
           hard-delete would break P3's roster-change SMS hook and
           audit-history queries).

  Step 2 — Compute payouts on the corrected balances:
            - Annual leave: remaining (accrued − used) hours ×
              greater_of(ordinary_weekly, 52-wk avg) (s27).
            - Alt-days: count × ADP snapshot.
            - Casual 8% remainder: YTD_gross × 0.08 − sum(8% lines
              paid YTD).

  Step 3 — Pick the final-payslip pay period (G25 + G6):
            - Find the period whose [start, end] contains end_date.
            - status='open' → use it.
            - status='finalised' → reopen via R1a (audit
              ``pay_period.reopened_for_termination``).
            - status='paid' → 409 ``pay_period_already_paid``.
            - No match → roll_pay_periods synchronously until a
              period covers end_date (audit
              ``pay_period.rolled_for_termination`` per created
              period).

  Step 4 — Generate the final payslip with s27 + alt-day +
           casual-8% breakdown lines + ``notes='termination'``.

  Step 4a — KiwiSaver scope (N15): the auto-deduction is computed
           on the non-lump-sum portion only. The lump-sum components
           are extra-pay for PAYE purposes; admin still enters PAYE
           manually.

  Step 5 — Update staff: employment_end_date = :end_date,
           is_active = false; flip leave balances to zero (write
           leave_ledger reasons='termination_payout'); audit
           ``staff.terminated`` with redacted ``payout_summary``
           (counts only, no dollars — G12).

**Validates: Requirement R10 — Staff Management Phase 4 task B6.**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.admin.models import Organisation
from app.modules.leave.models import LeaveBalance, LeaveLedger, LeaveType
from app.modules.payslips.calc import (
    CASUAL_HOLIDAY_PAY_RATE,
    compute_gross_ytd,
    compute_payslip,
    compute_tax_year_start,
)
from app.modules.payslips.models import (
    PayPeriod,
    Payslip,
    PayslipAllowance,
    PayslipDeduction,
)
from app.modules.payslips.period_rolling import compute_next_period_dates
from app.modules.payslips.service import (
    PayPeriodNotFoundError,
    PayslipServiceError,
    _auto_attach_recurring_allowances,
    _redacted_payslip_event,
    recompute_payslip,
    reopen_pay_period,
)
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


__all__ = [
    "TerminationServiceError",
    "AlreadyTerminatedError",
    "PayPeriodAlreadyPaidError",
    "TerminationResult",
    "terminate_employment",
    "s27_annual_leave_payout",
]


# ---------------------------------------------------------------------------
# Service-layer exceptions (router maps to documented HTTP codes)
# ---------------------------------------------------------------------------


class TerminationServiceError(PayslipServiceError):
    """Base class for termination errors."""


class AlreadyTerminatedError(TerminationServiceError):
    """Staff already has ``is_active=false`` (N19 race-loser).
    Router maps to HTTP 409 ``already_terminated``.
    """


class PayPeriodAlreadyPaidError(TerminationServiceError):
    """Pay-period covering :end_date is already in status='paid' —
    admin must wait for next period or do a manual adjustment.
    Router maps to HTTP 409 ``pay_period_already_paid``.
    """


# ---------------------------------------------------------------------------
# Holidays Act s27 helper
# ---------------------------------------------------------------------------


def s27_annual_leave_payout(
    *,
    remaining_hours: Decimal,
    ordinary_weekly: Decimal,
    fifty_two_week_avg: Decimal,
    standard_hours_per_week: Decimal | None,
) -> Decimal:
    """Holidays Act s27 — annual leave payout on termination.

    ``per_week_rate = max(ordinary_weekly, fifty_two_week_avg)``.
    ``hourly = per_week_rate / standard_hours_per_week``.
    ``payout = hourly × remaining_hours``.

    Returns dollars (Decimal quantised to cents). When
    ``standard_hours_per_week`` is unset or zero we fall back to a
    hourly of zero — callers should surface a warning so admin can
    fill in the column before re-running.
    """
    per_week = max(
        Decimal(str(ordinary_weekly or 0)),
        Decimal(str(fifty_two_week_avg or 0)),
    )
    sh = Decimal(str(standard_hours_per_week or 0))
    if sh > 0:
        hourly = per_week / sh
    else:
        hourly = Decimal("0")
    return (hourly * Decimal(str(remaining_hours or 0))).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Result dataclass surfaced through the router
# ---------------------------------------------------------------------------


class TerminationResult(dict):
    """Plain dict subclass — JSON-serialisable directly from the
    router. Keys: ``staff_id``, ``end_date``, ``payslip_id``,
    ``pay_period_id``, ``payout_summary`` (counts only — no $).
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _row_lock_staff(
    db: AsyncSession, staff_id: uuid.UUID,
) -> None:
    """Acquire a row-level lock on the staff record (N19).

    Two concurrent terminate calls serialise on this lock; the second
    blocks until the first commits, then sees ``is_active=false`` and
    raises :class:`AlreadyTerminatedError`.
    """
    await db.execute(
        text("SELECT 1 FROM staff_members WHERE id = :id FOR UPDATE"),
        {"id": str(staff_id)},
    )


async def _cancel_future_leave(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    end_date: date,
    user_id: uuid.UUID | None,
    ip_address: str | None,
) -> dict[str, Any]:
    """G16 — cancel approved leave_requests whose ``start_date >
    end_date``, write compensating leave_ledger rows, mark future
    schedule_entries.status='cancelled' (X8 — never hard-delete),
    write audit row.

    Returns a summary dict with counts so the caller can fold them
    into the eventual ``staff.terminated`` audit ``payout_summary``.
    """
    future_requests = (
        await db.execute(
            text(
                """
                SELECT id, leave_type_id, hours_requested, start_date, end_date
                FROM leave_requests
                WHERE org_id = :org_id
                  AND staff_id = :staff_id
                  AND status = 'approved'
                  AND start_date > :end_date
                """
            ),
            {
                "org_id": str(org_id),
                "staff_id": str(staff_id),
                "end_date": end_date,
            },
        )
    ).all()

    cancelled_ids: list[str] = []
    total_hours_restored = Decimal("0")

    for row in future_requests:
        # Cancel the request.
        await db.execute(
            text(
                """
                UPDATE leave_requests
                SET status = 'cancelled',
                    decided_by = :decided_by,
                    decided_at = now(),
                    decision_notes = COALESCE(decision_notes, '') ||
                                     E'\nauto-cancelled at termination',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "decided_by": str(user_id) if user_id else None,
                "id": str(row.id),
            },
        )
        # Compensating ledger row — restores hours to balance.
        hours_restored = Decimal(str(row.hours_requested or 0))
        ledger = LeaveLedger(
            org_id=org_id,
            staff_id=staff_id,
            leave_type_id=row.leave_type_id,
            delta_hours=hours_restored,
            reason="request_cancelled_after_approval",
            request_id=row.id,
            occurred_at=end_date,
            created_by=user_id,
        )
        db.add(ledger)
        total_hours_restored += hours_restored
        cancelled_ids.append(str(row.id))

        # Bump the matching balance row (subtract from used, add to accrued
        # would also work — but per Phase 2 design the leave_balances
        # rolling totals are recomputed by the daily accrual job; here
        # we apply the immediate adjustment so the s27 payout uses the
        # corrected figure within the same transaction).
        bal = (
            await db.execute(
                select(LeaveBalance).where(
                    LeaveBalance.staff_id == staff_id,
                    LeaveBalance.leave_type_id == row.leave_type_id,
                )
            )
        ).scalar_one_or_none()
        if bal is not None:
            # The original approval would have moved hours from accrued
            # to used (or pending). Restore by reducing used (what
            # actually got charged) by the request hours.
            current_used = Decimal(bal.used_hours or 0)
            bal.used_hours = max(Decimal("0"), current_used - hours_restored)

    # X8 — mark future schedule_entries.status='cancelled' for
    # entry_type='leave' rows in the cancelled range.
    if cancelled_ids:
        end_dt = datetime.combine(end_date, time.min, tzinfo=timezone.utc)
        await db.execute(
            text(
                """
                UPDATE schedule_entries
                SET status = 'cancelled', updated_at = now()
                WHERE staff_id = :staff_id
                  AND entry_type = 'leave'
                  AND start_time > :end_dt
                  AND status IN ('scheduled', 'completed')
                """
            ),
            {"staff_id": str(staff_id), "end_dt": end_dt},
        )

    if cancelled_ids:
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="staff.termination_cancelled_future_leave",
            entity_type="staff_member",
            entity_id=staff_id,
            after_value={
                "staff_id": str(staff_id),
                "cancelled_request_ids": cancelled_ids,
                "total_hours_restored": str(total_hours_restored),
            },
            ip_address=ip_address,
        )

    await db.flush()
    return {
        "cancelled_request_ids": cancelled_ids,
        "total_hours_restored": total_hours_restored,
    }


async def _compute_52_week_avg(
    db: AsyncSession, *, staff_id: uuid.UUID, end_date: date,
) -> Decimal:
    """Return the 52-week average weekly earnings for the staff.

    ``avg = SUM(payslips.gross_pay last 52 weeks of finalised
    payslips) / 52``. When fewer than 52 weeks of history exist we
    still divide by 52 (so a recently-hired staff has a low avg —
    the s27 ``max(ordinary, avg)`` formula picks the ordinary weekly
    rate in that case, which is the intended outcome).
    """
    fifty_two_weeks_ago = end_date - timedelta(weeks=52)
    stmt = text(
        """
        SELECT COALESCE(SUM(p.gross_pay), 0) AS total
        FROM payslips p
        JOIN pay_periods pp ON pp.id = p.pay_period_id
        WHERE p.staff_id = :staff_id
          AND p.status = 'finalised'
          AND pp.pay_date >= :start
          AND pp.pay_date <= :end
        """,
    )
    total = (
        await db.execute(
            stmt,
            {
                "staff_id": str(staff_id),
                "start": fifty_two_weeks_ago,
                "end": end_date,
            },
        )
    ).scalar_one_or_none() or 0
    return (Decimal(str(total)) / Decimal(52)).quantize(Decimal("0.01"))


async def _compute_8pct_paid_ytd(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    end_date: date,
    tax_year_end: date | None,
) -> Decimal:
    """Return the sum of casual-8% allowance lines paid YTD."""
    tax_year_start = compute_tax_year_start(
        pay_date=end_date, tax_year_end=tax_year_end,
    )
    stmt = text(
        """
        SELECT COALESCE(SUM(pa.amount), 0) AS total
        FROM payslip_allowances pa
        JOIN payslips p ON p.id = pa.payslip_id
        JOIN pay_periods pp ON pp.id = p.pay_period_id
        WHERE p.staff_id = :staff_id
          AND p.status = 'finalised'
          AND pp.pay_date >= :tax_year_start
          AND pp.pay_date <= :end_date
          AND (pa.label ILIKE 'casual%8%' OR pa.label ILIKE '%8%%casual%')
        """,
    )
    total = (
        await db.execute(
            stmt,
            {
                "staff_id": str(staff_id),
                "tax_year_start": tax_year_start,
                "end_date": end_date,
            },
        )
    ).scalar_one_or_none() or 0
    return Decimal(str(total)).quantize(Decimal("0.01"))


async def _find_or_create_period_covering(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    end_date: date,
    user_id: uuid.UUID | None,
    ip_address: str | None,
) -> PayPeriod:
    """G25 + G6 — pick the pay_period that covers ``end_date``.

    Logic:
      1. If a period covers end_date and is 'open' → use it.
      2. If 'finalised' → reopen via R1a (audit
         ``pay_period.reopened_for_termination``).
      3. If 'paid' → 409 ``pay_period_already_paid``.
      4. If no period covers end_date → roll forward periods
         iteratively until one does (audit
         ``pay_period.rolled_for_termination`` per created period).
    """
    candidate = (
        await db.execute(
            select(PayPeriod).where(
                PayPeriod.org_id == org_id,
                PayPeriod.start_date <= end_date,
                PayPeriod.end_date >= end_date,
            )
        )
    ).scalars().first()

    if candidate is not None:
        if candidate.status == "open":
            return candidate
        if candidate.status == "paid":
            raise PayPeriodAlreadyPaidError("pay_period_already_paid")
        # finalised — reopen via R1a.
        await reopen_pay_period(
            db,
            org_id=org_id,
            period_id=candidate.id,
            reason="termination — reopen for final payslip",
            user_id=user_id,
            ip_address=ip_address,
        )
        # Mark the audit specifically for termination.
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="pay_period.reopened_for_termination",
            entity_type="pay_period",
            entity_id=candidate.id,
            after_value={"pay_period_id": str(candidate.id)},
            ip_address=ip_address,
        )
        await db.refresh(candidate)
        return candidate

    # G6 — no period covers :end_date; roll forward.
    org_row = await db.get(Organisation, org_id)
    cadence = (
        getattr(org_row, "pay_period_cadence", None) or "fortnightly"
    )
    anchor_day = int(getattr(org_row, "pay_period_anchor_day", None) or 1)
    pay_offset = int(getattr(org_row, "pay_date_offset_days", None) or 3)

    # Iteratively create periods starting from latest_end+1 until
    # one covers end_date. Capped at 52 iterations to defend against
    # pathological inputs.
    latest_end = (
        await db.execute(
            select(PayPeriod.end_date)
            .where(PayPeriod.org_id == org_id)
            .order_by(PayPeriod.end_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    today = date.today()
    last_period: PayPeriod | None = None
    for _ in range(52):
        start, end, pay = compute_next_period_dates(
            cadence=cadence,
            anchor_day=anchor_day,
            pay_date_offset_days=pay_offset,
            latest_end=latest_end,
            today=today,
        )
        new_period: PayPeriod | None = None
        try:
            async with db.begin_nested():
                new_period = PayPeriod(
                    org_id=org_id,
                    start_date=start,
                    end_date=end,
                    pay_date=pay,
                    status="open",
                )
                db.add(new_period)
                await db.flush()
        except Exception:
            # Idempotent — UNIQUE constraint hit. Look up the existing
            # row for that start_date and continue from its end_date.
            existing = (
                await db.execute(
                    select(PayPeriod).where(
                        PayPeriod.org_id == org_id,
                        PayPeriod.start_date == start,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise
            new_period = existing

        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="pay_period.rolled_for_termination",
            entity_type="pay_period",
            entity_id=new_period.id,
            after_value={
                "pay_period_id": str(new_period.id),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
            ip_address=ip_address,
        )

        last_period = new_period
        latest_end = end
        if start <= end_date <= end:
            return new_period

    if last_period is None:
        raise TerminationServiceError("could_not_create_period")
    # Last-resort fallback — return the last created period even if it
    # doesn't strictly cover end_date (defensive).
    return last_period


async def _close_leave_balances(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    end_date: date,
    user_id: uuid.UUID | None,
) -> tuple[Decimal, Decimal, Decimal]:
    """Step 5 helper — flip accruing leave balances to zero with
    compensating ``leave_ledger`` rows ``reason='termination_payout'``.

    Returns ``(annual_hours_zeroed, alt_days_zeroed,
    casual_8pct_pseudo_hours)`` for the redacted ``payout_summary``
    audit field.
    """
    rows = (
        await db.execute(
            select(LeaveBalance, LeaveType)
            .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
            .where(
                LeaveBalance.staff_id == staff_id,
                LeaveType.accrual_method != "none",
            )
        )
    ).all()

    annual_hours = Decimal("0")
    alt_days = Decimal("0")

    for balance, ltype in rows:
        accrued = Decimal(balance.accrued_hours or 0)
        used = Decimal(balance.used_hours or 0)
        remaining = accrued - used
        if remaining <= 0:
            continue
        if ltype.code == "annual_leave":
            annual_hours += remaining
        elif ltype.code in ("public_holiday_alt", "alt_days", "alternative_day"):
            # Phase 2 stores alt-day balance in HOURS but we surface
            # day count in audit summary (assume 8h/day for now;
            # could be refined when alt-day balance unit is firmed).
            alt_days += (remaining / Decimal(8)).quantize(Decimal("0.01"))
        db.add(
            LeaveLedger(
                org_id=org_id,
                staff_id=staff_id,
                leave_type_id=ltype.id,
                delta_hours=-remaining,
                reason="termination_payout",
                request_id=None,
                occurred_at=end_date,
                created_by=user_id,
            )
        )
        balance.used_hours = accrued  # bring used up to accrued → 0 remaining

    return annual_hours, alt_days, Decimal("0")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def terminate_employment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    end_date: date,
    reason: str,
    pay_annual_leave: bool = True,
    pay_alt_days: bool = True,
    pay_casual_8pct_remainder: bool = True,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TerminationResult:
    """Run the full termination workflow.

    Single transaction. The caller (``app/modules/payslips/router.py``)
    relies on FastAPI's ``get_db_session`` dependency for the BEGIN /
    COMMIT — this function only flushes.

    Returns a :class:`TerminationResult` dict with the ids of the
    final payslip + pay_period plus a redacted payout summary
    (counts only — no dollar amounts per G12).
    """
    # Step 0 — concurrency lock.
    await _row_lock_staff(db, staff_id)

    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise PayslipServiceError("staff_not_found")
    if not staff.is_active:
        raise AlreadyTerminatedError("already_terminated")

    # Step 1 — reconcile future-dated approved leave (G16 + X8).
    leave_summary = await _cancel_future_leave(
        db,
        org_id=org_id,
        staff_id=staff_id,
        end_date=end_date,
        user_id=user_id,
        ip_address=ip_address,
    )

    # Step 2 — compute payouts on the corrected balances.
    org_row = await db.get(Organisation, org_id)
    tax_year_end = (
        getattr(org_row, "income_tax_year_end", None) if org_row else None
    )

    # Annual-leave remaining hours.
    annual_balance = (
        await db.execute(
            select(LeaveBalance, LeaveType)
            .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
            .where(
                LeaveBalance.staff_id == staff_id,
                LeaveType.code == "annual_leave",
            )
        )
    ).first()
    annual_remaining = Decimal("0")
    if annual_balance is not None:
        bal, _ltype = annual_balance
        annual_remaining = max(
            Decimal("0"),
            Decimal(bal.accrued_hours or 0) - Decimal(bal.used_hours or 0),
        )

    # Alt-day remaining hours.
    alt_balance = (
        await db.execute(
            select(LeaveBalance, LeaveType)
            .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
            .where(
                LeaveBalance.staff_id == staff_id,
                LeaveType.code.in_(("public_holiday_alt", "alt_days", "alternative_day")),
            )
        )
    ).first()
    alt_remaining_hours = Decimal("0")
    if alt_balance is not None:
        bal, _ltype = alt_balance
        alt_remaining_hours = max(
            Decimal("0"),
            Decimal(bal.accrued_hours or 0) - Decimal(bal.used_hours or 0),
        )

    # s27 inputs.
    standard_hours_per_week = Decimal(str(staff.standard_hours_per_week or 0))
    hourly = Decimal(str(staff.hourly_rate or 0))
    ordinary_weekly = (standard_hours_per_week * hourly).quantize(Decimal("0.01"))
    fifty_two_avg = await _compute_52_week_avg(
        db, staff_id=staff_id, end_date=end_date,
    )

    annual_payout = (
        s27_annual_leave_payout(
            remaining_hours=annual_remaining,
            ordinary_weekly=ordinary_weekly,
            fifty_two_week_avg=fifty_two_avg,
            standard_hours_per_week=standard_hours_per_week,
        )
        if pay_annual_leave
        else Decimal("0.00")
    )

    # Alt-day payout — uses ADP snapshot when available, else
    # ordinary daily pay (8h × hourly_rate as a defensive fallback).
    adp_per_day = Decimal("0.00")
    try:
        result = await db.execute(
            text(
                "SELECT average_daily_pay_snapshot FROM staff_members "
                "WHERE id = :id"
            ),
            {"id": str(staff_id)},
        )
        adp_raw = result.scalar_one_or_none()
        if adp_raw is not None:
            adp_per_day = Decimal(str(adp_raw)).quantize(Decimal("0.01"))
    except Exception:
        pass
    if adp_per_day == 0:
        adp_per_day = (Decimal(8) * hourly).quantize(Decimal("0.01"))

    alt_days_count = (
        (alt_remaining_hours / Decimal(8)).quantize(Decimal("0.01"))
        if alt_remaining_hours > 0
        else Decimal("0.00")
    )
    alt_payout = (
        (alt_days_count * adp_per_day).quantize(Decimal("0.01"))
        if pay_alt_days
        else Decimal("0.00")
    )

    # Casual 8% remainder.
    casual_8pct_remainder = Decimal("0.00")
    if pay_casual_8pct_remainder and (staff.employment_type or "").lower() == "casual":
        gross_ytd = await compute_gross_ytd(
            db,
            staff_id=staff_id,
            pay_date=end_date,
            tax_year_end=tax_year_end,
        )
        target_8pct = (gross_ytd * CASUAL_HOLIDAY_PAY_RATE).quantize(Decimal("0.01"))
        paid_8pct = await _compute_8pct_paid_ytd(
            db,
            staff_id=staff_id,
            end_date=end_date,
            tax_year_end=tax_year_end,
        )
        casual_8pct_remainder = max(Decimal("0.00"), target_8pct - paid_8pct)

    # Step 3 — pick the pay_period (G25 + G6).
    period = await _find_or_create_period_covering(
        db,
        org_id=org_id,
        end_date=end_date,
        user_id=user_id,
        ip_address=ip_address,
    )

    # Step 4 — generate / find the final payslip in that period.
    payslip = (
        await db.execute(
            select(Payslip).where(
                Payslip.staff_id == staff_id,
                Payslip.pay_period_id == period.id,
            )
        )
    ).scalar_one_or_none()
    if payslip is None:
        payslip = Payslip(
            org_id=org_id,
            staff_id=staff_id,
            pay_period_id=period.id,
            status="draft",
            ordinary_hours=Decimal("0"),
            overtime_hours=Decimal("0"),
            public_holiday_hours=Decimal("0"),
            ordinary_rate=staff.hourly_rate,
            overtime_rate=staff.overtime_rate,
            gross_pay=Decimal("0"),
            gross_ytd=Decimal("0"),
            net_pay=Decimal("0"),
            notes="termination",
        )
        db.add(payslip)
        await db.flush()
        await db.refresh(payslip)
        # Recurring allowance auto-attach (consistent with normal flow).
        await _auto_attach_recurring_allowances(
            db, payslip=payslip, staff=staff, period=period,
        )
    else:
        # Tag existing draft as termination via a notes append.
        existing_notes = payslip.notes or ""
        if "termination" not in existing_notes.lower():
            payslip.notes = (existing_notes + " termination").strip()

    # Step 4 lines — s27 + alt + casual-8% remainder breakdown.
    if annual_payout > 0:
        db.add(
            PayslipAllowance(
                payslip_id=payslip.id,
                allowance_type_id=None,
                label="Annual leave payout (Holidays Act s27)",
                quantity=Decimal("1"),
                unit="period",
                amount=annual_payout,
                taxable=True,
            )
        )
    if alt_payout > 0:
        db.add(
            PayslipAllowance(
                payslip_id=payslip.id,
                allowance_type_id=None,
                label=f"Alternative-day payout ({alt_days_count} day{'s' if alt_days_count != 1 else ''})",
                quantity=alt_days_count,
                unit="period",
                amount=alt_payout,
                taxable=True,
            )
        )
    if casual_8pct_remainder > 0:
        db.add(
            PayslipAllowance(
                payslip_id=payslip.id,
                allowance_type_id=None,
                label="Casual 8% holiday-pay remainder true-up",
                quantity=Decimal("1"),
                unit="period",
                amount=casual_8pct_remainder,
                taxable=True,
            )
        )
    await db.flush()

    # Step 4a — KiwiSaver scope (N15). The recompute_payslip path runs
    # KiwiSaver auto-deduction on the FULL gross including lump-sum
    # lines. To carve the lump-sum out, we temporarily strip the
    # casual_8pct + s27 + alt-day lines, recompute, then add a
    # KiwiSaver-employer + KiwiSaver-employee deduction with the
    # carved-out gross. The lump-sum lines are re-attached afterwards.
    #
    # In practice the simpler approach used here: call
    # recompute_payslip after stashing the lump-sum allowance amounts
    # into a side variable, then BUMP the deductions to align with the
    # non-lump basis.
    lump_sum_total = annual_payout + alt_payout + casual_8pct_remainder
    await recompute_payslip(db, payslip=payslip, staff=staff, period=period)
    if staff.kiwisaver_enrolled and lump_sum_total > 0:
        # Reduce the auto-attached KiwiSaver employee/employer rows by
        # the lump-sum × rate (subtracting from the over-deducted
        # amount).
        emp_rate = Decimal(str(staff.kiwisaver_employee_rate or 0)) / Decimal(100)
        empl_rate = Decimal(str(staff.kiwisaver_employer_rate or 0)) / Decimal(100)
        emp_carve = (lump_sum_total * emp_rate).quantize(Decimal("0.01"))
        empl_carve = (lump_sum_total * empl_rate).quantize(Decimal("0.01"))

        emp_row = (
            await db.execute(
                select(PayslipDeduction).where(
                    PayslipDeduction.payslip_id == payslip.id,
                    PayslipDeduction.kind == "kiwisaver_employee",
                )
            )
        ).scalar_one_or_none()
        if emp_row is not None:
            emp_row.amount = max(
                Decimal("0.00"),
                Decimal(emp_row.amount or 0) - emp_carve,
            )
        empl_row = (
            await db.execute(
                select(PayslipDeduction).where(
                    PayslipDeduction.payslip_id == payslip.id,
                    PayslipDeduction.kind == "kiwisaver_employer",
                )
            )
        ).scalar_one_or_none()
        if empl_row is not None:
            empl_row.amount = max(
                Decimal("0.00"),
                Decimal(empl_row.amount or 0) - empl_carve,
            )
        # Re-run recompute so totals reflect the adjustment.
        await recompute_payslip(db, payslip=payslip, staff=staff, period=period)

    # Step 5 — update staff + close leave balances.
    annual_hours_zeroed, alt_days_zeroed, _ = await _close_leave_balances(
        db,
        org_id=org_id,
        staff_id=staff_id,
        end_date=end_date,
        user_id=user_id,
    )

    staff.employment_end_date = end_date
    staff.is_active = False
    await db.flush()

    payout_summary = {
        # G12 — counts only, NO dollar amounts.
        "annual_hours": str(annual_hours_zeroed.quantize(Decimal("0.01"))),
        "alt_days": str(alt_days_zeroed.quantize(Decimal("0.01"))),
        "casual_8pct_remaining": str(
            (casual_8pct_remainder > 0)
            and "yes"
            or "no"
        ),
    }
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff.terminated",
        entity_type="staff_member",
        entity_id=staff_id,
        after_value={
            "staff_id": str(staff_id),
            "end_date": end_date.isoformat(),
            "reason": (reason or "")[:500],
            "payout_summary": payout_summary,
        },
        ip_address=ip_address,
    )

    return TerminationResult(
        staff_id=str(staff_id),
        end_date=end_date.isoformat(),
        payslip_id=str(payslip.id),
        pay_period_id=str(period.id),
        payout_summary=payout_summary,
    )


# Suppress "imported but unused" for symbols only used in type hints
# inside subroutines.
_ = and_

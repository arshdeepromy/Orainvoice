"""Staff service: CRUD, location assignment, utilisation, and labour costs.

**Validates: Requirement — Staff Module (R2, R3, R4 for Phase 1 task B4)**
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_encrypt
from app.modules.job_cards.models import JobCard
from app.modules.organisations.service import get_org_settings
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import (
    StaffLocationAssignment,
    StaffMember,
    StaffPayRate,
)
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
from app.modules.staff.security import is_masked_bank, is_masked_ird
from app.modules.time_clock.models import TimeClockEntry
from app.modules.time_tracking_v2.models import TimeEntry
from app.modules.timesheets.pay_cycles import (
    PayCycleValidationError,  # noqa: F401  (re-exported for callers/tests)
    set_staff_pay_cycle,
)

logger = logging.getLogger(__name__)


def _resolve_holiday_pay_method(
    employment_type: str | None,
    start: date | None,
    end: date | None,
) -> str:
    """Resolve the annual-holiday pay method (R11.1/R11.4/R11.5).

    Casual → ``casual_payg`` (R11.1). Fixed-term with an agreed term of 3 months
    or less → ``casual_payg`` automatically (R11.5). Fixed-term >3 & <12 months
    requires explicit agreement (R11.4) — no agreement field exists yet, so it
    stays ``accrued``. Everything else accrues.
    """
    et = (employment_type or "").lower()
    if et == "casual":
        return "casual_payg"
    if et == "fixed_term" and start is not None and end is not None:
        term_months = (end.year - start.year) * 12 + (end.month - start.month)
        if term_months <= 3:
            return "casual_payg"
    return "accrued"


async def _vest_on_demand(db: AsyncSession, staff_id: uuid.UUID) -> None:
    """Best-effort on-demand eligibility vesting (R7.4, R10.1, R10.4, R12.1).

    Vests day-one entitlements and any already-passed milestones immediately so
    the staff member doesn't wait for the nightly sweep. Never raises — a leave
    engine failure must not break staff create/update.
    """
    try:
        from app.modules.leave.rules.sweep import evaluate_one_staff

        await evaluate_one_staff(db, staff_id, date.today())
    except Exception:  # pragma: no cover - defensive, best-effort
        logger.warning(
            "on-demand leave vesting failed for staff=%s", staff_id, exc_info=True
        )


# ---------------------------------------------------------------------------
# Service-layer exceptions (Phase 1 task B4)
# ---------------------------------------------------------------------------


class MinimumWageBelowThresholdError(Exception):
    """Raised by ``create_staff`` / ``update_staff`` when the submitted
    ``hourly_rate`` is below the org's configured minimum-wage threshold
    and the request did not include ``minimum_wage_override=true``.

    The ``threshold`` attribute exposes the value the request was
    compared against so the router can surface it in the HTTP 422
    response body (per R4 / C10).
    """

    def __init__(self, threshold: Decimal) -> None:
        self.threshold = threshold
        super().__init__(
            f"hourly_rate is below the NZ minimum wage threshold of "
            f"NZD {threshold}",
        )


class DuplicateStaffError(ValueError):
    """Raised by ``StaffService._check_duplicates`` when a create/update would
    collide with an existing **active** staff member in the same organisation
    on a uniqueness-scoped field (email, phone, or employee_id).

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers
    keep working unchanged, while additionally exposing a machine-readable
    ``code`` and a human-readable ``message`` for the ``{message, code}``
    error contract the staff routers surface (R1.5).

    ``code`` is derived from the first conflicting field, e.g.
    ``duplicate_email`` / ``duplicate_phone`` / ``duplicate_employee_id``.

    Validates: Requirements 1.5, 1.9.
    """

    def __init__(self, conflicts: list[str], *, code: str = "duplicate_staff") -> None:
        self.conflicts = conflicts
        self.code = code
        self.message = "; ".join(conflicts)
        super().__init__(self.message)


# Default threshold applied when the org has not customised it via the
# Settings UI. Keeps create/update working before B6's settings entry is
# populated and matches the design's "no row backfill needed" rule.
_DEFAULT_MINIMUM_WAGE_THRESHOLD = Decimal("23.15")


# Org timezone fallback when ``organisations.timezone`` is absent or invalid.
_DEFAULT_ORG_TIMEZONE = "Pacific/Auckland"

# On-time grace window applied to scheduled clock-ins (R11.5).
ON_TIME_GRACE = timedelta(minutes=5)


@dataclass
class StaffMonthStats:
    """The four "this month" metrics plus last sign-in and linked user role
    for a single staff member, as computed by
    ``StaffService.get_staff_month_stats``.

    Each metric carries an explicit ``*_has_data`` flag so the frontend can
    render "—" instead of a misleading zero when no underlying data exists
    (R12). The router maps this dataclass onto ``StaffMonthStatsResponse``.
    """

    hours_logged: Decimal
    hours_logged_has_data: bool
    jobs_completed: int
    jobs_completed_has_data: bool
    billable_ratio: int
    billable_ratio_has_data: bool
    on_time_rate: int
    on_time_rate_has_data: bool
    last_sign_in: datetime | None
    user_role: str | None


@dataclass
class StaffListKpis:
    """Org-wide staff list KPIs surfaced on the Staff list page (R1.6).

    Computed by ``StaffService.get_list_kpis``. ``avg_hourly_rate`` is
    ``None`` when no active staff member has an hourly rate, so the frontend
    renders "—" rather than a misleading 0 (R1.7). The router maps this
    dataclass onto ``StaffListKpisResponse``.
    """

    total_staff: int
    employee_count: int
    with_login_count: int
    avg_hourly_rate: Decimal | None


def org_month_bounds_utc(
    org_tz_name: str | None,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Derive the ``[month_start_utc, month_end_utc)`` half-open window for
    the current calendar month evaluated in the organisation timezone (R11.7).

    ``org_tz_name`` is ``organisations.timezone`` (``String(50)``, default
    ``Pacific/Auckland``); a missing or invalid zone name falls back to UTC.
    ``now`` is injectable for deterministic testing and defaults to
    ``datetime.now(tz=UTC)``; a naive ``now`` is assumed to be UTC.

    The returned boundaries are timezone-aware UTC datetimes suitable for
    comparison against the timezone-aware UTC columns (``clock_in_at``,
    ``start_time``, ``updated_at``, ...). Metric queries filter with
    ``column >= month_start_utc AND column < month_end_utc`` so the boundary
    is never double-counted.
    """
    try:
        tz = ZoneInfo(org_tz_name or _DEFAULT_ORG_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    local_now = current.astimezone(tz)
    month_start_local = local_now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if month_start_local.month == 12:
        month_end_local = month_start_local.replace(
            year=month_start_local.year + 1, month=1
        )
    else:
        month_end_local = month_start_local.replace(
            month=month_start_local.month + 1
        )

    month_start_utc = month_start_local.astimezone(timezone.utc)
    month_end_utc = month_end_local.astimezone(timezone.utc)
    return month_start_utc, month_end_utc


class StaffService:
    """Service layer for staff and contractor management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_staff(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        role_type: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[StaffMember], int]:
        """List staff members with pagination and filtering."""
        stmt = select(StaffMember).where(StaffMember.org_id == org_id)

        if role_type is not None:
            stmt = stmt.where(StaffMember.role_type == role_type)
        if is_active is not None:
            stmt = stmt.where(StaffMember.is_active == is_active)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(StaffMember.name).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all()), total

    async def create_staff(
        self,
        org_id: uuid.UUID,
        payload: StaffMemberCreate,
        *,
        changed_by: uuid.UUID | None = None,
    ) -> StaffMember:
        """Create a new staff member.

        Phase 1 task B4 extends the original create flow to:
        - envelope-encrypt the IRD + bank account fields when supplied
          as plaintext (skipping mask-pattern values),
        - auto-set ``probation_end_date`` to ``employment_start_date +
          90 days`` when start_date is supplied and probation_end is
          not,
        - apply the minimum-wage gate (raises
          :class:`MinimumWageBelowThresholdError` when below the org's
          threshold and ``payload.minimum_wage_override`` is False),
        - insert an initial ``staff_pay_rates`` row when an hourly or
          overtime rate is supplied,
        - call ``await db.refresh(staff)`` after the final flush so
          relationships like ``location_assignments`` can be accessed
          lazily by ``StaffMemberResponse.from_attributes`` without
          tripping ``MissingGreenlet`` (P1-N15).
        """
        # Check for duplicates within the same org
        await self._check_duplicates(org_id, payload.email, payload.phone, payload.employee_id)

        # ------------------------------------------------------------------
        # Minimum-wage gate (R4 / C10).
        # The router-side audit log entry for an explicit override is
        # written by the C10 wiring; the service merely refuses without it.
        # ------------------------------------------------------------------
        await self._check_minimum_wage(
            org_id,
            hourly_rate=payload.hourly_rate,
            override=payload.minimum_wage_override,
        )

        first = payload.first_name.strip()
        last = (payload.last_name or "").strip()
        full_name = f"{first} {last}".strip()

        # ------------------------------------------------------------------
        # Encrypt PII (IRD + bank). Skip when the value is masked or
        # missing (defence-in-depth — schema validators already reject
        # masks on UPDATE; CREATE accepts plaintext only).
        # ------------------------------------------------------------------
        ird_ciphertext: bytes | None = None
        if payload.ird_number and not is_masked_ird(payload.ird_number):
            ird_ciphertext = envelope_encrypt(payload.ird_number)

        bank_ciphertext: bytes | None = None
        if payload.bank_account_number and not is_masked_bank(
            payload.bank_account_number,
        ):
            bank_ciphertext = envelope_encrypt(payload.bank_account_number)

        # ------------------------------------------------------------------
        # Auto-set probation_end_date when start_date is supplied and
        # probation_end is not. (R2.6.)
        # ------------------------------------------------------------------
        probation_end = payload.probation_end_date
        if probation_end is None and payload.employment_start_date is not None:
            probation_end = payload.employment_start_date + timedelta(days=90)

        # ------------------------------------------------------------------
        # Phase 3 task B3a (G9) — when the caller did NOT explicitly
        # supply ``self_service_clock_enabled`` (i.e. the schema field
        # is ``None``), derive the default from the org's
        # ``clock_in_policy.default_channel``:
        #   - ``'kiosk_and_self_service'`` → True
        #   - ``'kiosk_only'`` (system default) → False
        # An explicit boolean from the caller is respected as-is, even
        # when it disagrees with the org policy. Existing staff are
        # never touched by changes to ``default_channel`` — the policy
        # only applies on NEW staff insertion (R6b.3).
        #
        # Read the column directly via SQL because the ``Organisation``
        # ORM model does not yet declare ``clock_in_policy`` as a typed
        # field (the migration adds the JSONB column but the ORM
        # extension is owned by Phase 3 task B3, not Phase 1).
        # ------------------------------------------------------------------
        self_service_flag = payload.self_service_clock_enabled
        if self_service_flag is None:
            default_channel = await self._resolve_default_clock_channel(org_id)
            self_service_flag = default_channel == "kiosk_and_self_service"

        staff = StaffMember(
            org_id=org_id,
            user_id=payload.user_id,
            name=full_name,
            first_name=first,
            last_name=last or None,
            email=payload.email,
            phone=payload.phone,
            employee_id=payload.employee_id,
            position=payload.position,
            reporting_to=payload.reporting_to,
            shift_start=payload.shift_start,
            shift_end=payload.shift_end,
            role_type=payload.role_type,
            hourly_rate=payload.hourly_rate,
            overtime_rate=payload.overtime_rate,
            availability_schedule=payload.availability_schedule,
            skills=payload.skills,
            employment_basis=payload.employment_basis,
            working_arrangement=payload.working_arrangement,
            # ----------------------------------------------------------
            # Phase 1 employment record fields (R2.1).
            # ----------------------------------------------------------
            employment_start_date=payload.employment_start_date,
            employment_end_date=payload.employment_end_date,
            employment_type=payload.employment_type,
            standard_hours_per_week=payload.standard_hours_per_week,
            tax_code=payload.tax_code,
            ird_number_encrypted=ird_ciphertext,
            student_loan=payload.student_loan,
            kiwisaver_enrolled=payload.kiwisaver_enrolled,
            kiwisaver_employee_rate=payload.kiwisaver_employee_rate,
            kiwisaver_employer_rate=payload.kiwisaver_employer_rate,
            bank_account_number_encrypted=bank_ciphertext,
            probation_end_date=probation_end,
            residency_type=payload.residency_type,
            visa_expiry_date=payload.visa_expiry_date,
            self_service_clock_enabled=self_service_flag,
            on_file_photo_url=payload.on_file_photo_url,
            emergency_contact_name=payload.emergency_contact_name,
            emergency_contact_phone=payload.emergency_contact_phone,
            weekly_roster_email_enabled=payload.weekly_roster_email_enabled,
            weekly_roster_sms_enabled=payload.weekly_roster_sms_enabled,
        )
        # Leave Balances & Eligibility: resolve casual/fixed-term annual-holiday
        # pay method (R11.1/R11.5) before the first flush.
        staff.holiday_pay_method = _resolve_holiday_pay_method(
            payload.employment_type,
            payload.employment_start_date,
            payload.employment_end_date,
        )

        self.db.add(staff)
        await self.db.flush()

        # On-demand eligibility vest (day-one + already-passed milestones).
        await _vest_on_demand(self.db, staff.id)

        # ------------------------------------------------------------------
        # Insert initial pay-rate row when a rate is supplied (R3.3).
        # ------------------------------------------------------------------
        if payload.hourly_rate is not None or payload.overtime_rate is not None:
            self.db.add(
                StaffPayRate(
                    org_id=org_id,
                    staff_id=staff.id,
                    hourly_rate=payload.hourly_rate,
                    overtime_rate=payload.overtime_rate,
                    effective_from=date.today(),
                    changed_by=changed_by,
                    change_reason="initial_rate",
                ),
            )
            await self.db.flush()

        # ------------------------------------------------------------------
        # Per-staff pay-cycle selection (per-staff-pay-cycle feature, REQ
        # 2.1, 2.4, 2.5). When a cycle was chosen, persist a staff-level
        # ``pay_cycle_assignments`` row in the SAME transaction. A raised
        # ``PayCycleValidationError`` (wrong-org or inactive cycle)
        # propagates out of create_staff and aborts the whole create —
        # ``get_db_session`` commits only on a clean return, so the staff
        # insert above is rolled back too (REQ 2.4, 2.5: "reject the entire
        # operation … SHALL NOT create the staff member").
        # ------------------------------------------------------------------
        if payload.pay_cycle_id is not None:
            await set_staff_pay_cycle(
                self.db,
                org_id=org_id,
                staff_id=staff.id,
                pay_cycle_id=payload.pay_cycle_id,
            )

        # P1-N15: refresh so lazily-loaded relationships
        # (``location_assignments``) are available when the router
        # serialises the response via ``StaffMemberResponse.from_attributes``.
        await self.db.refresh(staff)
        return staff

    async def _check_duplicates(
        self,
        org_id: uuid.UUID,
        email: str | None,
        phone: str | None,
        employee_id: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Raise :class:`DuplicateStaffError` if email, phone, or employee_id
        already exists for another **active** staff member in the same org.

        The email and employee_id comparisons are deliberately identical to the
        database partial unique indexes created by migration 0224
        (``uq_staff_active_email_per_org`` and
        ``uq_staff_active_employee_id_per_org``) so this application-level
        pre-check and the DB constraint reach the *same* duplicate
        determination (R1.9):

        - **email** — normalised, case-insensitive, active-scoped:
          ``func.lower(func.btrim(StaffMember.email)) == value.strip().lower()``
          AND ``is_active``, matching the index key
          ``(org_id, lower(btrim(email))) WHERE is_active AND email IS NOT NULL
          AND btrim(email) <> ''``.
        - **employee_id** — active-scoped exact match, matching the index key
          ``(org_id, employee_id) WHERE is_active AND employee_id IS NOT NULL
          AND btrim(employee_id) <> ''``.

        ``phone`` has no database uniqueness constraint, so it keeps the
        active-scoped trimmed-exact comparison purely as a friendly pre-check.

        A duplicate create/update is rejected with a human-readable
        ``{message, code}`` error (e.g. a "duplicate email") and the existing
        staff member is left unchanged (R1.5).

        Validates: Requirements 1.1, 1.5, 1.9.
        """
        conflicts: list[str] = []
        first_field: str | None = None
        for field_name, value in [("email", email), ("phone", phone), ("employee_id", employee_id)]:
            if not value or not value.strip():
                continue
            normalised = value.strip()
            if field_name == "email":
                # Identical to uq_staff_active_email_per_org: trim + lowercase,
                # case-insensitive, active-scoped.
                match_expr = func.lower(func.btrim(StaffMember.email)) == normalised.lower()
            else:
                # phone (no DB constraint) and employee_id
                # (uq_staff_active_employee_id_per_org keys on the raw value):
                # active-scoped trimmed-exact comparison.
                col = getattr(StaffMember, field_name)
                match_expr = col == normalised
            stmt = select(StaffMember.id).where(
                StaffMember.org_id == org_id,
                match_expr,
                StaffMember.is_active.is_(True),
            )
            if exclude_id:
                stmt = stmt.where(StaffMember.id != exclude_id)
            result = await self.db.execute(stmt.limit(1))
            if result.scalar_one_or_none() is not None:
                if first_field is None:
                    first_field = field_name
                label = field_name.replace("_", " ").title()
                conflicts.append(f"{label} '{normalised}' is already in use by another staff member")
        if conflicts:
            raise DuplicateStaffError(conflicts, code=f"duplicate_{first_field}")



    async def get_staff(
        self, org_id: uuid.UUID, staff_id: uuid.UUID,
    ) -> StaffMember | None:
        """Get a single staff member by ID."""
        stmt = select(StaffMember).where(
            and_(StaffMember.org_id == org_id, StaffMember.id == staff_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Deletion preflight — which records block a PERMANENT delete?
    # ------------------------------------------------------------------

    # Tables whose FK to staff_members is ON DELETE NO ACTION/RESTRICT, i.e.
    # they block a permanent (hard) delete while any row references the staff
    # member. Each entry: (human label, SQL count expression). Kept in sync with
    # the DB constraints (see pg_constraint confdeltype='a' on staff_members).
    _DELETE_BLOCKERS: tuple[tuple[str, str], ...] = (
        ("Payslips", "SELECT count(*) FROM payslips WHERE staff_id = :sid"),
        ("Timesheets", "SELECT count(*) FROM timesheets WHERE staff_id = :sid"),
        ("Timesheet approvals", "SELECT count(*) FROM timesheet_approvals WHERE staff_id = :sid"),
        ("Clock entries", "SELECT count(*) FROM time_clock_entries WHERE staff_id = :sid"),
        ("Leave requests", "SELECT count(*) FROM leave_requests WHERE staff_id = :sid"),
        ("Overtime requests", "SELECT count(*) FROM overtime_requests WHERE staff_id = :sid"),
        ("Schedule entries", "SELECT count(*) FROM schedule_entries WHERE staff_id = :sid"),
        ("Bookings", "SELECT count(*) FROM bookings WHERE staff_id = :sid"),
        (
            "Shift swap requests",
            "SELECT count(*) FROM shift_swap_requests "
            "WHERE requester_staff_id = :sid OR target_staff_id = :sid",
        ),
        (
            "Shift cover requests",
            "SELECT count(*) FROM shift_cover_requests "
            "WHERE requester_staff_id = :sid OR accepted_by = :sid",
        ),
    )

    async def deletion_blockers(
        self, staff_id: uuid.UUID,
    ) -> list[dict[str, object]]:
        """Return the dependent record groups that block a permanent delete.

        Each item is ``{"label": str, "count": int}`` for a referencing table
        that still has rows for this staff member (count > 0). An empty list
        means the staff member can be permanently deleted. Such records (payroll,
        timesheets, leave, etc.) are retained by design — the staff member should
        be deactivated instead of hard-deleted.
        """
        blockers: list[dict[str, object]] = []
        for label, sql in self._DELETE_BLOCKERS:
            try:
                result = await self.db.execute(text(sql), {"sid": str(staff_id)})
                count = int(result.scalar() or 0)
            except Exception:  # noqa: BLE001 — a missing table must not break the check
                count = 0
            if count > 0:
                blockers.append({"label": label, "count": count})
        return blockers

    # ------------------------------------------------------------------
    # Staff redesign — "this month" metrics (R11, R12, R9.2)
    # ------------------------------------------------------------------

    async def get_staff_month_stats(
        self,
        org_id: uuid.UUID,
        staff_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> StaffMonthStats:
        """Compute the four "this month" metrics plus last sign-in and the
        linked user's role for a single staff member.

        ``now`` is injectable for deterministic testing and defaults to
        ``datetime.now(tz=UTC)``. The calendar-month window is derived in
        the organisation timezone (R11.7) via :func:`org_month_bounds_utc`.

        Each metric carries an explicit ``*_has_data`` flag so the frontend
        can render "—" rather than a misleading zero when no underlying data
        exists (R12). All aggregate queries are ``org_id``- and
        ``staff_id``-scoped and filter on the half-open
        ``[month_start_utc, month_end_utc)`` interval so the month boundary
        is never double-counted.

        Returns a :class:`StaffMonthStats` dataclass; the router maps it onto
        ``StaffMonthStatsResponse``. Assumes the caller has already verified
        the staff member belongs to ``org_id`` and passed the RBAC/self-scope
        check.
        """
        # Local import keeps this module free of an import-time dependency
        # on the auth module (avoids cycles), mirroring
        # ``get_pay_rate_history``.
        from app.modules.auth.models import User

        # Load the staff member to obtain the linked ``user_id``; the org
        # timezone drives the month-boundary calculation.
        staff = await self.get_staff(org_id, staff_id)

        org_tz_name = (
            await self.db.execute(
                text("SELECT timezone FROM organisations WHERE id = :org_id"),
                {"org_id": str(org_id)},
            )
        ).scalar_one_or_none()

        month_start_utc, month_end_utc = org_month_bounds_utc(
            org_tz_name, now=now,
        )

        # ------------------------------------------------------------------
        # Hours_Logged (R11.2, R12.2) — SUM(worked_minutes)/60 over completed
        # in-month clock entries; has_data false when no completed entries.
        # ------------------------------------------------------------------
        hours_row = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(TimeClockEntry.worked_minutes), 0,
                    ).label("minutes"),
                    func.count(TimeClockEntry.id).label("n"),
                ).where(
                    TimeClockEntry.org_id == org_id,
                    TimeClockEntry.staff_id == staff_id,
                    TimeClockEntry.clock_out_at.isnot(None),
                    TimeClockEntry.clock_in_at >= month_start_utc,
                    TimeClockEntry.clock_in_at < month_end_utc,
                )
            )
        ).one()
        hours_logged = Decimal(hours_row.minutes) / Decimal(60)
        hours_logged_has_data = hours_row.n > 0

        # ------------------------------------------------------------------
        # Jobs_Completed (R11.3) — count completed/invoiced job cards
        # assigned to this staff member whose updated_at is in-month.
        # ------------------------------------------------------------------
        jobs_completed = (
            await self.db.execute(
                select(func.count(JobCard.id)).where(
                    JobCard.org_id == org_id,
                    JobCard.assigned_to == staff_id,
                    JobCard.status.in_(("completed", "invoiced")),
                    JobCard.updated_at >= month_start_utc,
                    JobCard.updated_at < month_end_utc,
                )
            )
        ).scalar() or 0
        jobs_completed = int(jobs_completed)
        # A count of 0 is a true zero (the staff member completed no jobs),
        # so the count is always meaningful — has_data tracks that a count
        # was computed.
        jobs_completed_has_data = True

        # ------------------------------------------------------------------
        # Billable_Ratio (R11.4, R12.3) — SUM(billable)/SUM(total)*100,
        # mirroring reports_v2 Staff Utilisation; has_data false when total
        # logged minutes is zero.
        # ------------------------------------------------------------------
        billable_row = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(TimeEntry.duration_minutes), 0,
                    ).label("total"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    TimeEntry.is_billable.is_(True),
                                    TimeEntry.duration_minutes,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("billable"),
                ).where(
                    TimeEntry.org_id == org_id,
                    TimeEntry.staff_id == staff_id,
                    TimeEntry.start_time >= month_start_utc,
                    TimeEntry.start_time < month_end_utc,
                )
            )
        ).one()
        if billable_row.total > 0:
            billable_ratio = int(
                round(
                    Decimal(billable_row.billable)
                    / Decimal(billable_row.total)
                    * 100
                )
            )
            billable_ratio_has_data = True
        else:
            billable_ratio = 0
            billable_ratio_has_data = False

        # ------------------------------------------------------------------
        # On_Time_Rate (R11.5, R11.6, R12.4) — percentage of scheduled
        # in-month clock-ins within the 5-min grace window; unscheduled
        # entries excluded from the denominator; has_data false when no
        # scheduled in-month entries.
        # ------------------------------------------------------------------
        on_time_row = (
            await self.db.execute(
                select(
                    func.count(TimeClockEntry.id).label("scheduled"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    TimeClockEntry.clock_in_at
                                    <= ScheduleEntry.start_time + ON_TIME_GRACE,
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("on_time"),
                )
                .select_from(TimeClockEntry)
                .join(
                    ScheduleEntry,
                    TimeClockEntry.scheduled_entry_id == ScheduleEntry.id,
                )
                .where(
                    TimeClockEntry.org_id == org_id,
                    TimeClockEntry.staff_id == staff_id,
                    TimeClockEntry.scheduled_entry_id.isnot(None),
                    TimeClockEntry.clock_in_at >= month_start_utc,
                    TimeClockEntry.clock_in_at < month_end_utc,
                )
            )
        ).one()
        if on_time_row.scheduled > 0:
            on_time_rate = int(
                round(
                    Decimal(on_time_row.on_time)
                    / Decimal(on_time_row.scheduled)
                    * 100
                )
            )
            on_time_rate_has_data = True
        else:
            on_time_rate = 0
            on_time_rate_has_data = False

        # ------------------------------------------------------------------
        # Last_Sign_In + User_Role (R11.8, R9.2) — one combined lookup of the
        # linked users row via staff.user_id. Both None when no linked user.
        # ------------------------------------------------------------------
        last_sign_in: datetime | None = None
        user_role: str | None = None
        if staff is not None and staff.user_id is not None:
            user_row = (
                await self.db.execute(
                    select(User.last_login_at, User.role).where(
                        User.id == staff.user_id,
                    )
                )
            ).one_or_none()
            if user_row is not None:
                last_sign_in, user_role = user_row

        return StaffMonthStats(
            hours_logged=hours_logged,
            hours_logged_has_data=hours_logged_has_data,
            jobs_completed=jobs_completed,
            jobs_completed_has_data=jobs_completed_has_data,
            billable_ratio=billable_ratio,
            billable_ratio_has_data=billable_ratio_has_data,
            on_time_rate=on_time_rate,
            on_time_rate_has_data=on_time_rate_has_data,
            last_sign_in=last_sign_in,
            user_role=user_role,
        )

    # ------------------------------------------------------------------
    # Staff redesign — list KPI aggregates (R1.6)
    # ------------------------------------------------------------------

    async def get_list_kpis(self, org_id: uuid.UUID) -> StaffListKpis:
        """Org-wide staff KPIs for the list page (R1.6).

        Returns ``total_staff``, ``employee_count``, ``with_login_count``,
        and ``avg_hourly_rate``. All four are scoped to *active* staff for a
        consistent population: the list page's segmented filters default to
        active staff, and the with-login / avg-rate aggregates are explicitly
        defined over active staff in the design's "List KPI surfacing" note.

        ``with_login_count`` is ``COUNT(*) WHERE user_id IS NOT NULL`` over
        active staff; ``avg_hourly_rate`` is ``AVG(hourly_rate)`` over active
        staff with a non-null ``hourly_rate``, returned as ``None`` when no
        active staff member has a rate so the card renders "—" (R1.7).

        This is a pure read-only org-wide scan; no writes.
        """
        row = (
            await self.db.execute(
                select(
                    func.count(StaffMember.id).label("total_staff"),
                    func.coalesce(
                        func.sum(
                            case(
                                (StaffMember.role_type == "employee", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("employee_count"),
                    func.coalesce(
                        func.sum(
                            case(
                                (StaffMember.user_id.isnot(None), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("with_login_count"),
                    func.avg(StaffMember.hourly_rate).label("avg_hourly_rate"),
                ).where(
                    StaffMember.org_id == org_id,
                    StaffMember.is_active.is_(True),
                )
            )
        ).one()

        avg_rate = (
            Decimal(row.avg_hourly_rate)
            if row.avg_hourly_rate is not None
            else None
        )

        return StaffListKpis(
            total_staff=int(row.total_staff or 0),
            employee_count=int(row.employee_count or 0),
            with_login_count=int(row.with_login_count or 0),
            avg_hourly_rate=avg_rate,
        )

    async def update_staff(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, payload: StaffMemberUpdate,
        *,
        changed_by: uuid.UUID | None = None,
    ) -> StaffMember | None:
        """Update an existing staff member.

        Phase 1 task B4 extends the original update flow to:
        - envelope-encrypt incoming plaintext IRD + bank values, skip
          masked round-trips so the existing ciphertext is preserved,
        - apply the minimum-wage gate when ``hourly_rate`` is being
          changed (raises :class:`MinimumWageBelowThresholdError`),
        - insert a new ``staff_pay_rates`` row when ``hourly_rate`` or
          ``overtime_rate`` change to a different value, and bump
          ``last_pay_review_date`` to today (R3.4 + R6.3),
        - call ``await db.refresh(staff)`` after the final flush so
          lazy relationships continue to work post-flush (P1-N15).
        """
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            return None

        # ``model_dump(exclude_unset=True)`` keeps the "field omitted"
        # vs "field set to None" distinction the client cares about.
        update_data = payload.model_dump(exclude_unset=True)

        # Pull the special-handling fields out of the dict so the
        # generic ``setattr`` loop below can't accidentally write the
        # plaintext IRD / bank into a column that doesn't exist on the
        # model, or set the request-only override flag.
        ird_value = update_data.pop("ird_number", None)
        bank_value = update_data.pop("bank_account_number", None)
        # ``minimum_wage_override`` is a request-only flag; never a
        # column on ``staff_members``.
        update_data.pop("minimum_wage_override", None)

        # ``pay_cycle_id`` is request-only (per-staff-pay-cycle feature) and
        # NOT a ``staff_members`` column — it persists as a
        # ``pay_cycle_assignments`` row via ``set_staff_pay_cycle``. Tri-state
        # (REQ 2.2, 3.1, 3.3): the field's PRESENCE in the exclude_unset dump
        # distinguishes "omitted" (leave unchanged) from "explicit value"
        # (set/replace when a uuid, clear when null). Pop it here so the
        # generic ``setattr`` loop below can't write it to a missing column.
        pay_cycle_field_present = "pay_cycle_id" in update_data
        pay_cycle_value = update_data.pop("pay_cycle_id", None)

        # ------------------------------------------------------------------
        # Minimum-wage gate (R4 / C10) — apply when the request actually
        # supplies an ``hourly_rate`` (changed or not — same threshold
        # check the create path uses).
        # ------------------------------------------------------------------
        if "hourly_rate" in update_data:
            new_rate = update_data["hourly_rate"]
            await self._check_minimum_wage(
                org_id,
                hourly_rate=new_rate,
                override=payload.minimum_wage_override,
            )

        # ------------------------------------------------------------------
        # Encrypt IRD + bank when supplied as plaintext. Skip masked
        # values entirely so the existing ciphertext isn't overwritten.
        # ------------------------------------------------------------------
        if ird_value is not None and not is_masked_ird(ird_value):
            staff.ird_number_encrypted = envelope_encrypt(ird_value)
        if bank_value is not None and not is_masked_bank(bank_value):
            staff.bank_account_number_encrypted = envelope_encrypt(bank_value)

        # ------------------------------------------------------------------
        # Pay-rate history detection (R3.4) — capture the prior rate
        # values BEFORE the setattr loop overwrites them, so we can
        # compare and decide whether a new audit row is needed.
        # ------------------------------------------------------------------
        prior_hourly = staff.hourly_rate
        prior_overtime = staff.overtime_rate
        rate_changed = False
        if "hourly_rate" in update_data and update_data["hourly_rate"] != prior_hourly:
            rate_changed = True
        if "overtime_rate" in update_data and update_data["overtime_rate"] != prior_overtime:
            rate_changed = True

        # Check for duplicates, excluding the current staff member.
        await self._check_duplicates(
            org_id,
            update_data.get("email", staff.email),
            update_data.get("phone", staff.phone),
            update_data.get("employee_id", staff.employee_id),
            exclude_id=staff_id,
        )

        # Detect employment changes that affect leave eligibility / pay method.
        _leave_relevant_change = any(
            k in update_data
            for k in ("employment_start_date", "employment_type", "employment_end_date")
        )

        for field, value in update_data.items():
            setattr(staff, field, value)

        # Re-resolve casual/fixed-term annual-holiday pay method when the
        # employment fields changed (R11.1/R11.5). Only auto-switch INTO
        # casual_payg or out when employment_type leaves casual — never clobber
        # an explicit accrued↔casual choice for >3mo fixed-term (R11.4).
        if _leave_relevant_change:
            staff.holiday_pay_method = _resolve_holiday_pay_method(
                staff.employment_type,
                staff.employment_start_date,
                staff.employment_end_date,
            )

        # Keep legacy 'name' field in sync
        if "first_name" in update_data or "last_name" in update_data:
            first = staff.first_name or ""
            last = staff.last_name or ""
            staff.name = f"{first} {last}".strip()

        if rate_changed:
            new_hourly = update_data.get("hourly_rate", prior_hourly)
            new_overtime = update_data.get("overtime_rate", prior_overtime)
            self.db.add(
                StaffPayRate(
                    org_id=org_id,
                    staff_id=staff.id,
                    hourly_rate=new_hourly,
                    overtime_rate=new_overtime,
                    effective_from=date.today(),
                    changed_by=changed_by,
                    change_reason="rate_change",
                ),
            )
            staff.last_pay_review_date = date.today()

        # ------------------------------------------------------------------
        # Per-staff pay-cycle selection (per-staff-pay-cycle feature, REQ
        # 2.2, 3.1, 3.3). Only act when the field was present in the inbound
        # payload (tri-state): a uuid sets/replaces the staff-level
        # assignment, ``None`` clears it (→ resolves to the org default). A
        # raised ``PayCycleValidationError`` (wrong-org or inactive cycle)
        # propagates out and aborts the whole update — nothing is committed
        # (REQ 2.4, 2.5).
        # ------------------------------------------------------------------
        if pay_cycle_field_present:
            await set_staff_pay_cycle(
                self.db,
                org_id=org_id,
                staff_id=staff.id,
                pay_cycle_id=pay_cycle_value,
            )

        await self.db.flush()

        # On-demand eligibility vest when employment fields changed (so a newly
        # set start date vests day-one + passed milestones immediately).
        if _leave_relevant_change:
            await _vest_on_demand(self.db, staff.id)

        # P1-N15: refresh after the final flush so lazy relationships
        # remain accessible to the Pydantic response serialiser.
        await self.db.refresh(staff)
        return staff

    # ------------------------------------------------------------------
    # Phase 1 — pay-rate history (B5)
    # ------------------------------------------------------------------

    async def get_pay_rate_history(
        self,
        org_id: uuid.UUID,
        staff_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the pay-rate audit ledger for ``staff_id``.

        Joins ``staff_pay_rates`` to ``users`` (LEFT/OUTER — ``changed_by``
        is nullable for system-inserted rows) so each item carries the
        e-mail of whoever made the change. Mirrors the
        ``StaffPayRateResponse`` Pydantic shape so the router can pass
        the dicts straight through to ``StaffPayRateListResponse``.

        Ordered by ``effective_from DESC, created_at DESC`` so the most
        recent change appears first; ``created_at`` is the tiebreaker
        when several rows share the same effective date (e.g. the
        initial-rate row plus an immediate correction).

        Returns ``(items, total)``: ``total`` is the unfiltered count
        (without offset/limit applied) so the UI can render an accurate
        pagination footer.
        """
        # Local import keeps ``app.modules.staff.service`` free of an
        # import-time dependency on the auth module (avoids cycles).
        from app.modules.auth.models import User

        # Total — counts every row matching the org+staff filter,
        # before offset/limit. Using ``count(StaffPayRate.id)`` instead
        # of ``count()`` lets the planner avoid materialising the join.
        count_stmt = (
            select(func.count(StaffPayRate.id))
            .where(
                StaffPayRate.org_id == org_id,
                StaffPayRate.staff_id == staff_id,
            )
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginated rows with the changer's e-mail joined in.
        rows_stmt = (
            select(
                StaffPayRate.id,
                StaffPayRate.effective_from,
                StaffPayRate.hourly_rate,
                StaffPayRate.overtime_rate,
                StaffPayRate.change_reason,
                User.email.label("changed_by_email"),
            )
            .select_from(StaffPayRate)
            .outerjoin(User, StaffPayRate.changed_by == User.id)
            .where(
                StaffPayRate.org_id == org_id,
                StaffPayRate.staff_id == staff_id,
            )
            .order_by(
                StaffPayRate.effective_from.desc(),
                StaffPayRate.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(rows_stmt)
        items: list[dict[str, Any]] = [
            {
                "id": row.id,
                "effective_from": row.effective_from,
                "hourly_rate": row.hourly_rate,
                "overtime_rate": row.overtime_rate,
                "change_reason": row.change_reason,
                "changed_by_email": row.changed_by_email,
            }
            for row in result.all()
        ]
        return items, int(total)

    # ------------------------------------------------------------------
    # Phase 1 — compliance counters (C9, R6, G1, G2, G3)
    # ------------------------------------------------------------------

    async def get_compliance_summary(
        self,
        org_id: uuid.UUID,
        threshold: Decimal,
    ) -> dict[str, int]:
        """Return all 7 compliance counters in one round-trip.

        Each counter is computed via ``COUNT(*) FILTER (WHERE ...)``
        in a single SELECT against ``staff_members``, so the database
        scans the org's staff list once and bucketises into the seven
        aggregates in-pass. The partial indexes added by migration
        ``0204`` (``idx_staff_missing_employee_id`` and
        ``idx_staff_missing_start_date``) cover the G1/G3 counters, and
        the ``idx_staff_*`` indexes on ``probation_end_date``,
        ``visa_expiry_date``, etc. cover the rest.

        ``threshold`` is the org's ``minimum_wage_threshold_nzd``
        resolved by the caller (router) — not re-loaded here, to keep
        this method side-effect-free and easy to test.

        Returns a flat dict with all seven integer keys so the caller
        can shovel it straight into :class:`ComplianceSummary`.

        **Validates: Requirements R6, G1, G2, G3** (Phase 1 task C9).
        """
        # ``func.now()`` is rendered as PostgreSQL's ``now()`` which
        # uses the transaction-start timestamp — fine for compliance
        # counters that rely on coarse 14-day / 60-day / 12-month
        # windows. The ``text("interval '14 days'")`` literals avoid
        # parameterising arbitrary strings and let the planner
        # constant-fold the window bounds.
        in_14_days = func.now() + text("interval '14 days'")
        in_60_days = func.now() + text("interval '60 days'")
        twelve_months_ago = func.now() - text("interval '12 months'")
        active = StaffMember.is_active.is_(True)

        stmt = (
            select(
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.probation_end_date.between(
                            func.now(), in_14_days,
                        ),
                    ),
                )
                .label("probation_ending_soon"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.visa_expiry_date.between(
                            func.now(), in_60_days,
                        ),
                        StaffMember.residency_type.in_(
                            ("work_visa", "student_visa", "other"),
                        ),
                    ),
                )
                .label("visa_expiring_soon"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.employment_agreement_upload_id.is_(None),
                    ),
                )
                .label("missing_agreement"),
                func.count()
                .filter(
                    and_(
                        active,
                        or_(
                            StaffMember.last_pay_review_date.is_(None),
                            StaffMember.last_pay_review_date < twelve_months_ago,
                        ),
                    ),
                )
                .label("pay_review_due"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.hourly_rate.is_not(None),
                        StaffMember.hourly_rate < threshold,
                    ),
                )
                .label("below_minimum_wage"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.employee_id.is_(None),
                    ),
                )
                .label("missing_employee_id"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.employment_start_date.is_(None),
                    ),
                )
                .label("missing_start_date"),
            )
            .where(StaffMember.org_id == org_id)
        )
        row = (await self.db.execute(stmt)).one()
        return {
            "probation_ending_soon": int(row.probation_ending_soon or 0),
            "visa_expiring_soon": int(row.visa_expiring_soon or 0),
            "missing_agreement": int(row.missing_agreement or 0),
            "pay_review_due": int(row.pay_review_due or 0),
            "below_minimum_wage": int(row.below_minimum_wage or 0),
            "missing_employee_id": int(row.missing_employee_id or 0),
            "missing_start_date": int(row.missing_start_date or 0),
        }

    # ------------------------------------------------------------------
    # Phase 1 helpers (B4)
    # ------------------------------------------------------------------

    async def _resolve_minimum_wage_threshold(
        self, org_id: uuid.UUID,
    ) -> Decimal:
        """Return the org's minimum-wage threshold, defaulting to 23.15.

        Reads ``minimum_wage_threshold_nzd`` from the cached org
        settings. When the key is missing or the lookup fails (e.g.
        Redis is down and the DB read raises), returns the documented
        Phase 1 default so the create/update path keeps functioning.
        """
        try:
            settings = await get_org_settings(self.db, org_id=org_id)
        except Exception:
            return _DEFAULT_MINIMUM_WAGE_THRESHOLD
        raw = settings.get("minimum_wage_threshold_nzd")
        if raw is None:
            return _DEFAULT_MINIMUM_WAGE_THRESHOLD
        try:
            return Decimal(str(raw))
        except Exception:
            return _DEFAULT_MINIMUM_WAGE_THRESHOLD

    async def _check_minimum_wage(
        self,
        org_id: uuid.UUID,
        *,
        hourly_rate: Decimal | None,
        override: bool,
    ) -> None:
        """Raise ``MinimumWageBelowThresholdError`` when the rate is below
        the org threshold and ``override`` is False.

        ``hourly_rate`` of ``None`` short-circuits — there is no rate to
        compare. The caller must have already checked that the field is
        present in the inbound payload (so a partial update that does
        not touch the rate doesn't trip this gate).
        """
        if hourly_rate is None:
            return
        threshold = await self._resolve_minimum_wage_threshold(org_id)
        if hourly_rate < threshold and not override:
            raise MinimumWageBelowThresholdError(threshold=threshold)

    # ------------------------------------------------------------------
    # Phase 3 task B3a (G9) — default clock-in channel resolution
    # ------------------------------------------------------------------

    async def _resolve_default_clock_channel(
        self, org_id: uuid.UUID,
    ) -> str:
        """Return the org's ``clock_in_policy.default_channel``.

        Reads the JSONB column directly via SQL because the
        ``Organisation`` ORM model does not yet declare
        ``clock_in_policy`` as a typed field (the migration adds it but
        the ORM extension lives in the Phase 3 time_clock module). The
        helper falls back to the documented system default
        (``'kiosk_only'``) when the column is ``NULL``, the org row
        doesn't exist (e.g. an in-memory test using a random UUID), or
        the JSONB key is missing — so create_staff keeps working in
        every state of the data.
        """
        try:
            result = await self.db.execute(
                text(
                    "SELECT clock_in_policy FROM organisations "
                    "WHERE id = :org_id",
                ),
                {"org_id": str(org_id)},
            )
            row = result.scalar_one_or_none()
        except Exception:
            return "kiosk_only"
        if not isinstance(row, dict):
            return "kiosk_only"
        channel = row.get("default_channel")
        if not isinstance(channel, str):
            return "kiosk_only"
        return channel


    # ------------------------------------------------------------------
    # Location assignment
    # ------------------------------------------------------------------

    async def assign_to_location(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, location_id: uuid.UUID,
    ) -> StaffLocationAssignment:
        """Assign a staff member to a location. Inactive staff cannot be assigned."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            raise ValueError("Staff member not found")
        if not staff.is_active:
            raise ValueError("Cannot assign inactive staff to a location")

        # Check for existing assignment
        stmt = select(StaffLocationAssignment).where(
            and_(
                StaffLocationAssignment.staff_id == staff_id,
                StaffLocationAssignment.location_id == location_id,
            ),
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("Staff member is already assigned to this location")

        assignment = StaffLocationAssignment(
            staff_id=staff_id,
            location_id=location_id,
        )
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def remove_from_location(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, location_id: uuid.UUID,
    ) -> bool:
        """Remove a staff member from a location."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            return False
        stmt = select(StaffLocationAssignment).where(
            and_(
                StaffLocationAssignment.staff_id == staff_id,
                StaffLocationAssignment.location_id == location_id,
            ),
        )
        assignment = (await self.db.execute(stmt)).scalar_one_or_none()
        if assignment is None:
            return False
        await self.db.delete(assignment)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Utilisation calculation
    # ------------------------------------------------------------------

    async def calculate_utilisation(
        self,
        org_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        staff_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Calculate utilisation: billable hours / available hours for date range."""
        staff_stmt = select(StaffMember).where(StaffMember.org_id == org_id)
        if staff_id is not None:
            staff_stmt = staff_stmt.where(StaffMember.id == staff_id)
        staff_result = await self.db.execute(staff_stmt)
        staff_list = list(staff_result.scalars().unique().all())

        results: list[dict[str, Any]] = []
        for member in staff_list:
            # Get time entries for this staff member in the date range
            te_stmt = (
                select(
                    func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("total_minutes"),
                    func.coalesce(
                        func.sum(
                            func.case(
                                (TimeEntry.is_billable.is_(True), TimeEntry.duration_minutes),
                                else_=0,
                            )
                        ), 0,
                    ).label("billable_minutes"),
                )
                .where(
                    and_(
                        TimeEntry.org_id == org_id,
                        TimeEntry.staff_id == member.id,
                        TimeEntry.start_time >= date_from.isoformat(),
                        TimeEntry.start_time < date_to.isoformat(),
                    ),
                )
            )
            row = (await self.db.execute(te_stmt)).one()
            total_minutes = int(row[0])
            billable_minutes = int(row[1])

            # Calculate available minutes from availability schedule
            available_minutes = self._calculate_available_minutes(
                member.availability_schedule, date_from, date_to,
            )

            utilisation = (
                Decimal(str(billable_minutes)) / Decimal(str(available_minutes)) * 100
                if available_minutes > 0
                else Decimal("0")
            )

            results.append({
                "staff_id": member.id,
                "staff_name": member.name,
                "billable_minutes": billable_minutes,
                "total_minutes": total_minutes,
                "available_minutes": available_minutes,
                "utilisation_percent": round(utilisation, 2),
            })

        return results

    @staticmethod
    def _calculate_available_minutes(
        schedule: dict, date_from: date, date_to: date,
    ) -> int:
        """Calculate total available minutes from a weekly availability schedule.

        Schedule format: {"monday": {"start": "09:00", "end": "17:00"}, ...}
        Falls back to 8 hours/day, 5 days/week if schedule is empty.
        """
        if not schedule:
            # Default: 8 hours/day, Mon-Fri
            num_days = (date_to - date_from).days
            if num_days <= 0:
                return 0
            # Rough estimate: 5/7 of days are working days
            working_days = max(1, int(num_days * 5 / 7))
            return working_days * 8 * 60

        total = 0
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        current = date_from
        while current < date_to:
            day_name = day_names[current.weekday()]
            day_schedule = schedule.get(day_name)
            if day_schedule and isinstance(day_schedule, dict):
                start = day_schedule.get("start", "09:00")
                end = day_schedule.get("end", "17:00")
                try:
                    sh, sm = map(int, start.split(":"))
                    eh, em = map(int, end.split(":"))
                    minutes = (eh * 60 + em) - (sh * 60 + sm)
                    if minutes > 0:
                        total += minutes
                except (ValueError, AttributeError):
                    total += 480  # fallback 8 hours
            current = date(current.year, current.month, current.day)
            from datetime import timedelta
            current = current + timedelta(days=1)
        return total

    # ------------------------------------------------------------------
    # Labour costs
    # ------------------------------------------------------------------

    async def get_labour_costs(
        self,
        org_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        staff_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Calculate labour costs from time entries × hourly rate for date range."""
        staff_stmt = select(StaffMember).where(StaffMember.org_id == org_id)
        if staff_id is not None:
            staff_stmt = staff_stmt.where(StaffMember.id == staff_id)
        staff_result = await self.db.execute(staff_stmt)
        staff_list = list(staff_result.scalars().unique().all())

        entries: list[dict[str, Any]] = []
        grand_total = Decimal("0")

        for member in staff_list:
            te_stmt = (
                select(func.coalesce(func.sum(TimeEntry.duration_minutes), 0))
                .where(
                    and_(
                        TimeEntry.org_id == org_id,
                        TimeEntry.staff_id == member.id,
                        TimeEntry.start_time >= date_from.isoformat(),
                        TimeEntry.start_time < date_to.isoformat(),
                    ),
                )
            )
            total_minutes = (await self.db.execute(te_stmt)).scalar() or 0
            total_minutes = int(total_minutes)

            rate = member.hourly_rate or Decimal("0")
            hours = Decimal(str(total_minutes)) / Decimal("60")
            cost = round(hours * rate, 2)

            entries.append({
                "staff_id": member.id,
                "staff_name": member.name,
                "total_minutes": total_minutes,
                "hourly_rate": rate,
                "total_cost": cost,
            })
            grand_total += cost

        return {
            "entries": entries,
            "total_cost": grand_total,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }

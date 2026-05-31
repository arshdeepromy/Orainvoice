"""Public holiday engine — Phase 2 task B5.

Two responsibilities:

  1. **Otherwise Working Day (OWD) detection** (Holidays Act s12).
     :func:`is_otherwise_working_day` returns ``True`` when the
     holiday's weekday lines up with a day the staff would normally
     work. Phase 2 falls back to ``staff.availability_schedule`` —
     Phase 3 will swap in a pattern derived from ``time_clock_entries``.

  2. **Alt-day grant + s40A extension** (Holidays Act s40, s40A).
     :func:`process_holiday_for_org` runs once per (org, holiday) and:
       - flags any ``schedule_entries`` overlapping the holiday with a
         ``[Public holiday — time and a half]`` notes marker, and
       - writes a ``leave_ledger`` row with
         ``reason='public_holiday_extension'`` granting one alt-day's
         worth of hours to the ``public_holiday_alt`` balance.
     :func:`s40a_extension` extends an approved annual-leave request
     by one paid day per OWD public holiday inside the leave window.

Caching (P2-N9)
---------------

Two distinct Redis caches:

  - **Public-holiday list cache** keyed
    ``org:public_holidays:{org_id}:{from}:{to}`` — 1h TTL. Driven by
    the same Nager.Date sync that feeds ``public_holidays`` so a stale
    cache rebuilds within an hour of the next manual re-sync.

  - **Per-staff OWD cache** keyed ``staff:owd:{staff_id}:{holiday_date}``
    — 24h TTL. The OWD answer is stable for the holiday's lifetime so
    the longer TTL is safe.

**Validates: Requirement R8 — Staff Management Phase 2 task B5**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import PublicHoliday
from app.modules.leave.models import LeaveBalance, LeaveLedger, LeaveType
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember

if TYPE_CHECKING:  # pragma: no cover - import-time only
    from app.modules.leave.models import LeaveRequest

logger = logging.getLogger(__name__)


__all__ = [
    "is_otherwise_working_day",
    "process_holiday_for_org",
    "s40a_extension",
    "load_public_holidays_in_range",
]


# Map Python ``datetime.weekday()`` (Mon=0..Sun=6) onto the keys used
# by ``staff.availability_schedule`` (a JSONB blob keyed by lowercase
# weekday name). Matches design §12: "monday/tuesday/...".
_WEEKDAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Cache TTLs (seconds) — see module docstring for the rationale.
_OWD_CACHE_TTL_SECONDS = 86400  # 24h
_HOLIDAY_LIST_CACHE_TTL_SECONDS = 3600  # 1h


def _owd_cache_key(staff_id: uuid.UUID, holiday_date: date) -> str:
    return f"staff:owd:{staff_id}:{holiday_date.isoformat()}"


def _holiday_list_cache_key(
    org_id: uuid.UUID, from_date: date, to_date: date
) -> str:
    return (
        f"org:public_holidays:{org_id}:"
        f"{from_date.isoformat()}:{to_date.isoformat()}"
    )


def _std_daily_hours(staff: StaffMember) -> Decimal:
    """Working-day hours for ``staff``. Falls back to 8h when
    ``standard_hours_per_week`` is NULL — same rule used by the accrual
    engine (design §4.1.1)."""
    if staff.standard_hours_per_week:
        return (Decimal(staff.standard_hours_per_week) / Decimal(5)).quantize(
            Decimal("0.01")
        )
    return Decimal("8.00")


# ---------------------------------------------------------------------------
# OWD detection
# ---------------------------------------------------------------------------


async def is_otherwise_working_day(
    db: AsyncSession,
    staff_id: uuid.UUID,
    holiday_date: date,
) -> bool:
    """Return ``True`` when ``holiday_date`` is an Otherwise Working Day
    for the staff member.

    Phase 2 fallback: only ``staff.availability_schedule`` is consulted
    — Phase 3 will add the 4-week pattern from ``time_clock_entries``.
    The result is cached in Redis for 24h under
    ``staff:owd:{staff_id}:{holiday_date}``.

    Redis errors degrade gracefully: a Redis miss / outage falls
    through to the live computation but doesn't write back to cache,
    so we never return a stale answer.
    """
    cache_key = _owd_cache_key(staff_id, holiday_date)

    # Try the cache first. Local import keeps the module importable in
    # tests that patch ``app.core.redis.redis_pool`` per-call.
    try:
        from app.core.redis import redis_pool

        cached = await redis_pool.get(cache_key)
        if cached is not None:
            # ``decode_responses=True`` is the project default, so we
            # see strings here. Tolerate bytes for safety.
            value = cached.decode() if isinstance(cached, bytes) else cached
            return value == "1"
    except Exception:  # noqa: BLE001 - cache miss / outage; fall through.
        logger.debug("OWD cache miss for %s", cache_key, exc_info=True)

    staff: StaffMember | None = await db.get(StaffMember, staff_id)
    if staff is None:
        return False

    schedule = staff.availability_schedule or {}
    weekday_key = _WEEKDAY_KEYS[holiday_date.weekday()]
    entry = schedule.get(weekday_key)

    is_owd = False
    if isinstance(entry, dict):
        # Either a "start" string (e.g. "09:00") or an explicit
        # truthiness flag — accept both.
        is_owd = bool(entry.get("start") or entry.get("enabled"))
    elif isinstance(entry, bool):
        is_owd = entry
    elif isinstance(entry, str):
        is_owd = bool(entry.strip())

    # Best-effort cache write. Same Redis error tolerance as above.
    try:
        from app.core.redis import redis_pool

        await redis_pool.setex(
            cache_key, _OWD_CACHE_TTL_SECONDS, "1" if is_owd else "0"
        )
    except Exception:  # noqa: BLE001
        logger.debug("OWD cache write failed for %s", cache_key, exc_info=True)

    return is_owd


# ---------------------------------------------------------------------------
# Public-holiday list cache
# ---------------------------------------------------------------------------


async def load_public_holidays_in_range(
    db: AsyncSession,
    org_id: uuid.UUID,
    from_date: date,
    to_date: date,
    *,
    country_code: str = "NZ",
) -> list[PublicHoliday]:
    """Return the public-holiday rows in the inclusive ``[from, to]``
    range for the given country, with a 1h Redis cache.

    The cache stores the **list of (holiday_date, name) tuples** as a
    JSON-encoded string keyed per-org so we never serve another tenant's
    holiday list (the holidays are global per country, but the cache
    key honours the org_id contract from §4.2 / P2-N9 in case future
    work scopes the list per-org).
    """
    cache_key = _holiday_list_cache_key(org_id, from_date, to_date)

    try:
        import json

        from app.core.redis import redis_pool

        cached = await redis_pool.get(cache_key)
        if cached is not None:
            value = cached.decode() if isinstance(cached, bytes) else cached
            entries = json.loads(value)
            # Materialise into transient PublicHoliday-shaped objects so
            # callers iterate one consistent type.
            holidays: list[PublicHoliday] = []
            for row in entries:
                ph = PublicHoliday(
                    country_code=country_code,
                    holiday_date=date.fromisoformat(row["holiday_date"]),
                    name=row["name"],
                    year=date.fromisoformat(row["holiday_date"]).year,
                )
                holidays.append(ph)
            return holidays
    except Exception:  # noqa: BLE001
        logger.debug(
            "public-holiday cache miss for %s", cache_key, exc_info=True
        )

    stmt = (
        select(PublicHoliday)
        .where(
            PublicHoliday.country_code == country_code,
            PublicHoliday.holiday_date >= from_date,
            PublicHoliday.holiday_date <= to_date,
        )
        .order_by(PublicHoliday.holiday_date)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    # Best-effort cache fill.
    try:
        import json

        from app.core.redis import redis_pool

        payload = json.dumps(
            [
                {"holiday_date": r.holiday_date.isoformat(), "name": r.name}
                for r in rows
            ]
        )
        await redis_pool.setex(
            cache_key, _HOLIDAY_LIST_CACHE_TTL_SECONDS, payload
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "public-holiday cache write failed for %s", cache_key, exc_info=True
        )

    return rows


# ---------------------------------------------------------------------------
# Per-org holiday processing
# ---------------------------------------------------------------------------


async def _grant_alt_day(
    db: AsyncSession,
    staff: StaffMember,
    holiday_date: date,
) -> LeaveLedger | None:
    """Write a ``leave_ledger`` row reason='public_holiday_extension'
    crediting one alt-day's worth of hours to the staff's
    ``public_holiday_alt`` balance.

    Idempotency: a SELECT keyed on
    ``(staff_id, leave_type_id, reason='public_holiday_extension',
    occurred_at=holiday_date)`` short-circuits a duplicate run.
    Resolves the ``public_holiday_alt`` ``LeaveType`` for the staff's
    org on demand; returns ``None`` when the type is missing (e.g.
    Phase 2 migration not yet applied to the org).
    """
    lt_stmt = select(LeaveType).where(
        LeaveType.org_id == staff.org_id,
        LeaveType.code == "public_holiday_alt",
    )
    lt_result = await db.execute(lt_stmt)
    leave_type: LeaveType | None = lt_result.scalar_one_or_none()
    if leave_type is None:
        return None

    # Idempotency guard.
    exists_stmt = (
        select(LeaveLedger.id)
        .where(
            LeaveLedger.staff_id == staff.id,
            LeaveLedger.leave_type_id == leave_type.id,
            LeaveLedger.reason == "public_holiday_extension",
            LeaveLedger.occurred_at == holiday_date,
        )
        .limit(1)
    )
    if (await db.execute(exists_stmt)).scalar_one_or_none() is not None:
        return None

    granted = _std_daily_hours(staff)

    ledger = LeaveLedger(
        org_id=staff.org_id,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        delta_hours=granted,
        reason="public_holiday_extension",
        request_id=None,
        occurred_at=holiday_date,
        created_by=None,
    )
    db.add(ledger)

    # Bump the corresponding balance row (when present — backfill should
    # have created it for every active staff per migration 0205).
    bal_stmt = select(LeaveBalance).where(
        LeaveBalance.staff_id == staff.id,
        LeaveBalance.leave_type_id == leave_type.id,
    )
    balance: LeaveBalance | None = (await db.execute(bal_stmt)).scalar_one_or_none()
    if balance is not None:
        balance.accrued_hours = Decimal(balance.accrued_hours) + granted
        balance.updated_at = datetime.now(timezone.utc)

    return ledger


async def _mark_entries_time_and_a_half(
    db: AsyncSession,
    entries: list[ScheduleEntry],
) -> None:
    """Append a ``[Public holiday — time and a half]`` note to each
    schedule entry. The note is a soft flag rendered by the roster
    view; payroll consumes it via the same field. We append rather
    than overwrite so existing notes are preserved.
    """
    marker = "[Public holiday — time and a half]"
    for entry in entries:
        existing = entry.notes or ""
        if marker in existing:
            continue  # idempotent — don't double-mark.
        entry.notes = (existing + (" " if existing else "") + marker).strip()


async def _scheduled_work_entries_on_date(
    db: AsyncSession,
    staff_id: uuid.UUID,
    target_date: date,
) -> list[ScheduleEntry]:
    """Return ``schedule_entries`` for ``staff_id`` overlapping
    ``target_date`` whose ``entry_type`` indicates real work
    (``job``, ``booking``, ``other``). ``leave`` and ``break`` rows
    are excluded — they don't trigger time-and-a-half + alt-day.
    """
    day_start = datetime.combine(
        target_date, time(0, 0), tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)

    stmt = (
        select(ScheduleEntry)
        .where(
            ScheduleEntry.staff_id == staff_id,
            ScheduleEntry.entry_type.in_(("job", "booking", "other")),
            ScheduleEntry.start_time < day_end,
            ScheduleEntry.end_time > day_start,
        )
        .order_by(ScheduleEntry.start_time)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def process_holiday_for_org(
    db: AsyncSession,
    org_id: uuid.UUID,
    holiday_date: date,
) -> dict:
    """For every active staff in ``org_id``, detect OWD + react.

    Workflow per staff:

      1. Skip if the holiday is not an OWD.
      2. Look up ``schedule_entries`` overlapping ``holiday_date`` with a
         working ``entry_type``.
      3. If any such entry exists, grant the alt-day (idempotent) AND
         mark each entry with the time-and-a-half note (idempotent).

    Returns a small summary dict ``{ alt_days_granted, entries_marked,
    staff_processed }`` for the daily-task log.
    """
    staff_stmt = select(StaffMember).where(
        StaffMember.org_id == org_id,
        StaffMember.is_active.is_(True),
    )
    staff_result = await db.execute(staff_stmt)
    staff_list = list(staff_result.scalars().all())

    alt_days_granted = 0
    entries_marked = 0

    for staff in staff_list:
        if not await is_otherwise_working_day(db, staff.id, holiday_date):
            continue
        entries = await _scheduled_work_entries_on_date(
            db, staff.id, holiday_date
        )
        if not entries:
            # OWD but not scheduled to work — Phase 4 picks up "relevant
            # daily pay" for the unworked OWD; nothing for Phase 2 yet.
            continue

        ledger = await _grant_alt_day(db, staff, holiday_date)
        if ledger is not None:
            alt_days_granted += 1
        await _mark_entries_time_and_a_half(db, entries)
        entries_marked += len(entries)

    if alt_days_granted or entries_marked:
        await db.flush()

    return {
        "alt_days_granted": alt_days_granted,
        "entries_marked": entries_marked,
        "staff_processed": len(staff_list),
    }


# ---------------------------------------------------------------------------
# s40A extension
# ---------------------------------------------------------------------------


def _next_working_day(after: date) -> date:
    """Return the next weekday after ``after`` (skipping Sat / Sun).

    Public-holiday exclusions are layered in by the caller — this
    helper only handles weekend skipping so the logic in
    :func:`s40a_extension` remains linear.
    """
    cursor = after + timedelta(days=1)
    while cursor.weekday() >= 5:  # 5=Sat, 6=Sun
        cursor += timedelta(days=1)
    return cursor


async def s40a_extension(
    db: AsyncSession,
    request: "LeaveRequest",
) -> int:
    """Holidays Act s40A — when annual leave is approved and a public
    holiday falls inside the leave window on an OWD for the staff,
    extend the leave by one paid working day per such holiday.

    Triggered by :func:`app.modules.leave.service.approve_request` for
    leave requests where ``leave_type.code == 'annual'``.

    Each extension:
      1. Picks the next weekday after the request's current end_date,
         skipping any further public holidays.
      2. Inserts a ``schedule_entries`` row with ``entry_type='leave'``
         covering that day (full-day expansion).
      3. Writes a ``leave_ledger`` row with
         ``reason='public_holiday_extension'``,
         ``delta_hours=+std_daily_hours``, ``request_id`` set.

    Returns the number of extension days granted (0 when no public
    holidays inside the window are OWD for the staff).
    """
    # Lazy lookup — gating on leave-type code keeps the helper safe to
    # call defensively from approve_request.
    leave_type: LeaveType | None = await db.get(LeaveType, request.leave_type_id)
    if leave_type is None or leave_type.code != "annual":
        return 0
    if request.status != "approved":
        return 0

    staff: StaffMember | None = await db.get(StaffMember, request.staff_id)
    if staff is None:
        return 0

    holidays = await load_public_holidays_in_range(
        db, request.org_id, request.start_date, request.end_date
    )
    if not holidays:
        return 0

    holiday_dates = {h.holiday_date for h in holidays}

    extensions = 0
    cursor = request.end_date
    std_daily = _std_daily_hours(staff)

    for hol in holidays:
        if not await is_otherwise_working_day(db, staff.id, hol.holiday_date):
            continue

        # Walk forward to the next weekday that isn't itself a public
        # holiday inside the same range.
        cursor = _next_working_day(cursor)
        while cursor in holiday_dates:
            cursor = _next_working_day(cursor)

        # Insert schedule_entries row for the extension day.
        try:
            sh_h, sh_m = (staff.shift_start or "09:00").split(":")
            shift_start = time(int(sh_h), int(sh_m))
        except (ValueError, AttributeError):
            shift_start = time(9, 0)
        start_dt = datetime.combine(cursor, shift_start, tzinfo=timezone.utc)
        end_dt = datetime.fromtimestamp(
            start_dt.timestamp() + float(std_daily) * 3600,
            tz=timezone.utc,
        )
        db.add(
            ScheduleEntry(
                org_id=request.org_id,
                staff_id=request.staff_id,
                start_time=start_dt,
                end_time=end_dt,
                entry_type="leave",
                status="scheduled",
                title=f"s40A extension: {hol.name}",
                notes=f"s40A extension for {hol.name}",
            )
        )

        # Ledger row crediting the extra day.
        db.add(
            LeaveLedger(
                org_id=request.org_id,
                staff_id=request.staff_id,
                leave_type_id=request.leave_type_id,
                delta_hours=std_daily,
                reason="public_holiday_extension",
                request_id=request.id,
                occurred_at=cursor,
                created_by=request.decided_by,
            )
        )
        extensions += 1

    if extensions:
        await db.flush()

    return extensions

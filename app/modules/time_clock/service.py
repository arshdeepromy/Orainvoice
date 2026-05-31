"""Time-clock service: kiosk + self-service + admin-manual entry workflows.

Implements task B3 from `.kiro/specs/staff-management-p3`. Public surface:

  - :func:`lookup_for_kiosk` — kiosk employee_id → staff identity, with
    inline G12 rate limit (10/min/(org_id, sha256(employee_id)),
    distinct ``kiosk_lookup_rate_limited`` 429 body) layered on top of
    the dependency-level ``_check_kiosk_rate_limit`` (P3-N9).
  - :func:`kiosk_clock_action` — kiosk in/out with mandatory photo
    (``source='kiosk'``); auto-matches ``scheduled_entry_id``; computes
    ``worked_minutes`` on close.
  - :func:`self_service_clock_action` — mobile/web self-service in/out;
    refuses with 403 when ``self_service_clock_enabled=false``; honours
    org photo + geofence policy (per-branch
    ``branches.geofence_radius_metres`` is authoritative — G17).
  - :func:`admin_manual_entry` — admin-manual insert; audit-logged with
    ``action='time_clock.added'`` (R5).
  - :func:`update_manual_entry` / :func:`delete_manual_entry` — admin
    edit / delete of an existing entry; audit-logged with
    ``action='time_clock.edited'`` / ``time_clock.deleted`` (R5.4 +
    P3-N5: writes ``before_value`` + ``after_value`` JSONB).
  - :func:`lock_check` — returns ``True`` when a
    ``timesheet_approvals`` row for the staff/week with
    ``status='approved'`` exists. Manual edit / delete paths refuse
    with :class:`LockedWeekError` when locked. Scope: only
    ``time_clock_entries`` are locked (G7) — the existing
    ``time_tracking_v2`` billable timer is untouched.

Project conventions (project-overview.md):
  - All write paths use ``await db.flush()`` then
    ``await db.refresh(obj)`` (P1-N15) — never ``commit()`` because
    ``get_db_session`` runs the transaction with ``session.begin()``.
  - Audit rows go through :func:`app.core.audit.write_audit_log`
    against the ``audit_log`` table (P3-N2: singular).
  - Photo identifier param is ``photo_file_key`` everywhere
    (P3-N1) — the string returned as ``file_key`` from
    ``POST /api/v2/uploads/clock-photos``.

The break-related helpers (``start_break`` / ``end_break``) live in
:mod:`app.modules.time_clock.breaks` per task B4. The week-level
totals + lock-check helpers used by the approval router live in
:mod:`app.modules.time_clock.approvals` per task B5. The
:func:`lock_check` here is a thin local copy that the manual-edit
flow calls before mutating an entry — it does not need the totals
side of approvals.

**Validates: Requirements R3, R4, R5, R8, R9 — Staff Management Phase 3 task B3**
"""

from __future__ import annotations

import hashlib
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry, TimesheetApproval


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class TimeClockServiceError(Exception):
    """Base class for all time-clock service errors. Routers translate
    each subclass to the documented HTTP status + body shape (R3.2,
    R3.3, R3.5, R4.2, R4.4, R5.4, R9.3).
    """


class EmployeeNotFoundError(TimeClockServiceError):
    """Raised by :func:`lookup_for_kiosk` when no active staff member
    matches the submitted ``employee_id``. Router maps to HTTP 422
    ``employee_not_found`` (generic message — R3.2).
    """


class KioskLookupRateLimitedError(TimeClockServiceError):
    """Raised by :func:`lookup_for_kiosk` when the inline G12 counter
    (``kiosk_lookup:{org_id}:{sha256(employee_id)[:16]}``) trips above
    the documented 10/min budget. Router maps to HTTP 429 with
    ``Retry-After: 60`` and body ``{"detail":
    "kiosk_lookup_rate_limited"}`` per R3.3.
    """

    def __init__(self, retry_after_seconds: int = 60) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("kiosk_lookup_rate_limited")


class PhotoRequiredError(TimeClockServiceError):
    """Raised when a clock action is missing a required
    ``photo_file_key`` per the policy in force (kiosk: always required
    per R3.5 + DB CHECK; self-service: required when
    ``clock_in_policy.self_service_require_photo=true`` per R4.3).
    Router maps to HTTP 422 ``photo_required``.
    """


class SelfServiceDisabledError(TimeClockServiceError):
    """Raised by :func:`self_service_clock_action` when the staff record
    has ``self_service_clock_enabled=false``. Router maps to HTTP 403
    with body ``{"detail": "self_service_disabled"}`` per R4.2.
    """


class GeofenceFailedError(TimeClockServiceError):
    """Raised by :func:`self_service_clock_action` when geofence is
    enforced (``self_service_require_geofence=true``) and the supplied
    ``(lat, lng)`` is outside every configured branch's
    ``geofence_radius_metres`` window (G17 per-branch radius). Router
    maps to HTTP 422 ``geofence_failed`` per R4.4.
    """


class InvalidActionError(TimeClockServiceError):
    """Raised when the action sequence is invalid — e.g. ``action='in'``
    on a staff that already has an open entry, or ``action='out'`` on a
    staff with no open entry. Router maps to HTTP 409.
    """


class LockedWeekError(TimeClockServiceError):
    """Raised by manual edit / delete paths when the entry's
    ``clock_in_at`` falls inside an approved week
    (``timesheet_approvals.status='approved'``). Router maps to HTTP
    409 ``timesheet_locked`` per R9.3.
    """


class StaffNotFoundError(TimeClockServiceError):
    """Raised when a referenced ``staff_id`` does not exist in the
    target org. Router maps to HTTP 404.
    """


class TimeClockEntryNotFoundError(TimeClockServiceError):
    """Raised when a referenced ``time_clock_entry_id`` does not exist
    or belongs to a different org. Router maps to HTTP 404.
    """


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default G12 rate-limit budget (R3.3 / R6.1 default
# ``kiosk_employee_id_rate_limit: 10``). The org-level setting can
# override this via ``clock_in_policy.kiosk_employee_id_rate_limit``;
# we read that value at call time, falling back here when unset.
_DEFAULT_KIOSK_LOOKUP_BUDGET = 10
_KIOSK_LOOKUP_WINDOW_SECONDS = 60

# Default geofence radius applied when a branch has no
# ``geofence_radius_metres`` set (defensive fallback — migration 0207
# always populates the column with a 200m default).
_DEFAULT_GEOFENCE_RADIUS_METRES = 200

# Earth radius in metres — used by the haversine helper.
_EARTH_RADIUS_METRES = 6_371_000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hash_employee_id(employee_id: str) -> str:
    """SHA-256-hash + truncate the employee_id to the first 16 hex
    chars (R3.3 / G12). The raw code never touches Redis or the audit
    log — only the hash does.
    """
    return hashlib.sha256(employee_id.encode("utf-8")).hexdigest()[:16]


def _kiosk_lookup_redis_key(org_id: uuid.UUID, employee_id_hash: str) -> str:
    """Compose the Redis counter key for the G12 inline rate limit.
    Shape: ``kiosk_lookup:{org_id}:{sha256(employee_id)[:16]}``.
    """
    return f"kiosk_lookup:{org_id}:{employee_id_hash}"


async def _check_kiosk_lookup_rate_limit(
    redis: Any,
    *,
    org_id: uuid.UUID,
    employee_id_hash: str,
    budget: int,
) -> None:
    """Increment the per-(org_id, employee_id_hash) counter; raise
    :class:`KioskLookupRateLimitedError` when the counter exceeds the
    budget within the rolling 60-second window (R3.3 / G12).

    Implementation is the standard Redis ``INCR`` + ``EXPIRE`` pattern:
    on the first hit ``INCR`` returns 1 and we set the TTL; on
    subsequent hits we just increment. When the key is in soft-fail
    mode (Redis unavailable) we permit the lookup — the global
    ``_check_kiosk_rate_limit`` dependency still applies the
    coarse-grained 30/min/kiosk-user cap.
    """
    if redis is None:
        return  # Redis unavailable — soft-fail; rely on dependency cap.
    key = _kiosk_lookup_redis_key(org_id, employee_id_hash)
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _KIOSK_LOOKUP_WINDOW_SECONDS)
    except Exception:  # noqa: BLE001 — best-effort cap, fall through.
        logger.warning(
            "kiosk_lookup_rate_limit: redis error, soft-failing key=%s",
            key,
        )
        return
    if count > budget:
        raise KioskLookupRateLimitedError(
            retry_after_seconds=_KIOSK_LOOKUP_WINDOW_SECONDS,
        )


async def _load_clock_in_policy(
    db: AsyncSession, org_id: uuid.UUID,
) -> dict[str, Any]:
    """Return the org's ``clock_in_policy`` JSONB dict.

    Reads the column directly via SQL because the ``Organisation`` ORM
    model does not yet declare ``clock_in_policy`` as a typed field
    (the migration adds it but the ORM extension is out of scope for
    task B3). Falls back to the documented default block when the
    column is unset.
    """
    result = await db.execute(
        text("SELECT clock_in_policy FROM organisations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}
    return row if isinstance(row, dict) else {}


def _haversine_metres(
    lat1: Decimal | float,
    lng1: Decimal | float,
    lat2: Decimal | float,
    lng2: Decimal | float,
) -> float:
    """Great-circle distance between two ``(lat, lng)`` pairs in metres.

    Used by the geofence check (R4.4). Decimal inputs are cast to float
    for the trig math; the precision loss is well below the 1m
    threshold that matters for a 200m branch radius.
    """
    rlat1 = math.radians(float(lat1))
    rlat2 = math.radians(float(lat2))
    dlat = math.radians(float(lat2) - float(lat1))
    dlng = math.radians(float(lng2) - float(lng1))
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_METRES * c


async def _check_geofence(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    lat: Decimal | None,
    lng: Decimal | None,
) -> None:
    """Refuse with :class:`GeofenceFailedError` when ``(lat, lng)`` is
    outside every configured branch's ``geofence_radius_metres`` window.

    A branch counts as "configured" when both ``lat`` and ``lng`` are
    non-null. Branches with a null lat/lng don't constrain the staff
    (the org admin hasn't set a location yet). When NO branch in the
    org has a configured lat/lng, the geofence is treated as disabled
    — there's nothing to compare against — and the call passes.

    G17 — the per-branch ``geofence_radius_metres`` column is
    authoritative; the org-level ``clock_in_policy.branch_radius_metres``
    is only used at branch CREATE time (task B12).
    """
    if lat is None or lng is None:
        raise GeofenceFailedError("geofence_failed: lat/lng required")
    rows = (
        await db.execute(
            text(
                """
                SELECT lat, lng, geofence_radius_metres
                FROM branches
                WHERE org_id = :org_id
                  AND lat IS NOT NULL
                  AND lng IS NOT NULL
                """
            ),
            {"org_id": str(org_id)},
        )
    ).all()
    if not rows:
        # No anchored branch — geofence has nothing to enforce against.
        return
    for row in rows:
        radius = row.geofence_radius_metres or _DEFAULT_GEOFENCE_RADIUS_METRES
        distance = _haversine_metres(row.lat, row.lng, lat, lng)
        if distance <= float(radius):
            return
    raise GeofenceFailedError("geofence_failed: outside all branch radii")


async def _find_open_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
) -> TimeClockEntry | None:
    """Return the staff's currently-open ``time_clock_entries`` row
    (``clock_out_at IS NULL``) or ``None`` when the staff is not
    currently clocked in. Indexed by ``idx_time_clock_open`` per
    migration 0208.
    """
    stmt = (
        select(TimeClockEntry)
        .where(
            and_(
                TimeClockEntry.org_id == org_id,
                TimeClockEntry.staff_id == staff_id,
                TimeClockEntry.clock_out_at.is_(None),
            ),
        )
        .order_by(TimeClockEntry.clock_in_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _match_scheduled_entry(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    when: datetime,
) -> uuid.UUID | None:
    """Auto-match a ``schedule_entries`` row whose
    ``(start_time, end_time)`` window contains ``when`` (R3.8).

    When multiple shifts overlap (e.g. a long shift with a nested
    cover), pick the one whose ``start_time`` is closest to ``when``
    so the kiosk row links to the operator's intended shift. Excludes
    cancelled shifts via the positive ``status.in_(['scheduled',
    'completed'])`` set (P3-N7).
    """
    stmt = (
        select(ScheduleEntry.id, ScheduleEntry.start_time)
        .where(
            and_(
                ScheduleEntry.staff_id == staff_id,
                ScheduleEntry.start_time <= when,
                ScheduleEntry.end_time >= when,
                ScheduleEntry.entry_type.in_(["job", "booking", "other"]),
                ScheduleEntry.status.in_(["scheduled", "completed"]),
            ),
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return None
    # Sort by abs(start_time - when) — closest-start wins.
    best = min(rows, key=lambda r: abs((r.start_time - when).total_seconds()))
    return best.id


def _compute_worked_minutes(
    *,
    clock_in_at: datetime,
    clock_out_at: datetime,
    break_minutes: int,
) -> int:
    """Compute ``worked_minutes`` = ``(clock_out_at - clock_in_at) -
    break_minutes`` (R3.7). Floors at zero so negative break-minutes
    inputs (or pathological back-dated edits) can't yield a negative
    payable count downstream.
    """
    elapsed = clock_out_at - clock_in_at
    elapsed_minutes = int(elapsed.total_seconds() // 60)
    return max(0, elapsed_minutes - max(0, int(break_minutes or 0)))


async def lock_check(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    when_dt: datetime,
) -> bool:
    """Return ``True`` when the staff/date falls inside an approved
    timesheet week (R9.3 / G7 — ``time_clock_entries`` are locked, the
    ``time_entries`` billable timer is not).

    Used by the manual-edit / delete paths to refuse mutations against
    locked weeks. The approvals service in
    :mod:`app.modules.time_clock.approvals` owns the upsert + reopen
    flow; this helper is the read-only gate.
    """
    target_date = when_dt.date() if isinstance(when_dt, datetime) else when_dt
    stmt = (
        select(TimesheetApproval.id)
        .where(
            and_(
                TimesheetApproval.org_id == org_id,
                TimesheetApproval.staff_id == staff_id,
                TimesheetApproval.status == "approved",
                TimesheetApproval.week_start <= target_date,
                TimesheetApproval.week_end >= target_date,
            ),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


def _entry_to_dict(entry: TimeClockEntry) -> dict[str, Any]:
    """Serialise a :class:`TimeClockEntry` to a JSON-safe dict for the
    audit log ``before_value`` / ``after_value`` columns. Decimal /
    UUID / datetime values are cast to strings so the audit
    serialiser doesn't choke (P3-N5).
    """

    def _opt_str(v: Any) -> str | None:
        return None if v is None else str(v)

    return {
        "id": str(entry.id),
        "staff_id": str(entry.staff_id),
        "clock_in_at": entry.clock_in_at.isoformat() if entry.clock_in_at else None,
        "clock_out_at": entry.clock_out_at.isoformat() if entry.clock_out_at else None,
        "source": entry.source,
        "clock_in_photo_url": entry.clock_in_photo_url,
        "clock_out_photo_url": entry.clock_out_photo_url,
        "clock_in_lat": _opt_str(entry.clock_in_lat),
        "clock_in_lng": _opt_str(entry.clock_in_lng),
        "clock_out_lat": _opt_str(entry.clock_out_lat),
        "clock_out_lng": _opt_str(entry.clock_out_lng),
        "scheduled_entry_id": _opt_str(entry.scheduled_entry_id),
        "break_minutes": entry.break_minutes,
        "notes": entry.notes,
        "worked_minutes": entry.worked_minutes,
    }


# ---------------------------------------------------------------------------
# Public API: kiosk lookup
# ---------------------------------------------------------------------------


async def lookup_for_kiosk(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    employee_id: str,
    redis: Any | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Resolve an ``employee_id`` to a kiosk-ready staff identity.

    Returns a dict matching :class:`KioskLookupResponse`:
    ``{ staff_id, first_name, on_file_photo_url, currently_clocked_in }``.

    Raises:
      - :class:`KioskLookupRateLimitedError` — when the inline G12
        counter for ``(org_id, sha256(employee_id))`` exceeds the org's
        ``clock_in_policy.kiosk_employee_id_rate_limit`` (default 10)
        within 60 seconds (R3.3). Router maps to HTTP 429 with
        ``Retry-After: 60`` and body
        ``{"detail":"kiosk_lookup_rate_limited"}``.
      - :class:`EmployeeNotFoundError` — when no active staff member
        matches ``employee_id`` in this org (R3.2). Router maps to
        HTTP 422 with the generic
        ``"Employee code not recognised. Please see your manager."``
        body so the kiosk doesn't enumerate codes.

    The caller (the kiosk router) must already have passed the
    dependency-level ``_check_kiosk_rate_limit`` (30/min/kiosk-user)
    by the time this function runs — the two limiters layer per
    P3-N9.
    """
    employee_id_hash = _hash_employee_id(employee_id)

    # ---------------- Inline G12 rate limit ----------------
    policy = await _load_clock_in_policy(db, org_id)
    budget = int(
        policy.get("kiosk_employee_id_rate_limit", _DEFAULT_KIOSK_LOOKUP_BUDGET),
    )
    try:
        await _check_kiosk_lookup_rate_limit(
            redis,
            org_id=org_id,
            employee_id_hash=employee_id_hash,
            budget=budget,
        )
    except KioskLookupRateLimitedError:
        # Audit the trip so ops can see enumeration attempts in the
        # audit_log feed. Hashed identifier only — never the raw code.
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=None,
            action="kiosk.lookup_rate_limited",
            entity_type="kiosk_lookup",
            entity_id=None,
            after_value={
                "org_id": str(org_id),
                "employee_id_hash": employee_id_hash,
                "retry_after": _KIOSK_LOOKUP_WINDOW_SECONDS,
            },
            ip_address=ip_address,
        )
        raise

    # ---------------- Staff lookup ----------------
    stmt = (
        select(StaffMember)
        .where(
            and_(
                StaffMember.org_id == org_id,
                StaffMember.employee_id == employee_id,
                StaffMember.is_active.is_(True),
            ),
        )
        .limit(1)
    )
    staff: StaffMember | None = (await db.execute(stmt)).scalar_one_or_none()
    if staff is None:
        raise EmployeeNotFoundError("employee_not_found")

    open_entry = await _find_open_entry(db, org_id=org_id, staff_id=staff.id)

    return {
        "staff_id": staff.id,
        "first_name": staff.first_name or staff.name or "",
        "on_file_photo_url": staff.on_file_photo_url,
        "currently_clocked_in": open_entry is not None,
    }


# ---------------------------------------------------------------------------
# Public API: kiosk clock action (in/out + mandatory photo)
# ---------------------------------------------------------------------------


async def kiosk_clock_action(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    action: str,
    photo_file_key: str,
    ip_address: str | None = None,
) -> TimeClockEntry:
    """Handle a kiosk clock-in or clock-out action.

    Mandatory ``photo_file_key`` per R3.5 + the DB CHECK
    ``ck_time_clock_entries_kiosk_photo``. On clock-in:
      - inserts a new ``time_clock_entries`` row with ``source='kiosk'``,
      - auto-matches ``scheduled_entry_id`` via the
        ``schedule_entries`` window (R3.8),
      - writes audit ``time_clock.in``.
    On clock-out:
      - finds the staff's open entry,
      - sets ``clock_out_at = now()`` + ``clock_out_photo_url``,
      - computes ``worked_minutes`` via :func:`_compute_worked_minutes`
        (R3.7),
      - writes audit ``time_clock.out``.

    Raises:
      - :class:`PhotoRequiredError` — empty / missing ``photo_file_key``.
      - :class:`StaffNotFoundError` — staff not in org.
      - :class:`InvalidActionError` — ``action='in'`` while open entry
        exists, or ``action='out'`` with no open entry.
    """
    if not photo_file_key:
        raise PhotoRequiredError("photo_required")
    if action not in ("in", "out"):
        raise InvalidActionError(f"invalid_action: {action}")

    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise StaffNotFoundError("staff_not_found")

    return await _perform_clock_action(
        db,
        org_id=org_id,
        staff=staff,
        action=action,
        source="kiosk",
        photo_file_key=photo_file_key,
        lat=None,
        lng=None,
        created_by=None,
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Public API: self-service clock action
# ---------------------------------------------------------------------------


async def self_service_clock_action(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    action: str,
    photo_file_key: str | None,
    lat: Decimal | None = None,
    lng: Decimal | None = None,
    source: str = "self_service_mobile",
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TimeClockEntry:
    """Handle a self-service (mobile/web) clock-in or clock-out.

    Refuses with :class:`SelfServiceDisabledError` when the staff
    record's ``self_service_clock_enabled=false`` (R4.2). When the
    org's ``clock_in_policy.self_service_require_photo=true`` (default
    true per R4.3), refuses with :class:`PhotoRequiredError` when no
    ``photo_file_key`` is supplied. When
    ``clock_in_policy.self_service_require_geofence=true`` (R4.4),
    runs the geofence check via :func:`_check_geofence` against the
    org's branches.

    ``source`` must be one of ``self_service_mobile`` or
    ``self_service_web`` — the router resolves this from the
    User-Agent header.
    """
    if action not in ("in", "out"):
        raise InvalidActionError(f"invalid_action: {action}")
    if source not in ("self_service_mobile", "self_service_web"):
        raise InvalidActionError(f"invalid_source: {source}")

    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise StaffNotFoundError("staff_not_found")

    if not staff.self_service_clock_enabled:
        raise SelfServiceDisabledError("self_service_disabled")

    policy = await _load_clock_in_policy(db, org_id)
    require_photo = bool(policy.get("self_service_require_photo", True))
    require_geofence = bool(policy.get("self_service_require_geofence", False))

    if require_photo and not photo_file_key:
        raise PhotoRequiredError("photo_required")
    if require_geofence:
        await _check_geofence(db, org_id=org_id, lat=lat, lng=lng)

    return await _perform_clock_action(
        db,
        org_id=org_id,
        staff=staff,
        action=action,
        source=source,
        photo_file_key=photo_file_key,
        lat=lat,
        lng=lng,
        created_by=user_id,
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Internal: shared in/out body
# ---------------------------------------------------------------------------


async def _perform_clock_action(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff: StaffMember,
    action: str,
    source: str,
    photo_file_key: str | None,
    lat: Decimal | None,
    lng: Decimal | None,
    created_by: uuid.UUID | None,
    ip_address: str | None,
) -> TimeClockEntry:
    """Insert a clock-in row OR update the open entry on clock-out.

    Centralised so the kiosk + self-service public paths share the
    same writer + audit pattern. The caller is responsible for any
    pre-flight gating (photo required, geofence, staff lookup) — by
    the time we get here the action is approved.
    """
    open_entry = await _find_open_entry(
        db, org_id=org_id, staff_id=staff.id,
    )
    now = datetime.now(timezone.utc)

    if action == "in":
        if open_entry is not None:
            raise InvalidActionError("already_clocked_in")
        scheduled_entry_id = await _match_scheduled_entry(
            db, staff_id=staff.id, when=now,
        )
        entry = TimeClockEntry(
            org_id=org_id,
            staff_id=staff.id,
            clock_in_at=now,
            source=source,
            clock_in_photo_url=photo_file_key,
            clock_in_lat=lat,
            clock_in_lng=lng,
            scheduled_entry_id=scheduled_entry_id,
            break_minutes=0,
            created_by=created_by,
        )
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=created_by,
            action="time_clock.in",
            entity_type="time_clock_entry",
            entity_id=entry.id,
            after_value=_entry_to_dict(entry),
            ip_address=ip_address,
        )
        return entry

    # action == 'out'
    if open_entry is None:
        raise InvalidActionError("not_clocked_in")
    open_entry.clock_out_at = now
    open_entry.clock_out_photo_url = photo_file_key
    open_entry.clock_out_lat = lat
    open_entry.clock_out_lng = lng
    open_entry.worked_minutes = _compute_worked_minutes(
        clock_in_at=open_entry.clock_in_at,
        clock_out_at=now,
        break_minutes=open_entry.break_minutes or 0,
    )
    await db.flush()
    await db.refresh(open_entry)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=created_by,
        action="time_clock.out",
        entity_type="time_clock_entry",
        entity_id=open_entry.id,
        after_value=_entry_to_dict(open_entry),
        ip_address=ip_address,
    )
    return open_entry


# ---------------------------------------------------------------------------
# Public API: admin manual entry
# ---------------------------------------------------------------------------


async def admin_manual_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    clock_in_at: datetime,
    clock_out_at: datetime | None = None,
    break_minutes: int = 0,
    notes: str | None = None,
    scheduled_entry_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TimeClockEntry:
    """Admin-manual clock-entry insert (R5).

    Manual entries:
      - set ``source='admin_manual'`` and ``created_by=user_id``,
      - do NOT require a photo (R5.3),
      - auto-match ``scheduled_entry_id`` from the ``clock_in_at``
        window when not explicitly provided (mirrors the kiosk path),
      - compute ``worked_minutes`` when both ``clock_in_at`` and
        ``clock_out_at`` are set (so the row is "complete" on insert
        for back-dated edits — common admin flow),
      - write audit ``time_clock.added`` with the inserted row in
        ``after_value`` (R5.4 / P3-N5).

    Refuses with :class:`LockedWeekError` when the ``clock_in_at``
    falls inside an approved week (R9.3).
    """
    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise StaffNotFoundError("staff_not_found")

    if await lock_check(db, org_id=org_id, staff_id=staff_id, when_dt=clock_in_at):
        raise LockedWeekError("timesheet_locked")

    if scheduled_entry_id is None:
        scheduled_entry_id = await _match_scheduled_entry(
            db, staff_id=staff_id, when=clock_in_at,
        )

    worked_minutes: int | None = None
    if clock_out_at is not None:
        worked_minutes = _compute_worked_minutes(
            clock_in_at=clock_in_at,
            clock_out_at=clock_out_at,
            break_minutes=break_minutes,
        )

    entry = TimeClockEntry(
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=clock_in_at,
        clock_out_at=clock_out_at,
        source="admin_manual",
        scheduled_entry_id=scheduled_entry_id,
        break_minutes=int(break_minutes or 0),
        notes=notes,
        created_by=created_by,
        worked_minutes=worked_minutes,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=created_by,
        action="time_clock.added",
        entity_type="time_clock_entry",
        entity_id=entry.id,
        after_value=_entry_to_dict(entry),
        ip_address=ip_address,
    )
    return entry


async def update_manual_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
    updates: dict[str, Any],
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TimeClockEntry:
    """Admin-manual edit of an existing entry (R5).

    Captures ``before_value`` BEFORE applying updates so the audit
    row carries both pre/post snapshots (R5.4 / P3-N5). Refuses with
    :class:`LockedWeekError` when the entry's ``clock_in_at`` (or
    the new value if changed) falls inside an approved week.

    When ``break_minutes`` or ``clock_out_at`` change AND the entry
    is closed, ``worked_minutes`` is re-computed.
    """
    entry = await db.get(TimeClockEntry, entry_id)
    if entry is None or entry.org_id != org_id:
        raise TimeClockEntryNotFoundError("time_clock_entry_not_found")

    if await lock_check(
        db, org_id=org_id, staff_id=entry.staff_id, when_dt=entry.clock_in_at,
    ):
        raise LockedWeekError("timesheet_locked")
    new_clock_in = updates.get("clock_in_at", entry.clock_in_at)
    if new_clock_in != entry.clock_in_at and await lock_check(
        db, org_id=org_id, staff_id=entry.staff_id, when_dt=new_clock_in,
    ):
        raise LockedWeekError("timesheet_locked")

    before = _entry_to_dict(entry)

    allowed_fields = {
        "clock_in_at",
        "clock_out_at",
        "clock_in_photo_url",
        "clock_out_photo_url",
        "clock_in_lat",
        "clock_in_lng",
        "clock_out_lat",
        "clock_out_lng",
        "scheduled_entry_id",
        "break_minutes",
        "notes",
    }
    for field, value in updates.items():
        if field in allowed_fields:
            setattr(entry, field, value)

    if entry.clock_out_at is not None:
        entry.worked_minutes = _compute_worked_minutes(
            clock_in_at=entry.clock_in_at,
            clock_out_at=entry.clock_out_at,
            break_minutes=entry.break_minutes or 0,
        )
    else:
        entry.worked_minutes = None

    await db.flush()
    await db.refresh(entry)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="time_clock.edited",
        entity_type="time_clock_entry",
        entity_id=entry.id,
        before_value=before,
        after_value=_entry_to_dict(entry),
        ip_address=ip_address,
    )
    return entry


async def delete_manual_entry(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> None:
    """Hard-delete an entry (R5). Audit writes
    ``action='time_clock.deleted'`` with the deleted row in
    ``before_value`` so forensic queries can recover the values.

    Refuses with :class:`LockedWeekError` when the entry's
    ``clock_in_at`` falls inside an approved week.
    """
    entry = await db.get(TimeClockEntry, entry_id)
    if entry is None or entry.org_id != org_id:
        raise TimeClockEntryNotFoundError("time_clock_entry_not_found")
    if await lock_check(
        db, org_id=org_id, staff_id=entry.staff_id, when_dt=entry.clock_in_at,
    ):
        raise LockedWeekError("timesheet_locked")
    before = _entry_to_dict(entry)
    await db.delete(entry)
    await db.flush()
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="time_clock.deleted",
        entity_type="time_clock_entry",
        entity_id=entry_id,
        before_value=before,
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Running-late helpers (R14b / G3)
# ---------------------------------------------------------------------------


class NoUpcomingShiftError(TimeClockServiceError):
    """Raised by :func:`report_running_late` when the staff has no
    ``schedule_entries`` row whose ``start_time`` falls in the
    ``[now-60m, now+120m]`` window. Router maps to HTTP 422 with body
    ``{"detail": "no_upcoming_shift"}`` per R14b.2.
    """


class TooManyLateReportsError(TimeClockServiceError):
    """Raised by :func:`report_running_late` when the staff has already
    submitted 3 reports for the same ``schedule_entries.id`` within
    the rolling 4-hour window (R14b.8). Router maps to HTTP 429 with
    body ``{"detail": "too_many_late_reports"}``.
    """


# Sliding window for shifts considered "in window" for a running-late
# report — the spec (R14b.2) carves out the same generous span used by
# `find_in_window_shift`.
_RUNNING_LATE_WINDOW_BEFORE = 60   # minutes
_RUNNING_LATE_WINDOW_AFTER = 120   # minutes
_RUNNING_LATE_MAX_REPORTS_PER_SHIFT = 3
_RUNNING_LATE_RATE_TTL_SECONDS = 4 * 60 * 60  # 4h


def _shift_label(entry: ScheduleEntry) -> str:
    """Short human-readable shift label for embedding in SMS bodies.

    Matches the format used by :mod:`app.modules.time_clock.swaps`
    (``"Sat 10:00-16:00"``).
    """
    start = entry.start_time
    end = entry.end_time
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (
        f"{start.strftime('%a')} {start.strftime('%H:%M')}"
        f"-{end.strftime('%H:%M')}"
    )


async def find_in_window_shift(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    window_start: datetime,
    window_end: datetime,
) -> ScheduleEntry | None:
    """Return the staff's ``schedule_entries`` row whose ``start_time``
    falls within ``[window_start, window_end]``.

    Used by :func:`report_running_late` (R14b / G3). When multiple
    shifts overlap the window, picks the one whose ``start_time`` is
    closest to ``window_start + (window_end - window_start)/2`` —
    typically the one the staff is reporting against. Cancelled
    entries are excluded via the positive
    ``status.in_(['scheduled', 'completed'])`` set (P3-N7).
    """
    stmt = (
        select(ScheduleEntry)
        .where(
            and_(
                ScheduleEntry.staff_id == staff_id,
                ScheduleEntry.start_time >= window_start,
                ScheduleEntry.start_time <= window_end,
                ScheduleEntry.entry_type.in_(["job", "booking", "other"]),
                ScheduleEntry.status.in_(["scheduled", "completed"]),
            ),
        )
        .order_by(ScheduleEntry.start_time.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return None
    midpoint = window_start + (window_end - window_start) / 2
    return min(
        rows,
        key=lambda r: abs((r.start_time - midpoint).total_seconds()),
    )


async def _resolve_running_late_recipient(
    db: AsyncSession,
    *,
    staff: StaffMember,
) -> tuple[str | None, str]:
    """Walk the ``staff.reporting_to`` chain and return ``(phone, kind)``
    for the first manager with a ``phone`` set. Falls back to the org's
    first ``org_admin`` when the chain doesn't lead anywhere (X7).

    ``kind`` is one of ``'manager'`` / ``'org_admin'`` / ``'none'`` so
    the audit row can record which branch served the SMS.
    """
    seen: set[uuid.UUID] = set()
    cursor: StaffMember | None = staff
    while cursor and cursor.reporting_to and cursor.reporting_to not in seen:
        seen.add(cursor.id)
        manager = await db.get(StaffMember, cursor.reporting_to)
        if manager is None:
            break
        if manager.phone:
            return manager.phone, "manager"
        cursor = manager

    # Fallback — first org_admin in the org.
    from app.modules.auth.models import User

    stmt = (
        select(User)
        .where(
            and_(
                User.org_id == staff.org_id,
                User.role == "org_admin",
                User.is_active.is_(True),
            ),
        )
        .limit(1)
    )
    admin: User | None = (await db.execute(stmt)).scalar_one_or_none()
    if admin is None:
        return None, "none"
    # Resolve the admin's phone via their staff record (User has no phone).
    staff_stmt = (
        select(StaffMember.phone)
        .where(StaffMember.user_id == admin.id)
        .limit(1)
    )
    phone = (await db.execute(staff_stmt)).scalar_one_or_none()
    if not phone:
        return None, "org_admin_no_phone"
    return phone, "org_admin"


async def report_running_late(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff: StaffMember,
    minutes_late: int,
    reason: str | None = None,
    redis: Any | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Staff-initiated "I'm running late" report (R14b / G3).

    1. Looks up the staff's in-window ``schedule_entries`` row via
       :func:`find_in_window_shift`. Raises
       :class:`NoUpcomingShiftError` when none is found (R14b.2 →
       HTTP 422 ``no_upcoming_shift``).
    2. Per-shift rate limit (3/shift over 4h). When exceeded raises
       :class:`TooManyLateReportsError` (R14b.8 → HTTP 429
       ``too_many_late_reports``).
    3. Resolves the manager via :func:`_resolve_running_late_recipient`
       and dispatches an SMS via :func:`send_sms` (best-effort —
       failures land in DLQ via ``dlq_task_name='running_late_sms'``).
    4. Snoozes the automated ``check_late_arrivals`` task's per-shift
       Redis key ``late:{shift_id}`` with TTL =
       ``(minutes_late + 30) * 60`` so the upcoming alert is
       suppressed (R14b.4).
    5. Writes audit row ``staff.reported_late`` with the
       ``schedule_entry_id``, ``minutes_late``, and ``reason``
       (R14b.5 / R16).

    Returns a dict matching ``RunningLateResponse``:
    ``{"ok": True, "snoozed_until": <utc datetime>}``.
    """
    from app.integrations.sms_sender import send_sms as _send_sms

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=_RUNNING_LATE_WINDOW_BEFORE)
    window_end = now + timedelta(minutes=_RUNNING_LATE_WINDOW_AFTER)

    shift = await find_in_window_shift(
        db,
        staff_id=staff.id,
        window_start=window_start,
        window_end=window_end,
    )
    if shift is None:
        raise NoUpcomingShiftError("no_upcoming_shift")

    # ---------------- Per-shift rate limit ----------------
    report_count_key = f"running_late_reports:{shift.id}"
    if redis is not None:
        try:
            count = await redis.incr(report_count_key)
            if count == 1:
                await redis.expire(
                    report_count_key, _RUNNING_LATE_RATE_TTL_SECONDS,
                )
            if count > _RUNNING_LATE_MAX_REPORTS_PER_SHIFT:
                raise TooManyLateReportsError("too_many_late_reports")
        except TooManyLateReportsError:
            raise
        except Exception:  # noqa: BLE001 - rate limit is best-effort.
            logger.warning(
                "report_running_late: redis rate-limit error, soft-failing "
                "key=%s",
                report_count_key,
            )

    # ---------------- Manager SMS ----------------
    recipient_phone, recipient_kind = await _resolve_running_late_recipient(
        db, staff=staff,
    )
    if recipient_phone:
        first_name = staff.first_name or staff.name or "Your colleague"
        body = (
            f"Heads up: {first_name} expects to be {minutes_late} min "
            f"late for {_shift_label(shift)}."
        )
        if reason:
            body = f"{body} Reason: {reason}"
        try:
            await _send_sms(
                db,
                to_phone=recipient_phone,
                body=body,
                dlq_task_name="running_late_sms",
                dlq_task_args={
                    "schedule_entry_id": str(shift.id),
                    "staff_id": str(staff.id),
                    "minutes_late": minutes_late,
                },
                org_id=org_id,
            )
        except Exception:  # noqa: BLE001 - SMS failure is best-effort.
            logger.exception(
                "report_running_late: send_sms raised shift=%s staff=%s",
                shift.id, staff.id,
            )

    # ---------------- Snooze the automated late-arrival check ----------------
    snooze_ttl_seconds = (minutes_late + 30) * 60
    snoozed_until = now + timedelta(seconds=snooze_ttl_seconds)
    if redis is not None:
        try:
            await redis.set(
                f"late:{shift.id}", "1", ex=snooze_ttl_seconds,
            )
        except Exception:  # noqa: BLE001 - snooze is best-effort.
            logger.warning(
                "report_running_late: redis snooze error key=late:%s",
                shift.id,
            )

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="staff.reported_late",
        entity_type="schedule_entry",
        entity_id=shift.id,
        after_value={
            "schedule_entry_id": str(shift.id),
            "staff_id": str(staff.id),
            "minutes_late": minutes_late,
            "reason": reason,
            "recipient_kind": recipient_kind,
            "recipient_notified": recipient_phone is not None,
        },
        ip_address=ip_address,
    )

    return {"ok": True, "snoozed_until": snoozed_until}

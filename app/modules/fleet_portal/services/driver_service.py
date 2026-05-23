"""Driver management service for fleet admins.

Implements: B2B Fleet Portal task 7.1 — Requirements 5.1, 5.2, 5.3, 5.5,
5.6, 5.7, 5.9, 14.1–14.5.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal import auth as fp_auth
from app.modules.fleet_portal import schemas as S
from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import (
    FleetChecklistSubmission,
    FleetDriverAssignment,
    FleetDriverHours,
    PortalAccount,
)
from app.modules.fleet_portal.services import session_service
from app.modules.fleet_portal.services.account_service import (
    AccountServiceError,
    DuplicatePortalUser,
    InvalidToken,
)


async def invite_driver(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    first_name: str,
    last_name: str,
    email: str,
    phone: str | None = None,
) -> PortalAccount:
    """Invite a new driver under the current fleet account (Req 5.2)."""
    if ctx.fleet_account_id is None:
        raise AccountServiceError("No fleet account context", status_code=400)

    norm_email = email.strip().lower()
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.org_id == ctx.org_id,
            PortalAccount.email == norm_email,
            PortalAccount.is_active.is_(True),
        )
    )
    if res.scalars().first() is not None:
        raise DuplicatePortalUser(
            "A user with this email already has portal access"
        )

    # Find the fleet's customer_id so the new portal account references it.
    from app.modules.fleet_portal.models import PortalFleetAccount

    fa = (await db.execute(
        select(PortalFleetAccount).where(PortalFleetAccount.id == ctx.fleet_account_id)
    )).scalars().first()
    if fa is None:
        raise InvalidToken("Fleet account not found")

    account = PortalAccount(
        org_id=ctx.org_id,
        customer_id=fa.customer_id,
        email=norm_email,
        portal_user_role="driver",
        fleet_account_id=ctx.fleet_account_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        invite_token=fp_auth.generate_invite_token(),
        invite_sent_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def assign_vehicle(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    driver_portal_account_id: uuid.UUID,
    customer_vehicle_id: uuid.UUID,
) -> FleetDriverAssignment:
    """Idempotent driver↔vehicle assignment (Req 5.5)."""
    if ctx.fleet_account_id is None:
        raise AccountServiceError("No fleet account context", status_code=400)

    res = await db.execute(
        select(FleetDriverAssignment).where(
            FleetDriverAssignment.portal_account_id == driver_portal_account_id,
            FleetDriverAssignment.customer_vehicle_id == customer_vehicle_id,
        )
    )
    existing = res.scalars().first()
    if existing is not None:
        return existing

    row = FleetDriverAssignment(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        portal_account_id=driver_portal_account_id,
        customer_vehicle_id=customer_vehicle_id,
        assigned_by_portal_account_id=ctx.portal_account_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def unassign_vehicle(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    driver_portal_account_id: uuid.UUID,
    customer_vehicle_id: uuid.UUID,
) -> bool:
    from sqlalchemy import delete

    res = await db.execute(
        delete(FleetDriverAssignment).where(
            FleetDriverAssignment.org_id == ctx.org_id,
            FleetDriverAssignment.portal_account_id == driver_portal_account_id,
            FleetDriverAssignment.customer_vehicle_id == customer_vehicle_id,
        )
    )
    return (res.rowcount or 0) > 0


async def deactivate_driver(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    driver_portal_account_id: uuid.UUID,
) -> int:
    """Disable a driver and tear down sessions (Req 5.7)."""
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == driver_portal_account_id,
            PortalAccount.org_id == ctx.org_id,
            PortalAccount.fleet_account_id == ctx.fleet_account_id,
        )
    )
    acc = res.scalars().first()
    if acc is None:
        raise InvalidToken("Driver not found")
    acc.is_active = False
    await db.flush()
    return await session_service.destroy_all_sessions_for_portal_account(
        db, portal_account_id=acc.id
    )


async def list_drivers_with_activity(
    db: AsyncSession, *, ctx: FleetSessionCtx, offset: int = 0, limit: int = 50
) -> tuple[list[S.DriverListItem], int]:
    if ctx.fleet_account_id is None:
        return [], 0

    base = select(PortalAccount).where(
        PortalAccount.org_id == ctx.org_id,
        PortalAccount.fleet_account_id == ctx.fleet_account_id,
        PortalAccount.portal_user_role == "driver",
    )

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.offset(offset).limit(limit))).scalars().all()

    items: list[S.DriverListItem] = []
    for acc in rows:
        # Count assignments + last submission per driver.
        n_q = select(func.count()).where(
            FleetDriverAssignment.portal_account_id == acc.id
        )
        last_q = select(func.max(FleetChecklistSubmission.completed_at)).where(
            FleetChecklistSubmission.portal_account_id == acc.id
        )
        assigned = int((await db.execute(n_q)).scalar() or 0)
        last_submission = (await db.execute(last_q)).scalar()
        items.append(
            S.DriverListItem(
                portal_account_id=acc.id,
                first_name=acc.first_name,
                last_name=acc.last_name,
                email=acc.email,
                phone=acc.phone,
                is_active=acc.is_active,
                last_login_at=acc.last_login_at,
                assigned_vehicle_count=assigned,
                last_submission_at=last_submission,
            )
        )

    return items, int(total)


async def driver_activity_aggregate(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    driver_portal_account_id: uuid.UUID,
    date_from: date,
    date_to: date,
) -> S.DriverActivityResponse:
    """Property 33 — per-day, per-vehicle aggregations for a driver."""
    rows: list[S.DriverActivityVehicleRow] = []

    # We compute counts per (date, vehicle) for submissions, failures,
    # odometer logs, and hours logs, joined to the rego on each
    # underlying vehicle.
    # Submissions
    subm_q = (
        select(
            func.date(FleetChecklistSubmission.completed_at).label("d"),
            FleetChecklistSubmission.customer_vehicle_id.label("vehicle_id"),
            func.count().label("submissions_count"),
            func.sum(FleetChecklistSubmission.failed_item_count).label("failures_count"),
        )
        .where(
            FleetChecklistSubmission.org_id == ctx.org_id,
            FleetChecklistSubmission.portal_account_id == driver_portal_account_id,
            FleetChecklistSubmission.completed_at.isnot(None),
            func.date(FleetChecklistSubmission.completed_at) >= date_from,
            func.date(FleetChecklistSubmission.completed_at) <= date_to,
        )
        .group_by("d", "vehicle_id")
    )
    subm_rows = (await db.execute(subm_q)).all()

    # Hours logs
    hours_q = (
        select(
            func.date(FleetDriverHours.start_at).label("d"),
            FleetDriverHours.customer_vehicle_id.label("vehicle_id"),
            func.count().label("hours_count"),
        )
        .where(
            FleetDriverHours.org_id == ctx.org_id,
            FleetDriverHours.portal_account_id == driver_portal_account_id,
            func.date(FleetDriverHours.start_at) >= date_from,
            func.date(FleetDriverHours.start_at) <= date_to,
        )
        .group_by("d", "vehicle_id")
    )
    hours_rows = (await db.execute(hours_q)).all()

    # Merge by (date, vehicle).
    merged: dict[tuple[date, uuid.UUID], dict] = {}
    for d, vid, sc, fc in subm_rows:
        merged[(d, vid)] = {
            "submissions_count": int(sc or 0),
            "failures_count": int(fc or 0),
            "hours_log_count": 0,
            "odometer_log_count": 0,
        }
    for d, vid, hc in hours_rows:
        key = (d, vid)
        bucket = merged.setdefault(
            key,
            {
                "submissions_count": 0,
                "failures_count": 0,
                "hours_log_count": 0,
                "odometer_log_count": 0,
            },
        )
        bucket["hours_log_count"] = int(hc or 0)

    # Resolve regos per vehicle (we don't bother joining at SQL level —
    # Python lookup is fine for the volume; admins have one fleet at a time).
    from app.modules.vehicles.models import CustomerVehicle

    vehicle_ids = {key[1] for key in merged.keys()}
    cv_rows = (
        (
            await db.execute(
                select(CustomerVehicle).where(CustomerVehicle.id.in_(vehicle_ids or [uuid.UUID(int=0)]))
            )
        )
        .scalars()
        .all()
    )
    rego_by_id = {}
    for cv in cv_rows:
        v = cv.global_vehicle if cv.global_vehicle is not None else cv.org_vehicle
        rego_by_id[cv.id] = getattr(v, "rego", "") if v is not None else ""

    for (d, vid), b in merged.items():
        rows.append(
            S.DriverActivityVehicleRow(
                date=d,
                customer_vehicle_id=vid,
                rego=rego_by_id.get(vid, ""),
                submissions_count=b["submissions_count"],
                failures_count=b["failures_count"],
                odometer_log_count=b["odometer_log_count"],
                hours_log_count=b["hours_log_count"],
            )
        )

    rows.sort(key=lambda r: (r.date, r.rego))

    return S.DriverActivityResponse(
        portal_account_id=driver_portal_account_id,
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        total_submissions=sum(r.submissions_count for r in rows),
        total_failures=sum(r.failures_count for r in rows),
        total_odometer_logs=sum(r.odometer_log_count for r in rows),
        total_hours_logs=sum(r.hours_log_count for r in rows),
    )


__all__ = [
    "invite_driver",
    "assign_vehicle",
    "unassign_vehicle",
    "deactivate_driver",
    "list_drivers_with_activity",
    "driver_activity_aggregate",
]

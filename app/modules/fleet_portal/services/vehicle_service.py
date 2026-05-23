"""Vehicle access for fleet admins and drivers.

Implements: B2B Fleet Portal task 6.1 — Requirements 6.1, 6.2, 6.5, 6.6,
6.7, 6.9, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7.

The service applies Property 12 (tenant + fleet isolation) and Property
13 (driver-vehicle visibility) by always filtering vehicle queries on
``org_id = ctx.org_id`` AND, for drivers, joining
``fleet_driver_assignments`` to ensure the driver has an assignment to
the vehicle. Property 14 (per-role field allowlist) is enforced in
:func:`update_vehicle_fields` by checking that every key in the payload
is in the role's allow-list.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal import schemas as S
from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import (
    FleetDriverAssignment,
    FleetDriverHours,
)
from app.modules.fleet_portal.services.expiry import badge as expiry_badge


# ---------------------------------------------------------------------------
# Per-role field allowlists (Property 14 — Req 6.6, 7.2, 7.3, 7.4)
# ---------------------------------------------------------------------------


_FLEET_ADMIN_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "fleet_internal_name",
        "fleet_number",
        "notes",
        "colour",
        "odometer_last_recorded",
        "wof_expiry",
        "cof_expiry",
        "service_due_date",
        "fleet_checklist_template_id",
    }
)

_DRIVER_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "odometer_last_recorded",
        "service_due_date",
    }
)


def allowed_fields_for_role(role: str) -> frozenset[str]:
    """Property 14 source of truth — per-role field allowlist."""
    if role == "fleet_admin":
        return _FLEET_ADMIN_ALLOWED_FIELDS
    if role == "driver":
        return _DRIVER_ALLOWED_FIELDS
    return frozenset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _customer_id_for_fleet(
    db: AsyncSession, fleet_account_id: uuid.UUID
) -> uuid.UUID | None:
    from app.modules.fleet_portal.models import PortalFleetAccount

    res = await db.execute(
        select(PortalFleetAccount.customer_id).where(
            PortalFleetAccount.id == fleet_account_id
        )
    )
    row = res.first()
    return row[0] if row else None


async def _vehicle_query_for_session(
    db: AsyncSession, ctx: FleetSessionCtx
):
    """Return a SELECT statement scoped to the current session.

    For fleet_admin: every customer_vehicle linked to the fleet's
    ``customer_id`` within the current org.
    For driver: only vehicles joined via fleet_driver_assignments.
    """
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle
    from sqlalchemy.orm import selectinload

    if ctx.fleet_account_id is None:
        # No fleet account → no vehicles. Returns an always-empty SELECT
        # so callers don't accidentally see other fleets' vehicles.
        return select(CustomerVehicle).where(False)

    customer_id = await _customer_id_for_fleet(db, ctx.fleet_account_id)
    if customer_id is None:
        return select(CustomerVehicle).where(False)

    base = select(CustomerVehicle).options(
        selectinload(CustomerVehicle.global_vehicle),
        selectinload(CustomerVehicle.org_vehicle),
    ).where(
        CustomerVehicle.org_id == ctx.org_id,
        CustomerVehicle.customer_id == customer_id,
    )

    if ctx.portal_user_role == "driver":
        base = base.join(
            FleetDriverAssignment,
            FleetDriverAssignment.customer_vehicle_id == CustomerVehicle.id,
        ).where(FleetDriverAssignment.portal_account_id == ctx.portal_account_id)

    return base


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_vehicles_for_session(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[S.VehicleListItem], int]:
    """List vehicles for the session (Req 6.1, 7.1)."""
    from app.modules.vehicles.models import CustomerVehicle

    base = await _vehicle_query_for_session(db, ctx)

    total_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(total_q)).scalar_one()

    rows = await db.execute(base.offset(offset).limit(limit))
    today = _today()
    items: list[S.VehicleListItem] = []

    for cv in rows.scalars().all():
        gv = cv.global_vehicle
        ov = cv.org_vehicle
        v = gv if gv is not None else ov
        wof = getattr(v, "wof_expiry", None) if v is not None else None
        cof = getattr(v, "cof_expiry", None) if v is not None else None
        service = getattr(v, "service_due_date", None) if v is not None else None
        rego = getattr(v, "rego", "") if v is not None else ""

        items.append(
            S.VehicleListItem(
                customer_vehicle_id=cv.id,
                rego=rego,
                make=getattr(v, "make", None),
                model=getattr(v, "model", None),
                year=getattr(v, "year", None),
                colour=getattr(v, "colour", None),
                odometer_last_recorded=getattr(v, "odometer_last_recorded", None),
                wof_expiry=wof,
                cof_expiry=cof,
                registration_expiry=getattr(v, "registration_expiry", None),
                service_due_date=service,
                wof_badge=expiry_badge(wof, today),
                cof_badge=expiry_badge(cof, today),
                service_badge=expiry_badge(service, today),
                assigned_driver_names=[],
            )
        )

    return items, int(total)


async def get_vehicle(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
) -> S.VehicleDetailResponse | None:
    """Return one vehicle's detail or None on cross-tenant / missing."""
    from app.modules.vehicles.models import CustomerVehicle

    base = await _vehicle_query_for_session(db, ctx)
    res = await db.execute(base.where(CustomerVehicle.id == customer_vehicle_id))
    cv = res.scalars().first()
    if cv is None:
        return None

    gv = cv.global_vehicle
    ov = cv.org_vehicle
    v = gv if gv is not None else ov
    today = _today()
    wof = getattr(v, "wof_expiry", None) if v is not None else None
    cof = getattr(v, "cof_expiry", None) if v is not None else None
    service = getattr(v, "service_due_date", None) if v is not None else None
    rego = getattr(v, "rego", "") if v is not None else ""

    return S.VehicleDetailResponse(
        customer_vehicle_id=cv.id,
        rego=rego,
        make=getattr(v, "make", None),
        model=getattr(v, "model", None),
        year=getattr(v, "year", None),
        colour=getattr(v, "colour", None),
        odometer_last_recorded=getattr(v, "odometer_last_recorded", None),
        wof_expiry=wof,
        cof_expiry=cof,
        registration_expiry=getattr(v, "registration_expiry", None),
        service_due_date=service,
        wof_badge=expiry_badge(wof, today),
        cof_badge=expiry_badge(cof, today),
        service_badge=expiry_badge(service, today),
        assigned_driver_names=[],
        vin=getattr(v, "vin", None),
        chassis=getattr(v, "chassis", None),
        engine_no=getattr(v, "engine_no", None),
        notes=None,
        fleet_checklist_template_id=cv.fleet_checklist_template_id,
    )


async def log_odometer_reading(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
    value_km: int,
) -> S.OdometerLogResponse:
    """Strict-greater odometer log (Property 15 / Req 7.6, 7.7)."""
    from app.modules.vehicles.models import CustomerVehicle, OdometerReading

    base = await _vehicle_query_for_session(db, ctx)
    cv_row = (await db.execute(base.where(CustomerVehicle.id == customer_vehicle_id))).scalars().first()
    if cv_row is None:
        raise ValueError("Vehicle not found")

    # Find the previous max from the existing odometer_readings table
    # plus the global vehicle's last-recorded value.
    from app.modules.admin.models import GlobalVehicle

    gv = cv_row.global_vehicle
    ov = cv_row.org_vehicle

    previous_max = 0
    if gv is not None:
        previous_max = max(previous_max, gv.odometer_last_recorded or 0)
        last_reading_q = select(func.max(OdometerReading.odometer_km)).where(
            OdometerReading.global_vehicle_id == gv.id
        )
        prev = (await db.execute(last_reading_q)).scalar()
        if prev is not None:
            previous_max = max(previous_max, prev)
    if ov is not None:
        previous_max = max(previous_max, ov.odometer_last_recorded or 0)

    if value_km <= previous_max:
        raise ValueError(
            f"Odometer reading must be greater than the most recent recorded value of {previous_max} km"
        )

    # Persist on the global_vehicles last-recorded column when available;
    # also append an odometer_readings row for history.
    now = datetime.now(timezone.utc)
    if gv is not None:
        gv.odometer_last_recorded = value_km
        reading = OdometerReading(global_vehicle_id=gv.id, odometer_km=value_km, recorded_at=now)
        db.add(reading)
    elif ov is not None:
        ov.odometer_last_recorded = value_km

    await db.flush()
    return S.OdometerLogResponse(
        customer_vehicle_id=cv_row.id,
        odometer_km=value_km,
        recorded_at=now,
    )


async def log_driver_hours(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    notes: str | None,
) -> S.HoursLogResponse:
    """Persist a fleet_driver_hours row (Req 7.5)."""
    if end_at < start_at:
        raise ValueError("end_at must be greater than or equal to start_at")
    if ctx.fleet_account_id is None:
        raise ValueError("No fleet account context for hours log")

    from app.modules.vehicles.models import CustomerVehicle

    base = await _vehicle_query_for_session(db, ctx)
    cv = (await db.execute(base.where(CustomerVehicle.id == customer_vehicle_id))).scalars().first()
    if cv is None:
        raise ValueError("Vehicle not found")

    row = FleetDriverHours(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        customer_vehicle_id=customer_vehicle_id,
        portal_account_id=ctx.portal_account_id,
        start_at=start_at,
        end_at=end_at,
        notes=notes,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return S.HoursLogResponse(
        id=row.id,
        customer_vehicle_id=row.customer_vehicle_id,
        portal_account_id=row.portal_account_id,
        start_at=row.start_at,
        end_at=row.end_at,
        notes=row.notes,
        created_at=row.created_at,
    )


def update_vehicle_fields(
    *, role: str, payload: dict
) -> dict:
    """Property 14 enforcement: filter the payload to allowed fields only.

    Raises ``PermissionError`` when any key in ``payload`` is NOT in the
    allow-list for the role. Returns the (possibly empty) filtered
    payload — the actual UPDATE statement is the caller's responsibility.
    """
    allowed = allowed_fields_for_role(role)
    bad = [k for k in payload if k not in allowed]
    if bad:
        raise PermissionError(
            f"Drivers cannot change vehicle make, model, year, VIN, or registration: {bad!r}"
            if role == "driver"
            else f"Field(s) not allowed for role={role}: {bad!r}"
        )
    return {k: payload[k] for k in payload if k in allowed}


__all__ = [
    "allowed_fields_for_role",
    "list_vehicles_for_session",
    "get_vehicle",
    "log_odometer_reading",
    "log_driver_hours",
    "update_vehicle_fields",
]

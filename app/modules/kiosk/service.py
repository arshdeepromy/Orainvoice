"""Kiosk check-in orchestration logic.

Coordinates customer lookup/creation, vehicle lookup/creation (via Carjam
with manual fallback), and vehicle-customer linking in a single atomic
operation.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 9.1, 9.5, 9.7, 9.8
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GlobalVehicle
from app.modules.customers.models import Customer
from app.modules.kiosk.schemas import (
    KioskCheckInRequest,
    KioskCheckInRequestV2,
    KioskCheckInResponse,
    KioskCheckInResponseV2,
)
from app.modules.vehicles.models import CustomerVehicle, OdometerReading, OrgVehicle

logger = logging.getLogger(__name__)


async def _search_customer_by_phone(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str,
) -> Customer | None:
    """Find an existing non-anonymised customer by phone within an org."""
    result = await db.execute(
        select(Customer).where(
            Customer.org_id == org_id,
            Customer.phone == phone,
            Customer.is_anonymised.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def customer_lookup_for_kiosk(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str | None = None,
    email: str | None = None,
) -> dict:
    """Look up customers by phone or email for kiosk auto-fill.

    Searches the customers table within the given org for records matching
    the exact phone number OR case-insensitive email address. Anonymised
    customers are excluded from results.

    Returns up to 5 matches with a total count, compatible with
    KioskCustomerLookupResponse.

    Requirements: 9.1, 9.5, 9.7, 9.8
    """
    if not phone and not email:
        raise HTTPException(
            status_code=422,
            detail="At least one of phone or email must be provided",
        )

    # Build OR conditions for matching
    conditions = []
    if phone:
        conditions.append(Customer.phone == phone)
    if email:
        conditions.append(func.lower(Customer.email) == email.lower())

    # Base query: within org, not anonymised, matching phone or email
    base_query = (
        select(Customer)
        .where(
            Customer.org_id == org_id,
            Customer.is_anonymised.is_(False),
            or_(*conditions),
        )
    )

    # Get total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Get up to 5 matches
    results = await db.execute(base_query.limit(5))
    customers = results.scalars().all()

    items = [
        {
            "id": str(c.id),
            "first_name": c.first_name,
            "last_name": c.last_name,
            "phone": c.phone,
            "email": c.email,
        }
        for c in customers
    ]

    return {"items": items, "total": total}


async def _ensure_vehicle_linked(
    db: AsyncSession,
    *,
    vehicle_id: uuid.UUID,
    customer_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
    """Link a vehicle to a customer, skipping if the link already exists.

    This makes the operation idempotent — repeated check-ins with the same
    vehicle and customer won't create duplicate link rows.

    vehicle-data-isolation Task 11.7: the existence check is widened to be
    rego-keyed so it catches links pointing at either the pre-promotion
    ``GlobalVehicle.id`` OR the post-promotion ``OrgVehicle.id`` for the
    same rego. The previous global-id-only filter would miss promoted
    links and the calling flow would create a duplicate row on every
    subsequent kiosk check-in (Req 3.4, 9.6, 13.3).
    """
    from app.modules.vehicles.service import link_vehicle_to_customer

    # Resolve the target rego up front so the existence check covers
    # both link types. ``vehicle_id`` may resolve to either a
    # GlobalVehicle (CarJam-sourced cache) or an OrgVehicle (manual-
    # entry / already-promoted row), and either flavour can be present
    # on the customer_vehicles link for this customer.
    target_rego: str | None = None
    gv_lookup = await db.execute(
        select(GlobalVehicle.rego).where(GlobalVehicle.id == vehicle_id)
    )
    target_rego = gv_lookup.scalar_one_or_none()
    if target_rego is None:
        ov_lookup = await db.execute(
            select(OrgVehicle.rego).where(
                OrgVehicle.id == vehicle_id,
                OrgVehicle.org_id == org_id,
            )
        )
        target_rego = ov_lookup.scalar_one_or_none()

    # Widened existence check (Task 11.7): match a link via either the
    # GlobalVehicle or OrgVehicle key for the resolved rego. Without
    # this, every kiosk check-in for a previously-promoted vehicle
    # creates a duplicate ``customer_vehicles`` row.
    if target_rego is not None:
        existing_link = await db.execute(
            select(CustomerVehicle)
            .outerjoin(
                GlobalVehicle,
                CustomerVehicle.global_vehicle_id == GlobalVehicle.id,
            )
            .outerjoin(
                OrgVehicle,
                CustomerVehicle.org_vehicle_id == OrgVehicle.id,
            )
            .where(
                CustomerVehicle.org_id == org_id,
                CustomerVehicle.customer_id == customer_id,
                or_(
                    func.upper(GlobalVehicle.rego) == target_rego.upper(),
                    func.upper(OrgVehicle.rego) == target_rego.upper(),
                ),
            )
            .limit(1)
        )
    else:
        # Fallback when neither GlobalVehicle nor OrgVehicle resolves —
        # preserve the historical id-keyed behaviour so a missing rego
        # lookup does not silently bypass duplicate prevention.
        existing_link = await db.execute(
            select(CustomerVehicle).where(
                CustomerVehicle.org_id == org_id,
                CustomerVehicle.customer_id == customer_id,
                CustomerVehicle.global_vehicle_id == vehicle_id,
            )
        )

    if existing_link.scalar_one_or_none() is not None:
        logger.info(
            "Vehicle %s already linked to customer %s — skipping",
            vehicle_id,
            customer_id,
        )
        return

    await link_vehicle_to_customer(
        db,
        vehicle_id=vehicle_id,
        customer_id=customer_id,
        org_id=org_id,
        user_id=user_id,
        ip_address=ip_address,
    )


async def lookup_vehicle_for_kiosk(
    db: AsyncSession,
    redis: Redis,
    *,
    rego: str,
    org_id: uuid.UUID,
) -> dict:
    """Cascading vehicle lookup for the kiosk endpoint.

    Lookup order:
    1. org_vehicles — organisation-scoped manually-entered vehicles
    2. global_vehicles — cached CarJam data (shared across orgs)
    3. CarJam API — external NZ vehicle data provider

    On CarJam success, stores the result in global_vehicles for future cache
    hits. On not found anywhere, raises HTTP 404.

    Returns a dict compatible with KioskVehicleLookupResponse.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
    """
    from app.integrations.carjam import (
        CarjamError,
        CarjamNotFoundError,
        CarjamRateLimitError,
    )
    from app.modules.vehicles.service import (
        _carjam_data_to_global_vehicle,
        _load_carjam_client,
    )

    rego = rego.upper().strip()

    # --- Step 1: Check org_vehicles (Req 3.1) ---
    logger.info("Kiosk vehicle lookup: checking org_vehicles for rego=%s, org=%s", rego, org_id)
    org_result = await db.execute(
        select(OrgVehicle).where(
            OrgVehicle.org_id == org_id,
            OrgVehicle.rego == rego,
        )
    )
    org_vehicle = org_result.scalar_one_or_none()

    if org_vehicle is not None:
        logger.info("Kiosk vehicle lookup: found in org_vehicles (id=%s)", org_vehicle.id)
        return {
            "id": str(org_vehicle.id),
            "rego": org_vehicle.rego,
            "make": org_vehicle.make,
            "model": org_vehicle.model,
            "body_type": org_vehicle.body_type,
            "year": org_vehicle.year,
            "colour": org_vehicle.colour,
            "wof_expiry": org_vehicle.wof_expiry.isoformat() if org_vehicle.wof_expiry else None,
            "cof_expiry": org_vehicle.cof_expiry.isoformat() if org_vehicle.cof_expiry else None,
            "inspection_type": org_vehicle.inspection_type,
            "rego_expiry": org_vehicle.registration_expiry.isoformat() if org_vehicle.registration_expiry else None,
            "odometer": org_vehicle.odometer_last_recorded,
            "source": "manual",
        }

    # --- Step 2: Check global_vehicles (Req 3.2) ---
    logger.info("Kiosk vehicle lookup: checking global_vehicles for rego=%s", rego)
    global_result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.rego == rego)
    )
    global_vehicle = global_result.scalar_one_or_none()

    if global_vehicle is not None:
        logger.info("Kiosk vehicle lookup: found in global_vehicles (id=%s)", global_vehicle.id)
        return {
            "id": str(global_vehicle.id),
            "rego": global_vehicle.rego,
            "make": global_vehicle.make,
            "model": global_vehicle.model,
            "body_type": global_vehicle.body_type,
            "year": global_vehicle.year,
            "colour": global_vehicle.colour,
            "wof_expiry": global_vehicle.wof_expiry.isoformat() if global_vehicle.wof_expiry else None,
            "cof_expiry": global_vehicle.cof_expiry.isoformat() if global_vehicle.cof_expiry else None,
            "inspection_type": global_vehicle.inspection_type,
            "rego_expiry": global_vehicle.registration_expiry.isoformat() if global_vehicle.registration_expiry else None,
            "odometer": global_vehicle.odometer_last_recorded,
            "source": "cache",
        }

    # --- Step 3: Call CarJam API (Req 3.3) ---
    logger.info("Kiosk vehicle lookup: calling CarJam API for rego=%s", rego)
    try:
        client = await _load_carjam_client(db, redis)
        carjam_data = await client.lookup_vehicle(rego)
    except CarjamNotFoundError:
        logger.info("Kiosk vehicle lookup: CarJam returned not found for rego=%s", rego)
        raise HTTPException(
            status_code=404,
            detail=f"No vehicle found for registration '{rego}'",
        )
    except CarjamRateLimitError as e:
        logger.warning("Kiosk vehicle lookup: CarJam rate limit exceeded")
        raise HTTPException(
            status_code=429,
            detail="Vehicle lookup rate limit exceeded",
            headers={"Retry-After": str(e.retry_after)},
        )
    except CarjamError as e:
        logger.error("Kiosk vehicle lookup: CarJam service error: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Vehicle lookup service error: {e}",
        )

    # --- Step 4: Store in global_vehicles for future cache hits (Req 3.4) ---
    logger.info("Kiosk vehicle lookup: storing CarJam result in global_vehicles")
    new_vehicle = _carjam_data_to_global_vehicle(carjam_data)
    db.add(new_vehicle)
    await db.flush()
    await db.refresh(new_vehicle)

    logger.info("Kiosk vehicle lookup: cached new global vehicle (id=%s)", new_vehicle.id)
    return {
        "id": str(new_vehicle.id),
        "rego": new_vehicle.rego,
        "make": new_vehicle.make,
        "model": new_vehicle.model,
        "body_type": new_vehicle.body_type,
        "year": new_vehicle.year,
        "colour": new_vehicle.colour,
        "wof_expiry": new_vehicle.wof_expiry.isoformat() if new_vehicle.wof_expiry else None,
        "cof_expiry": new_vehicle.cof_expiry.isoformat() if new_vehicle.cof_expiry else None,
        "inspection_type": new_vehicle.inspection_type,
        "rego_expiry": new_vehicle.registration_expiry.isoformat() if new_vehicle.registration_expiry else None,
        "odometer": new_vehicle.odometer_last_recorded,
        "source": "carjam",
    }


async def kiosk_check_in(
    db: AsyncSession,
    redis: Redis,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: KioskCheckInRequest,
    ip_address: str | None = None,
) -> KioskCheckInResponse:
    """Orchestrate a kiosk walk-in check-in.

    1. Search for an existing customer by phone within the org.
    2. If not found, create a new individual customer.
    3. If a vehicle rego is provided, look it up via Carjam (fallback to
       manual creation) and link it to the customer idempotently.
    4. Return a response with the customer's first name, new-customer flag,
       and vehicle-linked flag.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
    """
    from app.integrations.carjam import CarjamError, CarjamNotFoundError
    from app.modules.customers.service import create_customer
    from app.modules.vehicles.service import create_manual_vehicle, lookup_vehicle

    # --- Step 1: Customer lookup / creation ---
    existing = await _search_customer_by_phone(db, org_id=org_id, phone=data.phone)

    if existing:
        customer_id = existing.id
        customer_first_name = existing.first_name
        is_new = False
        logger.info("Kiosk check-in: matched existing customer %s by phone", customer_id)
    else:
        customer_dict = await create_customer(
            db,
            org_id=org_id,
            user_id=user_id,
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
            email=data.email,
            customer_type="individual",
            ip_address=ip_address,
        )
        customer_id = uuid.UUID(customer_dict["id"])
        customer_first_name = customer_dict["first_name"]
        is_new = True
        logger.info("Kiosk check-in: created new customer %s", customer_id)

    # --- Step 2: Vehicle lookup / creation + linking ---
    vehicle_linked = False

    if data.vehicle_rego:
        try:
            vehicle_dict = await lookup_vehicle(
                db,
                redis,
                rego=data.vehicle_rego,
                org_id=org_id,
                user_id=user_id,
                ip_address=ip_address,
            )
        except (CarjamNotFoundError, CarjamError):
            logger.info(
                "Carjam lookup failed for rego=%s — creating manual vehicle",
                data.vehicle_rego,
            )
            vehicle_dict = await create_manual_vehicle(
                db,
                org_id=org_id,
                user_id=user_id,
                rego=data.vehicle_rego,
                ip_address=ip_address,
            )

        vehicle_id = uuid.UUID(vehicle_dict["id"])

        await _ensure_vehicle_linked(
            db,
            vehicle_id=vehicle_id,
            customer_id=customer_id,
            org_id=org_id,
            user_id=user_id,
            ip_address=ip_address,
        )
        vehicle_linked = True
        logger.info("Kiosk check-in: vehicle %s linked to customer %s", vehicle_id, customer_id)

    await db.commit()

    return KioskCheckInResponse(
        customer_first_name=customer_first_name,
        is_new_customer=is_new,
        vehicle_linked=vehicle_linked,
    )


async def kiosk_check_in_v2(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: KioskCheckInRequestV2,
    ip_address: str | None = None,
) -> KioskCheckInResponseV2:
    """Orchestrate an enhanced kiosk check-in with multi-vehicle support.

    1. If existing_customer_id provided, look up and update that customer.
    2. Otherwise, search by phone within the org or create a new customer.
    3. For each vehicle in the vehicles list, link it to the customer (idempotent).
    4. For vehicles with non-null odometer_km, record an odometer reading (source="kiosk").
    5. Return response with customer_first_name, is_new_customer, vehicles_linked count.

    Backward compatible: if vehicles list is empty, behaves like the current
    check-in endpoint (no vehicle linking).

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.5, 9.6
    """
    from app.modules.customers.service import create_customer

    is_new = False
    customer_id: uuid.UUID
    customer_first_name: str

    # --- Step 1: Customer resolution ---
    if data.existing_customer_id:
        # Look up the existing customer within this org
        existing_customer_uuid = uuid.UUID(data.existing_customer_id)
        result = await db.execute(
            select(Customer).where(
                Customer.id == existing_customer_uuid,
                Customer.org_id == org_id,
                Customer.is_anonymised.is_(False),
            )
        )
        customer = result.scalar_one_or_none()
        if customer is None:
            raise HTTPException(
                status_code=404,
                detail="Customer not found in this organisation",
            )

        # Update customer details if changed
        updated = False
        if customer.first_name != data.first_name:
            customer.first_name = data.first_name
            updated = True
        if customer.last_name != data.last_name:
            customer.last_name = data.last_name
            updated = True
        if customer.phone != data.phone:
            customer.phone = data.phone
            updated = True
        if data.email is not None and customer.email != data.email:
            customer.email = data.email
            updated = True

        if updated:
            await db.flush()
            await db.refresh(customer)
            logger.info("Kiosk check-in v2: updated existing customer %s", customer.id)

        customer_id = customer.id
        customer_first_name = customer.first_name
        is_new = False
        logger.info("Kiosk check-in v2: using existing customer %s", customer_id)
    else:
        # Look up by phone or create new
        existing = await _search_customer_by_phone(db, org_id=org_id, phone=data.phone)

        if existing:
            customer_id = existing.id
            customer_first_name = existing.first_name
            is_new = False
            logger.info("Kiosk check-in v2: matched customer %s by phone", customer_id)
        else:
            customer_dict = await create_customer(
                db,
                org_id=org_id,
                user_id=user_id,
                first_name=data.first_name,
                last_name=data.last_name,
                phone=data.phone,
                email=data.email,
                customer_type="individual",
                ip_address=ip_address,
            )
            customer_id = uuid.UUID(customer_dict["id"])
            customer_first_name = customer_dict["first_name"]
            is_new = True
            logger.info("Kiosk check-in v2: created new customer %s", customer_id)

    # --- Step 2: Vehicle linking ---
    vehicles_linked = 0

    for vehicle_entry in data.vehicles:
        vehicle_uuid = uuid.UUID(vehicle_entry.global_vehicle_id)

        # Link vehicle to customer (idempotent)
        await _ensure_vehicle_linked(
            db,
            vehicle_id=vehicle_uuid,
            customer_id=customer_id,
            org_id=org_id,
            user_id=user_id,
            ip_address=ip_address,
        )
        vehicles_linked += 1

        # Record odometer reading if provided
        if vehicle_entry.odometer_km is not None:
            from app.modules.vehicles.service import promote_vehicle

            odometer_reading = OdometerReading(
                global_vehicle_id=vehicle_uuid,
                reading_km=vehicle_entry.odometer_km,
                source="kiosk",
                recorded_by=user_id,
                org_id=org_id,
            )
            db.add(odometer_reading)

            # Promote the vehicle for the calling org (idempotent if the
            # link step already promoted) and bump the per-org odometer
            # cache. The shared `global_vehicles.odometer_last_recorded`
            # is intentionally NOT bumped — that field is owned by the
            # CarJam cache and per-org operational state must stay
            # private (Req 1.3, 3.4, 11.1, 11.2).
            ov = await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=vehicle_uuid,
                user_id=user_id,
                trigger_site="kiosk.v2_check_in",
                ip_address=ip_address,
            )
            current = ov.odometer_last_recorded or 0
            if vehicle_entry.odometer_km >= current:
                ov.odometer_last_recorded = vehicle_entry.odometer_km

            logger.info(
                "Kiosk check-in v2: recorded odometer %d km for vehicle %s",
                vehicle_entry.odometer_km,
                vehicle_uuid,
            )

    if data.vehicles:
        await db.flush()
        logger.info(
            "Kiosk check-in v2: linked %d vehicles to customer %s",
            vehicles_linked,
            customer_id,
        )

    return KioskCheckInResponseV2(
        customer_first_name=customer_first_name,
        is_new_customer=is_new,
        vehicles_linked=vehicles_linked,
    )

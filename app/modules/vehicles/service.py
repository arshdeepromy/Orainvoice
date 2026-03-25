"""Business logic for Vehicle module — cache-first lookup, refresh, manual entry.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.integrations.carjam import CarjamClient, CarjamVehicleData, CarjamError
from app.modules.admin.models import GlobalVehicle, Organisation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Carjam config loader (reads GUI-configured integration_configs)
# ---------------------------------------------------------------------------

async def _load_carjam_client(db: AsyncSession, redis: Redis) -> CarjamClient:
    """Build a CarjamClient using the GUI-configured integration settings.

    Falls back to env-var defaults if no DB config exists.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    config_result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    config_row = config_result.scalar_one_or_none()

    if config_row:
        try:
            config_data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
            api_key = config_data.get("api_key", "")
            base_url = config_data.get("endpoint_url", "https://www.carjam.co.nz")
            rate_limit = config_data.get("global_rate_limit_per_minute", 60)

            logger.info(
                "Loaded Carjam config from DB: base_url=%s, has_api_key=%s, rate_limit=%d",
                base_url, bool(api_key), rate_limit,
            )
            return CarjamClient(
                redis=redis,
                api_key=api_key,
                base_url=base_url,
                rate_limit=rate_limit,
            )
        except Exception as e:
            logger.error("Failed to load Carjam config from DB: %s", e)
            raise CarjamError("Failed to load Carjam configuration") from e

    # No DB config — fall back to env-var defaults
    logger.info("No Carjam DB config found, using env-var defaults")
    return CarjamClient(redis=redis)


def _parse_date(val: str | None) -> date | None:
    """Parse an ISO date string to a date object, returning None on failure."""
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except (ValueError, TypeError):
        return None


def _global_vehicle_to_dict(gv: GlobalVehicle, source: str) -> dict:
    """Convert a GlobalVehicle ORM instance to a serialisable dict."""
    return {
        "id": str(gv.id),
        "rego": gv.rego,
        "make": gv.make,
        "model": gv.model,
        "year": gv.year,
        "colour": gv.colour,
        "body_type": gv.body_type,
        "fuel_type": gv.fuel_type,
        "engine_size": gv.engine_size,
        "seats": gv.num_seats,
        "wof_expiry": gv.wof_expiry.isoformat() if gv.wof_expiry else None,
        "rego_expiry": gv.registration_expiry.isoformat() if gv.registration_expiry else None,
        "odometer": gv.odometer_last_recorded,
        "last_pulled_at": gv.last_pulled_at.isoformat() if gv.last_pulled_at else None,
        "source": source,
        "lookup_type": gv.lookup_type,
        # Extended fields
        "vin": gv.vin,
        "chassis": gv.chassis,
        "engine_no": gv.engine_no,
        "transmission": gv.transmission,
        "country_of_origin": gv.country_of_origin,
        "number_of_owners": gv.number_of_owners,
        "vehicle_type": gv.vehicle_type,
        "reported_stolen": gv.reported_stolen,
        "power_kw": gv.power_kw,
        "tare_weight": gv.tare_weight,
        "gross_vehicle_mass": gv.gross_vehicle_mass,
        "date_first_registered_nz": gv.date_first_registered_nz.isoformat() if gv.date_first_registered_nz else None,
        "plate_type": gv.plate_type,
        "submodel": gv.submodel,
        "second_colour": gv.second_colour,
    }


def _carjam_data_to_global_vehicle(data: CarjamVehicleData) -> GlobalVehicle:
    """Create a new GlobalVehicle ORM instance from CarjamVehicleData."""
    now = datetime.now(timezone.utc)
    return GlobalVehicle(
        rego=data.rego,
        make=data.make,
        model=data.model,
        year=data.year,
        colour=data.colour,
        body_type=data.body_type,
        fuel_type=data.fuel_type,
        engine_size=data.engine_size,
        num_seats=data.seats,
        wof_expiry=_parse_date(data.wof_expiry),
        registration_expiry=_parse_date(data.rego_expiry),
        odometer_last_recorded=data.odometer,
        last_pulled_at=now,
        lookup_type=data.lookup_type,
        # Extended fields
        vin=data.vin,
        chassis=data.chassis,
        engine_no=data.engine_no,
        transmission=data.transmission,
        country_of_origin=data.country_of_origin,
        number_of_owners=data.number_of_owners,
        vehicle_type=data.vehicle_type,
        reported_stolen=data.reported_stolen,
        power_kw=data.power_kw,
        tare_weight=data.tare_weight,
        gross_vehicle_mass=data.gross_vehicle_mass,
        date_first_registered_nz=_parse_date(data.date_first_registered_nz),
        plate_type=data.plate_type,
        submodel=data.submodel,
        second_colour=data.second_colour,
    )


# ---------------------------------------------------------------------------
# Odometer Reading Management
# ---------------------------------------------------------------------------


async def record_odometer_reading(
    db: AsyncSession,
    *,
    global_vehicle_id: uuid.UUID,
    reading_km: int,
    source: str = "manual",
    recorded_by: uuid.UUID | None = None,
    invoice_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> dict:
    """Record a new odometer reading and update global vehicle if higher.

    Saves to odometer_readings history table. Only updates
    global_vehicles.odometer_last_recorded if the new reading is >= current.
    """
    from app.modules.vehicles.models import OdometerReading

    # Load the global vehicle
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        raise ValueError(f"Vehicle with id '{global_vehicle_id}' not found")

    # Save to history
    reading = OdometerReading(
        global_vehicle_id=global_vehicle_id,
        reading_km=reading_km,
        source=source,
        recorded_by=recorded_by,
        invoice_id=invoice_id,
        org_id=org_id,
        notes=notes,
    )
    db.add(reading)
    await db.flush()

    # Update global vehicle only if new reading is higher
    current = vehicle.odometer_last_recorded or 0
    if reading_km >= current:
        vehicle.odometer_last_recorded = reading_km
        await db.flush()

    return {
        "id": str(reading.id),
        "global_vehicle_id": str(global_vehicle_id),
        "reading_km": reading_km,
        "source": source,
        "recorded_at": reading.recorded_at.isoformat() if reading.recorded_at else None,
        "vehicle_odometer_updated": reading_km >= current,
    }


async def get_odometer_history(
    db: AsyncSession,
    *,
    global_vehicle_id: uuid.UUID,
    limit: int = 50,
) -> list[dict]:
    """Get odometer reading history for a vehicle, newest first."""
    from app.modules.vehicles.models import OdometerReading

    result = await db.execute(
        select(OdometerReading)
        .where(OdometerReading.global_vehicle_id == global_vehicle_id)
        .order_by(OdometerReading.recorded_at.desc())
        .limit(limit)
    )
    readings = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "reading_km": r.reading_km,
            "source": r.source,
            "recorded_by": str(r.recorded_by) if r.recorded_by else None,
            "invoice_id": str(r.invoice_id) if r.invoice_id else None,
            "notes": r.notes,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        }
        for r in readings
    ]


async def update_odometer_reading(
    db: AsyncSession,
    *,
    reading_id: uuid.UUID,
    new_reading_km: int,
    user_id: uuid.UUID,
    notes: str | None = None,
) -> dict:
    """Correct an existing odometer reading (e.g. accidental wrong entry).

    Also recalculates the vehicle's odometer_last_recorded from the max
    of all readings.
    """
    from app.modules.vehicles.models import OdometerReading

    result = await db.execute(
        select(OdometerReading).where(OdometerReading.id == reading_id)
    )
    reading = result.scalar_one_or_none()
    if reading is None:
        raise ValueError(f"Odometer reading '{reading_id}' not found")

    old_km = reading.reading_km
    reading.reading_km = new_reading_km
    if notes is not None:
        reading.notes = notes
    await db.flush()

    # Recalculate vehicle's odometer_last_recorded from max of all readings
    from sqlalchemy import func as sa_func
    max_result = await db.execute(
        select(sa_func.max(OdometerReading.reading_km))
        .where(OdometerReading.global_vehicle_id == reading.global_vehicle_id)
    )
    max_km = max_result.scalar() or 0

    vehicle_result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == reading.global_vehicle_id)
    )
    vehicle = vehicle_result.scalar_one_or_none()
    if vehicle:
        vehicle.odometer_last_recorded = max_km
        await db.flush()

    return {
        "id": str(reading.id),
        "old_reading_km": old_km,
        "new_reading_km": new_reading_km,
        "vehicle_odometer_now": max_km,
    }


async def lookup_vehicle(
    db: AsyncSession,
    redis: Redis,
    *,
    rego: str,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Look up a vehicle by registration — cache-first strategy.

    1. Check Global_Vehicle_DB for existing record (cache hit).
    2. On miss, call Carjam API, store result, increment org counter.

    Returns a dict suitable for VehicleLookupResponse.

    Requirements: 14.1, 14.2, 14.3, 14.4
    """
    logger.info(f"=== lookup_vehicle called: rego={rego}, org_id={org_id}, user_id={user_id}")
    rego = rego.upper().strip()

    # --- Step 1: Check cache (Global_Vehicle_DB) ---
    logger.info(f"Checking Global_Vehicle_DB for rego={rego}")
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.rego == rego)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Cache hit — return without API call or counter increment (Req 14.2)
        logger.info("Vehicle cache hit for rego=%s", rego)
        return _global_vehicle_to_dict(existing, source="cache")

    # --- Step 2: Cache miss — call Carjam API (Req 14.3) ---
    logger.info("Vehicle cache miss for rego=%s — calling Carjam", rego)

    try:
        client = await _load_carjam_client(db, redis)
        logger.info(f"CarjamClient created, calling lookup_vehicle for {rego}")
        carjam_data = await client.lookup_vehicle(rego)
        logger.info(f"Carjam API returned data: {carjam_data}")
    except Exception as e:
        logger.error(f"Carjam API call failed: {e}", exc_info=True)
        raise

    # Store in Global_Vehicle_DB
    logger.info(f"Storing vehicle in Global_Vehicle_DB")
    new_vehicle = _carjam_data_to_global_vehicle(carjam_data)
    db.add(new_vehicle)
    await db.flush()

    # Increment org's Carjam usage counter (Req 14.3)
    logger.info(f"Incrementing Carjam counter for org {org_id}")
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is not None:
        org.carjam_lookups_this_month += 1
        await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="vehicle.carjam_lookup",
        entity_type="global_vehicle",
        entity_id=new_vehicle.id,
        before_value=None,
        after_value={"rego": rego, "source": "carjam"},
        ip_address=ip_address,
    )

    logger.info(f"Vehicle lookup complete, returning data")
    return _global_vehicle_to_dict(new_vehicle, source="carjam")


async def refresh_vehicle(
    db: AsyncSession,
    redis: Redis,
    *,
    vehicle_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Force a Carjam re-fetch for an existing GlobalVehicle record.

    Updates the Global_Vehicle_DB record in-place and increments the org's
    Carjam usage counter.

    Requirements: 14.5
    """
    from app.modules.vehicles.models import OrgVehicle

    # Load the existing GlobalVehicle
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        raise ValueError(f"Vehicle with id '{vehicle_id}' not found in Global_Vehicle_DB")

    before_value = _global_vehicle_to_dict(existing, source="cache")

    # Force Carjam re-fetch using ABCD-first strategy (using GUI-configured settings)
    import asyncio
    from app.integrations.carjam import CarjamNotFoundError as _NotFound

    client = await _load_carjam_client(db, redis)
    carjam_data = None
    lookup_source = "basic"

    # Step 1: Try ABCD (2 attempts with retry for async data fetch)
    for attempt in range(2):
        try:
            logger.info("Refresh ABCD attempt %d for rego=%s", attempt + 1, existing.rego)
            carjam_data = await client.lookup_vehicle_abcd(existing.rego, use_mvr=True)
            lookup_source = "abcd"
            break
        except CarjamError as exc:
            if str(exc) == "ABCD_FETCHING" and attempt < 1:
                logger.info("ABCD data being fetched for %s, retrying in 1s", existing.rego)
                await asyncio.sleep(1)
                continue
            logger.info("ABCD failed for %s: %s, falling back to Basic", existing.rego, exc)
            break
        except Exception as exc:
            logger.error("ABCD error for %s: %s, falling back to Basic", existing.rego, exc)
            break

    # Step 2: Fallback to Basic if ABCD didn't return data
    if carjam_data is None:
        logger.info("Falling back to Basic API for refresh of %s", existing.rego)
        carjam_data = await client.lookup_vehicle(existing.rego)
        lookup_source = "basic"

    # Update the existing record
    now = datetime.now(timezone.utc)
    existing.make = carjam_data.make
    existing.model = carjam_data.model
    existing.year = carjam_data.year
    existing.colour = carjam_data.colour
    existing.body_type = carjam_data.body_type
    existing.fuel_type = carjam_data.fuel_type
    existing.engine_size = carjam_data.engine_size
    existing.num_seats = carjam_data.seats
    existing.wof_expiry = _parse_date(carjam_data.wof_expiry)
    existing.registration_expiry = _parse_date(carjam_data.rego_expiry)
    existing.odometer_last_recorded = max(
        carjam_data.odometer or 0,
        existing.odometer_last_recorded or 0,
    ) or None
    existing.last_pulled_at = now
    existing.lookup_type = lookup_source

    # Record CarJam odometer reading in history if available
    if carjam_data.odometer and carjam_data.odometer > 0:
        await record_odometer_reading(
            db,
            global_vehicle_id=existing.id,
            reading_km=carjam_data.odometer,
            source="carjam",
            recorded_by=user_id,
            org_id=org_id,
            notes="CarJam resync",
        )
    # Extended fields
    existing.vin = carjam_data.vin
    existing.chassis = carjam_data.chassis
    existing.engine_no = carjam_data.engine_no
    existing.transmission = carjam_data.transmission
    existing.country_of_origin = carjam_data.country_of_origin
    existing.number_of_owners = carjam_data.number_of_owners
    existing.vehicle_type = carjam_data.vehicle_type
    existing.reported_stolen = carjam_data.reported_stolen
    existing.power_kw = carjam_data.power_kw
    existing.tare_weight = carjam_data.tare_weight
    existing.gross_vehicle_mass = carjam_data.gross_vehicle_mass
    existing.date_first_registered_nz = _parse_date(carjam_data.date_first_registered_nz)
    existing.plate_type = carjam_data.plate_type
    existing.submodel = carjam_data.submodel
    existing.second_colour = carjam_data.second_colour
    await db.flush()

    # Increment org's Carjam usage counter (charge the org)
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is not None:
        org.carjam_lookups_this_month += 1
        await db.flush()

    # Audit log
    after_value = _global_vehicle_to_dict(existing, source=lookup_source)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="vehicle.refresh",
        entity_type="global_vehicle",
        entity_id=existing.id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
    )

    return after_value


def _org_vehicle_to_dict(ov) -> dict:
    """Convert an OrgVehicle ORM instance to a serialisable dict."""
    return {
        "id": str(ov.id),
        "org_id": str(ov.org_id),
        "rego": ov.rego,
        "make": ov.make,
        "model": ov.model,
        "year": ov.year,
        "colour": ov.colour,
        "body_type": ov.body_type,
        "fuel_type": ov.fuel_type,
        "engine_size": ov.engine_size,
        "num_seats": ov.num_seats,
        "is_manual_entry": ov.is_manual_entry,
        "created_at": ov.created_at.isoformat() if ov.created_at else None,
    }


async def create_manual_vehicle(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    rego: str,
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    colour: str | None = None,
    body_type: str | None = None,
    fuel_type: str | None = None,
    engine_size: str | None = None,
    num_seats: int | None = None,
    vin: str | None = None,
    chassis: str | None = None,
    engine_no: str | None = None,
    transmission: str | None = None,
    country_of_origin: str | None = None,
    number_of_owners: int | None = None,
    vehicle_type: str | None = None,
    submodel: str | None = None,
    second_colour: str | None = None,
    wof_expiry: str | None = None,
    rego_expiry: str | None = None,
    odometer: int | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a manually entered vehicle in global_vehicles.

    Stores into the same table as CarJam vehicles with lookup_type='manual'
    so data is seamless regardless of source. If a global_vehicles record
    already exists for this rego, updates it instead.

    Requirements: 14.6, 14.7
    """
    rego = rego.upper().strip()
    now = datetime.now(timezone.utc)

    # Check if a global vehicle already exists for this rego
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.rego == rego)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Update existing record with manual data
        if make is not None:
            existing.make = make
        if model is not None:
            existing.model = model
        if year is not None:
            existing.year = year
        if colour is not None:
            existing.colour = colour
        if body_type is not None:
            existing.body_type = body_type
        if fuel_type is not None:
            existing.fuel_type = fuel_type
        if engine_size is not None:
            existing.engine_size = engine_size
        if num_seats is not None:
            existing.num_seats = num_seats
        if vin is not None:
            existing.vin = vin
        if chassis is not None:
            existing.chassis = chassis
        if engine_no is not None:
            existing.engine_no = engine_no
        if transmission is not None:
            existing.transmission = transmission
        if country_of_origin is not None:
            existing.country_of_origin = country_of_origin
        if number_of_owners is not None:
            existing.number_of_owners = number_of_owners
        if vehicle_type is not None:
            existing.vehicle_type = vehicle_type
        if submodel is not None:
            existing.submodel = submodel
        if second_colour is not None:
            existing.second_colour = second_colour
        if wof_expiry is not None:
            existing.wof_expiry = _parse_date(wof_expiry)
        if rego_expiry is not None:
            existing.registration_expiry = _parse_date(rego_expiry)
        if odometer is not None:
            existing.odometer_last_recorded = odometer
        existing.last_pulled_at = now
        await db.flush()
        vehicle = existing
    else:
        # Create new global vehicle record
        vehicle = GlobalVehicle(
            rego=rego,
            make=make,
            model=model,
            year=year,
            colour=colour,
            body_type=body_type,
            fuel_type=fuel_type,
            engine_size=engine_size,
            num_seats=num_seats,
            wof_expiry=_parse_date(wof_expiry),
            registration_expiry=_parse_date(rego_expiry),
            odometer_last_recorded=odometer,
            last_pulled_at=now,
            lookup_type="manual",
            vin=vin,
            chassis=chassis,
            engine_no=engine_no,
            transmission=transmission,
            country_of_origin=country_of_origin,
            number_of_owners=number_of_owners,
            vehicle_type=vehicle_type,
            submodel=submodel,
            second_colour=second_colour,
        )
        db.add(vehicle)
        await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="vehicle.manual_entry",
        entity_type="global_vehicle",
        entity_id=vehicle.id,
        before_value=None,
        after_value={"rego": rego, "source": "manual"},
        ip_address=ip_address,
    )

    await db.commit()

    return _global_vehicle_to_dict(vehicle, source="manual")


# ---------------------------------------------------------------------------
# Vehicle Linking (Req 15.1, 15.2)
# ---------------------------------------------------------------------------


async def link_vehicle_to_customer(
    db: AsyncSession,
    *,
    vehicle_id: uuid.UUID,
    customer_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    odometer: int | None = None,
    ip_address: str | None = None,
) -> dict:
    """Link a global vehicle to a customer within the org.

    The same global vehicle can be linked to different customers across
    different organisations (Req 15.1) and to multiple customers within
    a single organisation (Req 15.2).

    Requirements: 15.1, 15.2
    """
    from app.modules.customers.models import Customer
    from app.modules.vehicles.models import CustomerVehicle

    # Verify the global vehicle exists
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        raise ValueError(f"Vehicle with id '{vehicle_id}' not found")

    # Verify the customer exists and belongs to this org
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError(f"Customer with id '{customer_id}' not found in this organisation")

    # Create the link
    link = CustomerVehicle(
        org_id=org_id,
        customer_id=customer_id,
        global_vehicle_id=vehicle_id,
        org_vehicle_id=None,
        odometer_at_link=odometer,
    )
    db.add(link)
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="vehicle.link_customer",
        entity_type="customer_vehicle",
        entity_id=link.id,
        before_value=None,
        after_value={
            "vehicle_id": str(vehicle_id),
            "customer_id": str(customer_id),
            "rego": vehicle.rego,
        },
        ip_address=ip_address,
    )

    return {
        "id": str(link.id),
        "vehicle_id": str(vehicle_id),
        "customer_id": str(customer_id),
        "customer_name": f"{customer.first_name} {customer.last_name}",
        "odometer_at_link": odometer,
        "linked_at": link.linked_at.isoformat() if link.linked_at else datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Vehicle Profile (Req 15.3, 15.4)
# ---------------------------------------------------------------------------


def _compute_expiry_indicator(expiry_date: date | None) -> dict:
    """Compute WOF/rego expiry indicator colour.

    Green: >60 days remaining
    Amber: 30-60 days remaining
    Red: <30 days remaining or expired

    Requirements: 15.4
    """
    if expiry_date is None:
        return {
            "date": None,
            "days_remaining": None,
            "indicator": "red",
        }

    today = date.today()
    days_remaining = (expiry_date - today).days

    if days_remaining > 60:
        indicator = "green"
    elif days_remaining >= 30:
        indicator = "amber"
    else:
        indicator = "red"

    return {
        "date": expiry_date.isoformat(),
        "days_remaining": days_remaining,
        "indicator": indicator,
    }


async def get_vehicle_profile(
    db: AsyncSession,
    *,
    vehicle_id: uuid.UUID,
    org_id: uuid.UUID,
) -> dict:
    """Build the full vehicle profile for a global vehicle.

    Includes Carjam data, linked customers, service history (invoices
    matching the vehicle rego within the org), and WOF/rego expiry
    indicators.

    Requirements: 15.3, 15.4
    """
    from app.modules.customers.models import Customer
    from app.modules.invoices.models import Invoice
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

    is_org_vehicle = False

    # Try global vehicle first
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()

    # Fall back to org vehicle if not found in global
    if vehicle is None:
        ov_result = await db.execute(
            select(OrgVehicle).where(
                OrgVehicle.id == vehicle_id,
                OrgVehicle.org_id == org_id,
            )
        )
        vehicle = ov_result.scalar_one_or_none()
        if vehicle is None:
            raise ValueError(f"Vehicle with id '{vehicle_id}' not found")
        is_org_vehicle = True

    # Linked customers within this org
    if is_org_vehicle:
        links_result = await db.execute(
            select(CustomerVehicle, Customer)
            .join(Customer, CustomerVehicle.customer_id == Customer.id)
            .where(
                CustomerVehicle.org_vehicle_id == vehicle_id,
                CustomerVehicle.org_id == org_id,
            )
        )
    else:
        links_result = await db.execute(
            select(CustomerVehicle, Customer)
            .join(Customer, CustomerVehicle.customer_id == Customer.id)
            .where(
                CustomerVehicle.global_vehicle_id == vehicle_id,
                CustomerVehicle.org_id == org_id,
            )
        )
    linked_customers = []
    for link, cust in links_result.all():
        linked_customers.append({
            "id": str(cust.id),
            "first_name": cust.first_name,
            "last_name": cust.last_name,
            "email": cust.email,
            "phone": cust.phone,
        })

    # Service history — invoices matching this rego within the org
    invoices_result = await db.execute(
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.org_id == org_id,
            Invoice.vehicle_rego == vehicle.rego,
        )
        .order_by(Invoice.created_at.desc())
    )
    service_history = []
    for inv, cust in invoices_result.all():
        service_history.append({
            "invoice_id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "status": inv.status,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "total": str(inv.total),
            "odometer": inv.vehicle_odometer,
            "customer_name": f"{cust.first_name} {cust.last_name}",
            "description": None,
        })

    # WOF and rego expiry indicators (Req 15.4)
    wof_indicator = _compute_expiry_indicator(vehicle.wof_expiry)
    rego_indicator = _compute_expiry_indicator(vehicle.registration_expiry)

    # Build response — handle attribute differences between GlobalVehicle and OrgVehicle
    lookup_type = getattr(vehicle, "lookup_type", "import" if is_org_vehicle else None)
    last_pulled = getattr(vehicle, "last_pulled_at", None)

    return {
        "id": str(vehicle.id),
        "rego": vehicle.rego,
        "make": vehicle.make,
        "model": vehicle.model,
        "year": vehicle.year,
        "colour": vehicle.colour,
        "body_type": vehicle.body_type,
        "fuel_type": vehicle.fuel_type,
        "engine_size": vehicle.engine_size,
        "seats": vehicle.num_seats,
        "odometer": vehicle.odometer_last_recorded,
        "service_due_date": vehicle.service_due_date.isoformat() if vehicle.service_due_date else None,
        "last_pulled_at": last_pulled.isoformat() if last_pulled else None,
        "wof_expiry": wof_indicator,
        "rego_expiry": rego_indicator,
        # Extended fields
        "vin": vehicle.vin,
        "chassis": vehicle.chassis,
        "engine_no": vehicle.engine_no,
        "transmission": vehicle.transmission,
        "country_of_origin": vehicle.country_of_origin,
        "number_of_owners": vehicle.number_of_owners,
        "vehicle_type": vehicle.vehicle_type,
        "submodel": vehicle.submodel,
        "second_colour": vehicle.second_colour,
        "lookup_type": lookup_type,
        "linked_customers": linked_customers,
        "service_history": service_history,
    }


# ---------------------------------------------------------------------------
# Live Search & ABCD Fallback
# ---------------------------------------------------------------------------


async def search_vehicles(
    db: AsyncSession,
    *,
    query: str,
    limit: int = 10,
    org_id: uuid.UUID | None = None,
) -> list[dict]:
    """Search global_vehicles AND org_vehicles by rego prefix match.

    Returns up to `limit` results. No API calls, no usage tracking.
    Fast database-only search for live autocomplete.

    If org_id is provided, also returns linked customers for each vehicle
    and includes org_vehicles belonging to that org.
    """
    from app.modules.customers.models import Customer
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

    query_upper = query.upper().strip()
    logger.info(f"search_vehicles called: query={query_upper}, limit={limit}, org_id={org_id}")

    if not query_upper:
        return []

    # --- 1. Search global_vehicles ---
    stmt = (
        select(GlobalVehicle)
        .where(GlobalVehicle.rego.like(f"{query_upper}%"))
        .order_by(GlobalVehicle.rego)
        .limit(limit)
    )

    result = await db.execute(stmt)
    vehicles = result.scalars().all()

    results = []
    seen_regos: set[str] = set()

    for v in vehicles:
        seen_regos.add(v.rego.upper())
        vehicle_data = {
            "id": str(v.id),
            "rego": v.rego,
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "colour": v.colour,
            "lookup_type": v.lookup_type,
            "odometer": v.odometer_last_recorded,
            "service_due_date": v.service_due_date.isoformat() if v.service_due_date else None,
            "wof_expiry": v.wof_expiry.isoformat() if v.wof_expiry else None,
            "linked_customers": [],
        }

        # Fetch linked customers for this global vehicle within the org
        if org_id:
            links_result = await db.execute(
                select(CustomerVehicle, Customer)
                .join(Customer, CustomerVehicle.customer_id == Customer.id)
                .where(
                    CustomerVehicle.global_vehicle_id == v.id,
                    CustomerVehicle.org_id == org_id,
                )
            )
            for link, cust in links_result.all():
                vehicle_data["linked_customers"].append({
                    "id": str(cust.id),
                    "first_name": cust.first_name,
                    "last_name": cust.last_name,
                    "email": cust.email,
                    "phone": cust.phone,
                    "mobile_phone": cust.mobile_phone,
                    "display_name": cust.display_name,
                    "company_name": cust.company_name,
                })

        results.append(vehicle_data)

    # --- 2. Search org_vehicles (imported/manual) ---
    if org_id and len(results) < limit:
        remaining = limit - len(results)
        org_stmt = (
            select(OrgVehicle)
            .where(
                OrgVehicle.org_id == org_id,
                OrgVehicle.rego.like(f"{query_upper}%"),
            )
            .order_by(OrgVehicle.rego)
            .limit(remaining)
        )
        org_result = await db.execute(org_stmt)
        org_vehicles = org_result.scalars().all()

        for ov in org_vehicles:
            # Skip duplicates already found in global_vehicles
            if ov.rego.upper() in seen_regos:
                continue
            seen_regos.add(ov.rego.upper())

            vehicle_data = {
                "id": str(ov.id),
                "rego": ov.rego,
                "make": ov.make,
                "model": ov.model,
                "year": ov.year,
                "colour": ov.colour,
                "lookup_type": "imported",
                "odometer": ov.odometer_last_recorded,
                "service_due_date": ov.service_due_date.isoformat() if ov.service_due_date else None,
                "wof_expiry": ov.wof_expiry.isoformat() if ov.wof_expiry else None,
                "linked_customers": [],
            }

            # Fetch linked customers for this org vehicle
            links_result = await db.execute(
                select(CustomerVehicle, Customer)
                .join(Customer, CustomerVehicle.customer_id == Customer.id)
                .where(
                    CustomerVehicle.org_vehicle_id == ov.id,
                    CustomerVehicle.org_id == org_id,
                )
            )
            for link, cust in links_result.all():
                vehicle_data["linked_customers"].append({
                    "id": str(cust.id),
                    "first_name": cust.first_name,
                    "last_name": cust.last_name,
                    "email": cust.email,
                    "phone": cust.phone,
                    "mobile_phone": cust.mobile_phone,
                    "display_name": cust.display_name,
                    "company_name": cust.company_name,
                })

            results.append(vehicle_data)

    logger.info(f"search_vehicles found {len(results)} results (global + org)")
    return results




async def list_org_vehicles(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """List all vehicles associated with an org.

    Includes both:
    - Global vehicles linked via customer_vehicles
    - Org vehicles (manual entries / bulk imports)

    Returns paginated results with linked customer info, sorted by most
    recently created/linked first.
    """
    from sqlalchemy import func as sa_func, literal, union_all, text as sa_text
    from app.modules.customers.models import Customer
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

    # --- Build unified vehicle list ---
    # Source 1: Global vehicles linked to this org
    global_q = (
        select(
            GlobalVehicle.id,
            GlobalVehicle.rego,
            GlobalVehicle.make,
            GlobalVehicle.model,
            GlobalVehicle.year,
            GlobalVehicle.colour,
            GlobalVehicle.body_type,
            GlobalVehicle.fuel_type,
            GlobalVehicle.wof_expiry,
            GlobalVehicle.registration_expiry,
            GlobalVehicle.service_due_date,
            GlobalVehicle.created_at,
            literal("global").label("source"),
        )
        .join(CustomerVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
        .where(CustomerVehicle.org_id == org_id)
        .distinct()
    )

    # Source 2: Org vehicles (manual entries / imports)
    org_q = (
        select(
            OrgVehicle.id,
            OrgVehicle.rego,
            OrgVehicle.make,
            OrgVehicle.model,
            OrgVehicle.year,
            OrgVehicle.colour,
            OrgVehicle.body_type,
            OrgVehicle.fuel_type,
            OrgVehicle.wof_expiry,
            OrgVehicle.registration_expiry,
            OrgVehicle.service_due_date,
            OrgVehicle.created_at,
            literal("org").label("source"),
        )
        .where(OrgVehicle.org_id == org_id)
    )

    if search:
        search_upper = search.upper().strip()
        search_like = f"%{search_upper}%"
        global_q = global_q.where(
            GlobalVehicle.rego.ilike(search_like)
            | GlobalVehicle.make.ilike(f"%{search}%")
            | GlobalVehicle.model.ilike(f"%{search}%")
        )
        org_q = org_q.where(
            OrgVehicle.rego.ilike(search_like)
            | OrgVehicle.make.ilike(f"%{search}%")
            | OrgVehicle.model.ilike(f"%{search}%")
        )

    combined = union_all(global_q, org_q).subquery()

    # Count
    count_stmt = select(sa_func.count()).select_from(combined)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    rows_stmt = (
        select(combined)
        .order_by(combined.c.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(rows_stmt)).all()

    items = []
    for row in rows:
        vid = row.id
        source = row.source

        # Fetch linked customers (only for global vehicles)
        customers = []
        if source == "global":
            links_result = await db.execute(
                select(Customer)
                .join(CustomerVehicle, CustomerVehicle.customer_id == Customer.id)
                .where(
                    CustomerVehicle.global_vehicle_id == vid,
                    CustomerVehicle.org_id == org_id,
                )
            )
            customers = [
                {
                    "id": str(c.id),
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "email": c.email,
                    "phone": c.phone,
                }
                for c in links_result.scalars().all()
            ]
        else:
            # Check if org vehicle is linked to any customer
            links_result = await db.execute(
                select(Customer)
                .join(CustomerVehicle, CustomerVehicle.customer_id == Customer.id)
                .where(
                    CustomerVehicle.org_vehicle_id == vid,
                    CustomerVehicle.org_id == org_id,
                )
            )
            customers = [
                {
                    "id": str(c.id),
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "email": c.email,
                    "phone": c.phone,
                }
                for c in links_result.scalars().all()
            ]

        wof = _compute_expiry_indicator(row.wof_expiry)
        rego_exp = _compute_expiry_indicator(row.registration_expiry)

        items.append({
            "id": str(vid),
            "rego": row.rego,
            "make": row.make,
            "model": row.model,
            "year": row.year,
            "colour": row.colour,
            "body_type": row.body_type,
            "fuel_type": row.fuel_type,
            "wof_indicator": wof["indicator"],
            "wof_expiry_date": wof["date"],
            "rego_indicator": rego_exp["indicator"],
            "rego_expiry_date": rego_exp["date"],
            "service_due_date": row.service_due_date.isoformat() if row.service_due_date else None,
            "linked_customers": customers,
            "source": source,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def lookup_vehicle_with_abcd_fallback(
    db: AsyncSession,
    redis: Redis,
    *,
    rego: str,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Look up vehicle with ABCD-first strategy, fallback to Basic.
    
    Strategy:
    1. Check cache (global_vehicles) - if hit, return immediately
    2. Try ABCD API (2 attempts with 1s delay for async data fetch)
    3. If ABCD fails, fallback to Basic API
    4. Store result and increment appropriate usage counter
    
    Returns dict with:
    - success: bool
    - vehicle: dict (vehicle data)
    - source: 'cache' | 'abcd' | 'basic'
    - attempts: int (number of API attempts)
    - cost_estimate_nzd: float
    - message: str
    """
    import asyncio
    from app.integrations.carjam import CarjamNotFoundError, CarjamRateLimitError
    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import IntegrationConfig
    
    rego = rego.upper().strip()
    logger.info(f"lookup_vehicle_with_abcd_fallback: rego={rego}, org_id={org_id}")
    
    # Step 1: Check cache
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.rego == rego)
    )
    existing = result.scalar_one_or_none()
    
    if existing is not None:
        logger.info(f"Cache hit for {rego}")
        return {
            "success": True,
            "vehicle": _global_vehicle_to_dict(existing, source="cache"),
            "source": "cache",
            "attempts": 0,
            "cost_estimate_nzd": 0.0,
            "message": f"Vehicle found in database",
        }
    
    # Load Carjam config
    client = await _load_carjam_client(db, redis)
    
    # Step 2: Try ABCD (2 attempts)
    abcd_attempts = 0
    for attempt in range(2):
        abcd_attempts += 1
        try:
            logger.info(f"ABCD attempt {abcd_attempts} for {rego}")
            carjam_data = await client.lookup_vehicle_abcd(rego, use_mvr=True)
            
            # Success! Store and return
            new_vehicle = _carjam_data_to_global_vehicle(carjam_data)
            db.add(new_vehicle)
            await db.flush()
            
            # Increment org counter
            org_result = await db.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org = org_result.scalar_one_or_none()
            if org is not None:
                org.carjam_lookups_this_month += 1
                await db.flush()
            
            # Audit log
            await write_audit_log(
                session=db,
                org_id=org_id,
                user_id=user_id,
                action="vehicle.carjam_abcd_lookup",
                entity_type="global_vehicle",
                entity_id=new_vehicle.id,
                before_value=None,
                after_value={"rego": rego, "source": "abcd", "attempts": abcd_attempts},
                ip_address=ip_address,
            )
            
            await db.commit()
            
            message = f"Vehicle found via ABCD API"
            if abcd_attempts > 1:
                message += f" ({abcd_attempts} attempts)"
            
            return {
                "success": True,
                "vehicle": _global_vehicle_to_dict(new_vehicle, source="abcd"),
                "source": "abcd",
                "attempts": abcd_attempts,
                "cost_estimate_nzd": 0.05,  # ABCD cost estimate
                "message": message,
            }
            
        except CarjamError as exc:
            if str(exc) == "ABCD_FETCHING" and attempt < 1:
                # Data being fetched, retry after delay
                logger.info(f"ABCD data being fetched for {rego}, retrying in 1s")
                await asyncio.sleep(1)
                continue
            else:
                # ABCD failed, break to fallback
                logger.info(f"ABCD failed for {rego}: {exc}")
                break
        except Exception as exc:
            logger.error(f"ABCD error for {rego}: {exc}")
            break
    
    # Step 3: Fallback to Basic
    logger.info(f"Falling back to Basic API for {rego}")
    try:
        carjam_data = await client.lookup_vehicle(rego)
        
        # Store result
        new_vehicle = _carjam_data_to_global_vehicle(carjam_data)
        db.add(new_vehicle)
        await db.flush()
        
        # Increment org counter
        org_result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is not None:
            org.carjam_lookups_this_month += 1
            await db.flush()
        
        # Audit log
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="vehicle.carjam_basic_lookup",
            entity_type="global_vehicle",
            entity_id=new_vehicle.id,
            before_value=None,
            after_value={"rego": rego, "source": "basic", "abcd_attempts": abcd_attempts},
            ip_address=ip_address,
        )
        
        await db.commit()
        
        return {
            "success": True,
            "vehicle": _global_vehicle_to_dict(new_vehicle, source="basic"),
            "source": "basic",
            "attempts": 1,
            "cost_estimate_nzd": 0.15,  # Basic cost estimate
            "message": "Vehicle found via Basic lookup (ABCD unavailable)",
        }
        
    except CarjamNotFoundError:
        # Both ABCD and Basic failed - vehicle not found
        raise
    except CarjamRateLimitError:
        # Rate limit - don't catch, let it propagate
        raise
    except CarjamError as exc:
        # Other Carjam error
        raise

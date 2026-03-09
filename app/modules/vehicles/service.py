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

    # Load Carjam config from database
    from app.modules.admin.service import get_integration_config
    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import IntegrationConfig
    
    config_result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    config_row = config_result.scalar_one_or_none()
    
    if not config_row:
        raise CarjamError("Carjam integration not configured")
    
    try:
        config_data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
        api_key = config_data.get("api_key", "")
        base_url = config_data.get("endpoint_url", "https://www.carjam.co.nz")
        rate_limit = config_data.get("global_rate_limit_per_minute", 60)
        
        logger.info(f"Loaded Carjam config: base_url={base_url}, has_api_key={bool(api_key)}, rate_limit={rate_limit}")
    except Exception as e:
        logger.error(f"Failed to load Carjam config: {e}")
        raise CarjamError("Failed to load Carjam configuration")

    try:
        client = CarjamClient(
            redis=redis,
            api_key=api_key,
            base_url=base_url,
            rate_limit=rate_limit,
        )
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

    # Force Carjam re-fetch
    client = CarjamClient(redis=redis)
    carjam_data = await client.lookup_vehicle(existing.rego)

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
    existing.odometer_last_recorded = carjam_data.odometer
    existing.last_pulled_at = now
    existing.lookup_type = carjam_data.lookup_type
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
    after_value = _global_vehicle_to_dict(existing, source="carjam")
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
    ip_address: str | None = None,
) -> dict:
    """Create a manually entered vehicle in org_vehicles.

    The record is scoped to the organisation and marked as "manually entered".
    It is NOT stored in the Global_Vehicle_DB.

    Requirements: 14.6, 14.7
    """
    from app.modules.vehicles.models import OrgVehicle

    rego = rego.upper().strip()

    new_vehicle = OrgVehicle(
        org_id=org_id,
        rego=rego,
        make=make,
        model=model,
        year=year,
        colour=colour,
        body_type=body_type,
        fuel_type=fuel_type,
        engine_size=engine_size,
        num_seats=num_seats,
        is_manual_entry=True,
    )
    db.add(new_vehicle)
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="vehicle.manual_entry",
        entity_type="org_vehicle",
        entity_id=new_vehicle.id,
        before_value=None,
        after_value={"rego": rego, "source": "manual"},
        ip_address=ip_address,
    )

    return _org_vehicle_to_dict(new_vehicle)


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
    from app.modules.vehicles.models import CustomerVehicle

    # Load the global vehicle
    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        raise ValueError(f"Vehicle with id '{vehicle_id}' not found")

    # Linked customers within this org
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
        "last_pulled_at": vehicle.last_pulled_at.isoformat() if vehicle.last_pulled_at else None,
        "wof_expiry": wof_indicator,
        "rego_expiry": rego_indicator,
        "linked_customers": linked_customers,
        "service_history": service_history,
    }

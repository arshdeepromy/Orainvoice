"""Kiosk check-in orchestration logic.

Coordinates customer lookup/creation, vehicle lookup/creation (via Carjam
with manual fallback), and vehicle-customer linking in a single atomic
operation.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.kiosk.schemas import KioskCheckInRequest, KioskCheckInResponse
from app.modules.vehicles.models import CustomerVehicle

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
    """
    from app.modules.vehicles.service import link_vehicle_to_customer

    # Check for existing link
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

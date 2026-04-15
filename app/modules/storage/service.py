"""Storage quota calculation and enforcement service.

Calculates storage from compressed invoice JSON, customer records, and
vehicle records per organisation.  Logos and branding assets are excluded.

Requirements: 29.1, 29.2, 29.3, 29.4, 29.5
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.vehicles.models import OrgVehicle, CustomerVehicle


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BYTES_PER_GB = 1_073_741_824  # 1 GB = 2^30 bytes
AMBER_THRESHOLD = 80.0
RED_THRESHOLD = 90.0
BLOCKED_THRESHOLD = 100.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bytes_to_display(num_bytes: int) -> str:
    """Return a human-readable size string (e.g. '1.23 GB')."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1_048_576:
        return f"{num_bytes / 1024:.2f} KB"
    elif num_bytes < BYTES_PER_GB:
        return f"{num_bytes / 1_048_576:.2f} MB"
    else:
        return f"{num_bytes / BYTES_PER_GB:.2f} GB"


def determine_alert_level(percentage: float) -> str:
    """Return the alert level for a given usage percentage.

    Requirements: 29.2, 29.3, 29.4
    """
    if percentage >= BLOCKED_THRESHOLD:
        return "blocked"
    elif percentage >= RED_THRESHOLD:
        return "red"
    elif percentage >= AMBER_THRESHOLD:
        return "amber"
    return "none"


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------


async def calculate_org_storage(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Calculate total storage bytes for an organisation with breakdown.

    Sums the byte-length of:
    - invoice_data_json (compressed invoice JSON) for all invoices
    - customer records (first_name, last_name, email, phone, address, notes)
    - org vehicle records (rego, make, model, colour, etc.)

    Logos and branding assets are explicitly excluded (Req 29.1).

    Returns dict with total bytes and per-category breakdown.
    """
    # Invoice JSON storage
    invoice_size_result = await db.execute(
        select(
            func.coalesce(
                func.sum(func.octet_length(func.cast(Invoice.invoice_data_json, type_=_text_type()))),
                0,
            )
        ).where(Invoice.org_id == org_id)
    )
    invoice_bytes: int = invoice_size_result.scalar() or 0

    # Customer records storage
    customer_size_result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    func.octet_length(func.coalesce(Customer.first_name, ""))
                    + func.octet_length(func.coalesce(Customer.last_name, ""))
                    + func.octet_length(func.coalesce(Customer.email, ""))
                    + func.octet_length(func.coalesce(Customer.phone, ""))
                    + func.octet_length(func.coalesce(Customer.address, ""))
                    + func.octet_length(func.coalesce(Customer.notes, ""))
                ),
                0,
            )
        ).where(Customer.org_id == org_id)
    )
    customer_bytes: int = customer_size_result.scalar() or 0

    # Org vehicle records storage
    vehicle_size_result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    func.octet_length(func.coalesce(OrgVehicle.rego, ""))
                    + func.octet_length(func.coalesce(OrgVehicle.make, ""))
                    + func.octet_length(func.coalesce(OrgVehicle.model, ""))
                    + func.octet_length(func.coalesce(OrgVehicle.colour, ""))
                    + func.octet_length(func.coalesce(OrgVehicle.body_type, ""))
                    + func.octet_length(func.coalesce(OrgVehicle.fuel_type, ""))
                    + func.octet_length(func.coalesce(OrgVehicle.engine_size, ""))
                ),
                0,
            )
        ).where(OrgVehicle.org_id == org_id)
    )
    vehicle_bytes: int = vehicle_size_result.scalar() or 0

    total = invoice_bytes + customer_bytes + vehicle_bytes

    breakdown = []
    if invoice_bytes > 0:
        breakdown.append({"category": "Invoices", "bytes": invoice_bytes})
    if customer_bytes > 0:
        breakdown.append({"category": "Customers", "bytes": customer_bytes})
    if vehicle_bytes > 0:
        breakdown.append({"category": "Vehicles", "bytes": vehicle_bytes})

    return {"total_bytes": total, "breakdown": breakdown}


async def check_storage_quota(
    db: AsyncSession, org_id: uuid.UUID
) -> dict:
    """Return storage quota status for an organisation.

    Returns a dict with:
    - storage_used_bytes: total bytes used
    - storage_quota_bytes: total quota in bytes
    - usage_percentage: float 0.0–100.0+
    - alert_level: 'none' | 'amber' | 'red' | 'blocked'
    - can_create_invoice: bool
    - storage_used_display: human-readable used
    - storage_quota_display: human-readable quota

    Requirements: 29.1, 29.2, 29.3, 29.4, 29.5
    """
    # Get org quota
    org_result = await db.execute(
        select(Organisation.storage_quota_gb, Organisation.storage_used_bytes)
        .where(Organisation.id == org_id)
    )
    row = org_result.one_or_none()
    if row is None:
        raise ValueError("Organisation not found")

    storage_quota_gb, _ = row
    storage_quota_bytes = storage_quota_gb * BYTES_PER_GB

    # Calculate actual usage
    storage_result = await calculate_org_storage(db, org_id)
    storage_used_bytes = storage_result["total_bytes"]

    # Calculate percentage (avoid division by zero)
    if storage_quota_bytes > 0:
        usage_percentage = round((storage_used_bytes / storage_quota_bytes) * 100, 2)
    else:
        usage_percentage = 100.0 if storage_used_bytes > 0 else 0.0

    alert_level = determine_alert_level(usage_percentage)
    can_create_invoice = alert_level != "blocked"

    return {
        "storage_used_bytes": storage_used_bytes,
        "storage_quota_bytes": storage_quota_bytes,
        "usage_percentage": usage_percentage,
        "alert_level": alert_level,
        "can_create_invoice": can_create_invoice,
        "storage_used_display": _bytes_to_display(storage_used_bytes),
        "storage_quota_display": _bytes_to_display(storage_quota_bytes),
    }


def _text_type():
    """Return SQLAlchemy Text type for casting JSONB to text."""
    from sqlalchemy import Text
    return Text()


# ---------------------------------------------------------------------------
# Storage add-on defaults
# ---------------------------------------------------------------------------

DEFAULT_STORAGE_INCREMENTS_GB: list[int] = [1, 5, 20, 50]
DEFAULT_STORAGE_PRICE_PER_GB_NZD: float = 2.00


# ---------------------------------------------------------------------------
# Storage add-on purchasing — Requirements: 30.1, 30.2, 30.3, 30.4
# ---------------------------------------------------------------------------


async def get_storage_addon_config(db: AsyncSession) -> dict:
    """Retrieve Global_Admin-configured storage add-on settings.

    Falls back to defaults if no platform setting exists.

    Returns dict with:
    - increments_gb: list of allowed purchase increments
    - price_per_gb_nzd: price per GB per month in NZD
    """
    from app.modules.admin.models import PlatformSetting

    result = await db.execute(
        select(PlatformSetting.value).where(
            PlatformSetting.key == "storage_addon_config"
        )
    )
    row = result.scalar_one_or_none()

    if row and isinstance(row, dict):
        return {
            "increments_gb": row.get("increments_gb", DEFAULT_STORAGE_INCREMENTS_GB),
            "price_per_gb_nzd": row.get(
                "price_per_gb_nzd", DEFAULT_STORAGE_PRICE_PER_GB_NZD
            ),
        }

    return {
        "increments_gb": DEFAULT_STORAGE_INCREMENTS_GB,
        "price_per_gb_nzd": DEFAULT_STORAGE_PRICE_PER_GB_NZD,
    }


async def purchase_storage_addon(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    quantity_gb: int,
) -> dict:
    """Purchase a storage add-on for an organisation.

    1. Validate the increment is allowed (Global_Admin configurable).
    2. Charge via Stripe immediately using the org's stored payment method.
    3. Increase org's storage_quota_gb instantly.
    4. Return purchase details for audit logging and confirmation email.

    Requirements: 30.1, 30.2, 30.3, 30.4

    Returns dict with:
    - success: bool
    - quantity_gb: int
    - new_total_quota_gb: int
    - charge_amount_nzd: float
    - stripe_charge_id: str
    - price_per_gb_nzd: float
    - additional_monthly_charge_nzd: float

    Raises:
    - ValueError for validation errors (bad increment, missing payment method, etc.)
    - RuntimeError for Stripe charge failures
    """
    import stripe as stripe_lib

    from app.config import settings as app_settings

    stripe_lib.api_key = app_settings.stripe_secret_key

    # 1. Get addon config and validate increment
    addon_config = await get_storage_addon_config(db)
    allowed_increments = addon_config["increments_gb"]
    price_per_gb = addon_config["price_per_gb_nzd"]

    if quantity_gb not in allowed_increments:
        raise ValueError(
            f"Invalid storage increment. Allowed increments: {allowed_increments} GB"
        )

    # 2. Get org and validate it has a Stripe customer ID
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    if not org.stripe_customer_id:
        raise ValueError(
            "No payment method on file. Please add a payment method before purchasing storage."
        )

    # 3. Calculate charge
    charge_amount_nzd = round(quantity_gb * price_per_gb, 2)
    charge_amount_cents = int(charge_amount_nzd * 100)

    # 4. Charge via Stripe immediately
    try:
        payment_intent = stripe_lib.PaymentIntent.create(
            amount=charge_amount_cents,
            currency="nzd",
            customer=org.stripe_customer_id,
            confirm=True,
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            description=f"Storage add-on: +{quantity_gb} GB for {org.name}",
            metadata={
                "platform": "workshoppro_nz",
                "org_id": str(org_id),
                "type": "storage_addon",
                "quantity_gb": str(quantity_gb),
            },
        )
    except stripe_lib.error.CardError as exc:
        raise RuntimeError(f"Payment failed: {exc.user_message}") from exc
    except stripe_lib.error.StripeError as exc:
        raise RuntimeError(f"Stripe error: {str(exc)}") from exc

    stripe_charge_id = payment_intent.id

    # 5. Increase org's storage quota instantly
    previous_quota = org.storage_quota_gb
    org.storage_quota_gb = previous_quota + quantity_gb
    await db.flush()

    return {
        "success": True,
        "quantity_gb": quantity_gb,
        "new_total_quota_gb": org.storage_quota_gb,
        "charge_amount_nzd": charge_amount_nzd,
        "stripe_charge_id": stripe_charge_id,
        "price_per_gb_nzd": price_per_gb,
        "additional_monthly_charge_nzd": charge_amount_nzd,
        "previous_quota_gb": previous_quota,
    }


# ---------------------------------------------------------------------------
# Storage add-on v2 — Package-based purchase / resize / remove
# Requirements: 4.1–4.6, 5.1–5.7, 7.2
# ---------------------------------------------------------------------------

import logging
from datetime import datetime, timezone

from app.core.audit import write_audit_log
from app.modules.admin.models import (
    OrgStorageAddon,
    PlatformSetting,
    StoragePackage,
)

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_PRICE_PER_GB_NZD: float = 0.50


def _addon_to_dict(addon: OrgStorageAddon) -> dict:
    """Serialise an OrgStorageAddon row to a plain dict."""
    package_name = None
    if addon.storage_package is not None:
        package_name = addon.storage_package.name
    return {
        "id": str(addon.id),
        "package_name": package_name,
        "quantity_gb": addon.quantity_gb,
        "price_nzd_per_month": float(addon.price_nzd_per_month),
        "is_custom": addon.is_custom,
        "purchased_at": addon.purchased_at,
    }


async def _get_fallback_price_per_gb(db: AsyncSession) -> float:
    """Read fallback price_per_gb_nzd from platform_settings.storage_pricing."""
    result = await db.execute(
        select(PlatformSetting.value).where(PlatformSetting.key == "storage_pricing")
    )
    row = result.scalar_one_or_none()
    if row and isinstance(row, dict):
        return float(row.get("price_per_gb_nzd", DEFAULT_FALLBACK_PRICE_PER_GB_NZD))
    return DEFAULT_FALLBACK_PRICE_PER_GB_NZD


async def get_storage_addon_status(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """Return current add-on status, available packages, fallback price, and quotas.

    Requirements: 4.1–4.5, 5.1–5.2
    """
    from sqlalchemy.orm import selectinload

    # Load org with plan
    org_result = await db.execute(
        select(Organisation)
        .options(selectinload(Organisation.plan))
        .where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Load current add-on (if any) with its package
    addon_result = await db.execute(
        select(OrgStorageAddon)
        .options(selectinload(OrgStorageAddon.storage_package))
        .where(OrgStorageAddon.org_id == org_id)
    )
    addon = addon_result.scalar_one_or_none()

    # Available active packages
    pkg_result = await db.execute(
        select(StoragePackage)
        .where(StoragePackage.is_active.is_(True))
        .order_by(StoragePackage.sort_order.asc())
    )
    packages = pkg_result.scalars().all()

    fallback_price = await _get_fallback_price_per_gb(db)

    base_quota_gb = org.storage_quota_gb
    addon_gb = addon.quantity_gb if addon else 0
    total_quota_gb = base_quota_gb + addon_gb
    storage_used_gb = round(org.storage_used_bytes / (1024 ** 3), 2)

    return {
        "current_addon": _addon_to_dict(addon) if addon else None,
        "available_packages": [
            {
                "id": str(p.id),
                "name": p.name,
                "storage_gb": p.storage_gb,
                "price_nzd_per_month": float(p.price_nzd_per_month),
                "description": p.description,
                "is_active": p.is_active,
                "sort_order": p.sort_order,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in packages
        ],
        "fallback_price_per_gb_nzd": fallback_price,
        "base_quota_gb": base_quota_gb,
        "total_quota_gb": total_quota_gb,
        "storage_used_gb": storage_used_gb,
    }


async def purchase_storage_addon_v2(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    package_id: str | None = None,
    custom_gb: int | None = None,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Purchase a new storage add-on for an organisation (package-based).

    - Validates org has no existing add-on (409 if exists).
    - If package_id: loads package, validates active, creates addon record.
    - If custom_gb: uses fallback price_per_gb_nzd, creates addon with is_custom=True.
    - Updates org.storage_quota_gb += quantity_gb.
    - Writes audit log.

    Requirements: 4.1–4.6, 7.2
    """
    from sqlalchemy.orm import selectinload

    if not package_id and not custom_gb:
        raise ValueError("Provide either package_id or custom_gb")
    if package_id and custom_gb:
        raise ValueError("Provide either package_id or custom_gb, not both")

    # Check org exists
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Check no existing add-on (conflict)
    existing = await db.execute(
        select(OrgStorageAddon).where(OrgStorageAddon.org_id == org_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("Organisation already has a storage add-on. Use resize instead.")

    # Determine quantity and price
    storage_package = None
    if package_id:
        pkg_result = await db.execute(
            select(StoragePackage).where(StoragePackage.id == uuid.UUID(package_id))
        )
        storage_package = pkg_result.scalar_one_or_none()
        if storage_package is None:
            raise LookupError("Storage package not found")
        if not storage_package.is_active:
            raise ValueError("This storage package is no longer available")
        quantity_gb = storage_package.storage_gb
        price_nzd = float(storage_package.price_nzd_per_month)
        is_custom = False
    else:
        if custom_gb < 1:
            raise ValueError("custom_gb must be at least 1")
        fallback_price = await _get_fallback_price_per_gb(db)
        quantity_gb = custom_gb
        price_nzd = round(custom_gb * fallback_price, 2)
        is_custom = True

    # Create add-on record
    now = datetime.now(timezone.utc)
    addon = OrgStorageAddon(
        org_id=org_id,
        storage_package_id=storage_package.id if storage_package else None,
        quantity_gb=quantity_gb,
        price_nzd_per_month=price_nzd,
        is_custom=is_custom,
        purchased_at=now,
    )
    db.add(addon)
    await db.flush()

    # Update org quota
    previous_quota = org.storage_quota_gb
    org.storage_quota_gb = previous_quota + quantity_gb
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        action="storage_addon.purchased",
        org_id=org_id,
        user_id=user_id,
        entity_type="org_storage_addon",
        entity_id=addon.id,
        ip_address=ip_address,
        after_value={
            "quantity_gb": quantity_gb,
            "price_nzd_per_month": price_nzd,
            "is_custom": is_custom,
            "package_id": package_id,
            "previous_quota_gb": previous_quota,
            "new_quota_gb": org.storage_quota_gb,
        },
    )

    logger.info(
        "Org %s purchased storage add-on: %d GB ($%.2f/mo), custom=%s",
        org_id, quantity_gb, price_nzd, is_custom,
    )

    # Reload to get relationships for response
    await db.refresh(addon, ["storage_package"])
    return _addon_to_dict(addon)


async def resize_storage_addon(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    package_id: str | None = None,
    custom_gb: int | None = None,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Resize an existing storage add-on (upgrade or downgrade).

    - Validates org has existing add-on (404 if not).
    - Calculates new quantity, validates usage doesn't exceed new total on downgrade.
    - Updates addon record and org.storage_quota_gb.
    - Writes audit log with before/after.

    Requirements: 5.1–5.7, 7.2
    """
    from sqlalchemy.orm import selectinload

    if not package_id and not custom_gb:
        raise ValueError("Provide either package_id or custom_gb")
    if package_id and custom_gb:
        raise ValueError("Provide either package_id or custom_gb, not both")

    # Load org with plan
    org_result = await db.execute(
        select(Organisation)
        .options(selectinload(Organisation.plan))
        .where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Load existing add-on
    addon_result = await db.execute(
        select(OrgStorageAddon)
        .options(selectinload(OrgStorageAddon.storage_package))
        .where(OrgStorageAddon.org_id == org_id)
    )
    addon = addon_result.scalar_one_or_none()
    if addon is None:
        raise LookupError("No active storage add-on found")

    # Capture before state
    before = {
        "quantity_gb": addon.quantity_gb,
        "price_nzd_per_month": float(addon.price_nzd_per_month),
        "is_custom": addon.is_custom,
        "package_id": str(addon.storage_package_id) if addon.storage_package_id else None,
    }

    # Determine new quantity and price
    storage_package = None
    if package_id:
        pkg_result = await db.execute(
            select(StoragePackage).where(StoragePackage.id == uuid.UUID(package_id))
        )
        storage_package = pkg_result.scalar_one_or_none()
        if storage_package is None:
            raise LookupError("Storage package not found")
        if not storage_package.is_active:
            raise ValueError("This storage package is no longer available")
        new_quantity_gb = storage_package.storage_gb
        new_price_nzd = float(storage_package.price_nzd_per_month)
        new_is_custom = False
    else:
        if custom_gb < 1:
            raise ValueError("custom_gb must be at least 1")
        fallback_price = await _get_fallback_price_per_gb(db)
        new_quantity_gb = custom_gb
        new_price_nzd = round(custom_gb * fallback_price, 2)
        new_is_custom = True

    # Validate downgrade: usage must not exceed new total quota
    old_quantity_gb = addon.quantity_gb
    if new_quantity_gb < old_quantity_gb:
        base_quota_gb = org.storage_quota_gb
        new_total_quota_gb = base_quota_gb + new_quantity_gb
        storage_used_gb = org.storage_used_bytes / (1024 ** 3)
        if storage_used_gb > new_total_quota_gb:
            raise ValueError(
                f"Current storage usage ({storage_used_gb:.2f} GB) exceeds the new quota "
                f"({new_total_quota_gb} GB). Free up space first."
            )

    # Update add-on record
    addon.storage_package_id = storage_package.id if storage_package else None
    addon.quantity_gb = new_quantity_gb
    addon.price_nzd_per_month = new_price_nzd
    addon.is_custom = new_is_custom
    await db.flush()

    # Update org quota
    quota_diff = new_quantity_gb - old_quantity_gb
    previous_quota = org.storage_quota_gb
    org.storage_quota_gb = previous_quota + quota_diff
    await db.flush()

    # After state
    after = {
        "quantity_gb": new_quantity_gb,
        "price_nzd_per_month": new_price_nzd,
        "is_custom": new_is_custom,
        "package_id": package_id,
        "previous_quota_gb": previous_quota,
        "new_quota_gb": org.storage_quota_gb,
    }

    await write_audit_log(
        session=db,
        action="storage_addon.resized",
        org_id=org_id,
        user_id=user_id,
        entity_type="org_storage_addon",
        entity_id=addon.id,
        ip_address=ip_address,
        before_value=before,
        after_value=after,
    )

    direction = "upgraded" if quota_diff > 0 else "downgraded"
    logger.info(
        "Org %s %s storage add-on: %d → %d GB",
        org_id, direction, old_quantity_gb, new_quantity_gb,
    )

    await db.refresh(addon, ["storage_package"])
    return _addon_to_dict(addon)


async def remove_storage_addon(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Remove the active storage add-on, reverting to plan base quota.

    - Validates usage doesn't exceed base quota.
    - Deletes addon record, reduces org.storage_quota_gb.
    - Writes audit log.

    Requirements: 5.7, 7.2
    """
    from sqlalchemy.orm import selectinload

    # Load org with plan
    org_result = await db.execute(
        select(Organisation)
        .options(selectinload(Organisation.plan))
        .where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Load existing add-on
    addon_result = await db.execute(
        select(OrgStorageAddon)
        .options(selectinload(OrgStorageAddon.storage_package))
        .where(OrgStorageAddon.org_id == org_id)
    )
    addon = addon_result.scalar_one_or_none()
    if addon is None:
        raise LookupError("No active storage add-on found")

    # Validate usage doesn't exceed base quota
    base_quota_gb = org.storage_quota_gb
    storage_used_gb = org.storage_used_bytes / (1024 ** 3)
    if storage_used_gb > base_quota_gb:
        raise ValueError(
            f"Current storage usage ({storage_used_gb:.2f} GB) exceeds the base quota "
            f"({base_quota_gb} GB). Free up space first."
        )

    # Capture before state for audit
    before = {
        "quantity_gb": addon.quantity_gb,
        "price_nzd_per_month": float(addon.price_nzd_per_month),
        "is_custom": addon.is_custom,
        "package_id": str(addon.storage_package_id) if addon.storage_package_id else None,
    }

    # Reduce org quota
    previous_quota = org.storage_quota_gb
    org.storage_quota_gb = previous_quota - addon.quantity_gb
    await db.flush()

    # Delete add-on record
    await db.delete(addon)
    await db.flush()

    await write_audit_log(
        session=db,
        action="storage_addon.removed",
        org_id=org_id,
        user_id=user_id,
        entity_type="org_storage_addon",
        entity_id=addon.id,
        ip_address=ip_address,
        before_value=before,
        after_value={
            "previous_quota_gb": previous_quota,
            "new_quota_gb": org.storage_quota_gb,
        },
    )

    logger.info(
        "Org %s removed storage add-on: -%d GB, quota %d → %d",
        org_id, addon.quantity_gb, previous_quota, org.storage_quota_gb,
    )

    return {"message": "Storage add-on removed", "new_quota_gb": org.storage_quota_gb}

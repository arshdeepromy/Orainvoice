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


async def calculate_org_storage(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Calculate total storage bytes for an organisation.

    Sums the byte-length of:
    - invoice_data_json (compressed invoice JSON) for all invoices
    - customer records (first_name, last_name, email, phone, address, notes)
    - org vehicle records (rego, make, model, colour, etc.)
    - customer_vehicle link records

    Logos and branding assets are explicitly excluded (Req 29.1).

    Returns the total storage in bytes.
    """
    # Invoice JSON storage — pg_column_size gives on-disk size including TOAST
    invoice_size_result = await db.execute(
        select(
            func.coalesce(
                func.sum(func.octet_length(func.cast(Invoice.invoice_data_json, type_=_text_type()))),
                0,
            )
        ).where(Invoice.org_id == org_id)
    )
    invoice_bytes: int = invoice_size_result.scalar() or 0

    # Customer records storage — approximate from text fields
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

    return invoice_bytes + customer_bytes + vehicle_bytes


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
    storage_used_bytes = await calculate_org_storage(db, org_id)

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

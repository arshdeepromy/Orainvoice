"""Data import service — CSV parsing, validation, and import logic.

Requirements: 69.1, 69.2, 69.3, 69.5
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.vehicles.models import OrgVehicle
from app.modules.data_io.schemas import (
    FieldMapping,
    ImportCommitResponse,
    ImportPreviewResponse,
    ImportPreviewRow,
    ImportRowError,
)

# ---------------------------------------------------------------------------
# Known fields for each entity type
# ---------------------------------------------------------------------------

CUSTOMER_FIELDS: dict[str, dict[str, Any]] = {
    "first_name": {"required": True, "max_length": 100},
    "last_name": {"required": True, "max_length": 100},
    "email": {"required": False, "max_length": 255, "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
    "phone": {"required": False, "max_length": 50},
    "address": {"required": False, "max_length": 5000},
    "notes": {"required": False, "max_length": 5000},
}

VEHICLE_FIELDS: dict[str, dict[str, Any]] = {
    "rego": {"required": True, "max_length": 20},
    "make": {"required": False, "max_length": 100},
    "model": {"required": False, "max_length": 100},
    "year": {"required": False, "type": "int", "min": 1900, "max": 2100},
    "colour": {"required": False, "max_length": 50},
    "body_type": {"required": False, "max_length": 50},
    "fuel_type": {"required": False, "max_length": 50},
    "engine_size": {"required": False, "max_length": 50},
    "num_seats": {"required": False, "type": "int", "min": 1, "max": 100},
}

# Common aliases for auto-mapping CSV headers → target fields
_CUSTOMER_ALIASES: dict[str, str] = {
    "firstname": "first_name",
    "first name": "first_name",
    "first_name": "first_name",
    "lastname": "last_name",
    "last name": "last_name",
    "last_name": "last_name",
    "email": "email",
    "email_address": "email",
    "email address": "email",
    "phone": "phone",
    "phone_number": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "address": "address",
    "notes": "notes",
}

_VEHICLE_ALIASES: dict[str, str] = {
    "rego": "rego",
    "registration": "rego",
    "reg": "rego",
    "plate": "rego",
    "make": "make",
    "model": "model",
    "year": "year",
    "colour": "colour",
    "color": "colour",
    "body_type": "body_type",
    "body type": "body_type",
    "bodytype": "body_type",
    "fuel_type": "fuel_type",
    "fuel type": "fuel_type",
    "fueltype": "fuel_type",
    "engine_size": "engine_size",
    "engine size": "engine_size",
    "enginesize": "engine_size",
    "num_seats": "num_seats",
    "seats": "num_seats",
    "number of seats": "num_seats",
}


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_csv(content: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse CSV content and return (headers, rows).

    Each row is a dict mapping header → value.
    """
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    rows = list(reader)
    return list(headers), rows


# ---------------------------------------------------------------------------
# Auto-mapping
# ---------------------------------------------------------------------------

def auto_detect_mapping(
    headers: list[str],
    entity_type: str,
) -> list[FieldMapping]:
    """Attempt to map CSV headers to target fields using known aliases."""
    aliases = _CUSTOMER_ALIASES if entity_type == "customers" else _VEHICLE_ALIASES
    mappings: list[FieldMapping] = []
    for header in headers:
        normalised = header.strip().lower()
        target = aliases.get(normalised)
        if target:
            mappings.append(FieldMapping(csv_column=header, target_field=target))
    return mappings


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_row(
    row_number: int,
    row_data: dict[str, str],
    mapping: list[FieldMapping],
    field_specs: dict[str, dict[str, Any]],
) -> tuple[dict[str, str] | None, list[ImportRowError]]:
    """Validate a single mapped row against field specifications.

    Returns (mapped_data, errors). If errors is non-empty, mapped_data is None.
    """
    errors: list[ImportRowError] = []
    mapped: dict[str, str] = {}

    mapping_dict = {m.csv_column: m.target_field for m in mapping}

    for csv_col, target_field in mapping_dict.items():
        raw_value = row_data.get(csv_col, "").strip()
        spec = field_specs.get(target_field)
        if spec is None:
            # Unknown target field — skip silently
            continue

        # Required check
        if spec.get("required") and not raw_value:
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    field=target_field,
                    value=raw_value,
                    error=f"'{target_field}' is required",
                )
            )
            continue

        if not raw_value:
            mapped[target_field] = ""
            continue

        # Max length
        max_len = spec.get("max_length")
        if max_len and len(raw_value) > max_len:
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    field=target_field,
                    value=raw_value,
                    error=f"'{target_field}' exceeds max length of {max_len}",
                )
            )
            continue

        # Pattern (e.g. email)
        pattern = spec.get("pattern")
        if pattern and not re.match(pattern, raw_value):
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    field=target_field,
                    value=raw_value,
                    error=f"'{target_field}' has invalid format",
                )
            )
            continue

        # Integer type
        if spec.get("type") == "int":
            try:
                int_val = int(raw_value)
            except ValueError:
                errors.append(
                    ImportRowError(
                        row_number=row_number,
                        field=target_field,
                        value=raw_value,
                        error=f"'{target_field}' must be an integer",
                    )
                )
                continue
            min_val = spec.get("min")
            max_val = spec.get("max")
            if min_val is not None and int_val < min_val:
                errors.append(
                    ImportRowError(
                        row_number=row_number,
                        field=target_field,
                        value=raw_value,
                        error=f"'{target_field}' must be >= {min_val}",
                    )
                )
                continue
            if max_val is not None and int_val > max_val:
                errors.append(
                    ImportRowError(
                        row_number=row_number,
                        field=target_field,
                        value=raw_value,
                        error=f"'{target_field}' must be <= {max_val}",
                    )
                )
                continue

        mapped[target_field] = raw_value

    # Check required fields that weren't in the mapping at all
    for field_name, spec in field_specs.items():
        if spec.get("required") and field_name not in mapped:
            # Only add error if not already reported
            already_reported = any(e.field == field_name for e in errors)
            if not already_reported:
                errors.append(
                    ImportRowError(
                        row_number=row_number,
                        field=field_name,
                        value="",
                        error=f"'{field_name}' is required but not mapped",
                    )
                )

    if errors:
        return None, errors
    return mapped, []


def validate_import(
    headers: list[str],
    rows: list[dict[str, str]],
    mapping: list[FieldMapping],
    entity_type: str,
) -> ImportPreviewResponse:
    """Validate all rows and return a preview response."""
    field_specs = CUSTOMER_FIELDS if entity_type == "customers" else VEHICLE_FIELDS

    valid_rows: list[ImportPreviewRow] = []
    error_rows: list[ImportRowError] = []

    for idx, row in enumerate(rows, start=1):
        mapped_data, row_errors = _validate_row(idx, row, mapping, field_specs)
        if row_errors:
            error_rows.extend(row_errors)
        elif mapped_data is not None:
            valid_rows.append(ImportPreviewRow(row_number=idx, data=mapped_data))

    return ImportPreviewResponse(
        total_rows=len(rows),
        valid_rows=valid_rows,
        error_rows=error_rows,
        detected_mapping=mapping,
    )


# ---------------------------------------------------------------------------
# Commit import
# ---------------------------------------------------------------------------

async def commit_customer_import(
    db: AsyncSession,
    org_id: uuid.UUID,
    rows: list[dict[str, str]],
    mapping: list[FieldMapping],
) -> ImportCommitResponse:
    """Import validated customer rows into the database.

    Skips invalid rows and returns an error report.
    Requirements: 69.1, 69.5
    """
    imported = 0
    skipped = 0
    errors: list[ImportRowError] = []

    for idx, row in enumerate(rows, start=1):
        mapped_data, row_errors = _validate_row(idx, row, mapping, CUSTOMER_FIELDS)
        if row_errors:
            errors.extend(row_errors)
            skipped += 1
            continue
        if mapped_data is None:
            skipped += 1
            continue

        customer = Customer(
            org_id=org_id,
            first_name=mapped_data["first_name"],
            last_name=mapped_data["last_name"],
            email=mapped_data.get("email") or None,
            phone=mapped_data.get("phone") or None,
            address=mapped_data.get("address") or None,
            notes=mapped_data.get("notes") or None,
        )
        db.add(customer)
        imported += 1

    if imported > 0:
        await db.flush()

    return ImportCommitResponse(
        imported_count=imported,
        skipped_count=skipped,
        errors=errors,
    )


async def commit_vehicle_import(
    db: AsyncSession,
    org_id: uuid.UUID,
    rows: list[dict[str, str]],
    mapping: list[FieldMapping],
) -> ImportCommitResponse:
    """Import validated vehicle rows into the database.

    Vehicles are stored as org-scoped manual entries.
    Requirements: 69.2, 69.5
    """
    imported = 0
    skipped = 0
    errors: list[ImportRowError] = []

    for idx, row in enumerate(rows, start=1):
        mapped_data, row_errors = _validate_row(idx, row, mapping, VEHICLE_FIELDS)
        if row_errors:
            errors.extend(row_errors)
            skipped += 1
            continue
        if mapped_data is None:
            skipped += 1
            continue

        year_val = None
        if mapped_data.get("year"):
            try:
                year_val = int(mapped_data["year"])
            except ValueError:
                pass

        seats_val = None
        if mapped_data.get("num_seats"):
            try:
                seats_val = int(mapped_data["num_seats"])
            except ValueError:
                pass

        vehicle = OrgVehicle(
            org_id=org_id,
            rego=mapped_data["rego"],
            make=mapped_data.get("make") or None,
            model=mapped_data.get("model") or None,
            year=year_val,
            colour=mapped_data.get("colour") or None,
            body_type=mapped_data.get("body_type") or None,
            fuel_type=mapped_data.get("fuel_type") or None,
            engine_size=mapped_data.get("engine_size") or None,
            num_seats=seats_val,
            is_manual_entry=True,
        )
        db.add(vehicle)
        imported += 1

    if imported > 0:
        await db.flush()

    return ImportCommitResponse(
        imported_count=imported,
        skipped_count=skipped,
        errors=errors,
    )


def generate_error_report_csv(errors: list[ImportRowError]) -> str:
    """Generate a CSV string from a list of import row errors."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["row_number", "field", "value", "error"])
    for err in errors:
        writer.writerow([err.row_number, err.field, err.value, err.error])
    return output.getvalue()


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

CUSTOMER_EXPORT_HEADERS = [
    "id", "first_name", "last_name", "email", "phone", "address", "notes",
    "is_anonymised", "created_at",
]

VEHICLE_EXPORT_HEADERS = [
    "id", "rego", "make", "model", "year", "colour", "body_type",
    "fuel_type", "engine_size", "num_seats", "source", "customer_name",
]

INVOICE_EXPORT_HEADERS = [
    "id", "invoice_number", "status", "customer_name", "vehicle_rego",
    "issue_date", "due_date", "currency", "subtotal", "discount_amount",
    "gst_amount", "total", "amount_paid", "balance_due", "created_at",
]


async def export_customers_csv(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> str:
    """Export all customers for an org as CSV.

    Requirements: 69.4
    """
    result = await db.execute(
        select(Customer).where(Customer.org_id == org_id).order_by(Customer.created_at)
    )
    customers = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CUSTOMER_EXPORT_HEADERS)
    for c in customers:
        writer.writerow([
            str(c.id),
            c.first_name,
            c.last_name,
            c.email or "",
            c.phone or "",
            c.address or "",
            c.notes or "",
            c.is_anonymised,
            c.created_at.isoformat() if c.created_at else "",
        ])
    return output.getvalue()


async def export_vehicles_csv(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> str:
    """Export all vehicles linked to an org's customers as CSV.

    Includes both global vehicles and org-scoped manual entries linked
    via customer_vehicles.

    Requirements: 69.4
    """
    from app.modules.vehicles.models import CustomerVehicle
    from app.modules.admin.models import GlobalVehicle

    # Org vehicles (manual entries)
    org_result = await db.execute(
        select(OrgVehicle).where(OrgVehicle.org_id == org_id).order_by(OrgVehicle.created_at)
    )
    org_vehicles = org_result.scalars().all()

    # Global vehicles linked to this org's customers
    global_result = await db.execute(
        select(GlobalVehicle)
        .join(CustomerVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
        .where(CustomerVehicle.org_id == org_id)
        .distinct()
    )
    global_vehicles = global_result.scalars().all()

    # Build customer name lookup for linked vehicles
    cv_result = await db.execute(
        select(CustomerVehicle).where(CustomerVehicle.org_id == org_id)
    )
    cv_links = cv_result.scalars().all()

    # Preload customers for name lookup
    customer_ids = {cv.customer_id for cv in cv_links}
    cust_map: dict[uuid.UUID, str] = {}
    if customer_ids:
        cust_result = await db.execute(
            select(Customer).where(Customer.id.in_(customer_ids))
        )
        for cust in cust_result.scalars().all():
            cust_map[cust.id] = f"{cust.first_name} {cust.last_name}"

    # Map vehicle id -> customer names
    vehicle_customers: dict[uuid.UUID, list[str]] = {}
    for cv in cv_links:
        vid = cv.org_vehicle_id or cv.global_vehicle_id
        if vid:
            vehicle_customers.setdefault(vid, []).append(
                cust_map.get(cv.customer_id, "")
            )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(VEHICLE_EXPORT_HEADERS)

    for v in org_vehicles:
        names = "; ".join(vehicle_customers.get(v.id, []))
        writer.writerow([
            str(v.id), v.rego, v.make or "", v.model or "",
            v.year or "", v.colour or "", v.body_type or "",
            v.fuel_type or "", v.engine_size or "", v.num_seats or "",
            "manual", names,
        ])

    for v in global_vehicles:
        names = "; ".join(vehicle_customers.get(v.id, []))
        writer.writerow([
            str(v.id), v.rego, v.make or "", v.model or "",
            v.year or "", v.colour or "", v.body_type or "",
            v.fuel_type or "", v.engine_size or "", v.num_seats or "",
            "carjam", names,
        ])

    return output.getvalue()


async def export_invoices_csv(
    db: AsyncSession,
    org_id: uuid.UUID,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Export invoices for an org as CSV with optional date filtering.

    Requirements: 69.4
    """
    from datetime import date as date_type
    from app.modules.invoices.models import Invoice

    query = select(Invoice).where(Invoice.org_id == org_id)

    if date_from:
        try:
            d = date_type.fromisoformat(date_from)
            query = query.where(Invoice.issue_date >= d)
        except ValueError:
            pass

    if date_to:
        try:
            d = date_type.fromisoformat(date_to)
            query = query.where(Invoice.issue_date <= d)
        except ValueError:
            pass

    query = query.order_by(Invoice.created_at)
    result = await db.execute(query)
    invoices = result.scalars().all()

    # Preload customer names
    customer_ids = {inv.customer_id for inv in invoices}
    cust_map: dict[uuid.UUID, str] = {}
    if customer_ids:
        cust_result = await db.execute(
            select(Customer).where(Customer.id.in_(customer_ids))
        )
        for cust in cust_result.scalars().all():
            cust_map[cust.id] = f"{cust.first_name} {cust.last_name}"

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(INVOICE_EXPORT_HEADERS)
    for inv in invoices:
        writer.writerow([
            str(inv.id),
            inv.invoice_number or "",
            inv.status,
            cust_map.get(inv.customer_id, ""),
            inv.vehicle_rego or "",
            inv.issue_date.isoformat() if inv.issue_date else "",
            inv.due_date.isoformat() if inv.due_date else "",
            inv.currency,
            str(inv.subtotal),
            str(inv.discount_amount),
            str(inv.gst_amount),
            str(inv.total),
            str(inv.amount_paid),
            str(inv.balance_due),
            inv.created_at.isoformat() if inv.created_at else "",
        ])
    return output.getvalue()

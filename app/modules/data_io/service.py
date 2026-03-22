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
    "first_name": {"required": False, "max_length": 100},
    "last_name": {"required": False, "max_length": 100},
    "email": {"required": False, "max_length": 255, "pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$"},
    "phone": {"required": False, "max_length": 50},
    "mobile_phone": {"required": False, "max_length": 50},
    "work_phone": {"required": False, "max_length": 50},
    "company_name": {"required": False, "max_length": 255},
    "display_name": {"required": False, "max_length": 255},
    "customer_type": {"required": False, "max_length": 20},
    "salutation": {"required": False, "max_length": 20},
    "address": {"required": False, "max_length": 5000},
    "billing_address": {"required": False, "max_length": 5000},
    "shipping_address": {"required": False, "max_length": 5000},
    "currency": {"required": False, "max_length": 3},
    "language": {"required": False, "max_length": 10},
    "payment_terms": {"required": False, "max_length": 50},
    "company_id": {"required": False, "max_length": 100},
    "notes": {"required": False, "max_length": 5000},
    "remarks": {"required": False, "max_length": 5000},
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
    "vin": {"required": False, "max_length": 17},
    "chassis": {"required": False, "max_length": 50},
    "engine_no": {"required": False, "max_length": 50},
    "transmission": {"required": False, "max_length": 100},
    "country_of_origin": {"required": False, "max_length": 50},
    "number_of_owners": {"required": False, "type": "int", "min": 0, "max": 999},
    "vehicle_type": {"required": False, "max_length": 50},
    "power_kw": {"required": False, "type": "int", "min": 0, "max": 9999},
    "tare_weight": {"required": False, "type": "int", "min": 0, "max": 99999},
    "gross_vehicle_mass": {"required": False, "type": "int", "min": 0, "max": 99999},
    "plate_type": {"required": False, "max_length": 20},
    "submodel": {"required": False, "max_length": 150},
    "second_colour": {"required": False, "max_length": 50},
    "wof_expiry": {"required": False, "type": "date"},
    "registration_expiry": {"required": False, "type": "date"},
    "service_due_date": {"required": False, "type": "date"},
    "date_first_registered_nz": {"required": False, "type": "date"},
    "odometer_last_recorded": {"required": False, "type": "int", "min": 0, "max": 9999999},
}

# Common aliases for auto-mapping CSV headers → target fields
_CUSTOMER_ALIASES: dict[str, str] = {
    "name": "first_name",
    "customer name": "first_name",
    "customername": "first_name",
    "customer_name": "first_name",
    "full name": "first_name",
    "fullname": "first_name",
    "full_name": "first_name",
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
    "mobile": "mobile_phone",
    "mobile_phone": "mobile_phone",
    "mobile phone": "mobile_phone",
    "cell": "mobile_phone",
    "cell phone": "mobile_phone",
    "work_phone": "work_phone",
    "work phone": "work_phone",
    "workphone": "work_phone",
    "office phone": "work_phone",
    "company_name": "company_name",
    "company name": "company_name",
    "company": "company_name",
    "display_name": "display_name",
    "display name": "display_name",
    "customer_type": "customer_type",
    "customer type": "customer_type",
    "type": "customer_type",
    "salutation": "salutation",
    "title": "salutation",
    "address": "address",
    "billing_address": "billing_address",
    "billing address": "billing_address",
    "shipping_address": "shipping_address",
    "shipping address": "shipping_address",
    "currency": "currency",
    "language": "language",
    "payment_terms": "payment_terms",
    "payment terms": "payment_terms",
    "company_id": "company_id",
    "company id": "company_id",
    "business number": "company_id",
    "nzbn": "company_id",
    "notes": "notes",
    "remarks": "remarks",
}

_VEHICLE_ALIASES: dict[str, str] = {
    "rego": "rego",
    "registration": "rego",
    "reg": "rego",
    "plate": "rego",
    "plate number": "rego",
    "make": "make",
    "model": "model",
    "submodel": "submodel",
    "sub model": "submodel",
    "sub_model": "submodel",
    "year": "year",
    "colour": "colour",
    "color": "colour",
    "second_colour": "second_colour",
    "second colour": "second_colour",
    "second color": "second_colour",
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
    "vin": "vin",
    "vin number": "vin",
    "chassis": "chassis",
    "chassis number": "chassis",
    "engine_no": "engine_no",
    "engine no": "engine_no",
    "engine number": "engine_no",
    "transmission": "transmission",
    "gearbox": "transmission",
    "country_of_origin": "country_of_origin",
    "country of origin": "country_of_origin",
    "country": "country_of_origin",
    "number_of_owners": "number_of_owners",
    "number of owners": "number_of_owners",
    "owners": "number_of_owners",
    "vehicle_type": "vehicle_type",
    "vehicle type": "vehicle_type",
    "type": "vehicle_type",
    "power_kw": "power_kw",
    "power kw": "power_kw",
    "power": "power_kw",
    "kw": "power_kw",
    "tare_weight": "tare_weight",
    "tare weight": "tare_weight",
    "tare": "tare_weight",
    "gross_vehicle_mass": "gross_vehicle_mass",
    "gross vehicle mass": "gross_vehicle_mass",
    "gvm": "gross_vehicle_mass",
    "plate_type": "plate_type",
    "plate type": "plate_type",
    "wof_expiry": "wof_expiry",
    "wof expiry": "wof_expiry",
    "wof": "wof_expiry",
    "registration_expiry": "registration_expiry",
    "registration expiry": "registration_expiry",
    "rego expiry": "registration_expiry",
    "service_due_date": "service_due_date",
    "service due date": "service_due_date",
    "service due": "service_due_date",
    "date_first_registered_nz": "date_first_registered_nz",
    "date first registered nz": "date_first_registered_nz",
    "first registered": "date_first_registered_nz",
    "odometer_last_recorded": "odometer_last_recorded",
    "odometer": "odometer_last_recorded",
    "odometer last recorded": "odometer_last_recorded",
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
        # Support both original CSV headers and already-remapped headers.
        # The frontend may remap headers to target field names before sending,
        # so try the original csv_col first, then fall back to target_field.
        raw_value = row_data.get(csv_col, "")
        if not raw_value and csv_col != target_field:
            raw_value = row_data.get(target_field, "")
        raw_value = raw_value.strip()
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

        # Date type (YYYY-MM-DD)
        if spec.get("type") == "date":
            from datetime import date as date_type
            try:
                date_type.fromisoformat(raw_value)
            except ValueError:
                errors.append(
                    ImportRowError(
                        row_number=row_number,
                        field=target_field,
                        value=raw_value,
                        error=f"'{target_field}' must be a valid date (YYYY-MM-DD)",
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

        first_raw = mapped_data.get("first_name", "")
        last_raw = mapped_data.get("last_name")
        first, last = _split_name(first_raw, last_raw)
        if not first and not last:
            errors.append(ImportRowError(
                row_number=idx, field="first_name", value="",
                error="At least a name is required",
            ))
            skipped += 1
            continue

        customer = Customer(
            org_id=org_id,
            first_name=first or "",
            last_name=last or "",
            email=mapped_data.get("email") or None,
            phone=mapped_data.get("phone") or None,
            mobile_phone=mapped_data.get("mobile_phone") or None,
            work_phone=mapped_data.get("work_phone") or None,
            company_name=mapped_data.get("company_name") or None,
            display_name=mapped_data.get("display_name") or None,
            customer_type=mapped_data.get("customer_type") or "individual",
            salutation=mapped_data.get("salutation") or None,
            address=mapped_data.get("address") or None,
            billing_address={"line1": mapped_data["billing_address"]} if mapped_data.get("billing_address") else {},
            shipping_address={"line1": mapped_data["shipping_address"]} if mapped_data.get("shipping_address") else {},
            currency=mapped_data.get("currency") or "NZD",
            language=mapped_data.get("language") or "en",
            payment_terms=mapped_data.get("payment_terms") or "due_on_receipt",
            company_id=mapped_data.get("company_id") or None,
            notes=mapped_data.get("notes") or None,
            remarks=mapped_data.get("remarks") or None,
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

        def _safe_int(key: str) -> int | None:
            v = mapped_data.get(key)
            if not v:
                return None
            try:
                return int(v)
            except ValueError:
                return None

        def _safe_date(key: str):
            from datetime import date as date_type
            v = mapped_data.get(key)
            if not v:
                return None
            try:
                return date_type.fromisoformat(v)
            except ValueError:
                return None

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
            vin=mapped_data.get("vin") or None,
            chassis=mapped_data.get("chassis") or None,
            engine_no=mapped_data.get("engine_no") or None,
            transmission=mapped_data.get("transmission") or None,
            country_of_origin=mapped_data.get("country_of_origin") or None,
            number_of_owners=_safe_int("number_of_owners"),
            vehicle_type=mapped_data.get("vehicle_type") or None,
            power_kw=_safe_int("power_kw"),
            tare_weight=_safe_int("tare_weight"),
            gross_vehicle_mass=_safe_int("gross_vehicle_mass"),
            plate_type=mapped_data.get("plate_type") or None,
            submodel=mapped_data.get("submodel") or None,
            second_colour=mapped_data.get("second_colour") or None,
            wof_expiry=_safe_date("wof_expiry"),
            registration_expiry=_safe_date("registration_expiry"),
            service_due_date=_safe_date("service_due_date"),
            date_first_registered_nz=_safe_date("date_first_registered_nz"),
            odometer_last_recorded=_safe_int("odometer_last_recorded"),
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


def _split_name(first_name: str, last_name: str | None) -> tuple[str, str]:
    """Split a full name into first/last when last_name is missing.

    If last_name is empty but first_name contains multiple words,
    treat the last word as last_name and everything before as first_name.
    If only one word, use it as first_name and set last_name to empty string.
    """
    last = (last_name or "").strip()
    first = (first_name or "").strip()
    if last:
        return first, last
    parts = first.split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return first, ""


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


# ---------------------------------------------------------------------------
# JSON Bulk Import
# ---------------------------------------------------------------------------

from app.modules.data_io.schemas import (
    BulkCustomerItem,
    BulkVehicleItem,
    BulkImportError,
    BulkImportResponse,
)
from pydantic import ValidationError


async def bulk_import_customers_json(
    db: AsyncSession,
    org_id: uuid.UUID,
    items: list[dict],
) -> BulkImportResponse:
    """Import customers from a JSON array. Validates each item individually."""
    imported = 0
    skipped = 0
    errors: list[BulkImportError] = []

    for idx, raw in enumerate(items):
        try:
            item = BulkCustomerItem(**raw)
        except ValidationError as exc:
            for e in exc.errors():
                field = ".".join(str(loc) for loc in e["loc"]) if e["loc"] else None
                errors.append(BulkImportError(index=idx, field=field, error=e["msg"]))
            skipped += 1
            continue

        first, last = _split_name(item.first_name or "", item.last_name)
        if not first and not last:
            errors.append(BulkImportError(
                index=idx, field="first_name",
                error="At least a name (first_name or last_name) is required",
            ))
            skipped += 1
            continue

        customer = Customer(
            org_id=org_id,
            first_name=first or "",
            last_name=last or "",
            email=item.email or None,
            phone=item.phone or None,
            mobile_phone=item.mobile_phone or None,
            work_phone=item.work_phone or None,
            company_name=item.company_name or None,
            display_name=item.display_name or None,
            customer_type=item.customer_type or "individual",
            salutation=item.salutation or None,
            address=item.address or None,
            billing_address={"line1": item.billing_address} if item.billing_address else {},
            shipping_address={"line1": item.shipping_address} if item.shipping_address else {},
            currency=item.currency or "NZD",
            language=item.language or "en",
            payment_terms=item.payment_terms or "due_on_receipt",
            company_id=item.company_id or None,
            notes=item.notes or None,
            remarks=item.remarks or None,
        )
        db.add(customer)
        imported += 1

    if imported > 0:
        await db.flush()

    return BulkImportResponse(
        imported_count=imported,
        skipped_count=skipped,
        total_submitted=len(items),
        errors=errors,
    )


async def bulk_import_vehicles_json(
    db: AsyncSession,
    org_id: uuid.UUID,
    items: list[dict],
) -> BulkImportResponse:
    """Import vehicles from a JSON array. Validates each item individually."""
    imported = 0
    skipped = 0
    errors: list[BulkImportError] = []

    for idx, raw in enumerate(items):
        try:
            item = BulkVehicleItem(**raw)
        except ValidationError as exc:
            for e in exc.errors():
                field = ".".join(str(loc) for loc in e["loc"]) if e["loc"] else None
                errors.append(BulkImportError(index=idx, field=field, error=e["msg"]))
            skipped += 1
            continue

        def _parse_date(val: str | None):
            from datetime import date as date_type
            if not val:
                return None
            try:
                return date_type.fromisoformat(val)
            except ValueError:
                return None

        vehicle = OrgVehicle(
            org_id=org_id,
            rego=item.rego.upper().strip(),
            make=item.make or None,
            model=item.model or None,
            year=item.year,
            colour=item.colour or None,
            body_type=item.body_type or None,
            fuel_type=item.fuel_type or None,
            engine_size=item.engine_size or None,
            num_seats=item.num_seats,
            vin=item.vin or None,
            chassis=item.chassis or None,
            engine_no=item.engine_no or None,
            transmission=item.transmission or None,
            country_of_origin=item.country_of_origin or None,
            number_of_owners=item.number_of_owners,
            vehicle_type=item.vehicle_type or None,
            power_kw=item.power_kw,
            tare_weight=item.tare_weight,
            gross_vehicle_mass=item.gross_vehicle_mass,
            plate_type=item.plate_type or None,
            submodel=item.submodel or None,
            second_colour=item.second_colour or None,
            wof_expiry=_parse_date(item.wof_expiry),
            registration_expiry=_parse_date(item.registration_expiry),
            service_due_date=_parse_date(item.service_due_date),
            date_first_registered_nz=_parse_date(item.date_first_registered_nz),
            odometer_last_recorded=item.odometer_last_recorded,
            is_manual_entry=True,
        )
        db.add(vehicle)
        imported += 1

    if imported > 0:
        await db.flush()

    return BulkImportResponse(
        imported_count=imported,
        skipped_count=skipped,
        total_submitted=len(items),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Sample JSON templates
# ---------------------------------------------------------------------------

SAMPLE_CUSTOMERS_JSON = [
    {
        "first_name": "John",
        "last_name": "Smith",
        "email": "john.smith@example.com",
        "phone": "09 123 4567",
        "mobile_phone": "021 123 4567",
        "work_phone": None,
        "company_name": None,
        "display_name": None,
        "customer_type": "individual",
        "salutation": "Mr",
        "address": "123 Queen Street, Auckland 1010",
        "billing_address": None,
        "shipping_address": None,
        "currency": "NZD",
        "language": "en",
        "payment_terms": "due_on_receipt",
        "company_id": None,
        "notes": "Preferred contact by email",
        "remarks": None,
    },
    {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@acmecorp.co.nz",
        "phone": "04 987 6543",
        "mobile_phone": "027 987 6543",
        "work_phone": "04 987 6500",
        "company_name": "Acme Corp Ltd",
        "display_name": "Acme Corp - Jane Doe",
        "customer_type": "business",
        "salutation": "Ms",
        "address": "456 Lambton Quay, Wellington 6011",
        "billing_address": "PO Box 123, Wellington 6140",
        "shipping_address": "456 Lambton Quay, Wellington 6011",
        "currency": "NZD",
        "language": "en",
        "payment_terms": "net_30",
        "company_id": "NZBN-1234567890",
        "notes": None,
        "remarks": "Key account",
    },
]

SAMPLE_VEHICLES_JSON = [
    {
        "rego": "ABC123",
        "make": "Toyota",
        "model": "Corolla",
        "submodel": "GX Hatchback",
        "year": 2020,
        "colour": "Silver",
        "second_colour": None,
        "body_type": "Sedan",
        "fuel_type": "Petrol",
        "engine_size": "1.8L",
        "num_seats": 5,
        "vin": "JTDKN3DU5A0123456",
        "chassis": None,
        "engine_no": "2ZR-FE-1234567",
        "transmission": "CVT",
        "country_of_origin": "Japan",
        "number_of_owners": 2,
        "vehicle_type": "Passenger Car/Van",
        "power_kw": 103,
        "tare_weight": 1305,
        "gross_vehicle_mass": 1750,
        "plate_type": "Personalised",
        "wof_expiry": "2026-06-15",
        "registration_expiry": "2026-09-01",
        "service_due_date": "2026-04-01",
        "date_first_registered_nz": "2020-03-10",
        "odometer_last_recorded": 45230,
    },
    {
        "rego": "XYZ789",
        "make": "Ford",
        "model": "Ranger",
        "submodel": "XLT Double Cab",
        "year": 2022,
        "colour": "Blue",
        "second_colour": None,
        "body_type": "Ute",
        "fuel_type": "Diesel",
        "engine_size": "2.0L",
        "num_seats": 5,
        "vin": None,
        "chassis": None,
        "engine_no": None,
        "transmission": "Automatic",
        "country_of_origin": "Thailand",
        "number_of_owners": 1,
        "vehicle_type": "Light Goods Vehicle/Van",
        "power_kw": 157,
        "tare_weight": 2085,
        "gross_vehicle_mass": 3200,
        "plate_type": "Standard",
        "wof_expiry": "2026-12-01",
        "registration_expiry": "2027-01-15",
        "service_due_date": None,
        "date_first_registered_nz": "2022-07-20",
        "odometer_last_recorded": 18500,
    },
]

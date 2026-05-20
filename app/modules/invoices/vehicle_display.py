"""Vehicle display field builder for invoice rendering.

Pure utility that builds the ordered list of vehicle display fields shown on
invoices across all rendering surfaces (PDF, HTML share, email, POS receipt).

This mirrors the TypeScript implementation in
frontend/src/utils/buildVehicleDisplayFields.ts for use in backend template
rendering via WeasyPrint/Jinja2.

Requirements: 1.1, 1.2, 1.3, 2.1–2.7, 3.1–3.4, 7.2–7.5
"""

from __future__ import annotations


def _format_number(n: int) -> str:
    """Format a number with thousands separators (e.g. 125000 → '125,000')."""
    return f"{n:,}"


def _build_vehicle_string(
    make: str | None,
    model: str | None,
    year: int | None,
) -> str | None:
    """Build the vehicle make/model/year combined string.

    Returns None if no components are present.
    """
    parts: list[str] = []
    if year is not None and year > 0:
        parts.append(str(year))
    if make:
        parts.append(make)
    if model:
        parts.append(model)
    return " ".join(parts) if parts else None


def _should_show_expiry(
    updated: bool,
    expiry_date: str | None,
    issue_date: str,
) -> bool:
    """Determine whether an inspection expiry field should be shown.

    Rules:
    - Show when updated flag is true (user changed it during creation)
    - Show when updated flag is false AND expiry date is strictly after issue date
    - Hide when updated flag is false AND expiry date is on or before issue date
    - Hide when expiry date is null/empty
    """
    if not expiry_date:
        return False

    if updated:
        return True

    # Compare dates as strings (ISO format allows lexicographic comparison)
    return expiry_date > issue_date


def _build_fallback_fields(fallback: dict | None) -> list[dict]:
    """Build display fields from fallback data (backward compatibility).

    Shows all available data without conditional logic, matching the behaviour
    of invoices created before the vehicle_display feature was added.
    """
    if not fallback:
        return []

    fields: list[dict] = []

    # Registration
    vehicle_rego = fallback.get("vehicle_rego")
    if vehicle_rego:
        fields.append({"label": "Registration", "value": vehicle_rego, "hint": None})

    # Vehicle (make/model/year)
    vehicle_str = _build_vehicle_string(
        fallback.get("vehicle_make"),
        fallback.get("vehicle_model"),
        fallback.get("vehicle_year"),
    )
    if vehicle_str:
        fields.append({"label": "Vehicle", "value": vehicle_str, "hint": None})

    # Odometer (always shown in fallback mode when available)
    vehicle_odometer = fallback.get("vehicle_odometer")
    if vehicle_odometer is not None and vehicle_odometer > 0:
        fields.append({
            "label": "Odometer",
            "value": f"{_format_number(vehicle_odometer)} km",
            "hint": None,
        })

    # WOF/COF Expiry (from vehicle object, no conditional logic in fallback)
    vehicle = fallback.get("vehicle")
    if vehicle:
        inspection_type = vehicle.get("inspection_type")
        if inspection_type == "cof" and vehicle.get("cof_expiry"):
            fields.append({
                "label": "COF Expiry",
                "value": vehicle["cof_expiry"],
                "hint": None,
            })
        elif vehicle.get("wof_expiry"):
            fields.append({
                "label": "WOF Expiry",
                "value": vehicle["wof_expiry"],
                "hint": None,
            })

    return fields


def build_vehicle_display_fields(
    vehicle_display: dict | None,
    issue_date: str,
    fallback: dict | None = None,
) -> list[dict]:
    """Build the ordered array of vehicle display fields for an invoice.

    Args:
        vehicle_display: The vehicle display data stored in invoice_data_json,
            or None for old invoices.
        issue_date: The invoice issue date (ISO string) used for future/past
            comparison.
        fallback: Fallback fields from invoice columns for backward
            compatibility.

    Returns:
        Ordered list of dicts with keys: label (str), value (str), hint (str | None).
        Empty fields are omitted.
    """
    # Backward compatibility: when vehicle_display is None, use fallback fields
    # and show all available data without conditional logic
    if vehicle_display is None:
        return _build_fallback_fields(fallback)

    fields: list[dict] = []

    # 1. Registration
    rego = vehicle_display.get("rego")
    if rego:
        fields.append({"label": "Registration", "value": rego, "hint": None})

    # 2. Vehicle (make/model/year combined)
    vehicle_str = _build_vehicle_string(
        vehicle_display.get("make"),
        vehicle_display.get("model"),
        vehicle_display.get("year"),
    )
    if vehicle_str:
        fields.append({"label": "Vehicle", "value": vehicle_str, "hint": None})

    # 3. Odometer (always shown when available)
    service_due_updated = vehicle_display.get("service_due_updated", False)
    odometer = vehicle_display.get("odometer")

    if odometer is not None and odometer > 0:
        fields.append({
            "label": "Odometer",
            "value": f"{_format_number(odometer)} km",
            "hint": None,
        })

    # 3b. Service Due Date (shown additionally when service_due_updated is true)
    if service_due_updated:
        service_due_date = vehicle_display.get("service_due_date")
        if service_due_date:
            hint: str | None = None
            # Add hint when odometer is a positive value
            if odometer is not None and odometer > 0:
                hint = f"or due at {_format_number(odometer + 10000)} km"
            fields.append({
                "label": "Service Due",
                "value": service_due_date,
                "hint": hint,
            })

    # 4. WOF/COF Expiry (conditional on flags + date comparison)
    inspection_type = vehicle_display.get("inspection_type")

    if inspection_type == "cof":
        # COF logic
        cof_updated = vehicle_display.get("cof_updated", False)
        cof_expiry = vehicle_display.get("cof_expiry")
        if _should_show_expiry(cof_updated, cof_expiry, issue_date):
            fields.append({
                "label": "COF Expiry",
                "value": cof_expiry,
                "hint": None,
            })
    else:
        # WOF logic (default when inspection_type is 'wof' or None)
        wof_updated = vehicle_display.get("wof_updated", False)
        wof_expiry = vehicle_display.get("wof_expiry")
        if _should_show_expiry(wof_updated, wof_expiry, issue_date):
            fields.append({
                "label": "WOF Expiry",
                "value": wof_expiry,
                "hint": None,
            })

    return fields

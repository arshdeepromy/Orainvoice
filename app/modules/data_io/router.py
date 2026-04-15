"""Data Import router — CSV import endpoints for customers and vehicles.

Requirements: 69.1, 69.2, 69.3, 69.5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.data_io.schemas import (
    FieldMapping,
    ImportCommitResponse,
    ImportPreviewResponse,
)
from app.modules.data_io.service import (
    auto_detect_mapping,
    commit_customer_import,
    commit_vehicle_import,
    generate_error_report_csv,
    parse_csv,
    validate_import,
)

router = APIRouter()


def _extract_org_id(request: Request) -> uuid.UUID | None:
    """Extract org_id from request state."""
    org_id = getattr(request.state, "org_id", None)
    try:
        return uuid.UUID(org_id) if org_id else None
    except (ValueError, TypeError):
        return None


def _parse_field_mapping(field_mapping_json: str | None) -> list[FieldMapping] | None:
    """Parse optional field mapping JSON string from form data.

    Accepts two formats:
    - Array of objects: [{"csv_column": "Name", "target_field": "first_name"}, ...]
    - Flat object: {"Name": "first_name", "Email": "email", ...}
    """
    if not field_mapping_json:
        return None
    import json
    try:
        raw = json.loads(field_mapping_json)
        if isinstance(raw, list):
            return [FieldMapping(**item) for item in raw]
        if isinstance(raw, dict):
            return [
                FieldMapping(csv_column=csv_col, target_field=target)
                for csv_col, target in raw.items()
                if target  # skip empty/null mappings
            ]
        return None
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Customer import endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/import/customers",
    response_model=ImportPreviewResponse,
    responses={
        400: {"description": "Invalid CSV file"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Preview customer CSV import",
    description="Upload a CSV file to preview customer records before importing. "
    "Returns valid rows and error rows with validation details.",
    dependencies=[require_role("org_admin")],
)
async def preview_customer_import(
    request: Request,
    file: UploadFile = File(..., description="CSV file to import"),
    field_mapping: str | None = Form(
        None, description="JSON array of {csv_column, target_field} mappings"
    ),
    db: AsyncSession = Depends(get_db_session),
) -> ImportPreviewResponse:
    """Parse and validate a customer CSV, returning a preview.

    Requirements: 69.1, 69.3
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"detail": "File must be UTF-8 encoded CSV"})

    headers, rows = parse_csv(csv_text)
    if not headers:
        return JSONResponse(status_code=400, content={"detail": "CSV file is empty or has no headers"})

    mapping = _parse_field_mapping(field_mapping)
    if not mapping:
        mapping = auto_detect_mapping(headers, "customers")

    if not mapping:
        return JSONResponse(
            status_code=400,
            content={"detail": "Could not map any CSV columns to customer fields. "
                     "Please provide explicit field_mapping."},
        )

    return validate_import(headers, rows, mapping, "customers")


@router.post(
    "/import/customers/commit",
    response_model=ImportCommitResponse,
    responses={
        400: {"description": "Invalid CSV or mapping"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Commit customer CSV import",
    description="Re-upload the CSV and commit valid rows. Invalid rows are skipped.",
    dependencies=[require_role("org_admin")],
)
async def commit_customer_import_endpoint(
    request: Request,
    file: UploadFile = File(..., description="CSV file to import"),
    field_mapping: str = Form(
        ..., description="JSON array of {csv_column, target_field} mappings"
    ),
    db: AsyncSession = Depends(get_db_session),
) -> ImportCommitResponse:
    """Commit a customer CSV import after preview.

    Requirements: 69.1, 69.5
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"detail": "File must be UTF-8 encoded CSV"})

    headers, rows = parse_csv(csv_text)
    mapping = _parse_field_mapping(field_mapping)
    if not mapping:
        return JSONResponse(status_code=400, content={"detail": "field_mapping is required for commit"})

    return await commit_customer_import(db, org_id, rows, mapping)


# ---------------------------------------------------------------------------
# Vehicle import endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/import/vehicles",
    response_model=ImportPreviewResponse,
    responses={
        400: {"description": "Invalid CSV file"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Preview vehicle CSV import",
    description="Upload a CSV file to preview vehicle records before importing.",
    dependencies=[require_role("org_admin")],
)
async def preview_vehicle_import(
    request: Request,
    file: UploadFile = File(..., description="CSV file to import"),
    field_mapping: str | None = Form(
        None, description="JSON array of {csv_column, target_field} mappings"
    ),
    db: AsyncSession = Depends(get_db_session),
) -> ImportPreviewResponse:
    """Parse and validate a vehicle CSV, returning a preview.

    Requirements: 69.2, 69.3
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"detail": "File must be UTF-8 encoded CSV"})

    headers, rows = parse_csv(csv_text)
    if not headers:
        return JSONResponse(status_code=400, content={"detail": "CSV file is empty or has no headers"})

    mapping = _parse_field_mapping(field_mapping)
    if not mapping:
        mapping = auto_detect_mapping(headers, "vehicles")

    if not mapping:
        return JSONResponse(
            status_code=400,
            content={"detail": "Could not map any CSV columns to vehicle fields. "
                     "Please provide explicit field_mapping."},
        )

    return validate_import(headers, rows, mapping, "vehicles")


@router.post(
    "/import/vehicles/commit",
    response_model=ImportCommitResponse,
    responses={
        400: {"description": "Invalid CSV or mapping"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Commit vehicle CSV import",
    description="Re-upload the CSV and commit valid rows. Invalid rows are skipped.",
    dependencies=[require_role("org_admin")],
)
async def commit_vehicle_import_endpoint(
    request: Request,
    file: UploadFile = File(..., description="CSV file to import"),
    field_mapping: str = Form(
        ..., description="JSON array of {csv_column, target_field} mappings"
    ),
    db: AsyncSession = Depends(get_db_session),
) -> ImportCommitResponse:
    """Commit a vehicle CSV import after preview.

    Requirements: 69.2, 69.5
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"detail": "File must be UTF-8 encoded CSV"})

    headers, rows = parse_csv(csv_text)
    mapping = _parse_field_mapping(field_mapping)
    if not mapping:
        return JSONResponse(status_code=400, content={"detail": "field_mapping is required for commit"})

    return await commit_vehicle_import(db, org_id, rows, mapping)


# ---------------------------------------------------------------------------
# Error report download
# ---------------------------------------------------------------------------


@router.post(
    "/import/error-report",
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV error report"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Download import error report as CSV",
    dependencies=[require_role("org_admin")],
)
async def download_error_report(
    request: Request,
    file: UploadFile = File(..., description="CSV file that was imported"),
    field_mapping: str = Form(
        ..., description="JSON array of {csv_column, target_field} mappings"
    ),
    entity_type: str = Form(
        ..., description="Entity type: 'customers' or 'vehicles'"
    ),
) -> StreamingResponse:
    """Re-validate the CSV and return a downloadable CSV error report.

    Requirements: 69.5
    """
    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    if entity_type not in ("customers", "vehicles"):
        return JSONResponse(status_code=400, content={"detail": "entity_type must be 'customers' or 'vehicles'"})

    content = await file.read()
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"detail": "File must be UTF-8 encoded CSV"})

    headers, rows = parse_csv(csv_text)
    mapping = _parse_field_mapping(field_mapping)
    if not mapping:
        return JSONResponse(status_code=400, content={"detail": "field_mapping is required"})

    preview = validate_import(headers, rows, mapping, entity_type)
    csv_report = generate_error_report_csv(preview.error_rows)

    import io
    return StreamingResponse(
        io.StringIO(csv_report),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=import_errors_{entity_type}.csv"},
    )


# ---------------------------------------------------------------------------
# CSV Export endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/export/customers",
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV export of customers"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Export customers as CSV",
    description="Export all customer records for the organisation as a CSV file.",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def export_customers(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Export all customers as CSV.

    Requirements: 69.4
    """
    from app.modules.data_io.service import export_customers_csv

    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    csv_content = await export_customers_csv(db, org_id)

    # Audit log (REM-06)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="data_io.customers_exported",
        entity_type="export",
        entity_id=None,
        after_value={"format": "csv", "ip_address": ip_address},
        ip_address=ip_address,
    )
    await db.commit()

    import io as _io
    return StreamingResponse(
        _io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=customers_export.csv"},
    )


@router.get(
    "/export/vehicles",
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV export of vehicles"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Export vehicles as CSV",
    description="Export all vehicles linked to the organisation as a CSV file.",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def export_vehicles(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Export all vehicles as CSV.

    Requirements: 69.4
    """
    from app.modules.data_io.service import export_vehicles_csv

    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    csv_content = await export_vehicles_csv(db, org_id)

    # Audit log (REM-06)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="data_io.vehicles_exported",
        entity_type="export",
        entity_id=None,
        after_value={"format": "csv", "ip_address": ip_address},
        ip_address=ip_address,
    )
    await db.commit()

    import io as _io
    return StreamingResponse(
        _io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vehicles_export.csv"},
    )


@router.get(
    "/export/invoices",
    responses={
        200: {"content": {"text/csv": {}}, "description": "CSV export of invoices"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Export invoices as CSV",
    description="Export invoices for the organisation as a CSV file, with optional date filtering.",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def export_invoices(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Export invoices as CSV with optional date range filter.

    Requirements: 69.4
    """
    from app.modules.data_io.service import export_invoices_csv

    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    csv_content = await export_invoices_csv(db, org_id, date_from, date_to)

    # Audit log (REM-06)
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="data_io.invoices_exported",
        entity_type="export",
        entity_id=None,
        after_value={"format": "csv", "ip_address": ip_address},
        ip_address=ip_address,
    )
    await db.commit()

    import io as _io
    return StreamingResponse(
        _io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices_export.csv"},
    )

# ---------------------------------------------------------------------------
# JSON Bulk Import endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/import/json/customers",
    response_model=None,
    responses={
        200: {"description": "Import results"},
        400: {"description": "Invalid JSON"},
        403: {"description": "Org Admin role required"},
    },
    summary="Bulk import customers from JSON",
    description="Upload a JSON array of customer objects to import in bulk. "
    "Each item is validated independently — valid items are imported, invalid ones are skipped.",
    dependencies=[require_role("org_admin")],
)
async def bulk_import_customers_json_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Bulk import customers from a JSON array."""
    from app.modules.data_io.service import bulk_import_customers_json
    from app.modules.data_io.schemas import BulkImportResponse

    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

    if not isinstance(body, list):
        return JSONResponse(status_code=400, content={
            "detail": "Request body must be a JSON array of customer objects"
        })

    if len(body) > 1000:
        return JSONResponse(status_code=400, content={
            "detail": "Maximum 1000 records per import"
        })

    result: BulkImportResponse = await bulk_import_customers_json(db, org_id, body)

    # Audit log
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="data_io.customers_json_imported",
        entity_type="import",
        entity_id=None,
        after_value={
            "format": "json",
            "total": result.total_submitted,
            "imported": result.imported_count,
            "skipped": result.skipped_count,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return result


@router.post(
    "/import/json/vehicles",
    response_model=None,
    responses={
        200: {"description": "Import results"},
        400: {"description": "Invalid JSON"},
        403: {"description": "Org Admin role required"},
    },
    summary="Bulk import vehicles from JSON",
    description="Upload a JSON array of vehicle objects to import in bulk. "
    "Each item is validated independently — valid items are imported, invalid ones are skipped.",
    dependencies=[require_role("org_admin")],
)
async def bulk_import_vehicles_json_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Bulk import vehicles from a JSON array."""
    from app.modules.data_io.service import bulk_import_vehicles_json
    from app.modules.data_io.schemas import BulkImportResponse

    org_id = _extract_org_id(request)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

    if not isinstance(body, list):
        return JSONResponse(status_code=400, content={
            "detail": "Request body must be a JSON array of vehicle objects"
        })

    if len(body) > 1000:
        return JSONResponse(status_code=400, content={
            "detail": "Maximum 1000 records per import"
        })

    result: BulkImportResponse = await bulk_import_vehicles_json(db, org_id, body)

    # Audit log
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="data_io.vehicles_json_imported",
        entity_type="import",
        entity_id=None,
        after_value={
            "format": "json",
            "total": result.total_submitted,
            "imported": result.imported_count,
            "skipped": result.skipped_count,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return result


# ---------------------------------------------------------------------------
# Sample JSON download endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/import/json/sample/customers",
    summary="Download sample customer JSON template",
    description="Returns a sample JSON array showing the expected format for bulk customer import.",
)
async def download_sample_customers_json():
    """Return sample customer JSON for users to use as a template."""
    from app.modules.data_io.service import SAMPLE_CUSTOMERS_JSON
    return JSONResponse(content=SAMPLE_CUSTOMERS_JSON)


@router.get(
    "/import/json/sample/vehicles",
    summary="Download sample vehicle JSON template",
    description="Returns a sample JSON array showing the expected format for bulk vehicle import.",
)
async def download_sample_vehicles_json():
    """Return sample vehicle JSON for users to use as a template."""
    from app.modules.data_io.service import SAMPLE_VEHICLES_JSON
    return JSONResponse(content=SAMPLE_VEHICLES_JSON)

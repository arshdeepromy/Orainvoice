"""Invoice router — creation endpoint.

Requirements: 17.1, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.invoices.schemas import (
    AddLineItemRequest,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkExportRequest,
    BulkExportResponse,
    CreditNoteCreateRequest,
    CreditNoteCreateResponse,
    CreditNoteListResponse,
    CreditNoteResponse,
    DuplicateInvoiceResponse,
    GetInvoiceResponse,
    InvoiceCreateRequest,
    InvoiceCreateResponse,
    InvoiceEmailRequest,
    InvoiceEmailResponse,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceSearchResult,
    IssueInvoiceResponse,
    LineItemModifyResponse,
    LineItemResponse,
    UpdateInvoiceRequest,
    UpdateInvoiceResponse,
    UpdateNotesRequest,
    UpdateNotesResponse,
    VoidInvoiceRequest,
    VoidInvoiceResponse,
)
from app.modules.invoices.service import (
    add_line_item,
    bulk_delete_invoices,
    bulk_export_invoices,
    create_credit_note,
    create_invoice,
    delete_line_item,
    duplicate_invoice,
    get_credit_notes_for_invoice,
    get_invoice,
    invoices_to_csv,
    issue_invoice,
    search_invoices,
    update_invoice,
    update_invoice_notes,
    void_invoice,
)

router = APIRouter()


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


@router.post(
    "",
    response_model=InvoiceCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a new invoice (draft or issued)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_invoice_endpoint(
    payload: InvoiceCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new invoice with customer, vehicle, and line items.

    Supports saving as Draft (no invoice number, fully editable) or
    issuing (assigns sequential number with org prefix, locks structural edits).

    Auto-calculates subtotal (ex-GST), GST amount, and GST-inclusive total.

    Requirements: 17.1, 17.3, 17.4, 17.5, 17.6
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Convert line items to dicts for the service layer
    line_items_data = [
        {
            "item_type": li.item_type.value,
            "description": li.description,
            "catalogue_item_id": li.catalogue_item_id,
            "stock_item_id": li.stock_item_id,
            "part_number": li.part_number,
            "quantity": li.quantity,
            "unit_price": li.get_unit_price(),  # Use helper to get unit_price or rate
            "hours": li.hours,
            "hourly_rate": li.hourly_rate,
            "discount_type": li.discount_type,
            "discount_value": li.discount_value,
            "is_gst_exempt": li.is_gst_exempt,
            "gst_inclusive": li.gst_inclusive,
            "inclusive_price": li.inclusive_price,
            "warranty_note": li.warranty_note,
            "sort_order": li.sort_order,
        }
        for li in payload.line_items
    ]

    # "sent" means create as issued then auto-email the PDF
    should_email = payload.status.value == "sent"
    effective_status = "issued" if should_email else payload.status.value

    try:
        result = await create_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            customer_id=payload.customer_id,
            vehicle_rego=payload.vehicle_rego,
            vehicle_make=payload.vehicle_make,
            vehicle_model=payload.vehicle_model,
            vehicle_year=payload.vehicle_year,
            vehicle_odometer=payload.vehicle_odometer,
            global_vehicle_id=payload.global_vehicle_id,
            vehicle_service_due_date=payload.vehicle_service_due_date,
            vehicle_wof_expiry_date=payload.vehicle_wof_expiry_date,
            vehicles=[v.model_dump() for v in payload.vehicles] if payload.vehicles else None,
            branch_id=payload.branch_id,
            status=effective_status,
            line_items_data=line_items_data,
            fluid_usage_data=[fu.model_dump() for fu in payload.fluid_usage] if payload.fluid_usage else None,
            notes_internal=payload.notes_internal,
            notes_customer=payload.notes_customer,
            due_date=payload.due_date,
            issue_date=payload.issue_date,
            payment_terms=payload.payment_terms,
            discount_type=payload.discount_type,
            discount_value=payload.discount_value,
            currency=payload.currency,
            exchange_rate_to_nzd=payload.exchange_rate_to_nzd,
            terms_and_conditions=payload.terms_and_conditions,
            payment_gateway=payload.payment_gateway,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Prepare Xero sync data BEFORE committing (session is still open)
    _xero_data = None
    if payload.status.value != "draft" and org_uuid:
        from app.modules.customers.models import Customer as _Customer
        _cust_result = await db.execute(
            select(_Customer.display_name, _Customer.first_name, _Customer.last_name).where(
                _Customer.id == result.get("customer_id")
            )
        )
        _cust_row = _cust_result.first()
        _cust_name = "Unknown"
        if _cust_row:
            _cust_name = _cust_row.display_name or f"{_cust_row.first_name or ''} {_cust_row.last_name or ''}".strip() or "Unknown"
        _xero_data = {
            "id": str(result.get("id", "")),
            "invoice_number": result.get("invoice_number", ""),
            "customer_name": _cust_name,
            "date": result.get("issue_date"),
            "due_date": result.get("due_date"),
            "currency": result.get("currency", "NZD"),
            "gst_inclusive": True,
            "line_items": [
                {
                    "description": li.get("description", ""),
                    "quantity": float(li.get("quantity", 1)),
                    "unit_price": float(li.get("unit_price", 0)),
                    "account_code": "200",
                }
                for li in (result.get("line_items") or [])
            ],
        }

    # Commit so the invoice exists before emailing
    await db.commit()

    # Auto-email the invoice PDF when status was "sent" — fire-and-forget
    email_status = None
    if should_email:
        import asyncio as _asyncio
        _origin = request.headers.get("origin") or None
        async def _send_email_bg():
            try:
                from app.core.database import async_session_factory, _set_rls_org_id
                from app.modules.invoices.service import email_invoice
                invoice_uuid = result["id"] if isinstance(result["id"], uuid.UUID) else uuid.UUID(str(result["id"]))
                async with async_session_factory() as email_db:
                    async with email_db.begin():
                        await _set_rls_org_id(email_db, str(org_uuid))
                        await email_invoice(email_db, org_id=org_uuid, invoice_id=invoice_uuid, base_url=_origin)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception("Auto-email failed for invoice %s: %s", result.get("id"), exc)
        _asyncio.create_task(_send_email_bg())
        email_status = "queued"

    invoice_resp = InvoiceResponse(
        **{
            k: v
            for k, v in result.items()
            if k != "line_items"
        },
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    if should_email:
        status_label = "Invoice issued and emailed" if email_status != "email_failed" else "Invoice issued (email failed)"
    elif payload.status.value == "draft":
        status_label = "Draft saved"
    else:
        status_label = "Invoice issued"

    # Fire-and-forget: sync invoice to Xero if connected (non-draft only)
    if _xero_data and org_uuid:
        import asyncio as _asyncio_sync
        from app.modules.accounting.auto_sync import sync_invoice_bg
        _asyncio_sync.create_task(sync_invoice_bg(org_uuid, _xero_data))

    return InvoiceCreateResponse(
        invoice=invoice_resp,
        message=f"{status_label} successfully",
    )


# ---------------------------------------------------------------------------
# Invoice search and filtering (Task 10.6)
# Requirements: 21.1, 21.2, 21.3, 21.4
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=InvoiceListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Search and filter invoices",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_invoices_endpoint(
    request: Request,
    search: str | None = Query(default=None, description="Text search across invoice number, rego, customer name/phone/email"),
    status: str | None = Query(default=None, description="Filter by invoice status"),
    issue_date_from: date | None = Query(default=None, description="Filter invoices issued on or after this date"),
    issue_date_to: date | None = Query(default=None, description="Filter invoices issued on or before this date"),
    limit: int = Query(default=25, ge=1, le=100, description="Max results per page"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    db: AsyncSession = Depends(get_db_session),
):
    """Search and filter invoices with pagination.

    Supports text search across invoice number, vehicle rego, and customer
    name/phone/email. Filters are stackable — combine search, status, and
    date range as needed.

    Requirements: 21.1, 21.2, 21.3, 21.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await search_invoices(
        db,
        org_id=org_uuid,
        search=search,
        status=status,
        issue_date_from=issue_date_from,
        issue_date_to=issue_date_to,
        limit=limit,
        offset=offset,
        branch_id=getattr(request.state, "branch_id", None),
    )

    return InvoiceListResponse(
        invoices=[InvoiceSearchResult(**inv) for inv in result["invoices"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@router.post(
    "/{invoice_id}/line-items",
    response_model=LineItemModifyResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error or non-draft invoice"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Add a line item to a draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def add_line_item_endpoint(
    invoice_id: uuid.UUID,
    payload: AddLineItemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Add a line item to an existing draft invoice.

    Supports service (catalogue pre-fill), part, and labour types.
    Recalculates invoice totals after adding.

    Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    item_data = {
        "item_type": payload.item_type.value,
        "description": payload.description,
        "catalogue_item_id": payload.catalogue_item_id,
        "labour_rate_id": payload.labour_rate_id,
        "part_number": payload.part_number,
        "quantity": payload.quantity,
        "unit_price": payload.unit_price,
        "hours": payload.hours,
        "hourly_rate": payload.hourly_rate,
        "discount_type": payload.discount_type,
        "discount_value": payload.discount_value,
        "is_gst_exempt": payload.is_gst_exempt,
        "warranty_note": payload.warranty_note,
        "sort_order": payload.sort_order,
    }

    try:
        result = await add_line_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            item_data=item_data,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    return LineItemModifyResponse(
        invoice=invoice_resp,
        message="Line item added successfully",
    )


@router.delete(
    "/{invoice_id}/line-items/{line_item_id}",
    response_model=LineItemModifyResponse,
    responses={
        400: {"description": "Validation error or non-draft invoice"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Remove a line item from a draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def delete_line_item_endpoint(
    invoice_id: uuid.UUID,
    line_item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a line item from a draft invoice and recalculate totals.

    Requirements: 18.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await delete_line_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            line_item_id=line_item_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    return LineItemModifyResponse(
        invoice=invoice_resp,
        message="Line item removed successfully",
    )


# ---------------------------------------------------------------------------
# Template endpoints — MUST be before /{invoice_id} to avoid path conflicts
# Requirements: 1.1, 1.2, 6.1, 6.2, 6.5, 6.6
# ---------------------------------------------------------------------------

from typing import Optional

from pydantic import BaseModel, Field


class TemplatePreviewRequest(BaseModel):
    template_id: str = Field(..., description="Template ID from the registry")
    primary_colour: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_colour: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    header_bg_colour: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


@router.get(
    "/invoice-templates",
    summary="List available invoice PDF templates",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_invoice_templates():
    """Return the catalogue of available invoice templates.

    Requirements: 1.1, 1.2
    """
    from app.modules.invoices.template_registry import list_templates

    return {"templates": list_templates()}


@router.post(
    "/invoice-templates/preview",
    summary="Preview an invoice template with sample data",
    dependencies=[require_role("org_admin")],
)
async def preview_invoice_template(
    payload: TemplatePreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Render a sample invoice using the specified template and colour overrides.

    Returns HTML string for iframe rendering in the frontend.

    Requirements: 6.1, 6.2, 6.5, 6.6
    """
    from app.modules.invoices.template_registry import get_template_metadata
    from app.modules.invoices.template_preview import render_template_preview

    meta = get_template_metadata(payload.template_id)
    if meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{payload.template_id}' not found",
        )

    org_id = getattr(request.state, "org_id", None)
    org_uuid = uuid.UUID(org_id) if org_id else None

    html = await render_template_preview(
        db,
        org_id=org_uuid,
        template_meta=meta,
        colour_overrides={
            "primary_colour": payload.primary_colour,
            "accent_colour": payload.accent_colour,
            "header_bg_colour": payload.header_bg_colour,
        },
    )
    return {"html": html}


# ---------------------------------------------------------------------------
# Invoice lifecycle endpoints (Task 10.3)
# Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_id}",
    response_model=GetInvoiceResponse,
    responses={
        400: {"description": "Invoice not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get invoice details",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_invoice_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single invoice by ID.

    Requirements: 19.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_invoice(db, org_id=org_uuid, invoice_id=invoice_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Separate nested objects from flat invoice fields
    customer_data = result.pop("customer", None)
    payments_data = result.pop("payments", [])
    credit_notes_data = result.pop("credit_notes", [])
    line_items_data = result.pop("line_items", [])

    invoice_resp = InvoiceResponse(
        **result,
        customer=customer_data,
        line_items=[LineItemResponse(**li) for li in line_items_data],
        payments=payments_data,
        credit_notes=credit_notes_data,
    )

    return GetInvoiceResponse(invoice=invoice_resp)


@router.put(
    "/{invoice_id}",
    response_model=UpdateInvoiceResponse,
    responses={
        400: {"description": "Validation error, immutable field, or non-draft invoice"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Update a draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_invoice_endpoint(
    invoice_id: uuid.UUID,
    payload: UpdateInvoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a draft invoice's editable fields.

    Invoice numbers are system-assigned and immutable once set.
    Only draft invoices allow structural edits.
    If status is 'sent', the invoice is issued and emailed automatically.

    Requirements: 23.2, 23.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    should_email = payload.status and payload.status.value == "sent"
    updates = payload.model_dump(exclude_unset=True)
    # Don't pass 'sent' status to the service — it only knows draft/issued
    updates.pop("status", None)

    try:
        result = await update_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            updates=updates,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Failed to update invoice %s: %s", invoice_id, exc)
        await db.rollback()
        return JSONResponse(status_code=500, content={"detail": f"Failed to update invoice: {exc}"})

    # If "sent", issue the invoice then email it
    if should_email:
        try:
            result = await issue_invoice(
                db,
                org_id=org_uuid,
                user_id=user_uuid,
                invoice_id=invoice_id,
                ip_address=ip_address,
            )
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})

        await db.commit()

        # Send email in background (fire-and-forget)
        import asyncio as _asyncio
        _origin2 = request.headers.get("origin") or None
        async def _send_update_email():
            try:
                from app.core.database import async_session_factory, _set_rls_org_id
                from app.modules.invoices.service import email_invoice
                async with async_session_factory() as email_db:
                    async with email_db.begin():
                        await _set_rls_org_id(email_db, str(org_uuid))
                        await email_invoice(email_db, org_id=org_uuid, invoice_id=invoice_id, base_url=_origin2)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception("Auto-email failed for invoice %s: %s", invoice_id, exc)
        _asyncio.create_task(_send_update_email())

    _exclude = {"line_items", "tax_compliance", "line_item_tax_details"}
    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k not in _exclude},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    msg = "Invoice issued and emailed successfully" if should_email else "Invoice updated successfully"
    return UpdateInvoiceResponse(
        invoice=invoice_resp,
        message=msg,
    )


@router.put(
    "/{invoice_id}/issue",
    response_model=IssueInvoiceResponse,
    responses={
        400: {"description": "Invalid transition or invoice not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Issue a draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def issue_invoice_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Transition a draft invoice to issued status.

    Assigns a sequential invoice number with the org prefix and locks
    structural edits (line items, pricing). Notes remain editable.

    Requirements: 19.2, 19.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await issue_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    _exclude = {"line_items", "tax_compliance", "line_item_tax_details"}
    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k not in _exclude},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    # Fire-and-forget: sync issued invoice to Xero
    if org_uuid:
        try:
            import asyncio as _asyncio_issue
            from app.modules.accounting.auto_sync import sync_invoice_bg
            from app.modules.customers.models import Customer as _Cust
            _cr = await db.execute(
                select(_Cust.display_name, _Cust.first_name, _Cust.last_name).where(
                    _Cust.id == result.get("customer_id")
                )
            )
            _row = _cr.first()
            _name = "Unknown"
            if _row:
                _name = _row.display_name or f"{_row.first_name or ''} {_row.last_name or ''}".strip() or "Unknown"
            _xd = {
                "id": str(result.get("id", "")),
                "invoice_number": result.get("invoice_number", ""),
                "customer_name": _name,
                "date": result.get("issue_date"),
                "due_date": result.get("due_date"),
                "currency": result.get("currency", "NZD"),
                "gst_inclusive": True,
                "line_items": [
                    {"description": li.get("description", ""), "quantity": float(li.get("quantity", 1)),
                     "unit_price": float(li.get("unit_price", 0)), "account_code": "200"}
                    for li in (result.get("line_items") or [])
                ],
            }
            _asyncio_issue.create_task(sync_invoice_bg(org_uuid, _xd))
        except Exception:
            pass

    return IssueInvoiceResponse(
        invoice=invoice_resp,
        message="Invoice issued successfully",
    )


@router.put(
    "/{invoice_id}/void",
    response_model=VoidInvoiceResponse,
    responses={
        400: {"description": "Invalid transition, missing reason, or invoice not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Void an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def void_invoice_endpoint(
    invoice_id: uuid.UUID,
    payload: VoidInvoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Void any non-voided invoice.

    Requires a reason which is recorded in the audit log.
    The invoice number is retained in sequence.
    Voided invoices are excluded from revenue reporting.

    Requirements: 19.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await void_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            reason=payload.reason,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    return VoidInvoiceResponse(
        invoice=invoice_resp,
        message="Invoice voided successfully",
    )


@router.put(
    "/{invoice_id}/notes",
    response_model=UpdateNotesResponse,
    responses={
        400: {"description": "Invoice not found or voided"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Update notes on an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_notes_endpoint(
    invoice_id: uuid.UUID,
    payload: UpdateNotesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update internal or customer-facing notes on an invoice.

    Notes are the only field editable after issuing.

    Requirements: 19.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await update_invoice_notes(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            notes_internal=payload.notes_internal,
            notes_customer=payload.notes_customer,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    return UpdateNotesResponse(
        invoice=invoice_resp,
        message="Notes updated successfully",
    )


# ---------------------------------------------------------------------------
# Invoice duplication endpoint (Task 10.7)
# Requirements: 22.1, 22.2
# ---------------------------------------------------------------------------


@router.post(
    "/{invoice_id}/duplicate",
    response_model=DuplicateInvoiceResponse,
    status_code=201,
    responses={
        400: {"description": "Invoice not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Duplicate an invoice as a new draft",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def duplicate_invoice_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Duplicate an existing invoice as a new Draft.

    Creates a new draft pre-filled with the same customer, vehicle, and
    line items. No invoice number is assigned until the draft is issued.

    Requirements: 22.1, 22.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await duplicate_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    invoice_resp = InvoiceResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[LineItemResponse(**li) for li in result["line_items"]],
    )

    return DuplicateInvoiceResponse(
        invoice=invoice_resp,
        message="Invoice duplicated as new draft",
    )


# ---------------------------------------------------------------------------
# Credit note endpoints (Task 10.5)
# Requirements: 20.1, 20.2, 20.3, 20.4
# ---------------------------------------------------------------------------


@router.post(
    "/{invoice_id}/credit-note",
    response_model=CreditNoteCreateResponse,
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_credit_note_endpoint(
    invoice_id: uuid.UUID,
    payload: CreditNoteCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a credit note against an invoice.

    The credit note is a separate document linked to the original invoice
    with its own CN-prefixed reference number. It records what is being
    credited and the reason, updates the net balance on the original
    invoice, and prompts for Stripe refund when applicable.

    Requirements: 20.1, 20.2, 20.3, 20.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    items_dicts = [
        {"description": item.description, "amount": str(item.amount)}
        for item in payload.items
    ]

    try:
        result = await create_credit_note(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            amount=payload.amount,
            reason=payload.reason,
            items=items_dicts,
            process_stripe_refund=payload.process_stripe_refund,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    cn_resp = CreditNoteResponse(**result["credit_note"])
    invoice_data = result["invoice"]
    invoice_resp = InvoiceResponse(
        **{k: v for k, v in invoice_data.items() if k != "line_items"},
        line_items=[LineItemResponse(**li) for li in invoice_data["line_items"]],
    )

    message = "Credit note created successfully"
    if result["stripe_refund_prompted"]:
        message += ". Stripe refund available — process via payment module."

    # Fire-and-forget: sync credit note to Xero if connected
    if org_uuid:
        try:
            import asyncio as _asyncio_cn
            from app.modules.accounting.auto_sync import sync_credit_note_bg
            from app.modules.customers.models import Customer as _CustCN
            cn_data = result["credit_note"]
            # Resolve customer name from invoice's customer_id (same pattern as issue_invoice_endpoint)
            _cn_cust_name = "Unknown"
            try:
                _cn_cust_result = await db.execute(
                    select(_CustCN.display_name, _CustCN.first_name, _CustCN.last_name).where(
                        _CustCN.id == invoice_data.get("customer_id")
                    )
                )
                _cn_cust_row = _cn_cust_result.first()
                if _cn_cust_row:
                    _cn_cust_name = _cn_cust_row.display_name or f"{_cn_cust_row.first_name or ''} {_cn_cust_row.last_name or ''}".strip() or "Unknown"
            except Exception:
                pass  # Fall back to "Unknown"
            _xero_cn = {
                "id": str(cn_data.get("id", "")),
                "credit_note_number": cn_data.get("credit_note_number", ""),
                "customer_name": _cn_cust_name,
                "date": cn_data.get("created_at"),
                "currency": "NZD",
                "gst_inclusive": True,
                "line_items": [
                    {
                        "description": cn_data.get("reason", "Credit note"),
                        "quantity": 1,
                        "unit_price": float(cn_data.get("amount", 0)),
                        "account_code": "200",
                    }
                ],
            }
            _asyncio_cn.create_task(sync_credit_note_bg(org_uuid, _xero_cn))
        except Exception:
            pass  # Non-blocking — credit note was already created

    return CreditNoteCreateResponse(
        credit_note=cn_resp,
        invoice=invoice_resp,
        stripe_refund_prompted=result["stripe_refund_prompted"],
        message=message,
    )


@router.get(
    "/{invoice_id}/credit-notes",
    response_model=CreditNoteListResponse,
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_credit_notes_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all credit notes for an invoice.

    Requirements: 20.1, 20.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_credit_notes_for_invoice(
            db,
            org_id=org_uuid,
            invoice_id=invoice_id,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return CreditNoteListResponse(
        credit_notes=[CreditNoteResponse(**cn) for cn in result["credit_notes"]],
        total_credited=result["total_credited"],
    )


# ---------------------------------------------------------------------------
# Recurring Invoice Schedule Endpoints (Task 10.9)
# Requirements: 60.1, 60.2, 60.3, 60.4
# ---------------------------------------------------------------------------

from app.modules.invoices.schemas import (
    RecurringScheduleCreate,
    RecurringScheduleListResponse,
    RecurringScheduleResponse,
    RecurringScheduleUpdate,
)
from app.modules.invoices.service import (
    cancel_recurring_schedule,
    create_recurring_schedule,
    generate_recurring_invoice,
    list_recurring_schedules,
    pause_recurring_schedule,
    update_recurring_schedule,
)


@router.post(
    "/recurring",
    response_model=RecurringScheduleResponse,
    status_code=201,
    summary="Create a recurring invoice schedule",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_recurring_schedule_endpoint(
    payload: RecurringScheduleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a recurring invoice schedule linked to a customer.

    Requirements: 60.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await create_recurring_schedule(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            customer_id=payload.customer_id,
            frequency=payload.frequency.value,
            line_items=[item.model_dump(mode="json") for item in payload.line_items],
            next_due_date=payload.next_due_date,
            auto_issue=payload.auto_issue,
            notes=payload.notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return RecurringScheduleResponse(**result)


@router.get(
    "/recurring",
    response_model=RecurringScheduleListResponse,
    summary="List recurring invoice schedules",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_recurring_schedules_endpoint(
    request: Request,
    active_only: bool = Query(False, description="Filter to active schedules only"),
    db: AsyncSession = Depends(get_db_session),
):
    """List all recurring invoice schedules for the organisation.

    Requirements: 60.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    schedules = await list_recurring_schedules(
        db, org_id=org_uuid, active_only=active_only,
    )

    return RecurringScheduleListResponse(
        schedules=[RecurringScheduleResponse(**s) for s in schedules],
        total=len(schedules),
    )


@router.put(
    "/recurring/{schedule_id}",
    response_model=RecurringScheduleResponse,
    summary="Update a recurring invoice schedule",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_recurring_schedule_endpoint(
    schedule_id: uuid.UUID,
    payload: RecurringScheduleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing recurring invoice schedule.

    Requirements: 60.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await update_recurring_schedule(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            schedule_id=schedule_id,
            frequency=payload.frequency.value if payload.frequency else None,
            line_items=(
                [item.model_dump(mode="json") for item in payload.line_items]
                if payload.line_items is not None
                else None
            ),
            next_due_date=payload.next_due_date,
            auto_issue=payload.auto_issue,
            notes=payload.notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return RecurringScheduleResponse(**result)


@router.post(
    "/recurring/{schedule_id}/pause",
    response_model=RecurringScheduleResponse,
    summary="Pause a recurring invoice schedule",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def pause_recurring_schedule_endpoint(
    schedule_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Pause an active recurring invoice schedule.

    Requirements: 60.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await pause_recurring_schedule(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            schedule_id=schedule_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return RecurringScheduleResponse(**result)


@router.post(
    "/recurring/{schedule_id}/cancel",
    response_model=RecurringScheduleResponse,
    summary="Cancel a recurring invoice schedule",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def cancel_recurring_schedule_endpoint(
    schedule_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel a recurring invoice schedule permanently.

    Requirements: 60.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await cancel_recurring_schedule(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            schedule_id=schedule_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return RecurringScheduleResponse(**result)


# ---------------------------------------------------------------------------
# Bulk Export & Archive — Requirements: 31.1, 31.2, 31.3
# ---------------------------------------------------------------------------


@router.post(
    "/export",
    summary="Bulk export invoices by date range",
    dependencies=[require_role("org_admin")],
)
async def bulk_export_endpoint(
    payload: BulkExportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Export invoices filtered by date range as CSV or ZIP of PDFs.

    - CSV: returns invoice data as a downloadable CSV file.
    - ZIP_PDF: returns a ZIP archive of placeholder PDFs (actual PDF
      generation is handled by task 14.4).

    Requirements: 31.1
    """
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    invoice_dicts, invoices = await bulk_export_invoices(
        db,
        org_id=org_uuid,
        start_date=payload.start_date,
        end_date=payload.end_date,
        export_format=payload.format.value,
    )

    if not invoice_dicts:
        return JSONResponse(
            status_code=404,
            content={"detail": "No invoices found in the specified date range"},
        )

    if payload.format.value == "csv":
        csv_content = invoices_to_csv(invoice_dicts)
        filename = f"invoices_{payload.start_date}_{payload.end_date}.csv"
        return StreamingResponse(
            io.BytesIO(csv_content.encode("utf-8")),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Invoice-Count": str(len(invoice_dicts)),
            },
        )

    # ZIP of PDFs (placeholder — actual PDF generation is task 14.4)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for inv_dict in invoice_dicts:
            inv_number = inv_dict.get("invoice_number") or "DRAFT"
            # Placeholder text content until PDF generation is implemented
            pdf_placeholder = (
                f"PDF placeholder for invoice {inv_number}\n"
                f"Status: {inv_dict.get('status')}\n"
                f"Total: {inv_dict.get('total')}\n"
                f"Issue Date: {inv_dict.get('issue_date')}\n"
            )
            zf.writestr(f"{inv_number}.txt", pdf_placeholder)

    zip_buffer.seek(0)
    filename = f"invoices_{payload.start_date}_{payload.end_date}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Invoice-Count": str(len(invoice_dicts)),
        },
    )


@router.post(
    "/bulk-delete",
    response_model=BulkDeleteResponse,
    summary="Permanently delete invoices (irrecoverable)",
    dependencies=[require_role("org_admin")],
)
async def bulk_delete_endpoint(
    payload: BulkDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete invoices. This action is irrecoverable.

    The recommended workflow is export-then-delete.

    When ``confirm`` is False, returns a preview of what will be deleted.
    When ``confirm`` is True, performs the deletion.

    Requirements: 31.2, 31.3
    """
    from app.modules.storage.service import _bytes_to_display

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    if not payload.confirm:
        # Preview mode — show what would be deleted
        from sqlalchemy import select as sa_select, func as sa_func
        from app.modules.invoices.models import Invoice

        stmt = sa_select(
            sa_func.count(Invoice.id),
            sa_func.coalesce(
                sa_func.sum(
                    sa_func.octet_length(
                        sa_func.cast(Invoice.invoice_data_json, sa_func.text("text"))
                    )
                ),
                0,
            ),
        ).where(
            Invoice.org_id == org_uuid,
            Invoice.id.in_(payload.invoice_ids),
        )
        result = await db.execute(stmt)
        row = result.one()
        count = row[0]
        est_bytes = row[1] or 0

        return BulkDeleteResponse(
            deleted_count=0,
            estimated_space_recovered=_bytes_to_display(est_bytes),
            message=(
                f"This will permanently delete {count} invoice(s), "
                f"recovering approximately {_bytes_to_display(est_bytes)}. "
                f"This action is irrecoverable. Set confirm=true to proceed."
            ),
        )

    # Confirmed deletion
    deleted_count, bytes_recovered = await bulk_delete_invoices(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
        invoice_ids=payload.invoice_ids,
        ip_address=ip_address,
    )

    await db.commit()

    return BulkDeleteResponse(
        deleted_count=deleted_count,
        estimated_space_recovered=_bytes_to_display(bytes_recovered),
        message=(
            f"Successfully deleted {deleted_count} invoice(s). "
            f"Approximately {_bytes_to_display(bytes_recovered)} of storage recovered."
        ),
    )


# ---------------------------------------------------------------------------
# PDF Generation & Email — Requirements: 32.1, 32.2, 32.3, 32.4
# ---------------------------------------------------------------------------


@router.get(
    "/{invoice_id}/pdf",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Invoice PDF"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Invoice not found"},
    },
    summary="Generate and download invoice PDF on-the-fly",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_invoice_pdf_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate an invoice PDF in-memory and stream it to the client.

    The PDF is never written to permanent storage (Requirement 32.2).
    Organisation branding is applied at generation time (Requirement 32.3).

    Requirements: 32.1, 32.2, 32.3, 32.4
    """
    from fastapi.responses import Response
    from app.modules.invoices.service import generate_invoice_pdf

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        pdf_bytes = await generate_invoice_pdf(
            db, org_id=org_uuid, invoice_id=invoice_id
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    # Determine a filename for the download
    from app.modules.invoices.service import get_invoice as _get_inv

    inv = await _get_inv(db, org_id=org_uuid, invoice_id=invoice_id)
    filename = f"{inv.get('invoice_number') or 'DRAFT'}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post(
    "/{invoice_id}/email",
    response_model=InvoiceEmailResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Invoice not found"},
    },
    summary="Email invoice PDF to customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def email_invoice_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    payload: InvoiceEmailRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate the invoice PDF and email it to the customer.

    If ``recipient_email`` is provided in the body it overrides the
    customer's email on file.

    Requirements: 32.3
    """
    from app.modules.invoices.service import email_invoice

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    recipient = payload.recipient_email if payload else None

    try:
        result = await email_invoice(
            db,
            org_id=org_uuid,
            invoice_id=invoice_id,
            recipient_email=recipient,
            base_url=request.headers.get("origin") or None,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    await db.commit()

    return InvoiceEmailResponse(
        invoice_id=str(result["invoice_id"]),
        invoice_number=result["invoice_number"],
        recipient_email=result["recipient_email"],
        pdf_size_bytes=result["pdf_size_bytes"],
        status=result["status"],
    )


# ---------------------------------------------------------------------------
# Public Invoice Sharing — Requirements: Share invoice via public URL
# ---------------------------------------------------------------------------


@router.post(
    "/{invoice_id}/share",
    responses={
        200: {"description": "Share link generated"},
        400: {"description": "Invoice not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Generate a public share link for an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def share_invoice_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate or retrieve a public share token for an invoice.

    The token is stored in invoice_data_json and can be used to view
    the invoice without authentication.
    """
    import secrets

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    from app.modules.invoices.models import Invoice as InvoiceModel

    inv_result = await db.execute(
        select(InvoiceModel).where(
            InvoiceModel.id == invoice_id, InvoiceModel.org_id == org_uuid
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if invoice is None:
        return JSONResponse(status_code=400, content={"detail": "Invoice not found"})

    # Reuse existing token or generate a new one
    data = invoice.invoice_data_json or {}
    token = data.get("share_token")
    if not token:
        token = secrets.token_urlsafe(32)
        data["share_token"] = token
        invoice.invoice_data_json = data
        # Force SQLAlchemy to detect JSONB mutation
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(invoice, "invoice_data_json")
        await db.flush()
        await db.commit()

    return JSONResponse(content={"share_token": token, "invoice_id": str(invoice_id)})


# ---------------------------------------------------------------------------
# Send Payment Reminder — Requirements: 38.1
# ---------------------------------------------------------------------------


@router.post(
    "/{invoice_id}/send-reminder",
    responses={
        200: {"description": "Reminder sent"},
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Invoice not found"},
    },
    summary="Send a payment reminder via email or SMS",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def send_reminder_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    payload: dict,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a payment reminder for an invoice via email or SMS.

    Requirements: 38.1
    """
    from app.modules.invoices.service import send_payment_reminder

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    channel = payload.get("channel")
    if channel not in ("email", "sms"):
        return JSONResponse(
            status_code=400,
            content={"detail": "channel must be 'email' or 'sms'"},
        )

    try:
        result = await send_payment_reminder(
            db,
            org_id=org_uuid,
            invoice_id=invoice_id,
            channel=channel,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    await db.commit()
    return result


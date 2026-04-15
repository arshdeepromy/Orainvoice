"""Customer router — CRUD, search, profile, notify, vehicle tagging.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.customers.schemas import (
    CustomerAnonymiseResponse,
    CustomerCreateRequest,
    CustomerCreateResponse,
    CustomerExportResponse,
    CustomerListResponse,
    CustomerMergeRequest,
    CustomerMergeResponse,
    CustomerNotifyRequest,
    CustomerNotifyResponse,
    CustomerProfileResponse,
    CustomerResponse,
    CustomerSearchResult,
    CustomerUpdateRequest,
    CustomerUpdateResponse,
    CustomerVehicleTagRequest,
    CustomerVehicleTagResponse,
    FleetAccountCreateRequest,
    FleetAccountCreateResponse,
    FleetAccountDeleteResponse,
    FleetAccountListResponse,
    FleetAccountResponse,
    FleetAccountUpdateRequest,
    FleetAccountUpdateResponse,
)
from app.modules.customers.service import (
    anonymise_customer,
    create_customer,
    create_fleet_account,
    delete_fleet_account,
    export_customer_data,
    get_customer,
    get_customer_profile,
    get_customer_reminder_config,
    get_fleet_account,
    list_fleet_accounts,
    merge_customers,
    notify_customer,
    search_customers,
    tag_vehicle_to_customer,
    update_customer,
    update_customer_reminder_config,
    update_fleet_account,
    update_vehicle_expiry_dates,
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


# ---------------------------------------------------------------------------
# Background task — Xero contact sync on customer creation
# ---------------------------------------------------------------------------


async def _sync_customer_to_xero(org_id: uuid.UUID, customer_data: dict) -> None:
    """Fire-and-forget: sync a newly created customer as a Xero contact.

    Creates its own DB session since BackgroundTasks run after the
    response is sent and the request session is closed.
    """
    import logging

    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.accounting.models import AccountingIntegration
    from app.modules.accounting.service import sync_entity

    logger = logging.getLogger(__name__)

    try:
        async with async_session_factory() as session:
            async with session.begin():
                # Check for active Xero connection
                stmt = select(AccountingIntegration).where(
                    AccountingIntegration.org_id == org_id,
                    AccountingIntegration.provider == "xero",
                    AccountingIntegration.is_connected == True,  # noqa: E712
                )
                result = await session.execute(stmt)
                conn = result.scalar_one_or_none()
                if conn is None:
                    return

                # Map customer fields to contact sync format
                contact_data = {
                    "first_name": customer_data.get("first_name", ""),
                    "last_name": customer_data.get("last_name", ""),
                    "display_name": customer_data.get("display_name", ""),
                    "email": customer_data.get("email"),
                    "phone": customer_data.get("phone"),
                    "mobile_phone": customer_data.get("mobile_phone"),
                    "company_name": customer_data.get("company_name"),
                    "billing_address": customer_data.get("billing_address"),
                }

                entity_id = uuid.UUID(customer_data["id"]) if isinstance(customer_data.get("id"), str) else customer_data.get("id", uuid.uuid4())

                await sync_entity(
                    session,
                    org_id=org_id,
                    provider="xero",
                    entity_type="contact",
                    entity_id=entity_id,
                    entity_data=contact_data,
                )
    except Exception:
        logger.exception("Background Xero contact sync failed for org %s", org_id)


@router.get(
    "",
    response_model=CustomerListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List or search customers",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_customers(
    request: Request,
    q: str | None = Query(None, description="Search query (name, phone, email)"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    include_vehicles: bool = Query(False, description="Include linked vehicles for each customer"),
    db: AsyncSession = Depends(get_db_session),
):
    """Search customers by name, phone, or email with live dropdown results.

    When ``q`` is provided, performs a live search across customer name,
    phone number, and email simultaneously. Returns results suitable for
    a dropdown with customer name, phone, and email for quick identification.

    When no matching customer is found, the ``has_exact_match`` field is
    False, signalling the frontend to display a "Create new customer" option.
    
    When ``include_vehicles`` is True, also returns linked vehicles for each customer.

    Requirements: 11.1, 11.2, 11.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await search_customers(
        db, org_id=org_uuid, query=q, limit=limit, offset=offset, include_vehicles=include_vehicles,
        branch_id=getattr(request.state, "branch_id", None),
    )

    return CustomerListResponse(
        customers=[CustomerSearchResult(**c) for c in result["customers"]],
        total=result["total"],
        has_exact_match=result["has_exact_match"],
    )


@router.post(
    "",
    response_model=CustomerCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a new customer",
    dependencies=[require_role("org_admin", "salesperson", "kiosk")],
)
async def create_new_customer(
    payload: CustomerCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new customer record inline from the search dropdown.

    Accepts comprehensive customer information including contact details,
    business info, addresses, and preferences.
    The customer is scoped to the current organisation and never shared
    across organisations.

    Requirements: 11.4, 11.5, 11.6
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Parse tax_rate_id if provided
    tax_rate_uuid = None
    if payload.tax_rate_id:
        try:
            tax_rate_uuid = uuid.UUID(payload.tax_rate_id)
        except (ValueError, TypeError):
            pass

    customer_data = await create_customer(
        db,
        org_id=org_uuid,
        user_id=user_uuid or uuid.uuid4(),
        # Required fields
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        mobile_phone=payload.mobile_phone,
        # Identity
        customer_type=payload.customer_type or "individual",
        salutation=payload.salutation,
        company_name=payload.company_name,
        display_name=payload.display_name,
        # Contact
        work_phone=payload.work_phone,
        phone=payload.phone,
        # Preferences
        currency=payload.currency or "NZD",
        language=payload.language or "en",
        # Business/Tax
        tax_rate_id=tax_rate_uuid,
        company_id=payload.company_id,
        payment_terms=payload.payment_terms or "due_on_receipt",
        # Options
        enable_bank_payment=payload.enable_bank_payment or False,
        enable_portal=payload.enable_portal or False,
        # Addresses
        address=payload.address,
        billing_address=payload.billing_address.model_dump() if payload.billing_address else None,
        shipping_address=payload.shipping_address.model_dump() if payload.shipping_address else None,
        # Additional data
        contact_persons=[cp.model_dump() for cp in payload.contact_persons] if payload.contact_persons else None,
        custom_fields=payload.custom_fields,
        # Notes
        notes=payload.notes,
        remarks=payload.remarks,
        ip_address=ip_address,
    )

    # Fire-and-forget: sync new customer to Xero if connected
    if org_uuid:
        background_tasks.add_task(_sync_customer_to_xero, org_uuid, customer_data)

    return CustomerCreateResponse(
        message="Customer created",
        customer=CustomerResponse(**customer_data),
    )


@router.get(
    "/fleet-accounts",
    response_model=FleetAccountListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List fleet accounts",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_fleet_accounts_endpoint(
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List all fleet accounts for the organisation.

    Requirements: 66.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_fleet_accounts(
        db, org_id=org_uuid, limit=limit, offset=offset
    )

    return FleetAccountListResponse(
        fleet_accounts=[FleetAccountResponse(**fa) for fa in result["fleet_accounts"]],
        total=result["total"],
    )


@router.post(
    "/fleet-accounts",
    response_model=FleetAccountCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create a fleet account",
    dependencies=[require_role("org_admin")],
)
async def create_fleet_account_endpoint(
    payload: FleetAccountCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new fleet account for grouping vehicles under a commercial customer.

    Requirements: 66.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    fa_data = await create_fleet_account(
        db,
        org_id=org_uuid,
        user_id=user_uuid or uuid.uuid4(),
        name=payload.name,
        primary_contact_name=payload.primary_contact_name,
        primary_contact_email=payload.primary_contact_email,
        primary_contact_phone=payload.primary_contact_phone,
        billing_address=payload.billing_address,
        notes=payload.notes,
        pricing_overrides=payload.pricing_overrides,
        ip_address=ip_address,
    )

    return FleetAccountCreateResponse(
        message="Fleet account created",
        fleet_account=FleetAccountResponse(**fa_data),
    )


@router.get(
    "/fleet-accounts/{fleet_account_id}",
    response_model=FleetAccountResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Fleet account not found"},
    },
    summary="Get fleet account details",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_fleet_account_endpoint(
    fleet_account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single fleet account by ID.

    Requirements: 66.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        fa_uuid = uuid.UUID(fleet_account_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid fleet account ID format"},
        )

    try:
        fa_data = await get_fleet_account(
            db, org_id=org_uuid, fleet_account_id=fa_uuid
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return FleetAccountResponse(**fa_data)


@router.put(
    "/fleet-accounts/{fleet_account_id}",
    response_model=FleetAccountUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Fleet account not found"},
    },
    summary="Update a fleet account",
    dependencies=[require_role("org_admin")],
)
async def update_fleet_account_endpoint(
    fleet_account_id: str,
    payload: FleetAccountUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing fleet account. Only provided fields are changed.

    Requirements: 66.1, 66.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        fa_uuid = uuid.UUID(fleet_account_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid fleet account ID format"},
        )

    update_kwargs = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }

    try:
        fa_data = await update_fleet_account(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            fleet_account_id=fa_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    return FleetAccountUpdateResponse(
        message="Fleet account updated",
        fleet_account=FleetAccountResponse(**fa_data),
    )


@router.delete(
    "/fleet-accounts/{fleet_account_id}",
    response_model=FleetAccountDeleteResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Fleet account not found"},
    },
    summary="Delete a fleet account",
    dependencies=[require_role("org_admin")],
)
async def delete_fleet_account_endpoint(
    fleet_account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a fleet account and unlink all associated customers.

    Requirements: 66.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        fa_uuid = uuid.UUID(fleet_account_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid fleet account ID format"},
        )

    try:
        result = await delete_fleet_account(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            fleet_account_id=fa_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return FleetAccountDeleteResponse(
        message="Fleet account deleted",
        fleet_account_id=result["fleet_account_id"],
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerProfileResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer not found"},
    },
    summary="Get customer profile with vehicles, invoices, spend, and balance",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_customer_by_id(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a full customer profile including linked vehicles, invoice
    history, total spend, and outstanding balance.

    Requirements: 12.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    try:
        profile_data = await get_customer_profile(
            db, org_id=org_uuid, customer_id=cust_uuid
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return CustomerProfileResponse(**profile_data)


@router.put(
    "/{customer_id}",
    response_model=CustomerUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer not found"},
    },
    summary="Update a customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_existing_customer(
    customer_id: str,
    payload: CustomerUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing customer record. Only provided fields are changed.

    Requirements: 11.5, 11.6
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    update_kwargs = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }

    try:
        customer_data = await update_customer(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            customer_id=cust_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404 if "not found" in str(exc).lower() else 400,
            content={"detail": str(exc)},
        )

    return CustomerUpdateResponse(
        message="Customer updated",
        customer=CustomerResponse(**customer_data),
    )


# ---------------------------------------------------------------------------
# Task 7.4 — Privacy Act 2020 compliance endpoints
# Requirements: 13.1, 13.2, 13.3
# ---------------------------------------------------------------------------


@router.delete(
    "/{customer_id}",
    response_model=CustomerAnonymiseResponse,
    responses={
        400: {"description": "Validation error (already anonymised)"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Customer not found"},
    },
    summary="Anonymise customer (Privacy Act 2020)",
    dependencies=[require_role("org_admin")],
)
async def anonymise_customer_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Anonymise a customer record for Privacy Act 2020 compliance.

    Replaces customer name with "Anonymised Customer", clears all contact
    details (email, phone, address, notes), and anonymises customer PII
    on linked invoices while preserving all financial records intact.

    Only Org_Admin can process deletion requests.

    Requirements: 13.1, 13.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    try:
        result = await anonymise_customer(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            customer_id=cust_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    return CustomerAnonymiseResponse(
        message="Customer anonymised successfully",
        customer_id=result["customer_id"],
        is_anonymised=result["is_anonymised"],
        invoices_preserved=result["invoices_preserved"],
    )


@router.get(
    "/{customer_id}/export",
    response_model=CustomerExportResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Customer not found"},
    },
    summary="Export customer data as JSON (Privacy Act 2020)",
    dependencies=[require_role("org_admin")],
)
async def export_customer_data_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Export all data for a customer as JSON for Privacy Act 2020 compliance.

    Returns the customer record, linked vehicles, full invoice history
    with line items, and payment records.

    Only Org_Admin can process data access requests.

    Requirements: 13.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    try:
        export_data = await export_customer_data(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return CustomerExportResponse(
        customer=CustomerResponse(**export_data["customer"]),
        vehicles=export_data["vehicles"],
        invoices=export_data["invoices"],
        exported_at=export_data["exported_at"],
    )


# ---------------------------------------------------------------------------
# Task 7.3 — Customer record merging endpoint
# Requirements: 12.4
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/merge",
    response_model=CustomerMergeResponse,
    responses={
        400: {"description": "Validation error (e.g. merging with self)"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer not found"},
    },
    summary="Merge another customer into this customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def merge_customer_endpoint(
    customer_id: str,
    payload: CustomerMergeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Merge a source customer into the target customer (URL path).

    When ``preview_only`` is True (default), returns a preview showing
    exactly what will be combined: vehicles, invoices, and contact details.
    When False, executes the merge, moves all records, fills contact gaps,
    and marks the source customer as merged/inactive.

    Requirements: 12.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        target_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid target customer ID format"},
        )

    try:
        source_uuid = uuid.UUID(payload.source_customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid source customer ID format"},
        )

    try:
        result = await merge_customers(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            target_customer_id=target_uuid,
            source_customer_id=source_uuid,
            preview_only=payload.preview_only,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    from app.modules.customers.schemas import (
        CustomerMergePreview,
        CustomerResponse as CustResp,
        MergePreviewContactChanges,
        MergePreviewInvoice,
        MergePreviewVehicle,
    )

    preview_data = result["preview"]
    preview = CustomerMergePreview(
        target_customer=CustResp(**preview_data["target_customer"]),
        source_customer=CustResp(**preview_data["source_customer"]),
        vehicles_to_transfer=[
            MergePreviewVehicle(**v) for v in preview_data["vehicles_to_transfer"]
        ],
        invoices_to_transfer=[
            MergePreviewInvoice(**i) for i in preview_data["invoices_to_transfer"]
        ],
        contact_changes=MergePreviewContactChanges(**preview_data["contact_changes"]),
        fleet_account_transfer=preview_data["fleet_account_transfer"],
    )

    return CustomerMergeResponse(
        message=result["message"],
        preview=preview,
        merged=result["merged"],
    )


# ---------------------------------------------------------------------------
# Task 7.2 — Notify and vehicle tagging endpoints
# Requirements: 12.2, 12.3
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/notify",
    response_model=CustomerNotifyResponse,
    responses={
        400: {"description": "Validation error or missing contact info"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer not found"},
    },
    summary="Send one-off email or SMS to customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def notify_customer_endpoint(
    customer_id: str,
    payload: CustomerNotifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a one-off email or SMS directly from the customer profile.

    Requirements: 12.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    try:
        result = await notify_customer(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            customer_id=cust_uuid,
            channel=payload.channel,
            subject=payload.subject,
            message=payload.message,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    return CustomerNotifyResponse(**result)


@router.post(
    "/{customer_id}/vehicles",
    response_model=CustomerVehicleTagResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer or vehicle not found"},
    },
    summary="Tag a vehicle to a customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def tag_vehicle_endpoint(
    customer_id: str,
    payload: CustomerVehicleTagRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Link a vehicle (global or org-scoped) to a customer.

    Requirements: 12.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    # Parse vehicle IDs
    global_vid = None
    org_vid = None
    try:
        if payload.global_vehicle_id:
            global_vid = uuid.UUID(payload.global_vehicle_id)
        if payload.org_vehicle_id:
            org_vid = uuid.UUID(payload.org_vehicle_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid vehicle ID format"},
        )

    try:
        link_data = await tag_vehicle_to_customer(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            customer_id=cust_uuid,
            global_vehicle_id=global_vid,
            org_vehicle_id=org_vid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    from app.modules.customers.schemas import LinkedVehicleResponse

    return CustomerVehicleTagResponse(
        message="Vehicle tagged to customer",
        vehicle_link=LinkedVehicleResponse(**link_data),
    )


# ---------------------------------------------------------------------------
# Per-customer reminder configuration
# ---------------------------------------------------------------------------


@router.get("/{customer_id}/reminders")
async def get_customer_reminders_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get per-customer reminder configuration (Service Due, WOF Expiry)."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    try:
        config = await get_customer_reminder_config(
            db, org_id=org_uuid, customer_id=cust_uuid
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return config


@router.put("/{customer_id}/reminders")
async def update_customer_reminders_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update per-customer reminder configuration."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    body = await request.json()

    try:
        updated = await update_customer_reminder_config(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
            reminders=body,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return updated


@router.put("/{customer_id}/vehicle-dates")
async def update_vehicle_dates_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update service_due_date and wof_expiry on vehicles linked to a customer."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer ID format"},
        )

    body = await request.json()
    vehicles = body.get("vehicles", [])

    try:
        updated = await update_vehicle_expiry_dates(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
            vehicle_updates=vehicles,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return {"updated": updated}

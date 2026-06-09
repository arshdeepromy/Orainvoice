"""Customer router — CRUD, search, profile, notify, vehicle tagging.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.request_utils import extract_request_base_url
from app.modules.auth.models import User
from app.modules.auth.rbac import require_role
from app.modules.customers.consent import (
    RemindersConsentRecord,
    RemindersRevocationRecord,
    current_consent_text,
)
from app.modules.organisations.service import get_org_settings
from app.modules.customers.exceptions import (
    RemindersConsentRequiredError,
    RemindersRevocationError,
)
from app.modules.customers.schemas import (
    CustomerAnonymiseResponse,
    CustomerCreateRequest,
    CustomerCreateResponse,
    CustomerDeletionBlockedError,
    CustomerDeletionPreflightResponse,
    CustomerExportResponse,
    CustomerHardDeleteRequest,
    CustomerHardDeleteResponse,
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
    RemindersRevokeRequest,
)
from app.modules.email_compose.schemas import PortalLinkOverrideRequest
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
    hard_delete_customer,
    list_fleet_accounts,
    merge_customers,
    notify_customer,
    preflight_customer_deletion,
    search_customers,
    send_portal_link,
    tag_vehicle_to_customer,
    revoke_customer_reminders,
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
    "/consent-text",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def customer_consent_text_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the reminder-consent banner text + version for the staff-facing
    manual Consent Confirmation modal (F4).

    Mirrors the kiosk ``GET /kiosk/consent-text`` constant but is gated for
    customer-write roles, since the kiosk endpoint is ``require_role("kiosk")``
    and an org_admin/salesperson cannot call it. The ``{workshop_name}``
    placeholder is substituted server-side. Registered BEFORE
    ``GET /{customer_id}`` so the static path is not captured by the
    dynamic customer-id route.

    Refs: Requirement 6.3, 6.4.
    """
    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    text, version = current_consent_text()
    settings = await get_org_settings(db, org_id=org_uuid)
    workshop_name = (settings or {}).get("org_name") or "your workshop"
    text = text.replace("{workshop_name}", workshop_name)
    return {"text": text, "version": version}


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


# ---------------------------------------------------------------------------
# Task 4.1 — Hard delete preflight + execution endpoints
# Requirements: 1.5, 2.2, 2.3, 4.1, 5.2, 9.4, 10.1, 12.1, 12.2, 12.3
# ---------------------------------------------------------------------------


@router.get(
    "/{customer_id}/deletion-preflight",
    response_model=CustomerDeletionPreflightResponse,
    responses={
        400: {"description": "Invalid customer ID format"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Customer not found"},
    },
    summary="Preflight checks for hard-deleting a customer",
    dependencies=[require_role("org_admin")],
)
async def customer_deletion_preflight_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Read-only assessment for the hard-delete confirmation screen.

    Returns whether the customer can be hard-deleted now, the blocking
    documents that must be removed/resolved first, the deletable draft
    invoices, and the vehicles that would be orphaned.

    Only Org_Admin can access this endpoint (it reveals invoice numbers).

    Requirements: 2.2, 2.3, 3.1, 12.1, 12.2, 12.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid customer ID format"})
    try:
        data = await preflight_customer_deletion(db, org_id=org_uuid, customer_id=cust_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return CustomerDeletionPreflightResponse(**data)


@router.post(
    "/{customer_id}/hard-delete",
    response_model=CustomerHardDeleteResponse,
    responses={
        400: {"description": "Validation error (bad reason, bad confirmation, draft invoices remain)"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Customer not found"},
        409: {"description": "Blocked by legally-retained documents"},
    },
    summary="Guarded hard delete of a customer (irreversible)",
    dependencies=[require_role("org_admin")],
)
async def hard_delete_customer_endpoint(
    customer_id: str,
    payload: CustomerHardDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Guarded hard delete of a customer within one transaction.

    Permanently removes the customer row and all non-financial dependent
    rows. Blocks when legally-retained financial documents exist (issued
    invoices, open claims, job cards, fleet checklist submissions).
    Requires a mandatory reason and an irreversible confirmation string.
    Orphans linked vehicles instead of destroying them.

    Only Org_Admin can perform this irreversible action.

    Requirements: 1.5, 2.2, 2.3, 4.1, 5.2, 9.4, 10.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    try:
        cust_uuid = uuid.UUID(customer_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid customer ID format"})
    try:
        result = await hard_delete_customer(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
            user_id=user_uuid or uuid.uuid4(),
            reason=payload.reason,
            confirmation=payload.confirmation,
            ip_address=ip_address,
        )
    except CustomerDeletionBlockedError as exc:
        return JSONResponse(status_code=409, content={"detail": exc.message, "blocking": exc.payload})
    except ValueError as exc:
        msg = str(exc)
        status = 404 if "not found" in msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": msg})
    return CustomerHardDeleteResponse(**result)


# ---------------------------------------------------------------------------
# Task 5.2 — Send portal link to customer
# Requirements: 13.1, 13.2, 13.3, 13.4
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/send-portal-link",
    responses={
        200: {"description": "Portal link sent successfully"},
        400: {"description": "Validation error (no email, portal not enabled, invalid attachment)"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer not found"},
        413: {"description": "Email too large"},
        502: {"description": "Email provider authentication failed"},
        503: {"description": "Delivery temporarily failed"},
    },
    summary="Send portal access link to customer via email",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def send_portal_link_endpoint(
    customer_id: str,
    request: Request,
    payload: PortalLinkOverrideRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Send the customer portal access link to the customer's email.

    Validates that the customer has portal access enabled, a valid portal
    token, and an email address on file before sending.

    Two modes:

    - **No body (backward-compatible auto-send)** — keeps the existing
      fire-and-forget queued dispatch and returns the original 200 shape.
    - **Send Email Modal override** (``PortalLinkOverrideRequest``) — switches
      ``customers.service.send_portal_link`` to a direct synchronous send so
      this endpoint can map ``FailureKind`` → HTTP. ``override_blocklist`` is
      org_admin-gated (R13.5); attachment-token misses map to 400; send
      failures map their ``failure_kind`` to the right status (R8.5–R8.8); a
      missing customer maps to 404.

    Requirements: 2.6, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10,
                  11.2, 11.3, 11.5, 16.2
    """
    from app.modules.email_compose.service import (
        EmailSendFailure,
        InvalidAttachmentSelection,
    )

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

    _origin = extract_request_base_url(request)

    recipients = None
    cc = None
    bcc = None
    subject = None
    body_html = None
    attachments = None
    subject_was_edited = False
    body_was_edited = False
    override_blocklist = False
    if payload is not None:
        recipients = payload.recipients
        cc = payload.cc
        bcc = payload.bcc
        subject = payload.subject
        body_html = payload.body_html
        attachments = payload.attachments
        subject_was_edited = payload.subject_was_edited
        body_was_edited = payload.body_was_edited
        override_blocklist = payload.override_blocklist

    # Honour override_blocklist only for org_admin (R13.5).
    if override_blocklist:
        role = getattr(request.state, "role", None)
        if role != "org_admin":
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Only an organisation admin can override the "
                    "bounce blocklist."
                },
            )

    try:
        result = await send_portal_link(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            customer_id=cust_uuid,
            ip_address=ip_address,
            base_url=_origin,
            recipients=recipients,
            cc=cc,
            bcc=bcc,
            subject=subject,
            body_html=body_html,
            attachments=attachments,
            subject_was_edited=subject_was_edited,
            body_was_edited=body_was_edited,
            override_blocklist=override_blocklist,
        )
    except InvalidAttachmentSelection:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid attachment selection."},
        )
    except EmailSendFailure as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    await db.commit()

    return JSONResponse(
        status_code=200,
        content=result,
    )


@router.post(
    "/{customer_id}/vehicles",
    response_model=CustomerVehicleTagResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Customer or vehicle not found"},
        409: {"description": "Vehicle is already linked to this customer"},
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
    except LookupError as exc:
        # vehicle-data-isolation Task 9.1: duplicate-link guard. The
        # service layer raises ``LookupError`` when the same
        # (org_id, customer_id, vehicle) link already exists — return
        # HTTP 409 Conflict so the caller can distinguish duplicate-link
        # from validation/not-found.
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc)},
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
    """Update per-customer reminder configuration.

    Accepts an optional ``consent_record`` field in the request body.
    When the new ``reminders`` config newly enables a (category, channel)
    pair not covered by the existing ``customer.custom_fields["reminder_consent"]``
    and no ``consent_record`` is supplied, the service raises
    :class:`RemindersConsentRequiredError` which is mapped here to HTTP 409
    with body ``{"error": "consent_required", "missing": [...]}``.

    Refs: Requirements 2.12, 2.13, 1.16, 2.8.
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

    body = await request.json()

    # Pop the optional consent_record block off the raw body before it is
    # passed through as ``reminders=`` (the existing per-category dict).
    consent_block = body.pop("consent_record", None)
    consent_record = (
        RemindersConsentRecord.model_validate(consent_block)
        if consent_block is not None
        else None
    )

    # Build a SimpleNamespace proxy with ``.id`` so the consent helper can
    # populate the audit_log row's ``user_id`` column without us threading
    # the full ORM user object through. ``current_user`` is ``None`` when
    # the request is unauthenticated (the AuthMiddleware would normally
    # block this, but we guard defensively).
    current_user = (
        types.SimpleNamespace(id=user_uuid) if user_uuid else None
    )

    # Truncate the User-Agent header at 500 chars per design §3.1; an
    # absent or empty header collapses to ``None``.
    user_agent = (request.headers.get("user-agent") or "")[:500] or None

    try:
        updated = await update_customer_reminder_config(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
            reminders=body,
            consent_record=consent_record,
            current_user=current_user,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except RemindersConsentRequiredError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": "consent_required", "missing": exc.missing},
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return updated


@router.post(
    "/{customer_id}/reminders/revoke",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def revoke_customer_reminders_endpoint(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Record a manual revocation of reminder consent for a customer.

    The staff member confirms a revocation obtained out-of-band (phone /
    in person / email). The handler composes the persisted ``source`` as
    ``manually_recorded_by_staff:<obtained_method>``, builds a
    :class:`RemindersRevocationRecord`, and delegates to
    :func:`revoke_customer_reminders`, which flips
    ``reminder_config[<cat>].enabled = False`` and appends the revocation
    entry in one ``session.begin()`` transaction.

    Transaction discipline: pre-write validation errors are caught and
    mapped to 4xx; persistence failures are NOT swallowed — they propagate
    so the surrounding ``session.begin()`` rolls back the whole request
    (Req 3.6). Mirrors the write-path RBAC of ``PUT /{customer_id}``.

    Refs: Requirements 3.2, 3.4, 3.5.
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

    body = await request.json()
    try:
        payload = RemindersRevokeRequest.model_validate(body)
    except ValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    # The revocation record requires the acting user's email
    # (``recorded_by_user_email``) which ``request.state`` does not carry —
    # only the id. Resolve the User row for its email.
    current_user = await db.get(User, user_uuid) if user_uuid else None
    if current_user is None:
        return JSONResponse(
            status_code=403,
            content={"detail": "Authenticated user required"},
        )

    record = RemindersRevocationRecord(
        revoked_at=datetime.now(timezone.utc),
        source=f"manually_recorded_by_staff:{payload.obtained_method}",
        recorded_by_user_id=current_user.id,
        recorded_by_user_email=current_user.email,
        channel=payload.channel,
        categories_affected=payload.categories_affected,
        reason_note=payload.reason_note,
    )

    try:
        updated = await revoke_customer_reminders(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
            current_user=current_user,
            record=record,
            ip_address=ip_address,
        )
    except RemindersRevocationError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "revocation_invalid", "detail": str(exc)},
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
    """Update service_due_date, wof_expiry, and cof_expiry on the calling
    org's per-org snapshot of vehicles linked to a customer.

    vehicle-data-isolation Task 10.1: writes target the calling org's
    ``org_vehicles`` row (promoting the vehicle on first touch) rather
    than the cross-tenant ``global_vehicles`` cache. The request body
    schema gains an optional ``cof_expiry`` ISO date string per vehicle
    update; the response shape gains a ``cof_expiry`` key on each
    updated entry.
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

    body = await request.json()
    vehicles = body.get("vehicles", [])

    try:
        updated = await update_vehicle_expiry_dates(
            db,
            org_id=org_uuid,
            customer_id=cust_uuid,
            vehicle_updates=vehicles,
            user_id=user_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return {"updated": updated}

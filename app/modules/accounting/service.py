"""Service layer for accounting software integration (Xero & MYOB).

Manages OAuth connections, token lifecycle, entity sync dispatch,
failure logging, and manual retry.

Requirements: 68.1, 68.2, 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.integrations import myob as myob_client
from app.integrations import xero as xero_client
from app.modules.accounting.models import AccountingIntegration, AccountingSyncLog

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("xero", "myob")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connection_to_dict(conn: AccountingIntegration) -> dict[str, Any]:
    """Convert an AccountingIntegration ORM instance to a response dict."""
    return {
        "id": str(conn.id),
        "org_id": str(conn.org_id),
        "provider": conn.provider,
        "is_connected": conn.is_connected,
        "account_name": conn.account_name,
        "xero_tenant_id": conn.xero_tenant_id,
        "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        "created_at": conn.created_at.isoformat() if conn.created_at else "",
        "sync_status": "idle",  # TODO: Track sync status in real-time
        "error_message": None,  # TODO: Store last sync error
    }


def _sync_log_to_dict(entry: AccountingSyncLog) -> dict[str, Any]:
    """Convert an AccountingSyncLog ORM instance to a response dict."""
    return {
        "id": str(entry.id),
        "provider": entry.provider,
        "entity_type": entry.entity_type,
        "entity_id": str(entry.entity_id),
        "external_id": entry.external_id,
        "status": entry.status,
        "error_message": entry.error_message,
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
    }


def _build_redirect_uri(provider: str, *, base_url: str | None = None) -> str:
    """Build the OAuth callback redirect URI for a provider.

    Uses the explicit *base_url* (derived from the incoming request) when
    available so the redirect URI always matches the domain the browser is
    actually on.  Falls back to the FRONTEND_BASE_URL env var.
    """
    base = (base_url or settings.frontend_base_url).rstrip("/")
    return f"{base}/api/v1/org/accounting/callback/{provider}"


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


async def list_connections(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """List all accounting connections for an organisation.

    Requirements: 68.1, 68.2
    """
    stmt = (
        select(AccountingIntegration)
        .where(AccountingIntegration.org_id == org_id)
        .order_by(AccountingIntegration.created_at.desc())
    )
    result = await db.execute(stmt)
    connections = result.scalars().all()
    return {
        "connections": [_connection_to_dict(c) for c in connections],
        "total": len(connections),
    }


async def initiate_oauth(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str,
    base_url: str | None = None,
) -> str | None:
    """Generate the OAuth authorization URL for the given provider.

    Creates or reuses the AccountingIntegration row.
    Returns the authorization URL, or None if the provider is invalid.

    Requirements: 68.1, 68.2
    """
    if provider not in VALID_PROVIDERS:
        return None

    # Upsert the integration row (disconnected state)
    stmt = select(AccountingIntegration).where(
        AccountingIntegration.org_id == org_id,
        AccountingIntegration.provider == provider,
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    if conn is None:
        conn = AccountingIntegration(org_id=org_id, provider=provider)
        db.add(conn)
        await db.flush()

    state = f"{org_id}:{provider}"
    redirect_uri = _build_redirect_uri(provider, base_url=base_url)

    if provider == "xero":
        return await xero_client.get_authorization_url(redirect_uri, state)
    else:
        return myob_client.get_authorization_url(redirect_uri, state)


async def handle_oauth_callback(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str,
    code: str,
    base_url: str | None = None,
) -> dict[str, Any] | str:
    """Exchange the OAuth code for tokens and store them encrypted.

    Returns the connection dict on success, or an error string.
    Requirements: 68.1, 68.2
    """
    if provider not in VALID_PROVIDERS:
        return "Invalid provider"

    redirect_uri = _build_redirect_uri(provider, base_url=base_url)

    try:
        if provider == "xero":
            token_data = await xero_client.exchange_code(code, redirect_uri)
        else:
            token_data = await myob_client.exchange_code(code, redirect_uri)
    except Exception as exc:
        logger.error("OAuth token exchange failed for %s: %s", provider, exc, exc_info=True)
        return f"Token exchange failed: {exc}"

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 1800)

    # Store encrypted tokens
    stmt = select(AccountingIntegration).where(
        AccountingIntegration.org_id == org_id,
        AccountingIntegration.provider == provider,
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    if conn is None:
        conn = AccountingIntegration(org_id=org_id, provider=provider)
        db.add(conn)

    conn.access_token_encrypted = envelope_encrypt(access_token)
    conn.refresh_token_encrypted = envelope_encrypt(refresh_token)
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    conn.is_connected = True

    # Fetch and store Xero tenant ID + org name at connect time to avoid
    # redundant API calls on every sync.
    if provider == "xero":
        try:
            tenant_id = await xero_client.get_tenant_id(access_token)
            conn.xero_tenant_id = tenant_id
            if tenant_id:
                org_name = await xero_client.get_organisation_name(access_token, tenant_id)
                conn.account_name = org_name
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Failed to fetch Xero tenant info at connect: %s", exc)

    await db.flush()
    await db.refresh(conn)
    return _connection_to_dict(conn)


async def disconnect(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str,
) -> bool:
    """Disconnect an accounting integration.

    Clears tokens and marks as disconnected.
    Returns True if disconnected, False if not found.
    """
    stmt = select(AccountingIntegration).where(
        AccountingIntegration.org_id == org_id,
        AccountingIntegration.provider == provider,
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()
    if conn is None:
        return False

    conn.access_token_encrypted = None
    conn.refresh_token_encrypted = None
    conn.token_expires_at = None
    conn.is_connected = False
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Token refresh helper
# ---------------------------------------------------------------------------


async def _ensure_valid_token(
    db: AsyncSession,
    conn: AccountingIntegration,
) -> str | None:
    """Return a valid access token, refreshing if expired.

    Returns the access token string, or None if refresh fails.
    """
    if conn.access_token_encrypted is None or conn.refresh_token_encrypted is None:
        return None

    access_token = envelope_decrypt_str(conn.access_token_encrypted)

    # Check if token is still valid (with 60s buffer)
    if conn.token_expires_at and conn.token_expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
        return access_token

    # Token expired — refresh
    refresh_token = envelope_decrypt_str(conn.refresh_token_encrypted)
    try:
        if conn.provider == "xero":
            token_data = await xero_client.refresh_tokens(refresh_token)
        else:
            token_data = await myob_client.refresh_tokens(refresh_token)
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.error("Token refresh failed for %s org %s: %s", conn.provider, conn.org_id, exc, exc_info=True)
        return None

    new_access = token_data.get("access_token", "")
    new_refresh = token_data.get("refresh_token", refresh_token)
    expires_in = token_data.get("expires_in", 1800)

    conn.access_token_encrypted = envelope_encrypt(new_access)
    conn.refresh_token_encrypted = envelope_encrypt(new_refresh)
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await db.flush()

    return new_access


# ---------------------------------------------------------------------------
# Sync log
# ---------------------------------------------------------------------------


async def _log_sync(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str,
    entity_type: str,
    entity_id: uuid.UUID,
    status: str,
    external_id: str | None = None,
    error_message: str | None = None,
) -> AccountingSyncLog:
    """Write a sync attempt to the accounting_sync_log table.

    Requirements: 68.6
    """
    entry = AccountingSyncLog(
        org_id=org_id,
        provider=provider,
        entity_type=entity_type,
        entity_id=entity_id,
        status=status,
        external_id=external_id,
        error_message=error_message,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def get_sync_log(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Retrieve sync log entries for an organisation.

    Requirements: 68.6
    """
    stmt = (
        select(AccountingSyncLog)
        .where(AccountingSyncLog.org_id == org_id)
        .order_by(AccountingSyncLog.created_at.desc())
        .limit(limit)
    )
    if provider:
        stmt = stmt.where(AccountingSyncLog.provider == provider)

    result = await db.execute(stmt)
    entries = result.scalars().all()
    return {
        "entries": [_sync_log_to_dict(e) for e in entries],
        "total": len(entries),
    }


# ---------------------------------------------------------------------------
# Entity sync dispatch
# ---------------------------------------------------------------------------


async def sync_entity(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str,
    entity_type: str,
    entity_id: uuid.UUID,
    entity_data: dict[str, Any],
) -> dict[str, Any]:
    """Sync a single entity (invoice/payment/credit_note/contact) to the provider.

    Logs the result and returns the sync log entry dict.
    Requirements: 68.3, 68.4, 68.5, 68.6, 68.7
    """
    stmt = select(AccountingIntegration).where(
        AccountingIntegration.org_id == org_id,
        AccountingIntegration.provider == provider,
        AccountingIntegration.is_connected == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    if conn is None:
        entry = await _log_sync(
            db,
            org_id=org_id,
            provider=provider,
            entity_type=entity_type,
            entity_id=entity_id,
            status="failed",
            error_message=f"No active {provider} connection for this organisation",
        )
        return _sync_log_to_dict(entry)

    access_token = await _ensure_valid_token(db, conn)
    if access_token is None:
        entry = await _log_sync(
            db,
            org_id=org_id,
            provider=provider,
            entity_type=entity_type,
            entity_id=entity_id,
            status="failed",
            error_message="Failed to obtain valid access token",
        )
        return _sync_log_to_dict(entry)

    try:
        external_id = await _dispatch_sync(
            provider=provider,
            access_token=access_token,
            entity_type=entity_type,
            entity_data=entity_data,
            connection=conn,
        )
        conn.last_sync_at = datetime.now(timezone.utc)
        entry = await _log_sync(
            db,
            org_id=org_id,
            provider=provider,
            entity_type=entity_type,
            entity_id=entity_id,
            status="synced",
            external_id=external_id,
        )
    except (ValueError, KeyError, ConnectionError, TimeoutError, OSError) as exc:
        logger.error(
            "Sync failed for %s %s %s (org %s): %s",
            provider, entity_type, entity_id, org_id, exc, exc_info=True,
        )
        entry = await _log_sync(
            db,
            org_id=org_id,
            provider=provider,
            entity_type=entity_type,
            entity_id=entity_id,
            status="failed",
            error_message=str(exc)[:500],
        )

    return _sync_log_to_dict(entry)


async def _dispatch_sync(
    *,
    provider: str,
    access_token: str,
    entity_type: str,
    entity_data: dict[str, Any],
    connection: AccountingIntegration | None = None,
) -> str | None:
    """Route the sync call to the correct provider client.

    Returns the external ID from the provider response, or None.
    """
    if provider == "xero":
        # Use stored tenant ID from connection; fall back to API call only if missing
        tenant_id = (
            connection.xero_tenant_id if connection and connection.xero_tenant_id
            else entity_data.pop("_xero_tenant_id", None)
        )
        if not tenant_id:
            tenant_id = await xero_client.get_tenant_id(access_token)
        if not tenant_id:
            raise ValueError("Could not determine Xero tenant ID")

        if entity_type == "invoice":
            resp = await xero_client.sync_invoice(access_token, tenant_id, entity_data)
            invoices = resp.get("Invoices", [])
            return invoices[0].get("InvoiceID") if invoices else None
        elif entity_type == "payment":
            resp = await xero_client.sync_payment(access_token, tenant_id, entity_data)
            payments = resp.get("Payments", [])
            return payments[0].get("PaymentID") if payments else None
        elif entity_type == "credit_note":
            resp = await xero_client.sync_credit_note(access_token, tenant_id, entity_data)
            notes = resp.get("CreditNotes", [])
            return notes[0].get("CreditNoteID") if notes else None
        elif entity_type == "contact":
            resp = await xero_client.sync_contact(access_token, tenant_id, entity_data)
            contacts = resp.get("Contacts", [])
            return contacts[0].get("ContactID") if contacts else None

    elif provider == "myob":
        company_uri = entity_data.pop("_myob_company_uri", None)
        if not company_uri:
            cf = await myob_client.get_company_file(access_token)
            company_uri = cf.get("Uri") if cf else None
        if not company_uri:
            raise ValueError("Could not determine MYOB company file URI")

        if entity_type == "invoice":
            resp = await myob_client.sync_invoice(access_token, company_uri, entity_data)
            return resp.get("location")
        elif entity_type == "payment":
            resp = await myob_client.sync_payment(access_token, company_uri, entity_data)
            return resp.get("location")
        elif entity_type == "credit_note":
            resp = await myob_client.sync_credit_note(access_token, company_uri, entity_data)
            return resp.get("location")

    return None


# ---------------------------------------------------------------------------
# Entity data reconstruction for retries
# ---------------------------------------------------------------------------


async def _reconstruct_entity_data(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Fetch an entity from the DB and build the sync payload for retry.

    Returns the entity data dict, or None if the entity is not found.
    """
    if entity_type == "invoice":
        from app.modules.invoices.models import Invoice, LineItem
        stmt = select(Invoice).where(Invoice.id == entity_id, Invoice.org_id == org_id)
        result = await db.execute(stmt)
        invoice = result.scalar_one_or_none()
        if invoice is None:
            return None

        # Fetch line items
        li_stmt = select(LineItem).where(LineItem.invoice_id == entity_id)
        li_result = await db.execute(li_stmt)
        line_items = li_result.scalars().all()

        return {
            "id": str(invoice.id),
            "invoice_number": invoice.invoice_number or "",
            "customer_name": invoice.customer_name or "Unknown",
            "date": invoice.issue_date.strftime("%Y-%m-%d") if invoice.issue_date else "",
            "due_date": invoice.due_date.strftime("%Y-%m-%d") if invoice.due_date else "",
            "currency": getattr(invoice, "currency", "NZD") or "NZD",
            "gst_inclusive": True,
            "line_items": [
                {
                    "description": li.description or "",
                    "quantity": float(li.quantity) if li.quantity else 1,
                    "unit_price": float(li.unit_price) if li.unit_price else 0,
                    "account_code": "200",
                }
                for li in line_items
            ],
        }

    elif entity_type == "payment":
        from app.modules.payments.models import Payment
        from app.modules.invoices.models import Invoice
        stmt = select(Payment).where(Payment.id == entity_id, Payment.org_id == org_id)
        result = await db.execute(stmt)
        payment = result.scalar_one_or_none()
        if payment is None:
            return None

        # Get invoice number for the payment
        inv_stmt = select(Invoice.invoice_number).where(Invoice.id == payment.invoice_id)
        inv_result = await db.execute(inv_stmt)
        invoice_number = inv_result.scalar_one_or_none() or ""

        return {
            "id": str(payment.id),
            "invoice_number": invoice_number,
            "amount": float(payment.amount),
            "date": payment.created_at.strftime("%Y-%m-%d") if payment.created_at else "",
            "account_code": "090",
            "reference": f"Payment {payment.id}",
        }

    elif entity_type == "credit_note":
        from app.modules.invoices.models import CreditNote
        stmt = select(CreditNote).where(CreditNote.id == entity_id, CreditNote.org_id == org_id)
        result = await db.execute(stmt)
        cn = result.scalar_one_or_none()
        if cn is None:
            return None

        return {
            "id": str(cn.id),
            "credit_note_number": getattr(cn, "credit_note_number", "") or "",
            "customer_name": getattr(cn, "customer_name", "Unknown") or "Unknown",
            "date": cn.created_at.strftime("%Y-%m-%d") if cn.created_at else "",
            "currency": "NZD",
            "gst_inclusive": True,
            "line_items": [
                {
                    "description": getattr(cn, "reason", "Credit note"),
                    "quantity": 1,
                    "unit_price": float(getattr(cn, "amount", 0)),
                    "account_code": "200",
                }
            ],
        }

    elif entity_type == "contact":
        from app.modules.customers.models import Customer
        stmt = select(Customer).where(Customer.id == entity_id, Customer.org_id == org_id)
        result = await db.execute(stmt)
        customer = result.scalar_one_or_none()
        if customer is None:
            return None

        return {
            "id": str(customer.id),
            "first_name": customer.first_name or "",
            "last_name": customer.last_name or "",
            "display_name": customer.display_name or "",
            "email": customer.email,
            "phone": customer.phone,
            "mobile_phone": customer.mobile_phone,
            "company_name": customer.company_name,
            "billing_address": customer.billing_address,
        }

    return None


# ---------------------------------------------------------------------------
# Manual retry — re-sync all failed entries for a provider
# ---------------------------------------------------------------------------


async def retry_failed_syncs(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: str,
) -> dict[str, Any]:
    """Retry all failed sync entries for a provider.

    Fetches each entity from the DB by entity_id and entity_type,
    reconstructs the correct sync payload, then calls sync_entity().

    Returns a summary of results.
    Requirements: 68.6
    """
    stmt = (
        select(AccountingSyncLog)
        .where(
            AccountingSyncLog.org_id == org_id,
            AccountingSyncLog.provider == provider,
            AccountingSyncLog.status == "failed",
        )
        .order_by(AccountingSyncLog.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    failed_entries = result.scalars().all()

    synced = 0
    failed = 0

    for entry in failed_entries:
        try:
            entity_data = await _reconstruct_entity_data(
                db, org_id=org_id, entity_type=entry.entity_type, entity_id=entry.entity_id,
            )
            if entity_data is None:
                logger.warning(
                    "Cannot retry sync %s: %s %s not found in DB",
                    entry.id, entry.entity_type, entry.entity_id,
                )
                failed += 1
                continue

            new_entry = await sync_entity(
                db,
                org_id=org_id,
                provider=provider,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                entity_data=entity_data,
            )
            if new_entry.get("status") == "synced":
                synced += 1
            else:
                failed += 1
        except (ValueError, KeyError, ConnectionError, TimeoutError, OSError) as exc:
            logger.error("Retry failed for sync entry %s: %s", entry.id, exc, exc_info=True)
            failed += 1

    return {
        "provider": provider,
        "synced": synced,
        "failed": failed,
        "message": f"Retried {synced + failed} failed syncs: {synced} succeeded, {failed} failed",
    }

"""Xero OAuth 2.0 client — invoice, payment, credit note, refund, and contact sync.

Handles OAuth authorization flow, token management, and entity
synchronisation with the Xero Accounting API.

Requirements: 68.1, 68.3, 68.4, 68.5, 68.6, 68.7
"""

from __future__ import annotations

import logging
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Xero API constants
# ---------------------------------------------------------------------------

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"

SCOPES = (
    "openid profile email offline_access "
    "accounting.invoices accounting.payments "
    "accounting.contacts accounting.settings"
)
HTTP_TIMEOUT = 15

# ---------------------------------------------------------------------------
# Rate limiter — respects Xero's per-tenant limits (60/min, 5 concurrent)
# ---------------------------------------------------------------------------

import asyncio
import time
from collections import defaultdict

_tenant_locks: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(5))
_tenant_call_times: dict[str, list[float]] = defaultdict(list)
_CALLS_PER_MINUTE = 55  # stay under the 60/min limit with a small buffer


async def _rate_limited_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    tenant_id: str = "",
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request with per-tenant rate limiting and 429 retry.

    Enforces:
    - Max 5 concurrent requests per tenant (semaphore)
    - Max 55 requests per minute per tenant (sliding window)
    - Automatic retry on 429 with Retry-After header
    """
    sem = _tenant_locks[tenant_id]

    # Sliding window: wait if we've hit the per-minute limit
    now = time.monotonic()
    times = _tenant_call_times[tenant_id]
    # Prune entries older than 60s
    cutoff = now - 60
    _tenant_call_times[tenant_id] = [t for t in times if t > cutoff]
    times = _tenant_call_times[tenant_id]

    if len(times) >= _CALLS_PER_MINUTE:
        wait = times[0] - cutoff
        if wait > 0:
            logger.info("Xero rate limit: waiting %.1fs for tenant %s", wait, tenant_id[:8])
            await asyncio.sleep(wait)

    async with sem:
        _tenant_call_times[tenant_id].append(time.monotonic())
        resp = await client.request(method, url, **kwargs)

        # Handle 429 Too Many Requests
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning(
                "Xero 429 rate limited (tenant %s), retrying after %ds",
                tenant_id[:8], retry_after,
            )
            await asyncio.sleep(retry_after)
            resp = await client.request(method, url, **kwargs)

        return resp


async def _xero_api_call(
    method: str,
    url: str,
    *,
    access_token: str,
    tenant_id: str = "",
    **kwargs: Any,
) -> httpx.Response:
    """Make a rate-limited Xero API call with standard headers.

    Adds Authorization and Xero-Tenant-Id headers automatically.
    Logs error bodies for non-200 responses.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        **({"Xero-Tenant-Id": tenant_id} if tenant_id else {}),
        **kwargs.pop("headers", {}),
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await _rate_limited_request(
            client, method, url, tenant_id=tenant_id, headers=headers, **kwargs,
        )
        if resp.status_code >= 400:
            logger.error("Xero API %s %s: status=%s body=%s", method, url, resp.status_code, resp.text[:500])
        return resp


# ---------------------------------------------------------------------------
# Credential helpers — DB (platform_settings) takes precedence over env vars
# ---------------------------------------------------------------------------


async def _get_xero_client_id() -> str:
    """Return the Xero Client ID from platform_settings DB, falling back to env."""
    try:
        from app.core.database import async_session_factory
        from app.modules.platform_settings.service import get_setting
        async with async_session_factory() as db:
            val = await get_setting(db, "XERO_CLIENT_ID")
            if val:
                return val
    except Exception:
        pass
    return settings.xero_client_id


async def _get_xero_client_secret() -> str:
    """Return the Xero Client Secret from platform_settings DB, falling back to env."""
    try:
        from app.core.database import async_session_factory
        from app.modules.platform_settings.service import get_setting
        async with async_session_factory() as db:
            val = await get_setting(db, "XERO_CLIENT_SECRET")
            if val:
                return val
    except Exception:
        pass
    return settings.xero_client_secret


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------


async def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Build the Xero OAuth 2.0 authorization URL.

    Reads client_id from platform_settings DB, falling back to env var.
    Requirements: 68.1
    """
    client_id = await _get_xero_client_id()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
    }
    return f"{XERO_AUTH_URL}?{urllib.parse.urlencode(params)}"


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Build the Basic auth header value per Xero docs.

    Authorization: "Basic " + base64encode(client_id + ":" + client_secret)
    """
    import base64
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


async def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Uses Basic auth header per Xero OAuth 2.0 docs.
    Returns the raw token response dict from Xero.
    Requirements: 68.1
    """
    client_id = await _get_xero_client_id()
    client_secret = await _get_xero_client_secret()

    logger.warning("Xero token exchange — redirect_uri=%s client_id=%s...", redirect_uri, client_id[:8] if client_id else "EMPTY")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": _basic_auth_header(client_id, client_secret),
            },
        )
        if resp.status_code != 200:
            logger.error(
                "Xero token exchange failed: status=%s body=%s",
                resp.status_code, resp.text,
            )
        resp.raise_for_status()
        return resp.json()


async def refresh_tokens(refresh_token: str) -> dict[str, Any]:
    """Refresh an expired access token using the refresh token.

    Uses Basic auth header per Xero OAuth 2.0 docs.
    Returns the new token response dict.
    Requirements: 68.1
    """
    client_id = await _get_xero_client_id()
    client_secret = await _get_xero_client_secret()

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": _basic_auth_header(client_id, client_secret),
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_tenant_id(access_token: str) -> str | None:
    """Retrieve the first connected Xero tenant ID."""
    resp = await _xero_api_call("GET", XERO_CONNECTIONS_URL, access_token=access_token)
    resp.raise_for_status()
    connections = resp.json()
    if connections:
        return connections[0].get("tenantId")
    return None


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------


async def check_connection(access_token: str, tenant_id: str) -> bool:
    """Verify the Xero connection is still valid."""
    try:
        resp = await _xero_api_call(
            "GET", f"{XERO_API_BASE}/Organisation",
            access_token=access_token, tenant_id=tenant_id,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def get_organisation_name(access_token: str, tenant_id: str) -> str | None:
    """Retrieve the connected Xero organisation name."""
    try:
        resp = await _xero_api_call(
            "GET", f"{XERO_API_BASE}/Organisation",
            access_token=access_token, tenant_id=tenant_id,
        )
        resp.raise_for_status()
        data = resp.json()
        orgs = data.get("Organisations", [])
        if orgs:
            return orgs[0].get("Name")
    except httpx.HTTPError:
        pass
    return None


# ---------------------------------------------------------------------------
# Invoice sync
# ---------------------------------------------------------------------------


async def sync_invoice(
    access_token: str,
    tenant_id: str,
    invoice_data: dict[str, Any],
) -> dict[str, Any]:
    """Create or update an invoice in Xero.

    Returns the Xero response containing the created/updated invoice.
    Requirements: 68.3
    """
    raw_date = invoice_data.get("date", "")
    raw_due = invoice_data.get("due_date", "")
    inv_date = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date or "")
    due_date = raw_due.strftime("%Y-%m-%d") if hasattr(raw_due, "strftime") else str(raw_due or "")

    payload = {
        "Invoices": [
            {
                "Type": "ACCREC",
                "Contact": {"Name": invoice_data.get("customer_name", "Unknown")},
                "Date": inv_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "DueDate": due_date,
                "InvoiceNumber": invoice_data.get("invoice_number", ""),
                "Reference": "",
                "Status": "AUTHORISED",
                "LineItems": [
                    {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": str(item.get("unit_price", 0)),
                        "AccountCode": item.get("account_code", "200"),
                        "TaxType": "OUTPUT2" if invoice_data.get("gst_inclusive", True) else "NONE",
                    }
                    for item in invoice_data.get("line_items", [])
                ],
                "CurrencyCode": invoice_data.get("currency", "NZD"),
            }
        ]
    }

    resp = await _xero_api_call(
        "POST", f"{XERO_API_BASE}/Invoices",
        access_token=access_token, tenant_id=tenant_id, json=payload,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Payment sync
# ---------------------------------------------------------------------------


async def sync_payment(
    access_token: str,
    tenant_id: str,
    payment_data: dict[str, Any],
) -> dict[str, Any]:
    """Record a payment in Xero against an existing invoice.

    Automatically discovers the first active BANK account in the Xero org
    since our invoicing app doesn't track bank accounts.
    Requirements: 68.4
    """
    raw_date = payment_data.get("date", "")
    pay_date = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date or "")

    # Discover the Xero bank account dynamically
    account_code = None
    account_id = None
    acct_resp = await _xero_api_call(
        "GET", f"{XERO_API_BASE}/Accounts",
        access_token=access_token, tenant_id=tenant_id,
    )
    if acct_resp.status_code == 200:
        all_accounts = acct_resp.json().get("Accounts", [])
        bank_accounts = [
            a for a in all_accounts
            if a.get("Type") == "BANK" and a.get("Status") == "ACTIVE"
        ]
        logger.warning(
            "Xero accounts: %d total, %d BANK. Types: %s",
            len(all_accounts), len(bank_accounts),
            sorted(set(a.get("Type", "?") for a in all_accounts)),
        )
        if bank_accounts:
            ba = bank_accounts[0]
            account_code = ba.get("Code") or None
            account_id = ba.get("AccountID") or None
            logger.warning("Xero payment: using bank code=%s id=%s (%s)", account_code, account_id, ba.get("Name"))
    else:
        logger.error("Xero Accounts API failed: status=%s body=%s", acct_resp.status_code, acct_resp.text[:200])
    if not account_code and not account_id:
        raise ValueError("No active BANK account found in Xero. Add one at Settings > Chart of Accounts > Add Bank Account")

    # Build account reference — prefer Code, fall back to AccountID
    account_ref = {"Code": account_code} if account_code else {"AccountID": account_id}

    payload = {
        "Payments": [
            {
                "Invoice": {"InvoiceNumber": payment_data.get("invoice_number", "")},
                "Account": account_ref,
                "Date": pay_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "Amount": float(payment_data.get("amount", 0)),
                "Reference": payment_data.get("reference", ""),
            }
        ]
    }

    resp = await _xero_api_call(
        "POST", f"{XERO_API_BASE}/Payments",
        access_token=access_token, tenant_id=tenant_id, json=payload,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Credit note sync
# ---------------------------------------------------------------------------


async def sync_credit_note(
    access_token: str,
    tenant_id: str,
    credit_note_data: dict[str, Any],
) -> dict[str, Any]:
    """Create a credit note in Xero.

    Requirements: 68.5
    """
    raw_date = credit_note_data.get("date", "")
    cn_date = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date or "")

    payload = {
        "CreditNotes": [
            {
                "Type": "ACCRECCREDIT",
                "Contact": {"Name": credit_note_data.get("customer_name", "Unknown")},
                "Date": cn_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "Reference": credit_note_data.get("credit_note_number", ""),
                "Status": "AUTHORISED",
                "LineItems": [
                    {
                        "Description": item.get("description", ""),
                        "Quantity": item.get("quantity", 1),
                        "UnitAmount": str(item.get("unit_price", 0)),
                        "AccountCode": item.get("account_code", "200"),
                        "TaxType": "OUTPUT2" if credit_note_data.get("gst_inclusive", True) else "NONE",
                    }
                    for item in credit_note_data.get("line_items", [])
                ],
                "CurrencyCode": credit_note_data.get("currency", "NZD"),
            }
        ]
    }

    resp = await _xero_api_call(
        "PUT", f"{XERO_API_BASE}/CreditNotes",
        access_token=access_token, tenant_id=tenant_id, json=payload,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Refund sync (Credit Note + Allocation)
# ---------------------------------------------------------------------------


def _build_refund_credit_note_payload(refund_data: dict[str, Any]) -> dict[str, Any]:
    """Build the Xero Credit Note payload for a refund.

    Extracted as a pure function for testability (Property 1).
    Requirements: 1.1, 1.3, 1.4
    """
    raw_date = refund_data.get("date", "")
    ref_date = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date or "")

    return {
        "CreditNotes": [
            {
                "Type": "ACCRECCREDIT",
                "Contact": {"Name": refund_data.get("customer_name", "Unknown")},
                "Date": ref_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "Reference": f"Refund for {refund_data.get('invoice_number', '')}",
                "Status": "AUTHORISED",
                "LineAmountTypes": "Inclusive",
                "LineItems": [
                    {
                        "Description": f"Refund: {refund_data.get('reason', '')}",
                        "Quantity": 1,
                        "UnitAmount": str(float(refund_data.get("amount", 0))),
                        "AccountCode": "200",
                        "TaxType": "OUTPUT2",
                    }
                ],
                "CurrencyCode": "NZD",
            }
        ]
    }


def _build_refund_allocation_payload(
    refund_data: dict[str, Any],
    xero_invoice_id: str | None = None,
) -> dict[str, Any]:
    """Build the Xero Allocation payload to link a credit note to an invoice.

    Per Xero API docs, the PUT /CreditNotes/{id}/Allocations endpoint expects
    a flat object: {"Invoice": {"InvoiceID": "..."}, "Amount": ..., "Date": "..."}

    Uses InvoiceID (Xero UUID) when available, falls back to InvoiceNumber.

    Extracted as a pure function for testability (Property 2).
    Requirements: 1.2
    """
    raw_date = refund_data.get("date", "")
    ref_date = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date or "")

    invoice_ref: dict[str, str] = {}
    if xero_invoice_id:
        invoice_ref["InvoiceID"] = xero_invoice_id
    else:
        invoice_ref["InvoiceNumber"] = refund_data.get("invoice_number", "")

    return {
        "Invoice": invoice_ref,
        "Amount": float(refund_data.get("amount", 0)),
        "Date": ref_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


async def _lookup_xero_invoice_id(
    access_token: str,
    tenant_id: str,
    invoice_number: str,
) -> str | None:
    """Look up a Xero InvoiceID by InvoiceNumber.

    Returns the Xero UUID string, or None if not found.
    """
    try:
        resp = await _xero_api_call(
            "GET",
            f"{XERO_API_BASE}/Invoices?where=InvoiceNumber%3D%22{invoice_number}%22",
            access_token=access_token,
            tenant_id=tenant_id,
        )
        resp.raise_for_status()
        invoices = resp.json().get("Invoices", [])
        if invoices:
            return invoices[0].get("InvoiceID")
    except Exception:
        logger.warning("Failed to look up Xero InvoiceID for %s", invoice_number)
    return None


async def sync_refund(
    access_token: str,
    tenant_id: str,
    refund_data: dict[str, Any],
) -> dict[str, Any]:
    """Create a Credit Note in Xero and refund it via the Payments endpoint.

    Two-step process (per Xero docs — "To refund credit notes use the payments endpoint"):
    1. POST /CreditNotes — create the ACCRECCREDIT credit note (AUTHORISED)
    2. PUT /Payments — refund the credit note to the bank account

    This correctly handles refunds on paid invoices. The credit note records
    the accounting entry, and the refund payment records the money going back
    to the customer.

    If step 2 fails after step 1 succeeds, logs partial failure with CreditNoteID
    and re-raises so the caller can record the failure.

    Returns the full Xero Credit Note response dict.
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 7.1, 7.3, 7.4
    """
    # Step 1: Create the Credit Note
    cn_payload = _build_refund_credit_note_payload(refund_data)

    resp = await _xero_api_call(
        "POST", f"{XERO_API_BASE}/CreditNotes",
        access_token=access_token, tenant_id=tenant_id, json=cn_payload,
    )
    resp.raise_for_status()
    cn_response = resp.json()

    # Extract CreditNoteID
    credit_note_id = cn_response.get("CreditNotes", [{}])[0].get("CreditNoteID")

    # Step 2: Discover the Xero bank account (same pattern as sync_payment)
    account_ref: dict[str, str] = {}
    acct_resp = await _xero_api_call(
        "GET", f"{XERO_API_BASE}/Accounts",
        access_token=access_token, tenant_id=tenant_id,
    )
    if acct_resp.status_code == 200:
        all_accounts = acct_resp.json().get("Accounts", [])
        bank_accounts = [
            a for a in all_accounts
            if a.get("Type") == "BANK" and a.get("Status") == "ACTIVE"
        ]
        if bank_accounts:
            ba = bank_accounts[0]
            code = ba.get("Code")
            account_ref = {"Code": code} if code else {"AccountID": ba.get("AccountID", "")}

    if not account_ref:
        logger.error(
            "Xero refund: Credit Note %s created but no BANK account found for refund payment",
            credit_note_id,
        )
        raise ValueError("No active BANK account found in Xero for refund payment")

    # Step 3: Refund the Credit Note via the Payments endpoint
    raw_date = refund_data.get("date", "")
    ref_date = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date or "")

    refund_payment_payload = {
        "CreditNote": {"CreditNoteID": credit_note_id},
        "Account": account_ref,
        "Date": ref_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "Amount": float(refund_data.get("amount", 0)),
        "Reference": f"Refund for {refund_data.get('invoice_number', '')}",
    }

    try:
        pay_resp = await _xero_api_call(
            "PUT", f"{XERO_API_BASE}/Payments",
            access_token=access_token, tenant_id=tenant_id, json=refund_payment_payload,
        )
        if pay_resp.status_code >= 400:
            logger.error(
                "Xero refund payment full response: %s", pay_resp.text[:2000],
            )
        pay_resp.raise_for_status()
    except Exception:
        logger.error(
            "Xero refund: Credit Note %s created but refund payment failed for invoice %s",
            credit_note_id, refund_data.get("invoice_number"),
        )
        raise

    return cn_response


# ---------------------------------------------------------------------------
# Contact sync
# ---------------------------------------------------------------------------


async def sync_contact(
    access_token: str,
    tenant_id: str,
    contact_data: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a contact in Xero.

    Returns the Xero response containing the created/updated contact.
    Requirements: 68.7
    """
    # Build Name: prefer display_name, fall back to first + last
    name = contact_data.get("display_name") or ""
    if not name:
        first = contact_data.get("first_name", "")
        last = contact_data.get("last_name", "")
        name = f"{first} {last}".strip() or "Unknown"

    contact: dict[str, Any] = {
        "Name": name,
        "FirstName": contact_data.get("first_name", ""),
        "LastName": contact_data.get("last_name", ""),
    }

    email = contact_data.get("email")
    if email:
        contact["EmailAddress"] = email

    # Phones — map phone and mobile_phone
    phones: list[dict[str, str]] = []
    if contact_data.get("phone"):
        phones.append({"PhoneType": "DEFAULT", "PhoneNumber": contact_data["phone"]})
    if contact_data.get("mobile_phone"):
        phones.append({"PhoneType": "MOBILE", "PhoneNumber": contact_data["mobile_phone"]})
    if phones:
        contact["Phones"] = phones

    # Addresses — map billing_address
    billing = contact_data.get("billing_address")
    if billing and isinstance(billing, dict):
        address: dict[str, str] = {"AddressType": "POBOX"}
        if billing.get("line1"):
            address["AddressLine1"] = billing["line1"]
        if billing.get("line2"):
            address["AddressLine2"] = billing["line2"]
        if billing.get("city"):
            address["City"] = billing["city"]
        if billing.get("region"):
            address["Region"] = billing["region"]
        if billing.get("postal_code"):
            address["PostalCode"] = billing["postal_code"]
        if billing.get("country"):
            address["Country"] = billing["country"]
        contact["Addresses"] = [address]

    payload = {"Contacts": [contact]}

    resp = await _xero_api_call(
        "POST", f"{XERO_API_BASE}/Contacts",
        access_token=access_token, tenant_id=tenant_id, json=payload,
    )
    resp.raise_for_status()
    return resp.json()

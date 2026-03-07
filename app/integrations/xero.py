"""Xero OAuth 2.0 client — invoice, payment, and credit note sync.

Handles OAuth authorization flow, token management, and entity
synchronisation with the Xero Accounting API.

Requirements: 68.1, 68.3, 68.4, 68.5, 68.6
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

SCOPES = "openid profile email accounting.transactions accounting.contacts offline_access"
HTTP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------


def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Build the Xero OAuth 2.0 authorization URL.

    Requirements: 68.1
    """
    params = {
        "response_type": "code",
        "client_id": settings.xero_client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
    }
    return f"{XERO_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Returns the raw token response dict from Xero.
    Requirements: 68.1
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.xero_client_id,
                "client_secret": settings.xero_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_tokens(refresh_token: str) -> dict[str, Any]:
    """Refresh an expired access token using the refresh token.

    Returns the new token response dict.
    Requirements: 68.1
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.xero_client_id,
                "client_secret": settings.xero_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_tenant_id(access_token: str) -> str | None:
    """Retrieve the first connected Xero tenant ID.

    Requirements: 68.1
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        connections = resp.json()
        if connections:
            return connections[0].get("tenantId")
    return None


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------


async def check_connection(access_token: str, tenant_id: str) -> bool:
    """Verify the Xero connection is still valid.

    Requirements: 68.1
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{XERO_API_BASE}/Organisation",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Xero-Tenant-Id": tenant_id,
                    "Accept": "application/json",
                },
            )
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


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
    payload = {
        "Invoices": [
            {
                "Type": "ACCREC",
                "Contact": {"Name": invoice_data.get("customer_name", "Unknown")},
                "Date": invoice_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "DueDate": invoice_data.get("due_date", ""),
                "Reference": invoice_data.get("invoice_number", ""),
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

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            f"{XERO_API_BASE}/Invoices",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
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

    Requirements: 68.4
    """
    payload = {
        "Payments": [
            {
                "Invoice": {"InvoiceNumber": payment_data.get("invoice_number", "")},
                "Account": {"Code": payment_data.get("account_code", "090")},
                "Date": payment_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "Amount": str(payment_data.get("amount", 0)),
                "Reference": payment_data.get("reference", ""),
                "CurrencyRate": payment_data.get("currency_rate", 1.0),
            }
        ]
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.put(
            f"{XERO_API_BASE}/Payments",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
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
    payload = {
        "CreditNotes": [
            {
                "Type": "ACCRECCREDIT",
                "Contact": {"Name": credit_note_data.get("customer_name", "Unknown")},
                "Date": credit_note_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
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

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.put(
            f"{XERO_API_BASE}/CreditNotes",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()

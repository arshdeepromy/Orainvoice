"""MYOB AccountRight API client — invoice, payment, and credit note sync.

Handles OAuth authorization flow, token management, and entity
synchronisation with the MYOB AccountRight Live API.

Requirements: 68.2, 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MYOB API constants
# ---------------------------------------------------------------------------

MYOB_AUTH_URL = "https://secure.myob.com/oauth2/account/authorize"
MYOB_TOKEN_URL = "https://secure.myob.com/oauth2/v1/authorize"
MYOB_API_BASE = "https://api.myob.com/accountright"

HTTP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# OAuth helpers
# ---------------------------------------------------------------------------


def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Build the MYOB OAuth 2.0 authorization URL.

    Requirements: 68.2
    """
    params = {
        "response_type": "code",
        "client_id": settings.myob_client_id,
        "redirect_uri": redirect_uri,
        "scope": "CompanyFile",
        "state": state,
    }
    return f"{MYOB_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Returns the raw token response dict from MYOB.
    Requirements: 68.2
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            MYOB_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.myob_client_id,
                "client_secret": settings.myob_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_tokens(refresh_token: str) -> dict[str, Any]:
    """Refresh an expired access token using the refresh token.

    Returns the new token response dict.
    Requirements: 68.2
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            MYOB_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.myob_client_id,
                "client_secret": settings.myob_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_company_file(access_token: str) -> dict[str, Any] | None:
    """Retrieve the first available MYOB company file.

    Requirements: 68.2
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.get(
            MYOB_API_BASE,
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-myobapi-key": settings.myob_client_id,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        files = resp.json()
        if files:
            return files[0] if isinstance(files, list) else None
    return None


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------


async def check_connection(access_token: str) -> bool:
    """Verify the MYOB connection is still valid.

    Requirements: 68.2
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                MYOB_API_BASE,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "x-myobapi-key": settings.myob_client_id,
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
    company_file_uri: str,
    invoice_data: dict[str, Any],
) -> dict[str, Any]:
    """Create or update a sale invoice in MYOB.

    Requirements: 68.3
    """
    payload = {
        "Number": invoice_data.get("invoice_number", ""),
        "Date": invoice_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        "Customer": {"Name": invoice_data.get("customer_name", "Unknown")},
        "IsTaxInclusive": invoice_data.get("gst_inclusive", True),
        "Lines": [
            {
                "Description": item.get("description", ""),
                "Total": str(item.get("total", 0)),
                "TaxCode": {"Code": "GST"} if invoice_data.get("gst_inclusive", True) else {"Code": "N-T"},
            }
            for item in invoice_data.get("line_items", [])
        ],
    }

    url = f"{company_file_uri}/Sale/Invoice/Service"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-myobapi-key": settings.myob_client_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        # MYOB returns 201 with Location header for created resources
        return {"status": "created", "location": resp.headers.get("Location", "")}


# ---------------------------------------------------------------------------
# Payment sync
# ---------------------------------------------------------------------------


async def sync_payment(
    access_token: str,
    company_file_uri: str,
    payment_data: dict[str, Any],
) -> dict[str, Any]:
    """Record a customer payment in MYOB.

    Requirements: 68.4
    """
    payload = {
        "ReceiveFrom": payment_data.get("customer_name", "Unknown"),
        "Account": {"Name": payment_data.get("account_name", "Undeposited Funds")},
        "Date": payment_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        "AmountReceived": str(payment_data.get("amount", 0)),
        "Memo": payment_data.get("reference", ""),
        "Invoices": [
            {
                "Number": payment_data.get("invoice_number", ""),
                "AmountApplied": str(payment_data.get("amount", 0)),
            }
        ],
    }

    url = f"{company_file_uri}/Sale/CustomerPayment"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-myobapi-key": settings.myob_client_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return {"status": "created", "location": resp.headers.get("Location", "")}


# ---------------------------------------------------------------------------
# Credit note sync
# ---------------------------------------------------------------------------


async def sync_credit_note(
    access_token: str,
    company_file_uri: str,
    credit_note_data: dict[str, Any],
) -> dict[str, Any]:
    """Create a credit note (credit settlement) in MYOB.

    Requirements: 68.5
    """
    payload = {
        "Number": credit_note_data.get("credit_note_number", ""),
        "Date": credit_note_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        "Customer": {"Name": credit_note_data.get("customer_name", "Unknown")},
        "IsTaxInclusive": credit_note_data.get("gst_inclusive", True),
        "Lines": [
            {
                "Description": item.get("description", ""),
                "Total": str(item.get("total", 0)),
                "TaxCode": {"Code": "GST"} if credit_note_data.get("gst_inclusive", True) else {"Code": "N-T"},
            }
            for item in credit_note_data.get("line_items", [])
        ],
    }

    url = f"{company_file_uri}/Sale/CreditSettlement"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "x-myobapi-key": settings.myob_client_id,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return {"status": "created", "location": resp.headers.get("Location", "")}

"""Akahu OAuth 2.0 client — bank account and transaction sync.

Handles OAuth authorization flow, token management, and bank data
synchronisation with the Akahu open banking API.

Requirements: 15.1–15.5, 16.1–16.3, 17.1–17.5, 33.1–33.3
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.banking.models import AkahuConnection, BankAccount, BankTransaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Akahu API constants
# ---------------------------------------------------------------------------

AKAHU_AUTH_URL = "https://oauth.akahu.io/authorize"
AKAHU_TOKEN_URL = "https://api.akahu.io/token"
AKAHU_API_BASE = "https://api.akahu.io/v1"

HTTP_TIMEOUT = 10
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds

# Mask pattern for detecting masked tokens in API requests
MASK_PATTERN_PREFIX = "****"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_masked(value: str | None) -> bool:
    """Detect if a value is a mask pattern (should not overwrite real tokens)."""
    if not value:
        return False
    return value.startswith("****") or all(c == "*" for c in value)


def _mask_token(token: str | None) -> str | None:
    """Mask a token for safe display in API responses."""
    if not token:
        return None
    if len(token) <= 8:
        return "****"
    return "****" + token[-4:]


async def _akahu_request(
    method: str,
    url: str,
    *,
    access_token: str | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request to Akahu with retry + exponential backoff.

    Uses httpx.AsyncClient with 10s timeout and 3 retries.
    """
    headers = {
        "Accept": "application/json",
        "X-Akahu-Id": settings.akahu_app_token if hasattr(settings, "akahu_app_token") else "",
        **kwargs.pop("headers", {}),
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.request(method, url, headers=headers, **kwargs)
                if resp.status_code < 500:
                    return resp
                # Server error — retry
                logger.warning(
                    "Akahu %s %s: status=%s (attempt %d/%d)",
                    method, url, resp.status_code, attempt + 1, MAX_RETRIES,
                )
                last_exc = httpx.HTTPStatusError(
                    f"Server error {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "Akahu %s %s: %s (attempt %d/%d)",
                method, url, exc, attempt + 1, MAX_RETRIES,
            )
            last_exc = exc

        if attempt < MAX_RETRIES - 1:
            backoff = INITIAL_BACKOFF * (2 ** attempt)
            await asyncio.sleep(backoff)

    raise last_exc or httpx.HTTPError("Akahu request failed after retries")


# ---------------------------------------------------------------------------
# OAuth 2.0 flow
# ---------------------------------------------------------------------------


async def initiate_connection(redirect_uri: str, state: str) -> str:
    """Build the Akahu OAuth 2.0 authorization URL.

    Requirements: 15.1
    """
    import urllib.parse

    params = {
        "response_type": "code",
        "client_id": getattr(settings, "akahu_client_id", ""),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AKAHU_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def handle_callback(
    db: AsyncSession,
    org_id: uuid.UUID,
    code: str,
    redirect_uri: str,
) -> AkahuConnection:
    """Exchange authorization code for tokens and store encrypted.

    Requirements: 15.1, 15.2, 33.1
    """
    resp = await _akahu_request(
        "POST",
        AKAHU_TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": getattr(settings, "akahu_client_id", ""),
            "client_secret": getattr(settings, "akahu_client_secret", ""),
        },
    )
    resp.raise_for_status()
    token_data = resp.json()

    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 3600)

    # Upsert connection
    stmt = select(AkahuConnection).where(AkahuConnection.org_id == org_id)
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    encrypted_token = envelope_encrypt(access_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    if conn:
        conn.access_token_encrypted = encrypted_token
        conn.token_expires_at = expires_at
        conn.is_active = True
    else:
        conn = AkahuConnection(
            org_id=org_id,
            access_token_encrypted=encrypted_token,
            token_expires_at=expires_at,
            is_active=True,
        )
        db.add(conn)

    await db.flush()
    await db.refresh(conn)
    return conn


async def refresh_token(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> AkahuConnection | None:
    """Refresh the Akahu access token if expired.

    Requirements: 15.1
    """
    stmt = select(AkahuConnection).where(
        AkahuConnection.org_id == org_id,
        AkahuConnection.is_active.is_(True),
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()
    if not conn or not conn.access_token_encrypted:
        return None

    # Check if token is still valid
    if conn.token_expires_at and conn.token_expires_at > datetime.now(timezone.utc):
        return conn

    # Akahu uses long-lived tokens; if expired, user must re-authorize
    conn.is_active = False
    await db.flush()
    await db.refresh(conn)
    return conn


async def _get_access_token(db: AsyncSession, org_id: uuid.UUID) -> str | None:
    """Retrieve and decrypt the active Akahu access token."""
    stmt = select(AkahuConnection).where(
        AkahuConnection.org_id == org_id,
        AkahuConnection.is_active.is_(True),
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()
    if not conn or not conn.access_token_encrypted:
        return None
    return envelope_decrypt_str(conn.access_token_encrypted)


# ---------------------------------------------------------------------------
# Bank account sync
# ---------------------------------------------------------------------------


async def sync_accounts(db: AsyncSession, org_id: uuid.UUID) -> list[BankAccount]:
    """Fetch bank accounts from Akahu API and upsert to bank_accounts table.

    Requirements: 16.1, 16.2
    """
    access_token = await _get_access_token(db, org_id)
    if not access_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail={
            "code": "AKAHU_AUTH_FAILED",
            "message": "No active Akahu connection — please connect first",
        })

    resp = await _akahu_request(
        "GET",
        f"{AKAHU_API_BASE}/accounts",
        access_token=access_token,
    )
    resp.raise_for_status()
    data = resp.json()
    accounts_data = data.get("items", data.get("accounts", []))

    upserted: list[BankAccount] = []
    for acct in accounts_data:
        akahu_id = acct.get("_id", acct.get("id", ""))
        stmt = select(BankAccount).where(
            BankAccount.org_id == org_id,
            BankAccount.akahu_account_id == akahu_id,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.account_name = acct.get("name", existing.account_name)
            existing.account_number = acct.get("formatted_account", existing.account_number)
            existing.bank_name = acct.get("connection", {}).get("name", existing.bank_name)
            existing.account_type = acct.get("type", existing.account_type)
            existing.balance = acct.get("balance", {}).get("current", existing.balance)
            existing.last_refreshed_at = datetime.now(timezone.utc)
            upserted.append(existing)
        else:
            new_acct = BankAccount(
                org_id=org_id,
                akahu_account_id=akahu_id,
                account_name=acct.get("name", "Unknown"),
                account_number=acct.get("formatted_account"),
                bank_name=acct.get("connection", {}).get("name"),
                account_type=acct.get("type"),
                balance=acct.get("balance", {}).get("current", 0),
                last_refreshed_at=datetime.now(timezone.utc),
            )
            db.add(new_acct)
            upserted.append(new_acct)

    # Update last_sync_at on connection
    conn_stmt = select(AkahuConnection).where(AkahuConnection.org_id == org_id)
    conn_result = await db.execute(conn_stmt)
    conn = conn_result.scalar_one_or_none()
    if conn:
        conn.last_sync_at = datetime.now(timezone.utc)

    await db.flush()
    for acct in upserted:
        await db.refresh(acct)

    return upserted


# ---------------------------------------------------------------------------
# Bank transaction sync
# ---------------------------------------------------------------------------


async def sync_transactions(
    db: AsyncSession,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID | None = None,
    from_date: date | None = None,
) -> list[BankTransaction]:
    """Fetch transactions from Akahu API and upsert to bank_transactions.

    Initial sync: last 90 days. Subsequent: from last_sync_at.
    Requirements: 17.1, 17.2, 17.3, 17.4
    """
    access_token = await _get_access_token(db, org_id)
    if not access_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail={
            "code": "AKAHU_AUTH_FAILED",
            "message": "No active Akahu connection — please connect first",
        })

    if from_date is None:
        from_date = date.today() - timedelta(days=90)

    # Get bank accounts to sync
    if bank_account_id:
        stmt = select(BankAccount).where(
            BankAccount.id == bank_account_id,
            BankAccount.org_id == org_id,
        )
        result = await db.execute(stmt)
        accounts = [result.scalar_one_or_none()]
        accounts = [a for a in accounts if a is not None]
    else:
        stmt = select(BankAccount).where(
            BankAccount.org_id == org_id,
            BankAccount.is_active.is_(True),
        )
        result = await db.execute(stmt)
        accounts = list(result.scalars().all())

    all_transactions: list[BankTransaction] = []

    for acct in accounts:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "start": from_date.isoformat(),
                "end": date.today().isoformat(),
            }
            if cursor:
                params["cursor"] = cursor

            resp = await _akahu_request(
                "GET",
                f"{AKAHU_API_BASE}/accounts/{acct.akahu_account_id}/transactions",
                access_token=access_token,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            txns = data.get("items", data.get("transactions", []))

            for txn in txns:
                akahu_txn_id = txn.get("_id", txn.get("id", ""))
                stmt = select(BankTransaction).where(
                    BankTransaction.org_id == org_id,
                    BankTransaction.akahu_transaction_id == akahu_txn_id,
                )
                result = await db.execute(stmt)
                existing = result.scalar_one_or_none()

                txn_date = txn.get("date", date.today().isoformat())
                if isinstance(txn_date, str):
                    txn_date = date.fromisoformat(txn_date[:10])

                if existing:
                    existing.description = txn.get("description", existing.description)
                    existing.amount = txn.get("amount", existing.amount)
                    existing.balance = txn.get("balance", existing.balance)
                    existing.merchant_name = txn.get("merchant", {}).get("name") if isinstance(txn.get("merchant"), dict) else existing.merchant_name
                    existing.category = txn.get("category", {}).get("name") if isinstance(txn.get("category"), dict) else existing.category
                    existing.akahu_raw = txn
                    all_transactions.append(existing)
                else:
                    new_txn = BankTransaction(
                        org_id=org_id,
                        bank_account_id=acct.id,
                        akahu_transaction_id=akahu_txn_id,
                        date=txn_date,
                        description=txn.get("description", ""),
                        amount=txn.get("amount", 0),
                        balance=txn.get("balance"),
                        merchant_name=txn.get("merchant", {}).get("name") if isinstance(txn.get("merchant"), dict) else None,
                        category=txn.get("category", {}).get("name") if isinstance(txn.get("category"), dict) else None,
                        akahu_raw=txn,
                    )
                    db.add(new_txn)
                    all_transactions.append(new_txn)

            # Pagination
            cursor = data.get("cursor", {}).get("next") if isinstance(data.get("cursor"), dict) else None
            if not cursor or not txns:
                break

    # Update last_sync_at
    conn_stmt = select(AkahuConnection).where(AkahuConnection.org_id == org_id)
    conn_result = await db.execute(conn_stmt)
    conn = conn_result.scalar_one_or_none()
    if conn:
        conn.last_sync_at = datetime.now(timezone.utc)

    await db.flush()
    for txn in all_transactions:
        await db.refresh(txn)

    return all_transactions

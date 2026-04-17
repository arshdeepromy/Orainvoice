"""Payment token generation and validation service.

Generates secure, time-limited tokens for public payment page access
and validates them on incoming requests.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.payments.models import PaymentToken

logger = logging.getLogger(__name__)

# Token expiry window
_TOKEN_EXPIRY_HOURS = 72


async def generate_payment_token(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> tuple[str, str]:
    """Generate a payment token and payment page URL for an invoice.

    Invalidates any existing active tokens for the same invoice,
    creates a new token with a 72-hour expiry, and returns the
    token string and the full payment page URL.

    Returns
    -------
    tuple[str, str]
        ``(token_string, payment_page_url)``
    """
    # 1. Deactivate all existing active tokens for this invoice
    await db.execute(
        update(PaymentToken)
        .where(
            PaymentToken.invoice_id == invoice_id,
            PaymentToken.is_active == True,  # noqa: E712
        )
        .values(is_active=False)
    )

    # 2. Generate a cryptographically random URL-safe token (~64 chars)
    token = secrets.token_urlsafe(48)

    # 3. Set expiry to 72 hours from now
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_TOKEN_EXPIRY_HOURS)

    # 4. Insert new PaymentToken record
    payment_token = PaymentToken(
        token=token,
        invoice_id=invoice_id,
        org_id=org_id,
        expires_at=expires_at,
    )
    db.add(payment_token)
    await db.flush()
    await db.refresh(payment_token)

    # 5. Build the public payment page URL
    frontend_base = (settings.frontend_base_url or "http://localhost:5173").rstrip("/")
    url = f"{frontend_base}/pay/{token}"

    return token, url


async def validate_payment_token(
    db: AsyncSession,
    *,
    token: str,
) -> PaymentToken | None:
    """Validate a payment token.

    Returns
    -------
    PaymentToken | None
        The token record if valid, ``None`` if the token does not exist
        or has been deactivated.

    Raises
    ------
    ValueError
        With message ``"expired"`` if the token exists and is active but
        has passed its ``expires_at`` timestamp.
    """
    # 1. Query for an active token matching the provided string
    result = await db.execute(
        select(PaymentToken).where(
            PaymentToken.token == token,
            PaymentToken.is_active == True,  # noqa: E712
        )
    )
    payment_token = result.scalar_one_or_none()

    # 2. Not found → return None (generic "invalid link")
    if payment_token is None:
        return None

    # 3. Check expiry
    now = datetime.now(timezone.utc)
    if payment_token.expires_at < now:
        raise ValueError("expired")

    # 4. Valid token
    return payment_token

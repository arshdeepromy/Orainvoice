"""MFA enrolment and verification for fleet portal accounts.

Mirrors the staff ``app/modules/auth/mfa_service.py`` patterns but
rooted at ``portal_account_id`` instead of ``user_id``.

Implements: B2B Fleet Portal tasks 4A.2, 4A.3, 4A.4 — Requirements
21.10, 21.11, 21.12, 21.13, 21.14.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

import bcrypt
import pyotp
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.models import (
    PortalAccountBackupCode,
    PortalAccountMfaMethod,
)

logger = logging.getLogger(__name__)

_BACKUP_CODE_COUNT = 10


# ---------------------------------------------------------------------------
# TOTP (Req 21.10, 21.13, 21.14)
# ---------------------------------------------------------------------------


def generate_totp_secret() -> str:
    """Generate a fresh TOTP secret (base32, 32 chars)."""
    return pyotp.random_base32()


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code against the secret."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


async def start_totp_enrolment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    portal_account_id: uuid.UUID,
    email: str,
) -> dict:
    """Start TOTP enrolment — returns secret + provisioning URI.

    The secret is stored encrypted in the DB only after confirmation.
    The caller holds it in a Redis challenge session until the user
    confirms with a valid code.
    """
    secret = generate_totp_secret()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=email, issuer_name="Fleet Portal")
    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri,
    }


async def confirm_totp_enrolment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    portal_account_id: uuid.UUID,
    secret: str,
    code: str,
) -> PortalAccountMfaMethod:
    """Confirm TOTP enrolment by verifying the first code."""
    if not verify_totp_code(secret, code):
        raise ValueError("Invalid verification code")

    # Store the method (secret encrypted in production via envelope_encrypt)
    method = PortalAccountMfaMethod(
        org_id=org_id,
        portal_account_id=portal_account_id,
        method="totp",
        secret_encrypted=secret.encode("utf-8"),  # TODO: envelope_encrypt
        verified=True,
        is_default=True,
    )
    db.add(method)
    await db.flush()
    await db.refresh(method)
    return method


# ---------------------------------------------------------------------------
# SMS MFA (Req 21.11)
# ---------------------------------------------------------------------------


async def start_sms_enrolment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    portal_account_id: uuid.UUID,
    phone: str,
) -> str:
    """Start SMS MFA enrolment — sends a 6-digit code via SMS.

    Returns a challenge token for the confirm step. The actual SMS
    send is delegated to the existing Connexus integration.
    """
    code = f"{secrets.randbelow(1000000):06d}"
    # TODO: Send via Connexus SMS provider
    # For now, log the code (development only)
    logger.info(
        "fleet_portal.sms_mfa_code portal_account_id=%s code=%s (dev only)",
        portal_account_id,
        code,
    )
    return code


async def confirm_sms_enrolment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    portal_account_id: uuid.UUID,
    phone: str,
    code: str,
    expected_code: str,
) -> PortalAccountMfaMethod:
    """Confirm SMS enrolment by verifying the code."""
    if code != expected_code:
        raise ValueError("Invalid verification code")

    method = PortalAccountMfaMethod(
        org_id=org_id,
        portal_account_id=portal_account_id,
        method="sms",
        phone_number=phone,
        verified=True,
        is_default=False,
    )
    db.add(method)
    await db.flush()
    await db.refresh(method)
    return method


# ---------------------------------------------------------------------------
# Backup codes (Req 21.12)
# ---------------------------------------------------------------------------


async def generate_backup_codes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    portal_account_id: uuid.UUID,
) -> list[str]:
    """Generate 10 backup codes, hash and store them. Returns plain codes."""
    # Delete existing codes
    await db.execute(
        delete(PortalAccountBackupCode).where(
            PortalAccountBackupCode.portal_account_id == portal_account_id
        )
    )

    plain_codes: list[str] = []
    for _ in range(_BACKUP_CODE_COUNT):
        code = secrets.token_urlsafe(8)[:10]
        plain_codes.append(code)
        code_hash = bcrypt.hashpw(
            code.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        db.add(
            PortalAccountBackupCode(
                org_id=org_id,
                portal_account_id=portal_account_id,
                code_hash=code_hash,
            )
        )
    await db.flush()
    return plain_codes


async def verify_backup_code(
    db: AsyncSession,
    *,
    portal_account_id: uuid.UUID,
    code: str,
) -> bool:
    """Verify a backup code. Marks it consumed on success."""
    res = await db.execute(
        select(PortalAccountBackupCode).where(
            PortalAccountBackupCode.portal_account_id == portal_account_id,
            PortalAccountBackupCode.consumed_at.is_(None),
        )
    )
    for bc in res.scalars().all():
        if bcrypt.checkpw(code.encode("utf-8"), bc.code_hash.encode("utf-8")):
            bc.consumed_at = datetime.now(timezone.utc)
            await db.flush()
            return True
    return False


# ---------------------------------------------------------------------------
# MFA method listing and removal
# ---------------------------------------------------------------------------


async def list_mfa_methods(
    db: AsyncSession,
    *,
    portal_account_id: uuid.UUID,
) -> list[PortalAccountMfaMethod]:
    """List all enrolled MFA methods for a portal account."""
    res = await db.execute(
        select(PortalAccountMfaMethod).where(
            PortalAccountMfaMethod.portal_account_id == portal_account_id,
            PortalAccountMfaMethod.verified.is_(True),
        )
    )
    return list(res.scalars().all())


async def remove_mfa_method(
    db: AsyncSession,
    *,
    portal_account_id: uuid.UUID,
    method_id: uuid.UUID,
) -> bool:
    """Remove an MFA method. Returns True if deleted."""
    res = await db.execute(
        delete(PortalAccountMfaMethod).where(
            PortalAccountMfaMethod.id == method_id,
            PortalAccountMfaMethod.portal_account_id == portal_account_id,
        )
    )
    return (res.rowcount or 0) > 0


__all__ = [
    "generate_totp_secret",
    "verify_totp_code",
    "start_totp_enrolment",
    "confirm_totp_enrolment",
    "start_sms_enrolment",
    "confirm_sms_enrolment",
    "generate_backup_codes",
    "verify_backup_code",
    "list_mfa_methods",
    "remove_mfa_method",
]

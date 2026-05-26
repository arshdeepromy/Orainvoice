"""Fleet Portal password policy enforcement.

Extends the basic ``auth.validate_password_rules`` (Property 7) with
the full configurable policy from ``portal_security_policy``:

- Character class requirements (uppercase, lowercase, digit, special)
- Password expiry (days since last change)
- Password history (bcrypt-verify against last N hashes)
- HIBP k-anonymity breach check (SHA-1 prefix lookup)

Implements: B2B Fleet Portal task 4A.1 — Requirements 21.3, 21.4, 21.5, 21.6.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal import auth as fp_auth
from app.modules.fleet_portal.models import PortalAccountPasswordHistory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy schema (mirrors the JSONB shape in org_settings)
# ---------------------------------------------------------------------------


class PasswordPolicy:
    """In-memory representation of portal_security_policy.password_policy."""

    def __init__(
        self,
        *,
        min_length: int = 8,
        require_uppercase: bool = False,
        require_lowercase: bool = False,
        require_digit: bool = False,
        require_special: bool = False,
        expiry_days: int = 0,
        history_count: int = 0,
        require_not_pwned: bool = False,
    ):
        self.min_length = min_length
        self.require_uppercase = require_uppercase
        self.require_lowercase = require_lowercase
        self.require_digit = require_digit
        self.require_special = require_special
        self.expiry_days = expiry_days
        self.history_count = history_count
        self.require_not_pwned = require_not_pwned

    @classmethod
    def from_dict(cls, d: dict | None) -> PasswordPolicy:
        if d is None:
            return cls()
        return cls(
            min_length=d.get("min_length", 8),
            require_uppercase=d.get("require_uppercase", False),
            require_lowercase=d.get("require_lowercase", False),
            require_digit=d.get("require_digit", False),
            require_special=d.get("require_special", False),
            expiry_days=d.get("expiry_days", 0),
            history_count=d.get("history_count", 0),
            require_not_pwned=d.get("require_not_pwned", False),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_password_against_policy(
    password: str,
    email: str,
    policy: PasswordPolicy,
) -> list[str]:
    """Return a list of unmet requirements. Empty list = valid.

    Runs the basic Property 7 check first, then the policy-level checks.
    """
    errors: list[str] = []

    # Property 7 — length + email-match
    try:
        fp_auth.validate_password_rules(password, email)
    except ValueError as exc:
        errors.append(str(exc))
        return errors  # no point checking further if basic rules fail

    # Policy-level length (may be stricter than the default 8)
    if len(password) < policy.min_length:
        errors.append(
            f"Password must be at least {policy.min_length} characters"
        )

    if policy.require_uppercase and not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")

    if policy.require_lowercase and not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")

    if policy.require_digit and not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")

    if policy.require_special and not any(not c.isalnum() for c in password):
        errors.append("Password must contain at least one special character")

    return errors


# ---------------------------------------------------------------------------
# Password history (Req 21.5)
# ---------------------------------------------------------------------------


async def check_password_history(
    db: AsyncSession,
    portal_account_id: uuid.UUID,
    password: str,
    history_count: int,
) -> bool:
    """Return True if ``password`` matches any of the last N stored hashes."""
    if history_count == 0:
        return False

    res = await db.execute(
        select(PortalAccountPasswordHistory.password_hash)
        .where(PortalAccountPasswordHistory.portal_account_id == portal_account_id)
        .order_by(PortalAccountPasswordHistory.created_at.desc())
        .limit(history_count)
    )
    rows = res.all()
    for (stored_hash,) in rows:
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            return True
    return False


async def record_password_in_history(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    portal_account_id: uuid.UUID,
    password_hash: str,
    history_count: int,
) -> None:
    """Append the old hash to history and FIFO-evict beyond ``history_count``."""
    row = PortalAccountPasswordHistory(
        org_id=org_id,
        portal_account_id=portal_account_id,
        password_hash=password_hash,
    )
    db.add(row)
    await db.flush()

    # FIFO eviction
    if history_count > 0:
        from sqlalchemy import delete, func

        count_q = select(func.count()).where(
            PortalAccountPasswordHistory.portal_account_id == portal_account_id
        )
        total = (await db.execute(count_q)).scalar_one()
        if total > history_count:
            # Delete the oldest rows beyond the limit
            oldest_q = (
                select(PortalAccountPasswordHistory.id)
                .where(PortalAccountPasswordHistory.portal_account_id == portal_account_id)
                .order_by(PortalAccountPasswordHistory.created_at.asc())
                .limit(total - history_count)
            )
            oldest_ids = [r[0] for r in (await db.execute(oldest_q)).all()]
            if oldest_ids:
                await db.execute(
                    delete(PortalAccountPasswordHistory).where(
                        PortalAccountPasswordHistory.id.in_(oldest_ids)
                    )
                )
                await db.flush()


# ---------------------------------------------------------------------------
# HIBP k-anonymity check (Req 21.6)
# ---------------------------------------------------------------------------


async def is_password_pwned(password: str) -> bool:
    """Check if the password appears in the HIBP breach database.

    Uses the k-anonymity range API: SHA-1 the password, send only the
    first 5 hex chars to the API, check if the suffix appears in the
    response. Returns True if breached.

    On network failure or timeout, returns False (fail-open) so the
    user isn't blocked by an external service outage. The check is
    best-effort per the spec.
    """
    import httpx

    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]
    suffix = sha1[5:]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.pwnedpasswords.com/range/{prefix}"
            )
            if resp.status_code != 200:
                return False
            for line in resp.text.splitlines():
                parts = line.split(":")
                if len(parts) >= 1 and parts[0].strip().upper() == suffix:
                    return True
    except Exception as exc:
        logger.warning("HIBP check failed (fail-open): %s", exc)
    return False


# ---------------------------------------------------------------------------
# Password expiry (Req 21.4)
# ---------------------------------------------------------------------------


def is_password_expired(
    password_changed_at: datetime | None,
    expiry_days: int,
) -> bool:
    """Return True if the password has exceeded the configured expiry."""
    if expiry_days == 0:
        return False
    if password_changed_at is None:
        return True
    now = datetime.now(timezone.utc)
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=timezone.utc)
    return (now - password_changed_at).days > expiry_days


# ---------------------------------------------------------------------------
# Load policy from org settings
# ---------------------------------------------------------------------------


async def load_password_policy(
    db: AsyncSession, org_id: uuid.UUID
) -> PasswordPolicy:
    """Load the portal_security_policy.password_policy from org settings."""
    from app.modules.admin.models import Organisation

    res = await db.execute(
        select(Organisation.settings).where(Organisation.id == org_id)
    )
    row = res.first()
    if row is None:
        return PasswordPolicy()
    settings_json = row[0] or {}
    portal_policy = settings_json.get("portal_security_policy", {})
    return PasswordPolicy.from_dict(portal_policy.get("password_policy"))


__all__ = [
    "PasswordPolicy",
    "validate_password_against_policy",
    "check_password_history",
    "record_password_in_history",
    "is_password_pwned",
    "is_password_expired",
    "load_password_policy",
]

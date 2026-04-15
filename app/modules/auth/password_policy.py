"""Password Policy Engine.

Validates passwords against org-level password policies, checks password
history, records password hashes, and detects password expiry.

Feature: org-security-settings
Requirements: 2.3, 2.4, 2.6, 2.8
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.security_settings_schemas import PasswordPolicy


def validate_password_against_policy(password: str, policy: PasswordPolicy) -> list[str]:
    """Return a list of unmet password requirements. Empty list means valid.

    Requirements: 2.3, 2.4
    """
    errors: list[str] = []

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


async def check_password_history(
    db: AsyncSession,
    user_id: UUID,
    password: str,
    history_count: int,
) -> bool:
    """Return True if *password* matches any of the last *history_count* hashes.

    Requirements: 2.8
    """
    if history_count == 0:
        return False

    result = await db.execute(
        text(
            "SELECT password_hash FROM password_history "
            "WHERE user_id = :user_id "
            "ORDER BY created_at DESC "
            "LIMIT :limit"
        ),
        {"user_id": str(user_id), "limit": history_count},
    )
    rows = result.fetchall()

    for (stored_hash,) in rows:
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            return True

    return False


async def record_password_in_history(
    db: AsyncSession,
    user_id: UUID,
    password_hash: str,
) -> None:
    """Store a password hash in the password_history table.

    Requirements: 2.8
    """
    await db.execute(
        text(
            "INSERT INTO password_history (user_id, password_hash) "
            "VALUES (:user_id, :password_hash)"
        ),
        {"user_id": str(user_id), "password_hash": password_hash},
    )
    await db.flush()


def is_password_expired(user: object, policy: PasswordPolicy) -> bool:
    """Return True if the user's password has exceeded the configured expiry.

    *user* must have a ``password_changed_at`` attribute (datetime | None).

    Requirements: 2.6
    """
    if policy.expiry_days == 0:
        return False

    password_changed_at: datetime | None = getattr(user, "password_changed_at", None)
    if password_changed_at is None:
        return True

    # Ensure timezone-aware comparison
    now = datetime.now(timezone.utc)
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=timezone.utc)

    age_days = (now - password_changed_at).days
    return age_days > policy.expiry_days

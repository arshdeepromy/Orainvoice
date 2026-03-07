"""JWT creation and decoding utilities.

- Access tokens: short-lived (15 min), contain user claims.
- Refresh tokens: opaque random strings stored hashed in the sessions table.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings


def create_access_token(
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    role: str,
    email: str,
    assigned_location_ids: list[str] | None = None,
    franchise_group_id: uuid.UUID | None = None,
) -> str:
    """Create a signed JWT access token (15-min expiry by default).

    Includes role, assigned_location_ids, and franchise_group_id claims
    for RBAC enforcement.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": str(user_id),
        "org_id": str(org_id) if org_id else None,
        "role": role,
        "email": email,
        "assigned_location_ids": [str(lid) for lid in (assigned_location_ids or [])],
        "franchise_group_id": str(franchise_group_id) if franchise_group_id else None,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> str:
    """Generate a cryptographically random refresh token string."""
    return secrets.token_urlsafe(48)


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token. Raises ``JWTError`` on failure."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "access":
        raise JWTError("Token is not an access token")
    return payload

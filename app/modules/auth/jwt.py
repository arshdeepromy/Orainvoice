"""JWT creation and decoding utilities.

- Access tokens: short-lived (15 min), contain user claims.
- Refresh tokens: opaque random strings stored hashed in the sessions table.

Supports dual-algorithm signing (RS256 / HS256) for migration (REM-22).
When RS256 keys are configured, new tokens are signed with RS256.
During migration, decode_access_token accepts both RS256 and HS256 tokens.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RS256 / HS256 dual-algorithm helpers (REM-22)
# ---------------------------------------------------------------------------

def _get_signing_key_and_algorithm() -> tuple[str, str]:
    """Return (key, algorithm) for signing new JWTs.

    Uses RS256 when an RSA private key path is configured, otherwise
    falls back to HS256 with the shared secret.
    """
    if settings.jwt_rs256_private_key_path:
        with open(settings.jwt_rs256_private_key_path) as f:
            return f.read(), "RS256"
    return settings.jwt_secret, "HS256"


def _get_verification_keys() -> list[tuple[str, list[str]]]:
    """Return a list of (key, algorithms) tuples for token verification.

    Always includes HS256 (shared secret) so existing tokens remain valid
    during the migration period.  Adds RS256 (public key) when configured.
    """
    keys: list[tuple[str, list[str]]] = [
        (settings.jwt_secret, ["HS256"]),
    ]
    if settings.jwt_rs256_public_key_path:
        with open(settings.jwt_rs256_public_key_path) as f:
            keys.append((f.read(), ["RS256"]))
    return keys


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
    key, algorithm = _get_signing_key_and_algorithm()
    return jwt.encode(payload, key, algorithm=algorithm)


def create_refresh_token() -> str:
    """Generate a cryptographically random refresh token string."""
    return secrets.token_urlsafe(48)


def decode_access_token(token: str) -> dict:
    """Decode and validate an access token.

    During the RS256 migration period, tries RS256 first (when configured),
    then falls back to HS256.  Raises ``InvalidTokenError`` on failure.
    """
    verification_keys = _get_verification_keys()

    # Try RS256 first (if configured) so new tokens are verified quickly,
    # then fall back to HS256 for legacy tokens.
    last_error: Exception | None = None
    for key, algorithms in reversed(verification_keys):
        try:
            payload = jwt.decode(token, key, algorithms=algorithms)
            if payload.get("type") != "access":
                raise InvalidTokenError("Token is not an access token")
            return payload
        except InvalidTokenError as exc:
            last_error = exc
            continue

    # All keys exhausted — re-raise the last error.
    raise last_error  # type: ignore[misc]

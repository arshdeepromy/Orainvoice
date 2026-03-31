"""Firebase ID token verification.

Verifies Firebase ID tokens locally using Google's public signing keys,
following the official Firebase documentation for third-party JWT libraries:
https://firebase.google.com/docs/auth/admin/verify-id-tokens

This avoids making HTTP calls to the deprecated identitytoolkit v3 API,
which can timeout (504) from within Docker containers.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from jwt.exceptions import InvalidTokenError

logger = logging.getLogger(__name__)

# Google's public keys for verifying Firebase ID tokens
_GOOGLE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

# Cache for Google's public keys
_cached_keys: dict[str, Any] | None = None
_cache_expiry: float = 0


async def _fetch_google_public_keys() -> dict[str, str]:
    """Fetch Google's public signing keys, with in-memory caching.

    Keys are cached based on the Cache-Control max-age header from Google.
    Falls back to a 1-hour cache if the header is missing.
    """
    global _cached_keys, _cache_expiry

    now = time.time()
    if _cached_keys and now < _cache_expiry:
        return _cached_keys

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_GOOGLE_CERTS_URL)
        resp.raise_for_status()

    keys = resp.json()

    # Parse Cache-Control header for max-age
    cache_control = resp.headers.get("cache-control", "")
    max_age = 3600  # default 1 hour
    for part in cache_control.split(","):
        part = part.strip()
        if part.startswith("max-age="):
            try:
                max_age = int(part.split("=")[1])
            except (ValueError, IndexError):
                pass

    _cached_keys = keys
    _cache_expiry = now + max_age
    logger.debug("Fetched %d Google public keys, cached for %ds", len(keys), max_age)
    return keys


async def verify_firebase_id_token(
    id_token: str,
    project_id: str,
) -> dict[str, Any]:
    """Verify a Firebase ID token and return the decoded claims.

    Checks:
    - Algorithm is RS256
    - Token is signed by one of Google's public keys
    - Token is not expired
    - Audience matches the Firebase project ID
    - Issuer matches https://securetoken.google.com/<project_id>
    - Subject (sub) is non-empty

    Returns the decoded token payload on success.
    Raises ValueError with a descriptive message on failure.
    """
    # Decode header to get the key ID (kid)
    try:
        unverified_header = jwt.get_unverified_header(id_token)
    except InvalidTokenError as e:
        raise ValueError(f"Invalid token header: {e}")

    if unverified_header.get("alg") != "RS256":
        raise ValueError(
            f"Invalid algorithm: expected RS256, got {unverified_header.get('alg')}"
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise ValueError("Token header missing 'kid' claim")

    # Fetch Google's public keys
    try:
        public_keys = await _fetch_google_public_keys()
    except Exception as e:
        logger.error("Failed to fetch Google public keys: %s", e)
        raise ValueError("Could not fetch token verification keys")

    # Find the matching key
    cert_pem = public_keys.get(kid)
    if not cert_pem:
        # Keys might have rotated — force refresh and retry once
        global _cached_keys, _cache_expiry
        _cached_keys = None
        _cache_expiry = 0
        try:
            public_keys = await _fetch_google_public_keys()
        except Exception as e:
            raise ValueError(f"Could not refresh token verification keys: {e}")

        cert_pem = public_keys.get(kid)
        if not cert_pem:
            raise ValueError("Token signed with unknown key")

    # Extract the public key from the X.509 certificate
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode(), default_backend())
        public_key = cert.public_key()
    except Exception as e:
        logger.error("Failed to parse X.509 certificate for kid=%s: %s", kid, e)
        raise ValueError(f"Could not parse signing certificate: {e}")

    # Verify and decode the token
    expected_issuer = f"https://securetoken.google.com/{project_id}"
    try:
        payload = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=expected_issuer,
        )
    except InvalidTokenError as e:
        raise ValueError(f"Token verification failed: {e}")

    # sub must be non-empty
    if not payload.get("sub"):
        raise ValueError("Token missing 'sub' claim")

    return payload

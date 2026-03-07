"""HaveIBeenPwned password check using k-anonymity.

Uses the HIBP Passwords API v3 range endpoint. Only the first 5 characters
of the SHA-1 hash are sent to the API, preserving password privacy.

Usage::

    from app.integrations.hibp import is_password_compromised

    compromised = await is_password_compromised("P@ssw0rd123")
    if compromised:
        # warn the user
"""

from __future__ import annotations

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)

HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"
_TIMEOUT = 5.0  # seconds


async def is_password_compromised(password: str) -> bool:
    """Check if *password* appears in the HIBP breach database.

    Returns ``True`` if the password hash is found, ``False`` otherwise.
    On network errors, returns ``False`` (fail-open) so that registration
    is not blocked by a third-party outage.
    """
    sha1_hash = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1_hash[:5]
    suffix = sha1_hash[5:]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{HIBP_RANGE_URL}{prefix}",
                headers={"User-Agent": "WorkshopPro-NZ-PasswordCheck"},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("HIBP API request failed: %s", exc)
        return False

    # Response is a text list of "SUFFIX:COUNT" lines
    for line in response.text.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 1 and parts[0] == suffix:
            return True

    return False

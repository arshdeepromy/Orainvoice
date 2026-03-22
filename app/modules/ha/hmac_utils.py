"""HMAC-SHA256 signing and verification for HA heartbeat payloads.

The heartbeat payload is JSON-serialised with sorted keys and compact
separators so that both nodes produce an identical byte string for the
same logical payload, regardless of dict insertion order.

Requirements: 11.4, 11.5
"""

from __future__ import annotations

import hashlib
import hmac
import json


def compute_hmac(payload: dict, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of *payload* using *secret*.

    The payload is serialised deterministically with ``sort_keys=True``
    and ``separators=(',', ':')`` (no whitespace) before signing.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def verify_hmac(payload: dict, signature: str, secret: str) -> bool:
    """Return ``True`` if *signature* matches the HMAC-SHA256 of *payload*.

    Uses :func:`hmac.compare_digest` for constant-time comparison to
    prevent timing side-channel attacks.
    """
    expected = compute_hmac(payload, secret)
    return hmac.compare_digest(expected, signature)

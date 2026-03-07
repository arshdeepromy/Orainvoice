"""Webhook payload signing and verification using HMAC-SHA256.

Provides:
- sign_webhook_payload()   — produce hex-digest signature for outbound payloads
- verify_webhook_signature() — constant-time comparison of received signature

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import hashlib
import hmac


def sign_webhook_payload(payload: bytes, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of *payload* using *secret*."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Return True if *signature* matches the expected HMAC-SHA256 of *payload*."""
    expected = sign_webhook_payload(payload, secret)
    return hmac.compare_digest(expected, signature)

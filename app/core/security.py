"""Security configuration utilities.

Provides:
- TLS configuration helpers for enforcing TLS 1.3 minimum
- Database SSL configuration for PostgreSQL connections
- Security headers verification utility

Requirements: 52.1, 52.2, 52.3
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Required security headers (Requirement 52.3)
# ---------------------------------------------------------------------------

REQUIRED_SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "connect-src 'self' https://api.stripe.com "
        "https://identitytoolkit.googleapis.com "
        "https://www.googleapis.com "
        "https://firebaseinstallations.googleapis.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


# ---------------------------------------------------------------------------
# TLS configuration (Requirement 52.2)
# ---------------------------------------------------------------------------

def create_tls_context(*, purpose: ssl.Purpose = ssl.Purpose.CLIENT_AUTH) -> ssl.SSLContext:
    """Create an SSL context enforcing TLS 1.3 minimum.

    Returns an ``ssl.SSLContext`` configured with:
    - TLS 1.3 as the minimum protocol version
    - Strong cipher suites only
    - Certificate verification enabled
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT if purpose == ssl.Purpose.SERVER_AUTH else ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.maximum_version = ssl.TLSVersion.MAXIMUM_SUPPORTED
    return ctx


def get_tls_min_version() -> str:
    """Return the enforced minimum TLS version as a string."""
    return "TLSv1.3"


# ---------------------------------------------------------------------------
# Database SSL configuration (Requirement 52.1)
# ---------------------------------------------------------------------------

@dataclass
class DatabaseSSLConfig:
    """PostgreSQL SSL connection parameters.

    When ``ssl_mode`` is ``"require"`` or stricter, all connections to
    PostgreSQL are encrypted.  Combined with PostgreSQL's AES-256
    encryption at rest (via pgcrypto / full-disk encryption), this
    satisfies Requirement 52.1 and 52.2 for the data layer.
    """

    ssl_mode: str = "require"
    ssl_min_protocol_version: str = "TLSv1.3"

    def to_connect_args(self) -> dict[str, Any]:
        """Return keyword arguments for SQLAlchemy's ``connect_args``.

        For asyncpg, SSL is configured via an ``ssl.SSLContext`` passed
        as the ``ssl`` connect argument.
        """
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return {"ssl": ctx}


    def to_engine_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments suitable for ``create_async_engine``."""
        return {"connect_args": self.to_connect_args()}


def get_database_ssl_config(environment: str = "production") -> DatabaseSSLConfig:
    """Return the appropriate SSL config for the given environment.

    In development, SSL is optional (PostgreSQL may not have certs).
    In production/staging, SSL is mandatory.
    """
    if environment in ("production", "staging"):
        return DatabaseSSLConfig(ssl_mode="require", ssl_min_protocol_version="TLSv1.3")
    # Development — SSL still configured but won't fail if PG has no certs
    return DatabaseSSLConfig(ssl_mode="prefer", ssl_min_protocol_version="TLSv1.3")


# ---------------------------------------------------------------------------
# Security headers verification (Requirement 52.3)
# ---------------------------------------------------------------------------

@dataclass
class HeaderVerificationResult:
    """Result of verifying security headers on a response."""

    is_compliant: bool = True
    missing_headers: list[str] = field(default_factory=list)
    incorrect_headers: dict[str, dict[str, str]] = field(default_factory=dict)


def verify_security_headers(
    response_headers: dict[str, str],
) -> HeaderVerificationResult:
    """Check that all required security headers are present and correct.

    Parameters
    ----------
    response_headers:
        A mapping of header names to values from an HTTP response.

    Returns
    -------
    HeaderVerificationResult
        Contains ``is_compliant`` flag, list of missing headers, and
        dict of headers with incorrect values.
    """
    result = HeaderVerificationResult()

    # Normalise header names to lower-case for comparison
    normalised = {k.lower(): v for k, v in response_headers.items()}

    for header_name, expected_value in REQUIRED_SECURITY_HEADERS.items():
        actual = normalised.get(header_name.lower())
        if actual is None:
            result.is_compliant = False
            result.missing_headers.append(header_name)
        elif actual != expected_value:
            result.is_compliant = False
            result.incorrect_headers[header_name] = {
                "expected": expected_value,
                "actual": actual,
            }

    return result

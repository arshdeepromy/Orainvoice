"""JWT validation and org_id extraction middleware.

Validates the Authorization header on every request (except public paths),
decodes the JWT, and attaches user context to request.state for downstream use.

Implemented as pure ASGI middleware (not BaseHTTPMiddleware) to avoid
request body stream corruption when stacked with many middleware layers.
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def get_client_ip(request: Request) -> str | None:
    """Resolve the real client IP from proxy headers.

    Checks ``X-Forwarded-For`` first (first IP in the chain is the
    original client), then ``X-Real-IP``, and falls back to
    ``request.client.host``.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # X-Forwarded-For: client, proxy1, proxy2 — first entry is the client
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None

from app.config import settings

logger = logging.getLogger(__name__)

# Paths that do not require authentication.
PUBLIC_PATHS: set[str] = {
    "/health",
    "/api/v1/version",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth/login",
    "/api/v1/auth/login/google",
    "/api/v1/auth/login/passkey",
    "/api/v1/auth/token/refresh",
    "/api/v1/auth/password/reset-request",
    "/api/v1/auth/password/reset",
    "/api/v1/auth/signup",
    "/api/v1/auth/signup/confirm-payment",
    "/api/v1/auth/stripe-publishable-key",
    "/api/v1/auth/plans",
    "/api/v1/auth/signup-config",
    "/api/v1/auth/captcha",
    "/api/v1/auth/verify-captcha",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/verify-signup-email",
    "/api/v1/auth/resend-verification",
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/mfa/challenge/send",
    "/api/v1/auth/mfa/provider-config",
    "/api/v1/auth/mfa/firebase-verify",
    "/api/v1/auth/passkey/login/options",
    "/api/v1/auth/passkey/login/verify",
    "/api/v1/payments/stripe/webhook",
    "/api/v2/auth/login",
    "/api/v2/auth/login/google",
    "/api/v2/auth/login/passkey",
    "/api/v2/auth/token/refresh",
    "/api/v2/auth/password/reset-request",
    "/api/v2/auth/password/reset",
    "/api/v2/auth/signup",
    "/api/v2/auth/signup/confirm-payment",
    "/api/v2/auth/stripe-publishable-key",
    "/api/v2/auth/plans",
    "/api/v2/auth/signup-config",
    "/api/v2/auth/captcha",
    "/api/v2/auth/verify-captcha",
    "/api/v2/auth/verify-email",
    "/api/v2/auth/verify-signup-email",
    "/api/v2/auth/resend-verification",
    "/api/v2/auth/mfa/verify",
    "/api/v2/auth/mfa/challenge/send",
    "/api/v2/auth/mfa/provider-config",
    "/api/v2/auth/mfa/firebase-verify",
    "/api/v2/auth/passkey/login/options",
    "/api/v2/auth/passkey/login/verify",
    "/api/v2/payments/stripe/webhook",
    "/api/webhooks/connexus/incoming",
    "/api/webhooks/connexus/status",
    "/api/webhooks/xero",
    "/api/v1/ha/heartbeat",
    "/api/v1/ha/status",
    "/api/v2/trade-families",
}

# Prefixes that are public (e.g. customer portal tokens).
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/v1/portal/",
    "/api/v1/public/",
    "/api/v1/coupons/",
    "/api/v1/org/accounting/callback/",
    "/api/v2/portal/",
    "/api/v2/public/",
)

# Portal prefixes that require token expiry validation (REM-15).
_PORTAL_PREFIXES: tuple[str, ...] = (
    "/api/v1/portal/",
    "/api/v2/portal/",
)

# Paths considered "auth endpoints" for stricter rate limiting.
AUTH_ENDPOINT_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/",
    "/api/v2/auth/",
)

# Paths that are global-admin-only (not tenant-scoped).
_ADMIN_ONLY_PREFIXES: tuple[str, ...] = (
    "/api/v1/admin/",
    "/api/v2/admin/",
    "/api/v1/ha/",
    "/api/v2/ha/",
)


def _is_public(path: str) -> bool:
    """Return True if the path does not require a JWT."""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def is_auth_endpoint(path: str) -> bool:
    """Return True if the path is an authentication endpoint."""
    return any(path.startswith(prefix) for prefix in AUTH_ENDPOINT_PREFIXES)


def _is_tenant_scoped(path: str) -> bool:
    """Return True if the path is a tenant-scoped endpoint.

    Tenant-scoped endpoints are non-public, non-auth, non-admin paths that
    operate on organisation-specific data and require an org context.
    Paths in GLOBAL_ADMIN_DENIED_PREFIXES are excluded because RBAC already
    blocks global admins from those paths.
    """
    if _is_public(path):
        return False
    if is_auth_endpoint(path):
        return False
    if any(path.startswith(p) for p in _ADMIN_ONLY_PREFIXES):
        return False
    return True


class AuthMiddleware:
    """Validate JWT on every non-public request and populate request.state.

    Pure ASGI implementation — does not wrap the receive channel.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path

        # Resolve real client IP from proxy headers once for all downstream use
        request.state.client_ip = get_client_ip(request)

        if _is_public(path):
            # REM-15: Check portal token expiry for portal paths.
            if any(path.startswith(prefix) for prefix in _PORTAL_PREFIXES):
                expired_response = await self._check_portal_token_expiry(path)
                if expired_response is not None:
                    await expired_response(scope, receive, send)
                    return

            request.state.user_id = None
            request.state.org_id = None
            request.state.role = None
            request.state.assigned_location_ids = []
            request.state.branch_ids = []
            request.state.franchise_group_id = None
            await self.app(scope, receive, send)
            return

        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )
            await response(scope, receive, send)
            return

        token = auth_header.split(" ", 1)[1]
        try:
            # REM-22: Use dual-algorithm verification (RS256 first, HS256 fallback)
            # during the migration period.
            from app.modules.auth.jwt import _get_verification_keys

            verification_keys = _get_verification_keys()
            payload = None
            last_error: Exception | None = None
            for key, algorithms in reversed(verification_keys):
                try:
                    payload = jwt.decode(token, key, algorithms=algorithms)
                    break
                except InvalidTokenError as exc:
                    last_error = exc
                    continue

            if payload is None:
                raise last_error  # type: ignore[misc]
        except InvalidTokenError:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )
            await response(scope, receive, send)
            return

        user_id = payload.get("user_id")
        org_id = payload.get("org_id")
        role = payload.get("role")

        if not user_id or not role:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Token missing required claims"},
            )
            await response(scope, receive, send)
            return

        request.state.user_id = user_id
        request.state.org_id = org_id  # May be None for global_admin
        request.state.role = role
        request.state.assigned_location_ids = payload.get("assigned_location_ids", [])
        request.state.branch_ids = payload.get("branch_ids", [])
        request.state.franchise_group_id = payload.get("franchise_group_id")

        # REM-10: Global admin org context enforcement.
        # Global admins accessing tenant-scoped endpoints must have an active
        # org context stored in Redis. Without it, return 403.
        if role == "global_admin" and _is_tenant_scoped(path):
            try:
                from app.core.redis import redis_pool

                redis_key = f"admin_org_ctx:{user_id}"
                active_org_id = await redis_pool.get(redis_key)
                if not active_org_id:
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Organisation context required"},
                    )
                    await response(scope, receive, send)
                    return
                # Inject the org context into request.state so downstream
                # handlers can use it for tenant-scoped queries.
                request.state.org_id = active_org_id
            except Exception:
                logger.warning(
                    "Failed to check org context for global_admin user %s",
                    user_id,
                    exc_info=True,
                )
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Organisation context required"},
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # REM-15: Portal token expiry check
    # ------------------------------------------------------------------

    async def _check_portal_token_expiry(self, path: str) -> JSONResponse | None:
        """Return a 401 JSONResponse if the portal token in *path* has expired.

        Returns ``None`` when the token is still valid or when the token
        cannot be parsed (let the downstream handler deal with it).
        """
        # Extract the token segment — first path component after the prefix.
        token_str: str | None = None
        for prefix in _PORTAL_PREFIXES:
            if path.startswith(prefix):
                remainder = path[len(prefix):]
                token_str = remainder.split("/")[0]
                break

        if not token_str:
            return None

        try:
            token_uuid = _uuid.UUID(token_str)
        except (ValueError, AttributeError):
            return None  # Let the downstream handler return a proper 400.

        try:
            from app.core.database import async_session_factory
            from app.modules.customers.models import Customer

            async with async_session_factory() as db:
                result = await db.execute(
                    select(Customer.portal_token_expires_at).where(
                        Customer.portal_token == token_uuid
                    )
                )
                row = result.first()
                if row is None:
                    return None  # Unknown token — downstream will 400.

                expires_at = row[0]
                if expires_at is not None and expires_at < datetime.now(timezone.utc):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Portal token has expired"},
                    )
        except Exception:
            logger.warning(
                "Failed to check portal token expiry for %s",
                token_str,
                exc_info=True,
            )

        return None

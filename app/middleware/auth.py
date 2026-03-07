"""JWT validation and org_id extraction middleware.

Validates the Authorization header on every request (except public paths),
decodes the JWT, and attaches user context to request.state for downstream use.
"""

from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

# Paths that do not require authentication.
PUBLIC_PATHS: set[str] = {
    "/health",
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
    "/api/v1/payments/stripe/webhook",
    "/api/v2/auth/login",
    "/api/v2/auth/login/google",
    "/api/v2/auth/login/passkey",
    "/api/v2/auth/token/refresh",
    "/api/v2/auth/password/reset-request",
    "/api/v2/auth/password/reset",
    "/api/v2/auth/signup",
    "/api/v2/payments/stripe/webhook",
}

# Prefixes that are public (e.g. customer portal tokens).
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/v1/portal/",
    "/api/v2/portal/",
)

# Paths considered "auth endpoints" for stricter rate limiting.
AUTH_ENDPOINT_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/",
    "/api/v2/auth/",
)


def _is_public(path: str) -> bool:
    """Return True if the path does not require a JWT."""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def is_auth_endpoint(path: str) -> bool:
    """Return True if the path is an authentication endpoint."""
    return any(path.startswith(prefix) for prefix in AUTH_ENDPOINT_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate JWT on every non-public request and populate request.state."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if _is_public(path):
            request.state.user_id = None
            request.state.org_id = None
            request.state.role = None
            request.state.assigned_location_ids = []
            request.state.franchise_group_id = None
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
            )

        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
        except JWTError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        user_id = payload.get("user_id")
        org_id = payload.get("org_id")
        role = payload.get("role")

        if not user_id or not role:
            return JSONResponse(
                status_code=401,
                content={"detail": "Token missing required claims"},
            )

        request.state.user_id = user_id
        request.state.org_id = org_id  # May be None for global_admin
        request.state.role = role
        request.state.assigned_location_ids = payload.get("assigned_location_ids", [])
        request.state.franchise_group_id = payload.get("franchise_group_id")

        return await call_next(request)

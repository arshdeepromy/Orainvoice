"""Security headers middleware.

Adds the following headers to every response:
  • Content-Security-Policy (CSP)
  • Strict-Transport-Security (HSTS) — max-age=31536000; includeSubDomains
  • X-Frame-Options: DENY
  • X-Content-Type-Options: nosniff
  • X-XSS-Protection: 1; mode=block
  • Referrer-Policy: strict-origin-when-cross-origin
  • Permissions-Policy (restrictive defaults)

CSRF protection is enforced by requiring an ``X-CSRF-Token`` header on all
state-changing requests (POST/PUT/PATCH/DELETE) that carry a session cookie.
API clients using Bearer tokens are exempt because the token itself acts as
a CSRF mitigation (it cannot be sent automatically by a browser form).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import REQUIRED_SECURITY_HEADERS

# Methods that mutate state.
_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempt from CSRF checks (webhooks, auth token endpoints).
_CSRF_EXEMPT_PATHS: set[str] = {
    "/api/v1/payments/stripe/webhook",
    "/api/v2/payments/stripe/webhook",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers and enforce CSRF protection."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # --- CSRF protection ---
        if (
            request.method in _STATE_CHANGING_METHODS
            and request.url.path not in _CSRF_EXEMPT_PATHS
        ):
            # If the request uses cookie-based auth (has session cookie but
            # no Bearer token), require an X-CSRF-Token header.
            has_bearer = (
                request.headers.get("authorization", "").startswith("Bearer ")
            )
            has_session_cookie = "session" in request.cookies
            if has_session_cookie and not has_bearer:
                csrf_token = request.headers.get("x-csrf-token")
                if not csrf_token:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Missing CSRF token"},
                    )

        response: Response = await call_next(request)

        # --- Security headers (Requirement 52.3) ---
        # Apply all required headers from the central security config.
        for header_name, header_value in REQUIRED_SECURITY_HEADERS.items():
            response.headers[header_name] = header_value

        # Additional hardening headers (beyond Req 52.3 minimum)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        return response

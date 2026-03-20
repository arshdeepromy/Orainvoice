"""Security headers middleware.

Adds security headers to every response and enforces CSRF protection.

Implemented as pure ASGI middleware to avoid request body stream corruption.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.core.security import REQUIRED_SECURITY_HEADERS

# Methods that mutate state.
_STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempt from CSRF checks (webhooks, auth token endpoints).
_CSRF_EXEMPT_PATHS: set[str] = {
    "/api/v1/payments/stripe/webhook",
    "/api/v2/payments/stripe/webhook",
    "/api/webhooks/connexus/incoming",
    "/api/webhooks/connexus/status",
}


class SecurityHeadersMiddleware:
    """Inject security headers and enforce CSRF protection.

    Pure ASGI implementation — does not wrap the receive channel.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # --- CSRF protection ---
        if (
            request.method in _STATE_CHANGING_METHODS
            and request.url.path not in _CSRF_EXEMPT_PATHS
        ):
            has_bearer = (
                request.headers.get("authorization", "").startswith("Bearer ")
            )
            has_session_cookie = "session" in request.cookies
            if has_session_cookie and not has_bearer:
                csrf_token = request.headers.get("x-csrf-token")
                if not csrf_token:
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Missing CSRF token"},
                    )
                    await response(scope, receive, send)
                    return

        is_api = request.url.path.startswith("/api")
        is_dev = settings.environment == "development"
        is_public_html = request.url.path.startswith("/api/v1/public/") or request.url.path.startswith("/api/v2/public/")

        async def inject_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in REQUIRED_SECURITY_HEADERS.items():
                    # Skip CSP for public HTML pages — they set their own
                    if is_public_html and name.lower() == "content-security-policy":
                        continue
                    headers.append((name.lower().encode(), value.encode()))
                headers.append((b"x-xss-protection", b"1; mode=block"))
                if is_api and is_dev:
                    headers.append((b"cache-control", b"no-store, no-cache, must-revalidate, max-age=0"))
                    headers.append((b"pragma", b"no-cache"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, inject_headers)

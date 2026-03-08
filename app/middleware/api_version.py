"""API version deprecation middleware.

Adds ``Deprecation`` and ``Link`` headers to /api/v1/ responses.
After the sunset date, /api/v1/ requests receive HTTP 410 Gone.

Implemented as pure ASGI middleware to avoid request body stream corruption.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Sunset date: 12 months after v2 GA.
V2_GA_DATE: date = date(2026, 7, 1)
SUNSET_DATE: date = date(2027, 7, 1)

_SUNSET_HTTP_DATE: str = datetime(
    SUNSET_DATE.year,
    SUNSET_DATE.month,
    SUNSET_DATE.day,
    tzinfo=timezone.utc,
).strftime("%a, %d %b %Y %H:%M:%S GMT")

_V1_PREFIX = "/api/v1/"
_V2_PREFIX = "/api/v2/"


def _v2_equivalent(path: str) -> str:
    """Return the /api/v2/ equivalent of a /api/v1/ path."""
    return _V2_PREFIX + path[len(_V1_PREFIX):]


class APIVersionMiddleware:
    """Inject deprecation headers on /api/v1/ responses.

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

        if not path.startswith(_V1_PREFIX):
            await self.app(scope, receive, send)
            return

        v2_url = _v2_equivalent(path)

        # After sunset → HTTP 410 Gone
        if date.today() >= SUNSET_DATE:
            response = JSONResponse(
                status_code=410,
                content={
                    "detail": "This API version has been retired.",
                    "replacement": v2_url,
                },
            )
            await response(scope, receive, send)
            return

        # Before sunset → pass through with deprecation headers
        async def inject_deprecation(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"deprecation", _SUNSET_HTTP_DATE.encode()))
                headers.append((b"sunset", _SUNSET_HTTP_DATE.encode()))
                headers.append((b"link", f'<{v2_url}>; rel="successor-version"'.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, inject_deprecation)

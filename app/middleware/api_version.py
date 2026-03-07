"""API version deprecation middleware.

Adds ``Deprecation`` and ``Link`` headers to every ``/api/v1/`` response so
that consumers are informed about the upcoming sunset and can discover the
equivalent ``/api/v2/`` endpoint.

After the configured sunset date, ``/api/v1/`` requests receive an HTTP 410
Gone response with a JSON body containing the replacement URL.

Both API versions share the same authentication middleware and tenant
resolution — this middleware only handles header injection and sunset
enforcement.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Sunset date: 12 months after v2 GA.  Adjust when v2 goes live.
V2_GA_DATE: date = date(2026, 7, 1)
SUNSET_DATE: date = date(2027, 7, 1)

# RFC 9110 date format for the Deprecation header (IMF-fixdate).
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


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Inject deprecation headers on /api/v1/ responses.

    After the sunset date, /api/v1/ requests are rejected with HTTP 410.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if not path.startswith(_V1_PREFIX):
            return await call_next(request)

        v2_url = _v2_equivalent(path)

        # After sunset → HTTP 410 Gone
        if date.today() >= SUNSET_DATE:
            return JSONResponse(
                status_code=410,
                content={
                    "detail": "This API version has been retired.",
                    "replacement": v2_url,
                },
            )

        # Before sunset → pass through with deprecation headers
        response: Response = await call_next(request)

        response.headers["Deprecation"] = _SUNSET_HTTP_DATE
        response.headers["Sunset"] = _SUNSET_HTTP_DATE
        response.headers["Link"] = f'<{v2_url}>; rel="successor-version"'

        return response

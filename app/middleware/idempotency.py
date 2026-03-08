"""Idempotency key middleware.

On POST/PUT/PATCH requests that include an ``Idempotency-Key`` header,
the middleware checks the ``idempotency_keys`` table:

* If a non-expired record exists for the key + org, the cached response is
  returned immediately without executing the downstream handler.
* Otherwise the request proceeds normally and the response is stored with a
  24-hour expiry so subsequent retries receive the same result.

Implemented as pure ASGI middleware to avoid request body stream corruption.

**Validates: Requirement 10.3**
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import async_session_factory

logger = logging.getLogger(__name__)

# Methods that support idempotency keys
_IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}

# How long a cached response is valid
_EXPIRY_HOURS = 24


class IdempotencyMiddleware:
    """Return cached responses for duplicate idempotent requests.

    Pure ASGI implementation — does not wrap the receive channel.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # Only intercept state-changing methods
        if request.method not in _IDEMPOTENT_METHODS:
            await self.app(scope, receive, send)
            return

        idem_key: str | None = request.headers.get("Idempotency-Key")
        if not idem_key:
            await self.app(scope, receive, send)
            return

        org_id = getattr(request.state, "org_id", None)
        if not org_id:
            await self.app(scope, receive, send)
            return

        # --- Check for existing cached response ---
        try:
            cached = await self._get_cached(idem_key, str(org_id))
            if cached is not None:
                logger.debug("Idempotency cache hit for key=%s", idem_key)
                response = JSONResponse(
                    status_code=cached["response_status"],
                    content=cached["response_body"],
                )
                await response(scope, receive, send)
                return
        except Exception:
            logger.exception("Idempotency lookup failed for key=%s", idem_key)

        # --- Execute the actual request, capturing the response ---
        response_started = False
        response_status = 200
        response_headers: list[tuple[bytes, bytes]] = []
        response_body = b""

        async def capture_send(message):
            nonlocal response_started, response_status, response_headers, response_body
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body += message.get("body", b"")
            await send(message)

        await self.app(scope, receive, capture_send)

        # --- Store the response for future lookups ---
        if response_started:
            try:
                try:
                    body_json = json.loads(response_body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    body_json = {"raw": response_body.decode("utf-8", errors="replace")}

                await self._store(
                    idem_key,
                    str(org_id),
                    request.method,
                    str(request.url.path),
                    response_status,
                    body_json,
                )
            except Exception:
                logger.exception("Failed to store idempotency key=%s", idem_key)

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_cached(key: str, org_id: str) -> dict | None:
        """Return cached response dict or None if not found / expired."""
        from app.models.idempotency import IdempotencyKey

        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    select(IdempotencyKey)
                    .where(
                        IdempotencyKey.key == key,
                        IdempotencyKey.org_id == org_id,
                        IdempotencyKey.expires_at > now,
                    )
                )
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                if row is None:
                    return None
                return {
                    "response_status": row.response_status,
                    "response_body": row.response_body,
                }

    @staticmethod
    async def _store(
        key: str,
        org_id: str,
        method: str,
        endpoint: str,
        status_code: int,
        body: dict,
    ) -> None:
        """Insert or update the idempotency record with 24h expiry."""
        from app.models.idempotency import IdempotencyKey

        expires = datetime.now(timezone.utc) + timedelta(hours=_EXPIRY_HOURS)
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    pg_insert(IdempotencyKey.__table__)
                    .values(
                        key=key,
                        org_id=org_id,
                        method=method,
                        endpoint=endpoint,
                        response_status=status_code,
                        response_body=body,
                        expires_at=expires,
                    )
                    .on_conflict_do_update(
                        constraint="uq_idempotency_keys_key",
                        set_={
                            "response_status": status_code,
                            "response_body": body,
                            "expires_at": expires,
                        },
                    )
                )
                await session.execute(stmt)

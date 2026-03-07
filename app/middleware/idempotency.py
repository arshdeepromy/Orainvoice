"""Idempotency key middleware.

On POST/PUT/PATCH requests that include an ``Idempotency-Key`` header,
the middleware checks the ``idempotency_keys`` table:

* If a non-expired record exists for the key + org, the cached response is
  returned immediately without executing the downstream handler.
* Otherwise the request proceeds normally and the response is stored with a
  24-hour expiry so subsequent retries receive the same result.

**Validates: Requirement 10.3**
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import async_session_factory

logger = logging.getLogger(__name__)

# Methods that support idempotency keys
_IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}

# How long a cached response is valid
_EXPIRY_HOURS = 24


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Return cached responses for duplicate idempotent requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only intercept state-changing methods
        if request.method not in _IDEMPOTENT_METHODS:
            return await call_next(request)

        idem_key: str | None = request.headers.get("Idempotency-Key")
        if not idem_key:
            return await call_next(request)

        org_id = getattr(request.state, "org_id", None)
        if not org_id:
            # No org context — skip idempotency (e.g. unauthenticated)
            return await call_next(request)

        # --- Check for existing cached response ---
        try:
            cached = await self._get_cached(idem_key, str(org_id))
            if cached is not None:
                logger.debug("Idempotency cache hit for key=%s", idem_key)
                return JSONResponse(
                    status_code=cached["response_status"],
                    content=cached["response_body"],
                )
        except Exception:
            logger.exception("Idempotency lookup failed for key=%s", idem_key)
            # Fail open — proceed with the request

        # --- Execute the actual request ---
        response: Response = await call_next(request)

        # --- Store the response for future lookups ---
        try:
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                if isinstance(chunk, str):
                    body += chunk.encode("utf-8")
                else:
                    body += chunk

            # Try to parse body as JSON; fall back to wrapping as string
            try:
                body_json = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                body_json = {"raw": body.decode("utf-8", errors="replace")}

            await self._store(
                idem_key,
                str(org_id),
                request.method,
                str(request.url.path),
                response.status_code,
                body_json,
            )

            # Rebuild the response since we consumed the body iterator
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception:
            logger.exception("Failed to store idempotency key=%s", idem_key)
            # Return original-ish response even if storage fails
            return Response(
                content=body if "body" in dir() else b"",
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

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

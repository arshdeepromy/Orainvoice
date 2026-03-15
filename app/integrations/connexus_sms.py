"""Connexus SMS client.

Provides the ``ConnexusSmsClient`` that communicates with the WebSMS
Connexus REST API (https://websms.co.nz/api/connexus/) for sending SMS,
checking balance, validating numbers, and managing webhooks.

This module replaces the legacy Twilio and AWS SNS providers as the
platform's sole outbound SMS provider.

Token management
~~~~~~~~~~~~~~~~
A process-wide ``_TokenCache`` stores Bearer tokens keyed by credential
set.  A background ``_TokenRefresher`` task proactively refreshes the
token on the configured interval so that individual SMS sends, scheduled
reminders, and other API calls never trigger a token refresh themselves.

If an API call receives a 401 (token expired while a background refresh
is in progress), the client waits up to 4 seconds for the refresher to
deposit a new token, then retries once.

Requirements: 1.1
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.integrations.sms_types import SmsMessage, SmsSendResult

logger = logging.getLogger(__name__)


DEFAULT_API_BASE_URL = "https://websms.co.nz/api/connexus"


# ---------------------------------------------------------------------------
# Module-level token cache — shared across all ConnexusSmsClient instances
# ---------------------------------------------------------------------------

class _TokenCache:
    """Process-wide cache for Connexus Bearer tokens.

    Keyed by ``(client_id, api_base_url)`` so different credential sets
    each get their own cached token.  An ``asyncio.Lock`` per key
    prevents thundering-herd token refreshes when many coroutines hit
    the API concurrently.
    """

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], tuple[str, float]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        # Event fired whenever a token is stored — waiters can listen
        self._refresh_events: dict[tuple[str, str], asyncio.Event] = {}
        # Track when each token was last refreshed
        self._last_refresh_at: dict[tuple[str, str], float] = {}

    def _key(self, client_id: str, api_base_url: str) -> tuple[str, str]:
        return (client_id, api_base_url)

    def _get_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _get_event(self, key: tuple[str, str]) -> asyncio.Event:
        if key not in self._refresh_events:
            self._refresh_events[key] = asyncio.Event()
        return self._refresh_events[key]

    def get(self, client_id: str, api_base_url: str, margin: int = 300) -> str | None:
        """Return a cached token if still valid (with margin), else None."""
        key = self._key(client_id, api_base_url)
        entry = self._tokens.get(key)
        if entry is None:
            return None
        token, expires_at = entry
        if time.time() >= expires_at - margin:
            return None
        return token

    def get_unexpired(self, client_id: str, api_base_url: str) -> str | None:
        """Return a cached token if not yet expired (ignoring margin)."""
        key = self._key(client_id, api_base_url)
        entry = self._tokens.get(key)
        if entry is None:
            return None
        token, expires_at = entry
        if time.time() >= expires_at:
            return None
        return token

    def put(self, client_id: str, api_base_url: str, token: str, expires_in: int) -> None:
        """Store a token with its expiry and notify waiters."""
        key = self._key(client_id, api_base_url)
        self._tokens[key] = (token, time.time() + expires_in)
        self._last_refresh_at[key] = time.time()
        # Signal anyone waiting for a fresh token
        evt = self._get_event(key)
        evt.set()
        evt.clear()

    def invalidate(self, client_id: str, api_base_url: str) -> None:
        """Remove a cached token (e.g. after a 401)."""
        key = self._key(client_id, api_base_url)
        self._tokens.pop(key, None)

    def lock_for(self, client_id: str, api_base_url: str) -> asyncio.Lock:
        """Return the asyncio.Lock for a given credential set."""
        return self._get_lock(self._key(client_id, api_base_url))

    def event_for(self, client_id: str, api_base_url: str) -> asyncio.Event:
        """Return the asyncio.Event that fires when a new token is stored."""
        return self._get_event(self._key(client_id, api_base_url))

    def get_token_timing(self) -> dict[str, float | None]:
        """Return timing info for the first cached token (for dashboard display).

        Returns dict with ``last_refresh_at`` (epoch) and ``expires_at`` (epoch),
        or ``None`` values if no token is cached.
        """
        if not self._tokens:
            return {"last_refresh_at": None, "expires_at": None}
        # Take the first (and typically only) entry
        key = next(iter(self._tokens))
        _, expires_at = self._tokens[key]
        last_refresh = self._last_refresh_at.get(key)
        return {"last_refresh_at": last_refresh, "expires_at": expires_at}


_token_cache = _TokenCache()


# ---------------------------------------------------------------------------
# Token refresh log — tracks why each refresh happened
# ---------------------------------------------------------------------------

@dataclass
class _TokenRefreshEntry:
    """Single entry in the token refresh log."""
    timestamp: str          # ISO 8601
    reason: str             # Plain-English reason
    trigger: str            # Which function/code path triggered it
    was_early: bool         # True if token was refreshed before expiry
    token_remaining_secs: float | None  # Seconds left on old token (None if unknown)
    success: bool           # Whether the refresh succeeded


# Keep last 50 entries in memory (ring buffer)
_refresh_log: deque[_TokenRefreshEntry] = deque(maxlen=50)


def _log_refresh(
    reason: str,
    trigger: str,
    was_early: bool,
    token_remaining_secs: float | None,
    success: bool,
) -> None:
    """Append an entry to the in-memory token refresh log."""
    _refresh_log.append(_TokenRefreshEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        reason=reason,
        trigger=trigger,
        was_early=was_early,
        token_remaining_secs=token_remaining_secs,
        success=success,
    ))


def get_token_refresh_log() -> list[dict]:
    """Return the token refresh log as a list of dicts (newest first)."""
    return [
        {
            "timestamp": e.timestamp,
            "reason": e.reason,
            "trigger": e.trigger,
            "was_early": e.was_early,
            "token_remaining_secs": round(e.token_remaining_secs, 1) if e.token_remaining_secs is not None else None,
            "success": e.success,
        }
        for e in reversed(_refresh_log)
    ]


def get_token_status() -> dict[str, str | None]:
    """Return token timing info as ISO strings for the admin dashboard."""
    from datetime import datetime, timezone

    info = _token_cache.get_token_timing()
    result: dict[str, str | None] = {
        "last_refresh_at": None,
        "expires_at": None,
    }
    if info["last_refresh_at"] is not None:
        result["last_refresh_at"] = (
            datetime.fromtimestamp(info["last_refresh_at"], tz=timezone.utc).isoformat()
        )
    if info["expires_at"] is not None:
        result["expires_at"] = (
            datetime.fromtimestamp(info["expires_at"], tz=timezone.utc).isoformat()
        )
    return result


# ---------------------------------------------------------------------------
# Background token refresher
# ---------------------------------------------------------------------------

class _TokenRefresher:
    """Background task that proactively refreshes the Connexus token.

    Started once at application boot via ``start()``.  Reads the
    provider config from the database to determine the refresh interval.
    Runs in a loop, sleeping for the configured interval between
    refreshes.  This ensures SMS sends and scheduled reminders never
    need to trigger a token refresh themselves.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the background refresh loop (idempotent)."""
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="connexus-token-refresher")
        logger.info("Connexus token refresher started")

    async def stop(self) -> None:
        """Signal the loop to stop and wait for it to finish."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        self._task = None
        logger.info("Connexus token refresher stopped")

    async def _loop(self) -> None:
        """Main refresh loop — runs until stop() is called.

        Only refreshes when the cached token is within 5 minutes of
        expiry (or already expired / missing).  Otherwise sleeps until
        the token actually needs refreshing.
        """
        # On startup, try to restore the token from DB so we don't
        # needlessly hit the Connexus API after a container restart.
        await self._restore_token_from_db()

        while not self._stop_event.is_set():
            try:
                config, interval = await self._load_config()
                if config is None:
                    # No active Connexus provider — wait and retry
                    await self._sleep(60)
                    continue

                # Check if the cached token still has plenty of life left
                timing = _token_cache.get_token_timing()
                if timing["expires_at"] is not None:
                    remaining = timing["expires_at"] - time.time()
                    margin = 300  # 5 minutes before expiry
                    if remaining > margin:
                        # Token is still fresh — sleep until it needs refreshing
                        sleep_for = int(remaining - margin)
                        logger.debug(
                            "Connexus token still valid for %ds, sleeping %ds until refresh needed",
                            int(remaining),
                            sleep_for,
                        )
                        await self._sleep(sleep_for)
                        continue

                # Token is missing, expired, or within the 5-min margin — refresh now
                await self._do_refresh(config)

                # Sleep for the configured interval before checking again
                await self._sleep(interval)

            except Exception:
                logger.exception("Connexus token refresher error — retrying in 30s")
                await self._sleep(30)

    async def _sleep(self, seconds: int) -> None:
        """Sleep but wake early if stop() is called."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass  # Normal — just means the sleep completed

    async def _restore_token_from_db(self) -> None:
        """Load a previously persisted token from the DB into the in-memory cache.

        This avoids an unnecessary API call after a container restart when
        the token is still valid.
        """
        from app.core.database import async_session_factory
        from app.modules.admin.models import SmsVerificationProvider
        from sqlalchemy import select
        from app.core.encryption import envelope_decrypt_str
        import json

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(SmsVerificationProvider).where(
                        SmsVerificationProvider.provider_key == "connexus",
                        SmsVerificationProvider.is_active == True,  # noqa: E712
                    )
                )
                provider = result.scalar_one_or_none()
                if provider is None or not provider.credentials_encrypted:
                    return

                provider_config = provider.config or {}
                cached_token = provider_config.get("cached_token")
                cached_expires_at = provider_config.get("cached_token_expires_at")
                cached_refresh_at = provider_config.get("cached_token_refreshed_at")

                if not cached_token or not cached_expires_at:
                    return

                # Check if the persisted token is still valid
                remaining = cached_expires_at - time.time()
                if remaining <= 0:
                    logger.info(
                        "Persisted Connexus token already expired (%.0fs ago), will refresh",
                        -remaining,
                    )
                    return

                # Restore into in-memory cache
                creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
                client_id = creds.get("client_id", "").strip()
                api_base_url = creds.get(
                    "api_base_url", DEFAULT_API_BASE_URL
                ).strip()

                key = (client_id, api_base_url)
                _token_cache._tokens[key] = (cached_token, cached_expires_at)
                if cached_refresh_at:
                    _token_cache._last_refresh_at[key] = cached_refresh_at

                logger.info(
                    "Restored Connexus token from DB (%.0fs remaining)",
                    remaining,
                )
                _log_refresh(
                    reason="Token restored from database after container restart",
                    trigger="_TokenRefresher._restore_token_from_db",
                    was_early=True,
                    token_remaining_secs=remaining,
                    success=True,
                )
        except Exception:
            logger.exception("Failed to restore Connexus token from DB — will refresh normally")

    async def _persist_token_to_db(self, token: str, expires_at: float) -> None:
        """Save the current token and expiry to the provider's config JSONB.

        This ensures the token survives container restarts.
        """
        from app.core.database import async_session_factory
        from app.modules.admin.models import SmsVerificationProvider
        from sqlalchemy import select

        try:
            async with async_session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(SmsVerificationProvider).where(
                            SmsVerificationProvider.provider_key == "connexus",
                            SmsVerificationProvider.is_active == True,  # noqa: E712
                        )
                    )
                    provider = result.scalar_one_or_none()
                    if provider is None:
                        return

                    config = dict(provider.config or {})
                    config["cached_token"] = token
                    config["cached_token_expires_at"] = expires_at
                    config["cached_token_refreshed_at"] = time.time()
                    provider.config = config
        except Exception:
            logger.exception("Failed to persist Connexus token to DB")

    async def _load_config(self) -> tuple[ConnexusConfig | None, int]:
        """Read the Connexus provider config from the database.

        Returns ``(config, refresh_interval_seconds)`` or ``(None, 0)``
        if no active Connexus provider is configured.
        """
        # Late import to avoid circular dependency at module load time
        from app.core.database import async_session_factory
        from app.modules.admin.models import SmsVerificationProvider
        from sqlalchemy import select
        from app.core.encryption import envelope_decrypt_str
        import json

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(SmsVerificationProvider).where(
                        SmsVerificationProvider.provider_key == "connexus",
                        SmsVerificationProvider.is_active == True,  # noqa: E712
                    )
                )
                provider = result.scalar_one_or_none()
                if provider is None or not provider.credentials_encrypted:
                    return None, 0

                creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
                # Merge token_refresh_interval_seconds from provider config
                provider_config = provider.config or {}
                if provider_config.get("token_refresh_interval_seconds"):
                    creds["token_refresh_interval_seconds"] = provider_config[
                        "token_refresh_interval_seconds"
                    ]
                config = ConnexusConfig.from_dict(creds)

                # Determine refresh interval
                interval = config.token_refresh_interval_seconds
                if interval <= 0:
                    # Default: refresh 5 min before 1-hour expiry = every 55 min
                    interval = 3300
                return config, interval
        except Exception:
            logger.exception("Failed to load Connexus config for token refresher")
            return None, 0

    async def _do_refresh(self, config: ConnexusConfig) -> None:
        """Perform the actual token refresh using a temporary HTTP client."""
        url = f"{config.api_base_url}/auth/token"
        payload = {
            "client_id": config.client_id.strip(),
            "client_secret": config.client_secret.strip(),
        }

        # Check how much time the old token had left
        timing = _token_cache.get_token_timing()
        remaining = None
        was_early = False
        cache_empty = timing["expires_at"] is None
        if not cache_empty:
            remaining = timing["expires_at"] - time.time()
            was_early = remaining > 0

        async with httpx.AsyncClient(timeout=30) as http:
            try:
                resp = await http.post(url, data=payload)
                if resp.status_code == 401:
                    logger.error(
                        "Connexus token refresh 401 — client_id length=%d, url=%s",
                        len(config.client_id),
                        url,
                    )
                resp.raise_for_status()
                data = resp.json()
                token = data["access_token"]
                expires_in = int(data.get("expires_in", 3600))
                _token_cache.put(config.client_id, config.api_base_url, token, expires_in)
                logger.info(
                    "Connexus token refreshed (expires_in=%ds, next refresh in configured interval)",
                    expires_in,
                )

                # Persist to DB so the token survives container restarts
                expires_at_epoch = time.time() + expires_in
                await self._persist_token_to_db(token, expires_at_epoch)

                if cache_empty:
                    reason = "No token in memory (container restart or first boot) — fetched new token"
                elif was_early:
                    reason = "Token nearing expiry (<5 min left) — proactive background refresh"
                else:
                    reason = "Token had expired — background refresh"
                _log_refresh(
                    reason=reason,
                    trigger="_TokenRefresher._do_refresh (background loop)",
                    was_early=was_early,
                    token_remaining_secs=remaining,
                    success=True,
                )
            except Exception:
                _token_cache.invalidate(config.client_id, config.api_base_url)
                logger.exception("Connexus background token refresh failed")
                _log_refresh(
                    reason="Background refresh failed — "
                           + ("cache was empty" if cache_empty
                              else "token was nearing expiry" if was_early
                              else "token had expired"),
                    trigger="_TokenRefresher._do_refresh (background loop)",
                    was_early=was_early,
                    token_remaining_secs=remaining,
                    success=False,
                )
                raise


_token_refresher = _TokenRefresher()


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class ConnexusConfig:
    """Configuration for the Connexus SMS API."""

    client_id: str
    client_secret: str
    sender_id: str
    api_base_url: str = DEFAULT_API_BASE_URL
    token_refresh_interval_seconds: int = 0  # 0 = use default (5 min before expiry)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnexusConfig:
        """Create a ``ConnexusConfig`` from a plain dictionary."""
        return cls(
            client_id=data.get("client_id", "").strip(),
            client_secret=data.get("client_secret", "").strip(),
            sender_id=data.get("sender_id", "").strip(),
            api_base_url=data.get("api_base_url", DEFAULT_API_BASE_URL).strip(),
            token_refresh_interval_seconds=int(data.get("token_refresh_interval_seconds", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the config to a plain dictionary."""
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "sender_id": self.sender_id,
            "api_base_url": self.api_base_url,
            "token_refresh_interval_seconds": self.token_refresh_interval_seconds,
        }


class ConnexusSmsClient:
    """Async client for the WebSMS Connexus REST API.

    Token management is handled by a background ``_TokenRefresher`` task
    that proactively refreshes the token on the configured interval.
    Individual API calls (send, balance, etc.) only read from the shared
    cache — they never trigger a token refresh.

    If an API call gets a 401 (token expired while refresh is in
    progress), the client waits up to 4 seconds for the background
    refresher to deposit a new token, then retries once.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 1.8
    """

    _REFRESH_MARGIN: int = 300  # seconds – default margin before expiry
    _TOKEN_LIFETIME: int = 3600  # seconds – 1 hour
    _TIMEOUT: int = 30  # seconds – HTTP timeout for all calls
    _RETRY_WAIT: float = 4.0  # seconds – max wait for token on 401

    def __init__(self, config: ConnexusConfig) -> None:
        self._config = config
        self._http = httpx.AsyncClient(timeout=self._TIMEOUT)

    async def close(self) -> None:
        """Close the underlying HTTP client to release resources."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Token management (read-only from cache for API calls)
    # ------------------------------------------------------------------

    async def _refresh_token(self, reason: str = "Direct refresh (fallback — no background refresher)") -> str:
        """Request a new Bearer token from the Connexus auth endpoint.

        This is used as a fallback when no background refresher is
        running (e.g. during tests or first-time setup).  Normal
        production flow uses the background ``_TokenRefresher``.

        Requirements: 2.1, 2.5
        """
        url = f"{self._config.api_base_url}/auth/token"
        payload = {
            "client_id": self._config.client_id.strip(),
            "client_secret": self._config.client_secret.strip(),
        }

        # Check remaining time on old token
        timing = _token_cache.get_token_timing()
        remaining = None
        was_early = False
        if timing["expires_at"] is not None:
            remaining = timing["expires_at"] - time.time()
            was_early = remaining > 0

        try:
            resp = await self._http.post(url, data=payload)
            if resp.status_code == 401:
                body = resp.text[:500]
                logger.error(
                    "Connexus auth 401 — client_id length=%d, secret length=%d, url=%s, response=%s",
                    len(self._config.client_id),
                    len(self._config.client_secret),
                    url,
                    body,
                )
            resp.raise_for_status()
            data = resp.json()
            token = data["access_token"]
            expires_in = int(data.get("expires_in", self._TOKEN_LIFETIME))
            _token_cache.put(
                self._config.client_id,
                self._config.api_base_url,
                token,
                expires_in,
            )
            _log_refresh(
                reason=reason,
                trigger="ConnexusSmsClient._refresh_token",
                was_early=was_early,
                token_remaining_secs=remaining,
                success=True,
            )
            return token
        except Exception:
            _token_cache.invalidate(self._config.client_id, self._config.api_base_url)
            logger.exception("Connexus token refresh failed")
            _log_refresh(
                reason=reason + " (FAILED)",
                trigger="ConnexusSmsClient._refresh_token",
                was_early=was_early,
                token_remaining_secs=remaining,
                success=False,
            )
            raise

    async def _ensure_token(self) -> str:
        """Return a valid Bearer token from the shared cache.

        If the background refresher is running, this only reads from
        cache.  If no token exists at all (first boot, tests), falls
        back to a one-time refresh with lock protection.

        Requirements: 2.2, 2.3
        """
        # Fast path: cache hit (use margin=0 — accept any non-expired token,
        # the background refresher handles proactive refresh)
        cached = _token_cache.get_unexpired(
            self._config.client_id,
            self._config.api_base_url,
        )
        if cached is not None:
            return cached

        # No token at all — need to bootstrap (first request or tests).
        # Use lock to prevent thundering herd.
        lock = _token_cache.lock_for(self._config.client_id, self._config.api_base_url)
        async with lock:
            cached = _token_cache.get_unexpired(
                self._config.client_id,
                self._config.api_base_url,
            )
            if cached is not None:
                return cached
            return await self._refresh_token(
                reason="Bootstrap — no cached token exists (first request or app startup)"
            )

    async def _wait_for_fresh_token(self) -> str | None:
        """Wait up to 4 seconds for the background refresher to provide a new token.

        Returns the new token if one appears, or None if the wait times out.
        """
        evt = _token_cache.event_for(self._config.client_id, self._config.api_base_url)
        deadline = time.time() + self._RETRY_WAIT
        while time.time() < deadline:
            # Check if a fresh token appeared
            cached = _token_cache.get_unexpired(
                self._config.client_id,
                self._config.api_base_url,
            )
            if cached is not None:
                return cached
            # Wait for the event or timeout
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(evt.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass
        # Final check
        return _token_cache.get_unexpired(
            self._config.client_id,
            self._config.api_base_url,
        )

    # ------------------------------------------------------------------
    # Generic request helper with 401 wait-and-retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an authenticated HTTP request with 401 wait-and-retry.

        * Injects ``Authorization: Bearer <token>`` header.
        * On a 401 response, invalidates the stale token, waits up to
          4 seconds for the background refresher to provide a new one,
          then retries exactly once.

        Requirements: 2.4, 2.6, 1.8
        """
        token = await self._ensure_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        resp = await self._http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 401:
            logger.warning("Connexus API 401 — waiting for background token refresh")
            # Invalidate the stale token
            _token_cache.invalidate(self._config.client_id, self._config.api_base_url)
            # Wait for the background refresher to provide a new token
            new_token = await self._wait_for_fresh_token()
            if new_token is None:
                # Background refresher didn't provide a token in time —
                # fall back to a direct refresh as last resort
                logger.warning("Background refresh did not complete in time — doing direct refresh")
                try:
                    new_token = await self._refresh_token(
                        reason="API returned 401 — background refresher too slow, direct refresh as last resort"
                    )
                except Exception:
                    logger.exception("Direct token refresh also failed after 401")
                    return resp  # Return the original 401 response
            headers["Authorization"] = f"Bearer {new_token}"
            resp = await self._http.request(method, url, headers=headers, **kwargs)

        return resp


    # ------------------------------------------------------------------
    # Core SMS sending
    # ------------------------------------------------------------------

    async def send(self, message: SmsMessage) -> SmsSendResult:
        """Send an SMS via the Connexus API.

        POSTs to ``{api_base_url}/sms/out`` with ``to``, ``body``, and
        an optional ``from`` field (falls back to the configured
        ``sender_id``).

        Returns an ``SmsSendResult`` indicating success or failure.
        Network and timeout exceptions are caught, logged, and returned
        as structured error results rather than propagated.

        Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.9
        """
        url = f"{self._config.api_base_url}/sms/out"
        payload: dict[str, Any] = {
            "to": message.to_number,
            "body": message.body,
        }
        from_number = message.from_number or self._config.sender_id
        if from_number:
            payload["from"] = from_number

        try:
            resp = await self._request("POST", url, data=payload)

            if resp.is_success:
                data = resp.json()
                if data.get("status") == "accepted":
                    return SmsSendResult(
                        success=True,
                        message_sid=data["message_id"],
                        metadata={"parts_count": data.get("parts", 1)},
                    )

            # Non-success HTTP or unexpected status in body
            return SmsSendResult(
                success=False,
                error=f"{resp.status_code}: {resp.text}",
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            logger.exception("Connexus send failed due to network/timeout error")
            return SmsSendResult(success=False, error=str(exc))
        except Exception as exc:
            logger.exception("Connexus send failed with unexpected error")
            return SmsSendResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Balance, number validation, and webhook configuration
    # ------------------------------------------------------------------

    async def check_balance(self) -> dict:
        """Check the Connexus account balance.

        POSTs to ``{api_base_url}/sms/balance`` and returns the balance
        amount and currency.

        Returns ``{"balance": float, "currency": str}`` on success, or
        ``{"error": str}`` on failure.

        Requirements: 11.1, 11.3
        """
        url = f"{self._config.api_base_url}/sms/balance"
        try:
            resp = await self._request("POST", url)
            if resp.is_success:
                data = resp.json()
                return {
                    "balance": float(data.get("balance", 0)),
                    "currency": data.get("currency", "NZD"),
                }
            return {"error": f"{resp.status_code}: {resp.text}"}
        except Exception as exc:
            logger.exception("Connexus balance check failed")
            return {"error": str(exc)}

    async def validate_number(self, number: str) -> dict:
        """Validate a phone number via the Connexus IPMS lookup.

        POSTs to ``{api_base_url}/number/lookup`` with the number and
        returns carrier, porting status, and network information.

        Returns ``{"success": True, ...lookup data}`` on success, or
        ``{"success": False, "error": str}`` on failure.

        Requirements: 12.1, 12.2, 12.3
        """
        url = f"{self._config.api_base_url}/number/lookup"
        try:
            resp = await self._request("POST", url, data={"number": number})
            if resp.is_success:
                data = resp.json()
                return {"success": True, **data}
            return {
                "success": False,
                "error": f"{resp.status_code}: {resp.text}",
            }
        except Exception as exc:
            logger.exception("Connexus number validation failed")
            return {"success": False, "error": str(exc)}

    async def configure_webhooks(
        self, mo_webhook_url: str, dlr_webhook_url: str
    ) -> dict:
        """Configure Connexus webhook URLs for incoming SMS and delivery status.

        POSTs to ``{api_base_url}/configure`` with the MO (mobile-originated)
        and DLR (delivery report) webhook URLs.

        Returns the Connexus response data on success, or
        ``{"error": str}`` on failure.

        Requirements: 13.1
        """
        url = f"{self._config.api_base_url}/configure"
        payload = {
            "mo_webhook_url": mo_webhook_url,
            "dlr_webhook_url": dlr_webhook_url,
        }
        try:
            resp = await self._request("POST", url, json=payload)
            if resp.is_success:
                return resp.json()
            return {"error": f"{resp.status_code}: {resp.text}"}
        except Exception as exc:
            logger.exception("Connexus webhook configuration failed")
            return {"error": str(exc)}

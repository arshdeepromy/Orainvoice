"""Heartbeat service for HA peer health monitoring.

A background asyncio task that pings the peer node's heartbeat endpoint
at a configurable interval and tracks health history in a bounded deque.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import httpx

from app.modules.ha.hmac_utils import verify_hmac
from app.modules.ha.schemas import HeartbeatHistoryEntry
from app.modules.ha.utils import classify_peer_health, detect_split_brain, should_auto_promote

logger = logging.getLogger(__name__)

# Timeout for each HTTP heartbeat request (seconds).
_PING_TIMEOUT = 5.0


class HeartbeatService:
    """Monitors peer node health via periodic HTTP heartbeat pings.

    The service runs as a background asyncio task. Each ping cycle:
    1. Sends an HTTP GET to the peer's ``/api/v1/ha/heartbeat`` endpoint.
    2. Verifies the HMAC signature on the response.
    3. Records the result in a bounded history deque (max 100 entries).
    4. Updates the cached peer health classification.
    5. Logs transitions between health states.
    """

    def __init__(self, peer_endpoint: str, interval: int, secret: str, local_role: str = "standalone") -> None:
        self.peer_endpoint = peer_endpoint.rstrip("/")
        self.interval = interval
        self.secret = secret
        self.local_role = local_role
        self.history: deque[HeartbeatHistoryEntry] = deque(maxlen=100)
        self.peer_health: str = "unknown"
        self.split_brain_detected: bool = False
        self._task: asyncio.Task | None = None
        self._last_successful_heartbeat: float | None = None
        # Failover state tracking (Task 4)
        self._peer_unreachable_since: float | None = None  # monotonic timestamp
        self._auto_promote_attempted: bool = False
        self._auto_promote_failed_permanently: bool = False
        self._peer_promoted_at: datetime | None = None
        # Sync status DB update throttle (Task 16.4)
        self._last_sync_status_update: float = 0.0  # monotonic timestamp
        # Actual peer role from heartbeat responses (BUG-HA-15)
        self.peer_role: str = "unknown"
        # Redis distributed lock for multi-worker isolation (BUG-HA-06)
        self._redis_lock_key: str | None = None
        self._lock_ttl: int = 30
        self._redis_client = None  # redis.asyncio.Redis or None

    async def start(self) -> None:
        """Start the background heartbeat ping loop."""
        if self._task is not None and not self._task.done():
            logger.warning("HeartbeatService already running — ignoring start()")
            return
        self._task = asyncio.create_task(self._ping_loop())
        logger.info(
            "HeartbeatService started — pinging %s every %ds",
            self.peer_endpoint,
            self.interval,
        )

    async def stop(self) -> None:
        """Cancel the background heartbeat task and wait for it to finish."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("HeartbeatService stopped")

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def _ping_loop(self) -> None:
        """Continuously ping the peer at the configured interval.

        The loop body is wrapped in a try/except so that transient errors
        (network issues, DNS failures, JSON parse errors, DB errors) do not
        kill the background task.  ``asyncio.CancelledError`` is always
        re-raised so that ``stop()`` can cleanly cancel the task.

        A local ``_consecutive_failures`` counter tracks how many cycles in
        a row have failed.  After 5 consecutive failures a warning is logged
        to flag potential service degradation.

        Requirements: 15.1, 15.2, 15.3, 15.4
        """
        _consecutive_failures = 0
        try:
            while True:
                try:
                    entry = await self._ping_peer()
                    self.history.append(entry)

                    previous_health = self.peer_health
                    self.peer_health = self._classify_health()

                    # Log health transitions (Req 2.5, 2.6)
                    if previous_health != "unreachable" and self.peer_health == "unreachable":
                        logger.warning(
                            "Peer %s transitioned to UNREACHABLE (was %s)",
                            self.peer_endpoint,
                            previous_health,
                        )
                        # Record when peer became unreachable (Req 3.2)
                        self._peer_unreachable_since = time.monotonic()
                    elif previous_health == "unreachable" and self.peer_health != "unreachable":
                        logger.info(
                            "Peer %s is reachable again (now %s)",
                            self.peer_endpoint,
                            self.peer_health,
                        )
                        # Reset unreachable tracking when peer comes back (Req 3.5)
                        self._peer_unreachable_since = None

                    # --- Split-brain write protection (Req 8.1) ---
                    if self.split_brain_detected:
                        try:
                            from app.core.database import async_session_factory
                            from app.modules.ha.models import HAConfig
                            from app.modules.ha.middleware import set_split_brain_blocked
                            from sqlalchemy import select

                            async with async_session_factory() as sb_session:
                                async with sb_session.begin():
                                    result = await sb_session.execute(select(HAConfig).limit(1))
                                    cfg = result.scalars().first()
                                    local_promoted_at = cfg.promoted_at if cfg else None

                            if self.is_stale_primary(local_promoted_at):
                                set_split_brain_blocked(True)
                            # If not stale, don't block — the other node is stale
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.error("Error checking split-brain stale primary: %s", exc)
                    else:
                        from app.modules.ha.middleware import set_split_brain_blocked
                        set_split_brain_blocked(False)

                    # --- Auto-promote trigger (Req 4.1) ---
                    if (
                        self.peer_health == "unreachable"
                        and self._peer_unreachable_since is not None
                        and not self._auto_promote_attempted
                        and not self._auto_promote_failed_permanently
                    ):
                        elapsed = time.monotonic() - self._peer_unreachable_since
                        try:
                            from app.core.database import async_session_factory
                            from app.modules.ha.models import HAConfig
                            from sqlalchemy import select

                            async with async_session_factory() as check_session:
                                async with check_session.begin():
                                    result = await check_session.execute(select(HAConfig).limit(1))
                                    cfg = result.scalars().first()
                                    if cfg and should_auto_promote(
                                        cfg.auto_promote_enabled, elapsed, cfg.failover_timeout_seconds
                                    ):
                                        self._auto_promote_attempted = True
                                        logger.info(
                                            "Auto-promote conditions met: peer unreachable %.1fs > timeout %ds",
                                            elapsed,
                                            cfg.failover_timeout_seconds,
                                        )
                                        await self._execute_auto_promote()
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.error("Error checking auto-promote conditions: %s", exc)

                    # --- Sync status DB update (Req 16.1–16.4) ---
                    now_mono = time.monotonic()
                    if now_mono - self._last_sync_status_update > 30:
                        self._last_sync_status_update = now_mono
                        try:
                            from app.core.database import async_session_factory
                            from app.modules.ha.models import HAConfig
                            from sqlalchemy import select

                            async with async_session_factory() as sync_session:
                                async with sync_session.begin():
                                    result = await sync_session.execute(select(HAConfig).limit(1))
                                    cfg = result.scalars().first()
                                    if cfg:
                                        cfg.sync_status = self._determine_sync_status()
                                        cfg.last_peer_health = self.peer_health
                                        cfg.last_peer_heartbeat = datetime.now(timezone.utc)
                        except Exception:
                            pass  # Non-critical — don't crash heartbeat for status updates

                    # Successful cycle — reset consecutive failure counter
                    _consecutive_failures = 0

                    # --- BUG-HA-06: Renew Redis heartbeat lock TTL ---
                    try:
                        if self._redis_lock_key and self._redis_client:
                            await self._redis_client.expire(self._redis_lock_key, self._lock_ttl)
                    except Exception:
                        pass  # Non-critical; another worker takes over when lock expires

                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _consecutive_failures += 1
                    logger.error(
                        "Heartbeat ping cycle error (%d consecutive): %s",
                        _consecutive_failures,
                        exc,
                    )
                    if _consecutive_failures >= 5:
                        logger.warning(
                            "HeartbeatService: 5+ consecutive failures — service may be degraded"
                        )

                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Single ping
    # ------------------------------------------------------------------

    async def _ping_peer(self) -> HeartbeatHistoryEntry:
        """Send a single heartbeat ping to the peer and return a history entry."""
        url = f"{self.peer_endpoint}/api/v1/ha/heartbeat"
        now_iso = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
                resp = await client.get(url)
                elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code != 200:
                return HeartbeatHistoryEntry(
                    timestamp=now_iso,
                    peer_status="error",
                    response_time_ms=elapsed_ms,
                    error=f"HTTP {resp.status_code}",
                )

            data = resp.json()

            # Verify HMAC signature (Req 11.4)
            signature = data.pop("hmac_signature", "")
            if not verify_hmac(data, signature, self.secret):
                return HeartbeatHistoryEntry(
                    timestamp=now_iso,
                    peer_status="error",
                    response_time_ms=elapsed_ms,
                    error="Invalid HMAC signature",
                )

            # Successful heartbeat
            self._last_successful_heartbeat = time.monotonic()

            # Store actual peer role from response (BUG-HA-15)
            self.peer_role = data.get("role", "unknown")

            # Parse promoted_at from peer heartbeat response (Req 11.3)
            raw_promoted_at = data.get("promoted_at")
            if raw_promoted_at:
                try:
                    self._peer_promoted_at = datetime.fromisoformat(raw_promoted_at)
                except (ValueError, TypeError):
                    self._peer_promoted_at = None
            else:
                self._peer_promoted_at = None

            # Split-brain detection: warn if both nodes claim primary
            peer_role = data.get("role", "")
            if detect_split_brain(self.local_role, peer_role):
                self.split_brain_detected = True
                logger.critical(
                    "SPLIT-BRAIN DETECTED: both local (%s) and peer (%s) "
                    "claim role 'primary'. Manual intervention required!",
                    self.local_role,
                    peer_role,
                )
            else:
                self.split_brain_detected = False

            return HeartbeatHistoryEntry(
                timestamp=now_iso,
                peer_status=data.get("status", "healthy"),
                replication_lag_seconds=data.get("replication_lag_seconds"),
                response_time_ms=elapsed_ms,
            )

        except (httpx.RequestError, Exception) as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return HeartbeatHistoryEntry(
                timestamp=now_iso,
                peer_status="error",
                response_time_ms=elapsed_ms,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Health queries
    # ------------------------------------------------------------------

    def _classify_health(self) -> str:
        """Derive peer health from the time since the last successful heartbeat."""
        if self._last_successful_heartbeat is None:
            return "unknown"
        delta = time.monotonic() - self._last_successful_heartbeat
        return classify_peer_health(delta)

    def get_peer_health(self) -> str:
        """Return the current peer health classification.

        One of: ``"healthy"``, ``"degraded"``, ``"unreachable"``, or ``"unknown"``.
        """
        return self.peer_health

    def get_history(self) -> list[HeartbeatHistoryEntry]:
        """Return the heartbeat history as a plain list (most recent last)."""
        return list(self.history)

    # ------------------------------------------------------------------
    # Failover state queries (Task 4)
    # ------------------------------------------------------------------

    def get_peer_unreachable_seconds(self) -> float | None:
        """Return seconds since peer became unreachable, or None if reachable."""
        if self._peer_unreachable_since is None:
            return None
        return time.monotonic() - self._peer_unreachable_since

    def get_seconds_until_auto_promote(self, failover_timeout: int) -> float | None:
        """Return seconds until auto-promote triggers, or None if peer is reachable."""
        elapsed = self.get_peer_unreachable_seconds()
        if elapsed is None:
            return None
        return max(0.0, failover_timeout - elapsed)

    def is_stale_primary(self, local_promoted_at: datetime | None) -> bool:
        """Compare local vs peer promoted_at timestamps.

        Returns True (stale) when:
        - local is None and peer is not None → stale
        - both are not None and local < peer → stale
        Otherwise → not stale
        """
        if self._peer_promoted_at is None:
            return False
        if local_promoted_at is None:
            return True
        return local_promoted_at < self._peer_promoted_at

    # ------------------------------------------------------------------
    # Sync status determination (Task 16.2)
    # ------------------------------------------------------------------

    def _determine_sync_status(self) -> str:
        """Determine the current sync status based on replication state.

        Checks the latest heartbeat entry's replication_lag_seconds and
        peer_status to classify the sync status:
        - "healthy": subscription active + lag < 60s
        - "lagging": subscription active + lag >= 60s
        - "disconnected": subscription disabled or peer unreachable
        - "not_configured": no subscription/publication (no successful heartbeat data)

        Requirements: 16.2
        """
        # Look at the most recent heartbeat entry for replication data
        if not self.history:
            return "not_configured"

        latest = self.history[-1]

        # If peer is unreachable, the subscription is effectively disconnected
        if self.peer_health == "unreachable":
            return "disconnected"

        # If the latest heartbeat had an error (peer_status == "error"),
        # treat as disconnected
        if latest.peer_status == "error":
            return "disconnected"

        # If we have replication lag data, the subscription is active
        if latest.replication_lag_seconds is not None:
            if latest.replication_lag_seconds < 60:
                return "healthy"
            else:
                return "lagging"

        # No lag data available — could mean no subscription/publication exists
        # If peer is reachable but no lag data, subscription may not be configured
        if self.peer_health in ("healthy", "degraded"):
            # Peer is reachable but no replication lag reported — not configured
            return "not_configured"

        return "not_configured"

    # ------------------------------------------------------------------
    # Auto-promote execution (Task 5)
    # ------------------------------------------------------------------

    async def _execute_auto_promote(self) -> None:
        """Promote this node to primary automatically.

        Uses a dedicated short-lived DB session via ``async_session_factory()``
        to avoid transaction timeout issues with the heartbeat loop.

        On failure: logs error, waits 10 seconds, retries once.
        On second failure: sets ``_auto_promote_failed_permanently = True``.

        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 4.8
        """
        # --- BUG-HA-06: Redis distributed lock for auto-promote ---
        PROMOTE_LOCK_KEY = "ha:auto_promote_lock"
        worker_id = str(os.getpid())
        try:
            from app.core.redis import redis_pool
            acquired = await redis_pool.set(PROMOTE_LOCK_KEY, worker_id, nx=True, ex=60)
            if not acquired:
                logger.info("Auto-promote lock held by another worker — skipping")
                return
        except Exception as redis_exc:
            logger.warning(
                "Redis unavailable for auto-promote lock — proceeding without lock: %s",
                redis_exc,
            )

        for attempt in range(2):
            try:
                from app.core.database import async_session_factory
                from app.core.audit import write_audit_log
                from app.modules.ha.middleware import set_node_role
                from app.modules.ha.models import HAConfig
                from app.modules.ha.replication import ReplicationManager
                from sqlalchemy import select

                async with async_session_factory() as session:
                    async with session.begin():
                        result = await session.execute(select(HAConfig).limit(1))
                        cfg = result.scalars().first()

                        if cfg is None:
                            logger.error("Auto-promote aborted: no HAConfig found")
                            return

                        # Verify role is still standby (guard against race)
                        if cfg.role != "standby":
                            logger.info(
                                "Auto-promote skipped: role is already '%s'", cfg.role
                            )
                            return

                        # Stop the replication subscription
                        try:
                            await ReplicationManager.stop_subscription(session)
                        except Exception as sub_exc:
                            logger.warning(
                                "Could not stop subscription during auto-promote: %s",
                                sub_exc,
                            )

                        # Update role to primary and set promoted_at
                        now = datetime.now(timezone.utc)
                        cfg.role = "primary"
                        cfg.promoted_at = now
                        cfg.updated_at = now

                        # Update middleware cache so node starts accepting writes
                        set_node_role("primary", cfg.peer_endpoint)
                        self.local_role = "primary"

                        # Post-promotion sequence sync (BUG-HA-01 safety net)
                        try:
                            await ReplicationManager.sync_sequences_post_promotion()
                        except Exception as seq_exc:
                            logger.warning("Post-promotion sequence sync failed: %s", seq_exc)

                        # Write audit log with system UUID (no user session active)
                        system_user_id = uuid.uuid4()
                        unreachable_secs = self.get_peer_unreachable_seconds()
                        await write_audit_log(
                            session=session,
                            action="ha.auto_promoted",
                            entity_type="ha_config",
                            user_id=system_user_id,
                            entity_id=cfg.id,
                            after_value={
                                "role": "primary",
                                "promoted_at": now.isoformat(),
                                "peer_unreachable_seconds": unreachable_secs,
                                "failover_timeout_seconds": cfg.failover_timeout_seconds,
                            },
                        )

                logger.info(
                    "Auto-promote SUCCEEDED: node is now PRIMARY (attempt %d)",
                    attempt + 1,
                )
                return  # Success — exit retry loop

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Auto-promote FAILED (attempt %d/2): %s", attempt + 1, exc
                )
                if attempt == 0:
                    # Wait 10 seconds before retry
                    await asyncio.sleep(10)
                else:
                    # Second failure — give up permanently
                    self._auto_promote_failed_permanently = True
                    logger.critical(
                        "Auto-promote failed permanently after 2 attempts. "
                        "Manual promotion required."
                    )

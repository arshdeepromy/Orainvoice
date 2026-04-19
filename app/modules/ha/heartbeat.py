"""Heartbeat service for HA peer health monitoring.

A background asyncio task that pings the peer node's heartbeat endpoint
at a configurable interval and tracks health history in a bounded deque.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone

import httpx

from app.modules.ha.hmac_utils import verify_hmac
from app.modules.ha.schemas import HeartbeatHistoryEntry
from app.modules.ha.utils import classify_peer_health, detect_split_brain

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
        """Continuously ping the peer at the configured interval."""
        try:
            while True:
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
                elif previous_health == "unreachable" and self.peer_health != "unreachable":
                    logger.info(
                        "Peer %s is reachable again (now %s)",
                        self.peer_endpoint,
                        self.peer_health,
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

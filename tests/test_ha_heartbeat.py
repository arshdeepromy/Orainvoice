"""Unit tests for the HeartbeatService.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from app.modules.ha.heartbeat import HeartbeatService
from app.modules.ha.hmac_utils import compute_hmac
from app.modules.ha.schemas import HeartbeatHistoryEntry


PEER = "http://192.168.1.100:8999"
SECRET = "test-secret"


# ── __init__ ─────────────────────────────────────────────────────────


def test_init_defaults():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    assert svc.peer_endpoint == PEER
    assert svc.interval == 10
    assert svc.secret == SECRET
    assert isinstance(svc.history, deque)
    assert svc.history.maxlen == 100
    assert svc.peer_health == "unknown"
    assert svc._task is None


def test_init_strips_trailing_slash():
    svc = HeartbeatService(f"{PEER}/", interval=10, secret=SECRET)
    assert svc.peer_endpoint == PEER


# ── start / stop ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_creates_task():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    with patch.object(svc, "_ping_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.side_effect = asyncio.CancelledError
        await svc.start()
        assert svc._task is not None
        await svc.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    with patch.object(svc, "_ping_loop", new_callable=AsyncMock) as mock_loop:
        # Make the loop hang so we can cancel it
        mock_loop.side_effect = asyncio.CancelledError
        await svc.start()
        await svc.stop()
        assert svc._task is None


@pytest.mark.asyncio
async def test_stop_noop_when_not_started():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    await svc.stop()  # Should not raise
    assert svc._task is None


# ── _ping_peer ───────────────────────────────────────────────────────


def _make_heartbeat_payload() -> dict:
    """Build a valid heartbeat response payload (without hmac_signature)."""
    return {
        "node_id": "abc-123",
        "node_name": "Pi-Standby",
        "role": "standby",
        "status": "healthy",
        "database_status": "connected",
        "replication_lag_seconds": 1.2,
        "sync_status": "healthy",
        "uptime_seconds": 3600.0,
        "maintenance": False,
        "timestamp": "2025-01-01T00:00:00+00:00",
    }


def _signed_response(payload: dict, secret: str = SECRET) -> dict:
    """Return payload with a valid hmac_signature appended."""
    sig = compute_hmac(payload, secret)
    return {**payload, "hmac_signature": sig}


@pytest.mark.asyncio
async def test_ping_peer_success():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    payload = _make_heartbeat_payload()
    signed = _signed_response(payload)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = signed.copy()

    with patch("app.modules.ha.heartbeat.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        entry = await svc._ping_peer()

    assert entry.peer_status == "healthy"
    assert entry.error is None
    assert entry.response_time_ms is not None
    assert entry.replication_lag_seconds == 1.2


@pytest.mark.asyncio
async def test_ping_peer_bad_hmac():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    payload = _make_heartbeat_payload()
    # Sign with wrong secret
    bad_signed = _signed_response(payload, secret="wrong-secret")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = bad_signed.copy()

    with patch("app.modules.ha.heartbeat.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        entry = await svc._ping_peer()

    assert entry.peer_status == "error"
    assert "HMAC" in entry.error


@pytest.mark.asyncio
async def test_ping_peer_http_error():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.json.return_value = {}

    with patch("app.modules.ha.heartbeat.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        entry = await svc._ping_peer()

    assert entry.peer_status == "error"
    assert "500" in entry.error


@pytest.mark.asyncio
async def test_ping_peer_connection_error():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)

    with patch("app.modules.ha.heartbeat.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        entry = await svc._ping_peer()

    assert entry.peer_status == "error"
    assert entry.error is not None


# ── get_peer_health / get_history ────────────────────────────────────


def test_get_peer_health_initial():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    assert svc.get_peer_health() == "unknown"


def test_get_history_empty():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    assert svc.get_history() == []


def test_get_history_returns_list():
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    entry = HeartbeatHistoryEntry(
        timestamp="2025-01-01T00:00:00+00:00",
        peer_status="healthy",
    )
    svc.history.append(entry)
    result = svc.get_history()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].peer_status == "healthy"


def test_history_bounded_at_100():
    """Deque never exceeds maxlen=100."""
    svc = HeartbeatService(PEER, interval=10, secret=SECRET)
    for i in range(150):
        svc.history.append(
            HeartbeatHistoryEntry(
                timestamp=f"2025-01-01T00:00:{i:02d}+00:00",
                peer_status="healthy",
            )
        )
    assert len(svc.history) == 100
    assert len(svc.get_history()) == 100


# ── Crash recovery (Task 15) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ping_loop_continues_after_exception():
    """15.1/15.2: An exception in the loop body does not kill the task."""
    svc = HeartbeatService(PEER, interval=0, secret=SECRET)

    call_count = 0

    async def _failing_ping():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("transient DB error")
        # Third call succeeds — then we cancel to exit the loop
        svc._task.cancel()
        return HeartbeatHistoryEntry(
            timestamp="2025-01-01T00:00:00+00:00",
            peer_status="healthy",
        )

    with patch.object(svc, "_ping_peer", side_effect=_failing_ping):
        with patch.object(svc, "_classify_health", return_value="unknown"):
            with patch("app.modules.ha.heartbeat.asyncio.sleep", new_callable=AsyncMock):
                with patch("app.modules.ha.middleware.set_split_brain_blocked"):
                    svc._task = asyncio.current_task()  # so cancel works
                    task = asyncio.create_task(svc._ping_loop())
                    svc._task = task
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    # The loop survived 2 failures and reached the 3rd call
    assert call_count == 3


@pytest.mark.asyncio
async def test_ping_loop_logs_consecutive_failures(caplog):
    """15.3: After 5 consecutive failures, a degraded warning is logged."""
    svc = HeartbeatService(PEER, interval=0, secret=SECRET)

    call_count = 0

    async def _always_fail():
        nonlocal call_count
        call_count += 1
        if call_count >= 6:
            # Stop after 6 failures so we can check logs
            raise asyncio.CancelledError
        raise RuntimeError(f"error #{call_count}")

    with patch.object(svc, "_ping_peer", side_effect=_always_fail):
        with patch("app.modules.ha.heartbeat.asyncio.sleep", new_callable=AsyncMock):
            import logging
            with caplog.at_level(logging.WARNING, logger="app.modules.ha.heartbeat"):
                task = asyncio.create_task(svc._ping_loop())
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # 5 failures should trigger the degraded warning
    assert any("5+ consecutive failures" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_ping_loop_resets_failures_on_success():
    """15.3: Consecutive failure counter resets after a successful cycle."""
    svc = HeartbeatService(PEER, interval=0, secret=SECRET)

    call_count = 0

    async def _fail_then_succeed():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise RuntimeError("transient error")
        if call_count == 4:
            # Success — this resets the counter
            return HeartbeatHistoryEntry(
                timestamp="2025-01-01T00:00:00+00:00",
                peer_status="healthy",
            )
        # 5th call: fail again, then cancel
        if call_count == 5:
            raise RuntimeError("another error")
        raise asyncio.CancelledError

    with patch.object(svc, "_ping_peer", side_effect=_fail_then_succeed):
        with patch.object(svc, "_classify_health", return_value="unknown"):
            with patch("app.modules.ha.heartbeat.asyncio.sleep", new_callable=AsyncMock):
                with patch("app.modules.ha.middleware.set_split_brain_blocked"):
                    task = asyncio.create_task(svc._ping_loop())
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    # After 3 failures + 1 success + 1 failure + cancel = 6 calls
    assert call_count == 6


@pytest.mark.asyncio
async def test_ping_loop_cancelled_error_propagates():
    """15.1: asyncio.CancelledError is always re-raised, never swallowed."""
    svc = HeartbeatService(PEER, interval=0, secret=SECRET)

    async def _raise_cancelled():
        raise asyncio.CancelledError

    with patch.object(svc, "_ping_peer", side_effect=_raise_cancelled):
        with pytest.raises(asyncio.CancelledError):
            await svc._ping_loop()


@pytest.mark.asyncio
async def test_ping_loop_auto_promote_error_does_not_crash_loop():
    """15.4: A failed auto-promote doesn't crash the heartbeat loop."""
    svc = HeartbeatService(PEER, interval=0, secret=SECRET, local_role="standby")
    svc._peer_unreachable_since = 0.0  # pretend peer has been unreachable

    call_count = 0

    async def _success_ping():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError
        return HeartbeatHistoryEntry(
            timestamp="2025-01-01T00:00:00+00:00",
            peer_status="error",
            error="Connection refused",
        )

    # Make _classify_health return "unreachable" to trigger auto-promote path
    with patch.object(svc, "_ping_peer", side_effect=_success_ping):
        with patch.object(svc, "_classify_health", return_value="unreachable"):
            with patch("app.modules.ha.heartbeat.asyncio.sleep", new_callable=AsyncMock):
                with patch("app.modules.ha.middleware.set_split_brain_blocked"):
                    # Mock the auto-promote DB check to raise an error
                    with patch("app.modules.ha.heartbeat.should_auto_promote", return_value=True):
                        with patch("app.core.database.async_session_factory", side_effect=RuntimeError("DB down")):
                            task = asyncio.create_task(svc._ping_loop())
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass

    # Loop survived the auto-promote error and continued
    assert call_count >= 2


@pytest.mark.asyncio
async def test_ping_loop_sleep_outside_inner_try():
    """15.2: asyncio.sleep is called even after an exception in the cycle body."""
    svc = HeartbeatService(PEER, interval=5, secret=SECRET)

    call_count = 0
    sleep_calls = []

    async def _fail_once():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("boom")
        raise asyncio.CancelledError

    async def _mock_sleep(seconds):
        sleep_calls.append(seconds)

    with patch.object(svc, "_ping_peer", side_effect=_fail_once):
        with patch("app.modules.ha.heartbeat.asyncio.sleep", side_effect=_mock_sleep):
            task = asyncio.create_task(svc._ping_loop())
            try:
                await task
            except asyncio.CancelledError:
                pass

    # Sleep should have been called after the failed cycle
    assert len(sleep_calls) >= 1
    assert sleep_calls[0] == 5

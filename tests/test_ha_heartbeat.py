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

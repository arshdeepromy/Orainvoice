"""Unit tests for ``RestoreMaintenanceMiddleware`` gate + drain logic.

Feature: cloud-backup-restore (task 15.1)
Requirements: 12.1, 12.2

These tests drive the middleware directly as an ASGI app with the DB-backed
flag primed in-process (no DB needed) — they verify the request gate (503 for
non-exempt traffic, pass-through for Global-Admin + health) and the in-flight
active-request counter / drain helper.
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.backup_restore import middleware as mw


def _http_scope(path: str = "/api/v1/invoices", role: str | None = None) -> dict:
    """Build a minimal ASGI http scope with an optional auth role in state."""
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "state": {"role": role},
    }


async def _collect(scope: dict):
    """Run the middleware over *scope*, returning (downstream_called, messages)."""
    downstream_called = False

    async def downstream_app(s, receive, send):
        nonlocal downstream_called
        downstream_called = True

    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    async def receive():  # pragma: no cover - not exercised
        return {"type": "http.request", "body": b""}

    mid = mw.RestoreMaintenanceMiddleware(downstream_app)
    await mid(scope, receive, send)
    return downstream_called, messages


def _status_of(messages: list[dict]) -> int | None:
    for m in messages:
        if m["type"] == "http.response.start":
            return m["status"]
    return None


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module-level cache + counter around every test."""
    mw.prime_maintenance_active(False)
    mw._active_requests = 0
    yield
    mw.prime_maintenance_active(False)
    mw._active_requests = 0


@pytest.mark.asyncio
async def test_non_exempt_request_blocked_with_503_during_maintenance():
    """Req 12.1 — normal traffic gets HTTP 503 while maintenance is active."""
    mw.prime_maintenance_active(True)

    called, messages = await _collect(_http_scope(role="owner"))

    assert called is False
    assert _status_of(messages) == 503
    # Counter is untouched for blocked requests.
    assert mw.get_active_request_count() == 0


@pytest.mark.asyncio
async def test_global_admin_request_passes_during_maintenance():
    """Req 12.1 — Global-Admin can keep monitoring / cancelling the restore."""
    mw.prime_maintenance_active(True)

    called, messages = await _collect(_http_scope(role="global_admin"))

    assert called is True
    assert _status_of(messages) is None
    # Exempt requests are not counted toward the drain.
    assert mw.get_active_request_count() == 0


@pytest.mark.asyncio
async def test_health_path_passes_during_maintenance():
    """Req 12.1 — health/liveness probes stay up during maintenance."""
    mw.prime_maintenance_active(True)

    called, messages = await _collect(_http_scope(path="/health", role=None))

    assert called is True
    assert _status_of(messages) is None


@pytest.mark.asyncio
async def test_request_passes_and_counter_balances_when_inactive():
    """When maintenance is inactive, traffic flows and the counter returns to 0."""
    mw.prime_maintenance_active(False)

    called, messages = await _collect(_http_scope(role="owner"))

    assert called is True
    assert _status_of(messages) is None
    assert mw.get_active_request_count() == 0


@pytest.mark.asyncio
async def test_counter_increments_while_request_in_flight():
    """The active-request counter reflects an in-flight non-exempt request."""
    observed = {}

    async def slow_app(scope, receive, send):
        observed["count"] = mw.get_active_request_count()

    mid = mw.RestoreMaintenanceMiddleware(slow_app)
    await mid(_http_scope(role="owner"), None, lambda m: asyncio.sleep(0))

    assert observed["count"] == 1
    assert mw.get_active_request_count() == 0


@pytest.mark.asyncio
async def test_counter_decrements_even_when_downstream_raises():
    """An exception downstream must not leak the active-request counter."""

    async def boom_app(scope, receive, send):
        raise RuntimeError("downstream failure")

    mid = mw.RestoreMaintenanceMiddleware(boom_app)
    with pytest.raises(RuntimeError):
        await mid(_http_scope(role="owner"), None, lambda m: asyncio.sleep(0))

    assert mw.get_active_request_count() == 0


@pytest.mark.asyncio
async def test_wait_for_drain_returns_true_when_idle():
    """Drain completes immediately when no requests are in flight (Req 12.1)."""
    mw._active_requests = 0
    drained = await mw.wait_for_drain(grace_seconds=1.0, poll_interval=0.01)
    assert drained is True


@pytest.mark.asyncio
async def test_wait_for_drain_times_out_when_requests_stuck():
    """Drain returns False if the grace expires with requests still in flight."""
    mw._active_requests = 2
    drained = await mw.wait_for_drain(grace_seconds=0.1, poll_interval=0.02)
    assert drained is False


@pytest.mark.asyncio
async def test_wait_for_drain_succeeds_when_request_completes_within_grace():
    """Drain succeeds once the in-flight count falls to zero within the grace."""
    mw._active_requests = 1

    async def finish_soon():
        await asyncio.sleep(0.05)
        mw._active_requests = 0

    task = asyncio.create_task(finish_soon())
    drained = await mw.wait_for_drain(grace_seconds=1.0, poll_interval=0.01)
    await task
    assert drained is True


@pytest.mark.asyncio
async def test_non_http_scope_passes_through():
    """Websocket / lifespan scopes are not gated by this middleware."""
    called = False

    async def downstream_app(scope, receive, send):
        nonlocal called
        called = True

    mid = mw.RestoreMaintenanceMiddleware(downstream_app)
    await mid({"type": "websocket", "path": "/ws/x"}, None, None)
    assert called is True

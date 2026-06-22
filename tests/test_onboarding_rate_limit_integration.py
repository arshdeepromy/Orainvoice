"""Integration test for the public staff-onboarding per-IP rate limit.

Feature: staff-onboarding-link (Task 9.2)

Requirement 11.2: THE Staff_Module SHALL apply per-IP rate limiting of
30 requests per minute to the onboarding endpoints, returning HTTP 429
with a ``Retry-After`` header once the limit is exceeded.

This is an example/integration test (NOT a Hypothesis property test).
It mounts a tiny stub route under the public onboarding prefix
(``/api/v2/public/staff-onboarding/{token}``) behind the real
``RateLimitMiddleware`` and drives >30 requests/min from a single client
IP, asserting that the first 30 are allowed and the 31st is rejected with
``429`` + ``Retry-After``.

The rate limiter is the system under test — it is NOT bypassed. A real
in-memory ``fakeredis`` instance backs the sliding window so the
sorted-set window logic runs exactly as it would against Redis.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis as AsyncFakeRedis
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.middleware.rate_limit import (
    _PUBLIC_STAFF_ONBOARDING_RATE_LIMIT,
    RateLimitMiddleware,
)

# A fixed client IP so every request shares the same per-IP rate-limit key.
_CLIENT_IP = "203.0.113.42"
_ONBOARDING_PATH = "/api/v2/public/staff-onboarding/tok-abc-123"


def _build_stub_app() -> Starlette:
    """A minimal ASGI app with one stub route under the onboarding prefix.

    The real onboarding endpoint isn't needed — proving the prefix is
    rate-limited at 30/min is enough. The stub always returns 200 so any
    429 we observe must originate from the rate limiter, not the handler.
    """

    async def _onboarding_stub(request):  # noqa: ANN001
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route(
                "/api/v2/public/staff-onboarding/{token}",
                _onboarding_stub,
                methods=["GET"],
            ),
        ],
    )


@pytest_asyncio.fixture
async def fake_redis():
    """Real in-memory async Redis double backing the sliding window."""
    redis = AsyncFakeRedis(decode_responses=True)
    yield redis
    await redis.flushall()
    await redis.aclose()


@pytest_asyncio.fixture
async def client(fake_redis):
    """httpx client wired to the stub app behind the live RateLimitMiddleware."""
    app = RateLimitMiddleware(_build_stub_app(), redis=fake_redis)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestPublicOnboardingRateLimit:
    """Requirement 11.2 — 30 req/min per IP on the onboarding prefix."""

    @pytest.mark.asyncio
    async def test_thirty_first_request_returns_429_with_retry_after(self, client):
        """First 30 requests are allowed; the 31st within the window is 429.

        Drives 31 requests from the same client IP. The limit is 30/min, so
        requests 1-30 must pass through to the stub handler (200) and the
        31st must be rejected by the rate limiter with 429 + Retry-After.
        """
        headers = {"X-Forwarded-For": _CLIENT_IP}

        # First 30 requests are within budget and reach the stub handler.
        for i in range(_PUBLIC_STAFF_ONBOARDING_RATE_LIMIT):
            resp = await client.get(_ONBOARDING_PATH, headers=headers)
            assert resp.status_code == 200, (
                f"request {i + 1} should be allowed (within the 30/min budget), "
                f"got {resp.status_code}"
            )

        # The 31st request within the same minute exceeds the limit.
        over_limit = await client.get(_ONBOARDING_PATH, headers=headers)
        assert over_limit.status_code == 429, (
            "the 31st request within the window must be rate-limited"
        )
        assert "Retry-After" in over_limit.headers, (
            "a 429 rate-limit response must carry a Retry-After header"
        )
        # Retry-After is a positive integer number of seconds.
        retry_after = over_limit.headers["Retry-After"]
        assert retry_after.isdigit() and int(retry_after) >= 1, (
            f"Retry-After must be a positive integer, got {retry_after!r}"
        )

    @pytest.mark.asyncio
    async def test_separate_ips_have_independent_budgets(self, fake_redis):
        """The limit is per-IP: a second IP is unaffected by the first's spend.

        Confirms the rate limit keys on the client IP (not globally), so an
        over-limit IP does not throttle a different, well-behaved client.
        """
        app = RateLimitMiddleware(_build_stub_app(), redis=fake_redis)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            # Exhaust the budget for the first IP (30 ok, 31st blocked).
            for _ in range(_PUBLIC_STAFF_ONBOARDING_RATE_LIMIT):
                ok = await ac.get(_ONBOARDING_PATH, headers={"X-Forwarded-For": _CLIENT_IP})
                assert ok.status_code == 200
            blocked = await ac.get(
                _ONBOARDING_PATH, headers={"X-Forwarded-For": _CLIENT_IP}
            )
            assert blocked.status_code == 429

            # A different IP still has its full budget.
            other = await ac.get(
                _ONBOARDING_PATH, headers={"X-Forwarded-For": "198.51.100.7"}
            )
            assert other.status_code == 200

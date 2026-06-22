"""Integration tests for the four employee-portal per-IP rate limits.

Feature: organisation-employee-portal (Task 17.6)

Validates Requirements 9.6, 9.7, 16.1, 16.2: THE Employee_Portal SHALL apply
per-IP sliding-window rate limiting to its public/admin surfaces, returning
HTTP ``429`` with a ``Retry-After`` header once the limit is exceeded, and the
rate-limited request SHALL perform no action and establish no session.

The four configured limits (wired in task 12.2, see ``app/middleware/rate_limit``):
  * portal login           ``POST /e/api/auth/login``                  10/min
  * slug-availability      ``GET  /api/v2/organisations/slug-availability`` 30/min
  * portal-resolve         ``GET  /api/v2/public/portal-resolve``       30/min
  * password-reset (pair)  ``POST /e/api/auth/password/reset-request``   5/min
                           ``POST /e/api/auth/password/reset``  (shared bucket)

These are example/integration tests (NOT Hypothesis property tests). Each
mounts a tiny stub route at the exact rate-limited path behind the *real*
``RateLimitMiddleware`` and drives requests past the threshold from a single
client IP. The rate limiter is the system under test — it is NOT bypassed. A
real in-memory ``fakeredis`` instance backs the sliding window so the
sorted-set window logic runs exactly as it would against Redis.

Each stub records how many times it was actually invoked, so we can assert the
over-limit request never reached the handler — i.e. it performed *no action*
and could not have established a session.
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
    _EMPLOYEE_PORTAL_LOGIN_PATH,
    _EMPLOYEE_PORTAL_LOGIN_RATE_LIMIT,
    _EMPLOYEE_PORTAL_PASSWORD_RESET_LIMIT,
    _EMPLOYEE_PORTAL_PASSWORD_RESET_PATHS,
    _PORTAL_RESOLVE_PATH,
    _PORTAL_RESOLVE_RATE_LIMIT,
    _SLUG_AVAILABILITY_PATH,
    _SLUG_AVAILABILITY_RATE_LIMIT,
    RateLimitMiddleware,
)

# A fixed client IP so every request shares the same per-IP rate-limit key.
_CLIENT_IP = "203.0.113.77"
_OTHER_IP = "198.51.100.9"


def _build_stub_app(invocations: dict[str, int]) -> Starlette:
    """A minimal ASGI app with one stub route per rate-limited portal path.

    The real handlers aren't needed — proving each path is rate-limited at its
    configured threshold is enough. Every stub increments an invocation counter
    and returns 200, so:
      * any 429 we observe must originate from the rate limiter, not the handler;
      * the final invocation count proves the over-limit request never reached
        the handler (no action taken, no session established).
    """

    def _make_stub(path_key: str):
        async def _stub(request):  # noqa: ANN001
            invocations[path_key] = invocations.get(path_key, 0) + 1
            return JSONResponse({"ok": True})

        return _stub

    # Sort the reset paths for deterministic route registration.
    reset_paths = sorted(_EMPLOYEE_PORTAL_PASSWORD_RESET_PATHS)

    routes = [
        Route(_EMPLOYEE_PORTAL_LOGIN_PATH, _make_stub(_EMPLOYEE_PORTAL_LOGIN_PATH), methods=["POST"]),
        Route(_SLUG_AVAILABILITY_PATH, _make_stub(_SLUG_AVAILABILITY_PATH), methods=["GET"]),
        Route(_PORTAL_RESOLVE_PATH, _make_stub(_PORTAL_RESOLVE_PATH), methods=["GET"]),
    ]
    # The two password-reset paths share a single rate-limit bucket; record
    # their invocations under a shared key so the "no action" assertion covers
    # the bucket as a whole.
    for p in reset_paths:
        routes.append(Route(p, _make_stub("password-reset"), methods=["POST"]))

    return Starlette(routes=routes)


@pytest_asyncio.fixture
async def fake_redis():
    """Real in-memory async Redis double backing the sliding window."""
    redis = AsyncFakeRedis(decode_responses=True)
    yield redis
    await redis.flushall()
    await redis.aclose()


@pytest_asyncio.fixture
async def invocations() -> dict[str, int]:
    """Shared counter recording how many times each stub handler ran."""
    return {}


@pytest_asyncio.fixture
async def client(fake_redis, invocations):
    """httpx client wired to the stub app behind the live RateLimitMiddleware."""
    app = RateLimitMiddleware(_build_stub_app(invocations), redis=fake_redis)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _assert_retry_after(response: httpx.Response) -> None:
    """A 429 rate-limit response must carry a positive integer Retry-After."""
    assert response.status_code == 429, (
        f"expected 429 once the limit is exceeded, got {response.status_code}"
    )
    assert "Retry-After" in response.headers, (
        "a 429 rate-limit response must carry a Retry-After header (R16.2)"
    )
    retry_after = response.headers["Retry-After"]
    assert retry_after.isdigit() and int(retry_after) >= 1, (
        f"Retry-After must be a positive integer number of seconds, got {retry_after!r}"
    )


class TestEmployeePortalLoginRateLimit:
    """Login: 10 req/min per IP (R16.1, R16.2)."""

    @pytest.mark.asyncio
    async def test_eleventh_login_returns_429_with_retry_after_and_no_action(
        self, client, invocations
    ):
        headers = {"X-Forwarded-For": _CLIENT_IP}

        for i in range(_EMPLOYEE_PORTAL_LOGIN_RATE_LIMIT):
            resp = await client.post(_EMPLOYEE_PORTAL_LOGIN_PATH, headers=headers, json={})
            assert resp.status_code == 200, (
                f"login request {i + 1} should be within the 10/min budget, got {resp.status_code}"
            )

        over_limit = await client.post(_EMPLOYEE_PORTAL_LOGIN_PATH, headers=headers, json={})
        _assert_retry_after(over_limit)

        # The over-limit request never reached the handler → no auth attempt,
        # no session established (R16.1: "no action on exceed").
        assert invocations.get(_EMPLOYEE_PORTAL_LOGIN_PATH) == _EMPLOYEE_PORTAL_LOGIN_RATE_LIMIT, (
            "the rate-limited login must not invoke the handler (no action / no session)"
        )


class TestSlugAvailabilityRateLimit:
    """Slug availability: 30 req/min per IP (R3.1, R16.1)."""

    @pytest.mark.asyncio
    async def test_thirty_first_check_returns_429_with_retry_after_and_no_action(
        self, client, invocations
    ):
        headers = {"X-Forwarded-For": _CLIENT_IP}
        path = f"{_SLUG_AVAILABILITY_PATH}?slug=acme"

        for i in range(_SLUG_AVAILABILITY_RATE_LIMIT):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 200, (
                f"slug-availability request {i + 1} should be within the 30/min budget, "
                f"got {resp.status_code}"
            )

        over_limit = await client.get(path, headers=headers)
        _assert_retry_after(over_limit)
        assert invocations.get(_SLUG_AVAILABILITY_PATH) == _SLUG_AVAILABILITY_RATE_LIMIT, (
            "the rate-limited slug-availability check must not invoke the handler"
        )


class TestPortalResolveRateLimit:
    """Portal resolve: 30 req/min per IP (R9.6, R9.7, R16.1)."""

    @pytest.mark.asyncio
    async def test_thirty_first_resolve_returns_429_with_retry_after_and_no_action(
        self, client, invocations
    ):
        headers = {"X-Forwarded-For": _CLIENT_IP}
        path = f"{_PORTAL_RESOLVE_PATH}?q=acme&portal_type=employee"

        for i in range(_PORTAL_RESOLVE_RATE_LIMIT):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 200, (
                f"portal-resolve request {i + 1} should be within the 30/min budget, "
                f"got {resp.status_code}"
            )

        over_limit = await client.get(path, headers=headers)
        _assert_retry_after(over_limit)
        assert invocations.get(_PORTAL_RESOLVE_PATH) == _PORTAL_RESOLVE_RATE_LIMIT, (
            "the rate-limited portal-resolve must not invoke the handler"
        )


class TestEmployeePortalPasswordResetRateLimit:
    """Password reset: 5 req/min per IP, shared across both reset paths (R16.1, R16.2)."""

    @pytest.mark.asyncio
    async def test_sixth_reset_returns_429_with_retry_after_and_no_action(
        self, client, invocations
    ):
        headers = {"X-Forwarded-For": _CLIENT_IP}
        reset_request = "/e/api/auth/password/reset-request"

        for i in range(_EMPLOYEE_PORTAL_PASSWORD_RESET_LIMIT):
            resp = await client.post(reset_request, headers=headers, json={})
            assert resp.status_code == 200, (
                f"password-reset request {i + 1} should be within the 5/min budget, "
                f"got {resp.status_code}"
            )

        over_limit = await client.post(reset_request, headers=headers, json={})
        _assert_retry_after(over_limit)
        assert invocations.get("password-reset") == _EMPLOYEE_PORTAL_PASSWORD_RESET_LIMIT, (
            "the rate-limited password-reset must not invoke the handler (no action)"
        )

    @pytest.mark.asyncio
    async def test_reset_bucket_is_shared_across_both_paths(self, client, invocations):
        """The two reset endpoints draw from one shared 5/min per-IP bucket.

        Mixing requests across ``reset-request`` and ``reset`` must still trip
        the limit at the 6th combined request — not 6 per path.
        """
        headers = {"X-Forwarded-For": _CLIENT_IP}
        reset_request = "/e/api/auth/password/reset-request"
        reset = "/e/api/auth/password/reset"

        # 3 to reset-request + 2 to reset = 5 combined (the full budget).
        for _ in range(3):
            resp = await client.post(reset_request, headers=headers, json={})
            assert resp.status_code == 200
        for _ in range(2):
            resp = await client.post(reset, headers=headers, json={})
            assert resp.status_code == 200

        # The 6th combined request (to either path) is rejected.
        over_limit = await client.post(reset, headers=headers, json={})
        _assert_retry_after(over_limit)
        assert invocations.get("password-reset") == _EMPLOYEE_PORTAL_PASSWORD_RESET_LIMIT, (
            "the shared reset bucket must block the 6th combined request with no action"
        )


class TestRateLimitsArePerIp:
    """Each limit keys on the client IP — an over-limit IP never throttles another."""

    @pytest.mark.asyncio
    async def test_login_limit_is_per_ip(self, client, invocations):
        # Exhaust the login budget for the first IP.
        for _ in range(_EMPLOYEE_PORTAL_LOGIN_RATE_LIMIT):
            ok = await client.post(
                _EMPLOYEE_PORTAL_LOGIN_PATH,
                headers={"X-Forwarded-For": _CLIENT_IP},
                json={},
            )
            assert ok.status_code == 200
        blocked = await client.post(
            _EMPLOYEE_PORTAL_LOGIN_PATH, headers={"X-Forwarded-For": _CLIENT_IP}, json={}
        )
        assert blocked.status_code == 429

        # A different IP still has its full budget.
        other = await client.post(
            _EMPLOYEE_PORTAL_LOGIN_PATH, headers={"X-Forwarded-For": _OTHER_IP}, json={}
        )
        assert other.status_code == 200, "a second IP must have an independent budget"

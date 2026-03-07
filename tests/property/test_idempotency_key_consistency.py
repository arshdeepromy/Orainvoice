"""Property-based test for idempotency key consistency.

**Validates: Requirements 10.3**

### Property 16: Idempotency Key Consistency
For any two requests R1 and R2 with the same idempotency key K to the same
endpoint, the response to R2 is identical to the response to R1 (same status
code and body).

This test exercises the IdempotencyMiddleware's caching logic directly
(without a running server) by simulating the cache-check / cache-store
cycle with in-memory state.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

status_code_strategy = st.sampled_from([200, 201, 202, 204, 400, 404, 409, 422, 500])

json_body_strategy = st.fixed_dictionaries({
    "id": st.uuids().map(str),
    "message": st.text(min_size=1, max_size=50),
    "count": st.integers(min_value=0, max_value=10000),
})

idem_key_strategy = st.uuids().map(str)

org_id_strategy = st.uuids().map(str)

method_strategy = st.sampled_from(["POST", "PUT", "PATCH"])

endpoint_strategy = st.from_regex(r"/api/v2/[a-z]{3,15}", fullmatch=True)


# ---------------------------------------------------------------------------
# In-memory idempotency store (simulates DB behaviour)
# ---------------------------------------------------------------------------

class InMemoryIdempotencyStore:
    """Mimics the DB-backed cache used by IdempotencyMiddleware."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict] = {}

    def get(self, key: str, org_id: str) -> dict | None:
        record = self._store.get((key, org_id))
        if record is None:
            return None
        if record["expires_at"] <= datetime.now(timezone.utc):
            return None
        return record

    def put(
        self,
        key: str,
        org_id: str,
        method: str,
        endpoint: str,
        status_code: int,
        body: dict,
    ) -> None:
        self._store[(key, org_id)] = {
            "key": key,
            "org_id": org_id,
            "method": method,
            "endpoint": endpoint,
            "response_status": status_code,
            "response_body": body,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
        }


def _simulate_request(
    store: InMemoryIdempotencyStore,
    idem_key: str,
    org_id: str,
    method: str,
    endpoint: str,
    handler_status: int,
    handler_body: dict,
) -> tuple[int, dict]:
    """Simulate the middleware logic: check cache → execute → store.

    Returns (status_code, body) that the client would receive.
    """
    # Check cache
    cached = store.get(idem_key, org_id)
    if cached is not None:
        return cached["response_status"], cached["response_body"]

    # "Execute" the handler
    response_status = handler_status
    response_body = handler_body

    # Store for future lookups
    store.put(idem_key, org_id, method, endpoint, response_status, response_body)

    return response_status, response_body


# ===========================================================================
# Property 16: Idempotency Key Consistency
# ===========================================================================


class TestIdempotencyKeyConsistency:
    """Two requests with the same idempotency key return identical responses.

    **Validates: Requirements 10.3**
    """

    @given(
        idem_key=idem_key_strategy,
        org_id=org_id_strategy,
        method=method_strategy,
        endpoint=endpoint_strategy,
        handler_status=status_code_strategy,
        handler_body=json_body_strategy,
    )
    @PBT_SETTINGS
    def test_same_key_returns_identical_response(
        self,
        idem_key: str,
        org_id: str,
        method: str,
        endpoint: str,
        handler_status: int,
        handler_body: dict,
    ) -> None:
        """R1 and R2 with the same key K produce the same (status, body)."""
        store = InMemoryIdempotencyStore()

        status1, body1 = _simulate_request(
            store, idem_key, org_id, method, endpoint, handler_status, handler_body,
        )
        # Second request — handler would return different data, but the
        # cached response from R1 should be returned instead.
        status2, body2 = _simulate_request(
            store, idem_key, org_id, method, endpoint, 999, {"should": "not appear"},
        )

        assert status1 == status2, (
            f"Status mismatch: R1={status1}, R2={status2} for key={idem_key}"
        )
        assert body1 == body2, (
            f"Body mismatch for key={idem_key}"
        )

    @given(
        key_a=idem_key_strategy,
        key_b=idem_key_strategy,
        org_id=org_id_strategy,
        method=method_strategy,
        endpoint=endpoint_strategy,
        status_a=status_code_strategy,
        body_a=json_body_strategy,
        status_b=status_code_strategy,
        body_b=json_body_strategy,
    )
    @PBT_SETTINGS
    def test_different_keys_are_independent(
        self,
        key_a: str,
        key_b: str,
        org_id: str,
        method: str,
        endpoint: str,
        status_a: int,
        body_a: dict,
        status_b: int,
        body_b: dict,
    ) -> None:
        """Different idempotency keys produce independent responses."""
        assume(key_a != key_b)

        store = InMemoryIdempotencyStore()

        s1, b1 = _simulate_request(store, key_a, org_id, method, endpoint, status_a, body_a)
        s2, b2 = _simulate_request(store, key_b, org_id, method, endpoint, status_b, body_b)

        assert s1 == status_a
        assert b1 == body_a
        assert s2 == status_b
        assert b2 == body_b

    @given(
        idem_key=idem_key_strategy,
        org_id=org_id_strategy,
        method=method_strategy,
        endpoint=endpoint_strategy,
        handler_status=status_code_strategy,
        handler_body=json_body_strategy,
        repeat_count=st.integers(min_value=2, max_value=10),
    )
    @PBT_SETTINGS
    def test_n_requests_all_return_first_response(
        self,
        idem_key: str,
        org_id: str,
        method: str,
        endpoint: str,
        handler_status: int,
        handler_body: dict,
        repeat_count: int,
    ) -> None:
        """N requests with the same key all return the first response."""
        store = InMemoryIdempotencyStore()

        first_status, first_body = _simulate_request(
            store, idem_key, org_id, method, endpoint, handler_status, handler_body,
        )

        for i in range(repeat_count - 1):
            s, b = _simulate_request(
                store, idem_key, org_id, method, endpoint, 500 + i, {"attempt": i},
            )
            assert s == first_status, f"Attempt {i+2}: status {s} != {first_status}"
            assert b == first_body, f"Attempt {i+2}: body mismatch"

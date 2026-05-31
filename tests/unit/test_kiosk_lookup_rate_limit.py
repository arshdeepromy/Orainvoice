"""Unit tests for the G12 kiosk-lookup rate limit (task B9).

Covers the inline G12 check that runs on top of the existing
``_check_kiosk_rate_limit`` dependency at the
``POST /api/v1/kiosk/clock/lookup`` route.

Per ``.kiro/specs/staff-management-p3/tasks.md`` task B9:
  - 11th lookup for the same ``(org_id, employee_id)`` within 60s
    returns HTTP 429 with ``Retry-After: 60`` and body
    ``{"detail": "kiosk_lookup_rate_limited"}``.
  - The Redis key is hashed (``sha256(employee_id)[:16]``) so the
    raw employee_id never lands in Redis or audit logs.
  - An audit row ``kiosk.lookup_rate_limited`` is written with the
    hashed identifier in ``after_value``.

Also asserts the two-layer interaction (P3-N9):
  - ``_check_kiosk_rate_limit`` (30/min/kiosk-user dependency)
    rejects with body ``{"detail": "Rate limit exceeded"}`` —
    distinct from the G12 body.

**Validates: Requirements R3.3 — Staff Management Phase 3 task B9 / G12**
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure SQLAlchemy mappers are registered before any model is touched.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401

from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry
from app.modules.time_clock.service import (
    KioskLookupRateLimitedError,
    _hash_employee_id,
    lookup_for_kiosk,
)


# ---------------------------------------------------------------------------
# In-memory test doubles
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal :mod:`redis.asyncio` double covering the calls made by
    :func:`app.modules.time_clock.service._check_kiosk_lookup_rate_limit`
    — ``incr`` + ``expire``.

    Keeps real counter state so a sequence of calls trips the budget at
    the same point a real Redis would.
    """

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True

    def keys_view(self) -> list[str]:
        """Helper for assertions — what a Redis SCAN would surface."""
        return list(self.counters.keys())


def _make_staff(
    *,
    org_id: uuid.UUID,
    employee_id: str = "EMP-001",
) -> StaffMember:
    return StaffMember(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        employee_id=employee_id,
        self_service_clock_enabled=False,
        on_file_photo_url="https://uploads/staff/jane.jpg",
        employment_type="permanent",
    )


def _make_db(
    *,
    staff: StaffMember | None = None,
    open_entry: TimeClockEntry | None = None,
    clock_in_policy: dict | None = None,
) -> AsyncMock:
    """Build an :class:`AsyncMock` DB session covering the queries the
    service issues in the lookup path:

    1. ``text("SELECT clock_in_policy ...")`` — returns the org policy
       JSONB (or empty dict).
    2. ``select(StaffMember)`` by employee_id — returns the staff (or
       ``None`` for the not-found path).
    3. ``select(TimeClockEntry)`` open-entry probe — returns the open
       row (or ``None``).
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    async def _fake_execute(stmt, params=None):
        result = MagicMock()
        rendered = str(stmt).lower()
        try:
            text_repr = (stmt.text or "").lower()
        except AttributeError:
            text_repr = ""

        if "clock_in_policy" in text_repr:
            result.scalar_one_or_none.return_value = (
                clock_in_policy if clock_in_policy is not None else {}
            )
            return result
        if "staff_members" in rendered and "employee_id" in rendered:
            result.scalar_one_or_none.return_value = staff
            return result
        if (
            "time_clock_entries" in rendered
            and "clock_out_at is null" in rendered
        ):
            result.scalar_one_or_none.return_value = open_entry
            return result
        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db


@pytest.fixture
def captured_audit():
    """Capture every ``write_audit_log`` call the service makes."""
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.service.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


# ---------------------------------------------------------------------------
# G12 — the headline test from task B9
# ---------------------------------------------------------------------------


class TestG12KioskLookupRateLimit:
    """Validates: Requirements R3.3 (G12) — kiosk lookup rate limit."""

    @pytest.mark.asyncio
    async def test_eleventh_lookup_returns_429_with_retry_after(
        self, captured_audit,
    ):
        """The 11th lookup for the same ``(org_id, employee_id)`` in
        60s raises :class:`KioskLookupRateLimitedError` with
        ``retry_after_seconds == 60``. This is the exception the kiosk
        router translates into HTTP 429 + ``Retry-After: 60`` header
        and body ``{"detail": "kiosk_lookup_rate_limited"}``.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, employee_id="EMP-007")
        db = _make_db(staff=staff)
        redis = _FakeRedis()

        # First 10 calls all succeed.
        for i in range(10):
            result = await lookup_for_kiosk(
                db,
                org_id=org_id,
                employee_id="EMP-007",
                redis=redis,
            )
            assert result["staff_id"] == staff.id, (
                f"call #{i + 1} should have returned staff identity"
            )

        # 11th call trips the limit.
        with pytest.raises(KioskLookupRateLimitedError) as exc:
            await lookup_for_kiosk(
                db,
                org_id=org_id,
                employee_id="EMP-007",
                redis=redis,
            )
        assert exc.value.retry_after_seconds == 60

    @pytest.mark.asyncio
    async def test_redis_key_uses_hashed_employee_id(self, captured_audit):
        """The Redis counter key encodes the SHA-256 hash (truncated to
        16 hex chars) of the employee_id — never the raw code (G12).
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, employee_id="EMP-007")
        db = _make_db(staff=staff)
        redis = _FakeRedis()

        await lookup_for_kiosk(
            db,
            org_id=org_id,
            employee_id="EMP-007",
            redis=redis,
        )

        expected_hash = _hash_employee_id("EMP-007")
        expected_key = f"kiosk_lookup:{org_id}:{expected_hash}"
        keys = redis.keys_view()
        assert expected_key in keys, (
            f"Redis key should be hashed; got {keys}"
        )
        # And the raw employee_id never appears anywhere in the Redis
        # state — neither as a key nor inside one.
        for key in keys:
            assert "EMP-007" not in key, (
                f"raw employee_id leaked into Redis key: {key}"
            )
        # TTL set to the 60-second window.
        assert redis.expires.get(expected_key) == 60

    @pytest.mark.asyncio
    async def test_audit_row_written_with_hashed_identifier(
        self, captured_audit,
    ):
        """When the limit trips, an audit row
        ``kiosk.lookup_rate_limited`` is written with
        ``employee_id_hash`` in ``after_value`` — the raw code never
        appears in the audit trail.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, employee_id="EMP-007")
        db = _make_db(staff=staff)
        redis = _FakeRedis()

        # Burn through the 10 free hits.
        for _ in range(10):
            await lookup_for_kiosk(
                db, org_id=org_id, employee_id="EMP-007", redis=redis,
            )

        with pytest.raises(KioskLookupRateLimitedError):
            await lookup_for_kiosk(
                db, org_id=org_id, employee_id="EMP-007", redis=redis,
            )

        rate_audits = [
            a for a in captured_audit
            if a.get("action") == "kiosk.lookup_rate_limited"
        ]
        assert len(rate_audits) == 1, (
            f"expected one rate-limit audit row, got {captured_audit}"
        )

        after = rate_audits[0]["after_value"]
        assert after["employee_id_hash"] == _hash_employee_id("EMP-007")
        assert after["retry_after"] == 60
        assert after["org_id"] == str(org_id)
        # The raw code never appears in the audit payload.
        assert "EMP-007" not in str(after), (
            "raw employee_id leaked into audit row"
        )
        # And no audit row carries the raw employee_id anywhere.
        for audit_call in captured_audit:
            assert "EMP-007" not in str(audit_call.get("after_value") or {})

    @pytest.mark.asyncio
    async def test_distinct_employee_ids_have_independent_budgets(
        self, captured_audit,
    ):
        """The G12 budget is keyed off ``(org_id, employee_id)`` — two
        different employee_ids in the same org each get their own
        10/min budget.
        """
        org_id = uuid.uuid4()
        staff_a = _make_staff(org_id=org_id, employee_id="EMP-001")
        staff_b = _make_staff(org_id=org_id, employee_id="EMP-002")
        redis = _FakeRedis()

        # Burn EMP-001 to its 10-call budget.
        db_a = _make_db(staff=staff_a)
        for _ in range(10):
            await lookup_for_kiosk(
                db_a, org_id=org_id, employee_id="EMP-001", redis=redis,
            )
        # EMP-002 should still get a fresh 10-call budget.
        db_b = _make_db(staff=staff_b)
        for _ in range(10):
            await lookup_for_kiosk(
                db_b, org_id=org_id, employee_id="EMP-002", redis=redis,
            )

        # 11th call on EMP-002 trips its own limit.
        with pytest.raises(KioskLookupRateLimitedError):
            await lookup_for_kiosk(
                db_b, org_id=org_id, employee_id="EMP-002", redis=redis,
            )

        # Both hashed keys are present in Redis.
        h1 = _hash_employee_id("EMP-001")
        h2 = _hash_employee_id("EMP-002")
        assert f"kiosk_lookup:{org_id}:{h1}" in redis.keys_view()
        assert f"kiosk_lookup:{org_id}:{h2}" in redis.keys_view()

    @pytest.mark.asyncio
    async def test_distinct_orgs_have_independent_budgets(
        self, captured_audit,
    ):
        """The same employee_id in two different orgs each gets its own
        10/min budget — the key namespaces by ``org_id``.
        """
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()
        staff_a = _make_staff(org_id=org_a, employee_id="EMP-001")
        staff_b = _make_staff(org_id=org_b, employee_id="EMP-001")
        redis = _FakeRedis()

        # Burn org_a/EMP-001 to its budget.
        db_a = _make_db(staff=staff_a)
        for _ in range(10):
            await lookup_for_kiosk(
                db_a, org_id=org_a, employee_id="EMP-001", redis=redis,
            )

        # org_b/EMP-001 should still be free.
        db_b = _make_db(staff=staff_b)
        result = await lookup_for_kiosk(
            db_b, org_id=org_b, employee_id="EMP-001", redis=redis,
        )
        assert result["staff_id"] == staff_b.id


# ---------------------------------------------------------------------------
# Two-layer interaction (P3-N9) — body shape distinct from the dependency
# ---------------------------------------------------------------------------


class TestTwoLayerRateLimitBodyDistinctness:
    """The two layers have DISTINCT response bodies so ops can tell
    which one tripped from the kiosk app's error handling. The
    dependency-level :func:`_check_kiosk_rate_limit` returns
    ``{"detail": "Rate limit exceeded"}`` while the inline G12 check
    returns ``{"detail": "kiosk_lookup_rate_limited"}``.

    Validates: P3-N9 — two-layer rate-limit interaction.
    """

    @pytest.mark.asyncio
    async def test_dependency_layer_uses_generic_body(self):
        """The 30/min/kiosk-user dependency raises HTTP 429 with body
        ``{"detail": "Rate limit exceeded"}`` — distinct from the G12
        body so the kiosk app's error handler can distinguish them.
        """
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        from app.modules.kiosk.router import (
            _KIOSK_RATE_LIMIT,
            _check_kiosk_rate_limit,
        )

        # Build a request whose state.user_id is set so the dependency
        # actually runs (no-ops when missing).
        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())

        # Build a Redis double whose pipeline reports the user has
        # already burned through the global 30/min budget.
        import time as _time

        redis = AsyncMock()
        pipe1 = AsyncMock()
        pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
        pipe1.zcard = MagicMock(return_value=pipe1)
        pipe1.execute = AsyncMock(return_value=[0, _KIOSK_RATE_LIMIT])
        redis.pipeline = MagicMock(return_value=pipe1)
        redis.zrange = AsyncMock(
            return_value=[(b"oldest", _time.time() - 50)],
        )

        with pytest.raises(HTTPException) as exc:
            await _check_kiosk_rate_limit(request, redis=redis)
        assert exc.value.status_code == 429
        # Distinct body — NOT the G12 ``kiosk_lookup_rate_limited``.
        assert exc.value.detail == "Rate limit exceeded"

    @pytest.mark.asyncio
    async def test_g12_layer_uses_distinct_kiosk_lookup_body(
        self, captured_audit,
    ):
        """The inline G12 check raises
        :class:`KioskLookupRateLimitedError` which the kiosk router
        translates to body ``{"detail": "kiosk_lookup_rate_limited"}``.

        Here we verify the exception path; the router's response body
        translation is exercised via end-to-end tests elsewhere.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, employee_id="EMP-001")
        db = _make_db(staff=staff)
        redis = _FakeRedis()

        # Burn through the 10 free hits.
        for _ in range(10):
            await lookup_for_kiosk(
                db, org_id=org_id, employee_id="EMP-001", redis=redis,
            )

        with pytest.raises(KioskLookupRateLimitedError) as exc:
            await lookup_for_kiosk(
                db, org_id=org_id, employee_id="EMP-001", redis=redis,
            )
        # The error message itself encodes the distinct body the
        # router emits — see :func:`_translate_clock_service_error`.
        assert "kiosk_lookup_rate_limited" in str(exc.value)
        assert exc.value.retry_after_seconds == 60

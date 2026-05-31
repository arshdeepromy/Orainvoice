"""Unit tests for ``app/modules/staff/public_router.py`` (Phase 1 task C7).

Covers ``GET /api/v2/public/staff-roster/:token`` from
`.kiro/specs/staff-management-p1`:

The public viewer endpoint distinguishes three failure modes and one
success path:

1. **Token doesn't exist** → HTTP 404
   ``{"detail": "token_not_found"}``.
2. **Token expired AND staff deactivated** → HTTP 410
   ``{"detail": "token_expired_staff_deactivated"}`` — the
   deactivation/termination flow (C11) revokes tokens by setting
   ``expires_at = now()``, so a deactivated staff is the signal we
   use to distinguish this case from a natural TTL expiry.
3. **Token expired, staff still active** → HTTP 410
   ``{"detail": "token_expired"}`` — natural 30-day TTL.
4. **Token valid + staff active** → HTTP 200 with
   ``{ staff_name, week_start, week_end, entries: [...] }``.

The DB session is stubbed with an ``AsyncMock`` so these tests don't
hit PostgreSQL — the focus is the endpoint's branching logic. The
per-IP rate-limit (G5) lives in ``app/middleware/rate_limit.py`` and
is exercised separately (just the constants are asserted here so a
careless rename trips a test).

**Validates: Requirements R9.4, R9.8, G5 — Staff Phase 1 task C7**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember, StaffRosterViewToken
from app.modules.staff.public_router import view_staff_roster


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_token(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    expires_at: datetime,
    token: str = "test-token-value",
) -> StaffRosterViewToken:
    """Build an in-memory ``StaffRosterViewToken`` instance."""
    return StaffRosterViewToken(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        token=token,
        week_start=week_start,
        expires_at=expires_at,
    )


def _make_staff(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    is_active: bool = True,
    first_name: str = "Jane",
    last_name: str = "Doe",
    name: str = "Jane Doe",
) -> StaffMember:
    """Build an in-memory ``StaffMember`` instance for the viewer."""
    return StaffMember(
        id=staff_id,
        org_id=org_id,
        name=name,
        first_name=first_name,
        last_name=last_name,
        role_type="employee",
        is_active=is_active,
        availability_schedule={},
        skills=[],
    )


def _make_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    title: str | None = None,
    notes: str | None = None,
    entry_type: str = "other",
) -> ScheduleEntry:
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        title=title,
        start_time=start_time,
        end_time=end_time,
        entry_type=entry_type,
        status="scheduled",
        notes=notes,
    )


def _make_db(
    *,
    token_row: StaffRosterViewToken | None,
    staff: StaffMember | None = None,
    entries: list[ScheduleEntry] | None = None,
) -> AsyncMock:
    """Build an AsyncMock DB.

    The ``view_staff_roster`` endpoint issues up to three SELECTs in
    order: token lookup, staff lookup, schedule_entries lookup.
    Returning the right mock for each call by tracking call count is
    fragile — instead we inspect the SQL statement to decide which
    payload to return.
    """
    entries = entries or []
    db = AsyncMock()
    call_log: list[str] = []

    async def fake_execute(stmt):
        sql = str(stmt).lower()
        call_log.append(sql)
        result = MagicMock()
        if "staff_roster_view_tokens" in sql:
            result.scalar_one_or_none.return_value = token_row
        elif "staff_members" in sql:
            result.scalar_one_or_none.return_value = staff
        elif "schedule_entries" in sql:
            scalars = MagicMock()
            scalars.all.return_value = entries
            result.scalars.return_value = scalars
        else:  # pragma: no cover - safety net
            raise AssertionError(f"Unexpected SQL: {sql}")
        return result

    db.execute = fake_execute
    db._calls = call_log  # type: ignore[attr-defined]
    return db


# ---------------------------------------------------------------------------
# 1. Token not found → 404 token_not_found
# ---------------------------------------------------------------------------


class TestTokenNotFound:
    """Token lookup miss → HTTP 404 ``token_not_found``."""

    @pytest.mark.asyncio
    async def test_unknown_token_raises_404(self):
        db = _make_db(token_row=None)

        with pytest.raises(HTTPException) as excinfo:
            await view_staff_roster(token="does-not-exist", db=db)

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "token_not_found"


# ---------------------------------------------------------------------------
# 2. Token expired + staff deactivated → 410 token_expired_staff_deactivated
# ---------------------------------------------------------------------------


class TestExpiredTokenDeactivatedStaff:
    """Per R9.7/G4: deactivation flow sets ``expires_at = now()`` on
    every active token. The public viewer must distinguish that case
    from natural TTL expiry by checking ``staff.is_active``.
    """

    @pytest.mark.asyncio
    async def test_expired_with_deactivated_staff_returns_410_deactivated(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        # Token revoked 5 minutes ago by the deactivation flow.
        token_row = _make_token(
            org_id=org_id, staff_id=staff_id, week_start=week_start,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            token="revoked-tok",
        )
        # Staff is deactivated — the signal that this is C11 revocation,
        # not natural TTL expiry.
        staff = _make_staff(
            org_id=org_id, staff_id=staff_id, is_active=False,
        )
        db = _make_db(token_row=token_row, staff=staff)

        with pytest.raises(HTTPException) as excinfo:
            await view_staff_roster(token="revoked-tok", db=db)

        assert excinfo.value.status_code == 410
        assert excinfo.value.detail == "token_expired_staff_deactivated"


# ---------------------------------------------------------------------------
# 3. Token expired naturally + staff still active → 410 token_expired
# ---------------------------------------------------------------------------


class TestExpiredTokenNaturalTTL:
    """Token aged past 30-day TTL but staff is still on the books →
    plain ``token_expired`` (no ``_staff_deactivated`` suffix).
    """

    @pytest.mark.asyncio
    async def test_expired_with_active_staff_returns_410_token_expired(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        # Token expired 1 day ago — natural 30-day TTL elapsed.
        token_row = _make_token(
            org_id=org_id, staff_id=staff_id, week_start=week_start,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            token="natural-ttl-tok",
        )
        # Staff still active — the deactivation flow didn't touch it.
        staff = _make_staff(
            org_id=org_id, staff_id=staff_id, is_active=True,
        )
        db = _make_db(token_row=token_row, staff=staff)

        with pytest.raises(HTTPException) as excinfo:
            await view_staff_roster(token="natural-ttl-tok", db=db)

        assert excinfo.value.status_code == 410
        assert excinfo.value.detail == "token_expired"


# ---------------------------------------------------------------------------
# 4. Valid token → 200 with schedule data
# ---------------------------------------------------------------------------


class TestValidTokenReturnsRoster:
    """Happy path: valid token → 200 with ``staff_name``,
    ``week_start``, ``week_end``, and an ``entries`` list shaped per
    the spec.
    """

    @pytest.mark.asyncio
    async def test_valid_token_returns_roster_payload(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)  # Monday
        token_row = _make_token(
            org_id=org_id, staff_id=staff_id, week_start=week_start,
            expires_at=datetime.now(timezone.utc) + timedelta(days=25),
            token="valid-tok",
        )
        staff = _make_staff(
            org_id=org_id, staff_id=staff_id, is_active=True,
            first_name="Hēmi", last_name="Smith", name="Hēmi Smith",
        )
        # Two entries inside the week window.
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc),
                title="Workshop",
                notes="Wear safety boots",
                entry_type="job",
            ),
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                start_time=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc),
                title=None,
                notes=None,
                entry_type="other",
            ),
        ]
        db = _make_db(token_row=token_row, staff=staff, entries=entries)

        result = await view_staff_roster(token="valid-tok", db=db)

        # Display name preserves the macron — never transliterated (G7).
        assert result["staff_name"] == "Hēmi Smith"
        assert result["week_start"] == "2026-06-01"
        # week_end is week_start + 7 days.
        assert result["week_end"] == "2026-06-08"
        assert len(result["entries"]) == 2

        first = result["entries"][0]
        assert first["start_time"] == "2026-06-01T09:00:00+00:00"
        assert first["end_time"] == "2026-06-01T17:00:00+00:00"
        assert first["title"] == "Workshop"
        assert first["notes"] == "Wear safety boots"
        assert first["entry_type"] == "job"

        second = result["entries"][1]
        assert second["title"] is None
        assert second["notes"] is None

    @pytest.mark.asyncio
    async def test_valid_token_with_no_entries_returns_empty_list(self):
        """A staff with no shifts in the week still gets a valid 200
        response — the ``entries`` array is just empty. The "no shifts
        in week" refusal is a SEND-side concern (R8.5/R9.2), not a
        VIEW-side concern.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        token_row = _make_token(
            org_id=org_id, staff_id=staff_id, week_start=week_start,
            expires_at=datetime.now(timezone.utc) + timedelta(days=25),
            token="valid-empty-tok",
        )
        staff = _make_staff(org_id=org_id, staff_id=staff_id, is_active=True)
        db = _make_db(token_row=token_row, staff=staff, entries=[])

        result = await view_staff_roster(token="valid-empty-tok", db=db)

        assert result["entries"] == []
        assert result["staff_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_valid_token_falls_back_to_name_when_first_last_blank(self):
        """If ``first_name`` and ``last_name`` are both blank, fall
        back to the legacy ``name`` field. Defensive against legacy
        rows pre-dating the first/last split.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        token_row = _make_token(
            org_id=org_id, staff_id=staff_id, week_start=week_start,
            expires_at=datetime.now(timezone.utc) + timedelta(days=25),
        )
        staff = _make_staff(
            org_id=org_id, staff_id=staff_id, is_active=True,
            first_name="", last_name="", name="Legacy Staff Name",
        )
        db = _make_db(token_row=token_row, staff=staff, entries=[])

        result = await view_staff_roster(token="test-token-value", db=db)

        assert result["staff_name"] == "Legacy Staff Name"


# ---------------------------------------------------------------------------
# 5. G5 — rate-limit middleware constants are wired up
# ---------------------------------------------------------------------------


class TestRateLimitConstants:
    """The per-IP rate limit (30 req/min) for the public roster
    viewer is configured via two module-level constants in
    ``app/middleware/rate_limit.py``. Import them and verify the
    values + path prefix exactly — careless renames would break the
    middleware silently otherwise.
    """

    def test_rate_limit_constants_are_set_correctly(self):
        from app.middleware import rate_limit as rl

        assert rl._PUBLIC_STAFF_ROSTER_PATH_PREFIX == "/api/v2/public/staff-roster/"
        assert rl._PUBLIC_STAFF_ROSTER_RATE_LIMIT == 30

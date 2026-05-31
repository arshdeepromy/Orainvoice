"""Unit tests for ``app/modules/staff/roster_tokens.py`` (Phase 1 task C5).

Covers ``get_or_create_viewer_token`` from `.kiro/specs/staff-management-p1`:

1. First call for a new (staff, week) creates a row and returns the
   token (string of length >= 40 — ``secrets.token_urlsafe(32)`` yields
   43 URL-safe characters).
2. Second call with the same (staff, week) is **idempotent**: returns
   the same token string and does NOT add a second row (the unique
   constraint on ``(staff_id, week_start)`` in migration 0203 would
   otherwise raise ``IntegrityError``).
3. When the existing row is expired (natural TTL or deliberately
   revoked by C11), the helper re-mints the token in-place: the row
   id stays the same, the token string changes, ``expires_at`` is
   bumped 30 days into the future.
4. ``expires_at`` is approximately 30 days from ``now()`` per R9.4 —
   tolerance is 1 minute to absorb clock jitter between the helper
   and the assertion.
5. Different staff or different weeks each get their own row + token.

The DB session is stubbed with ``AsyncMock`` so these tests don't hit
PostgreSQL — the focus is the helper's branching logic. The cascade
deletion on hard-delete (the second half of the verify step) is
enforced by the ``ON DELETE CASCADE`` constraint in migration 0203
itself; verifying that requires a live database and is covered by the
E2E script `scripts/test_staff_employment_record_e2e.py` (task F1).

**Validates: Requirements R9.4, G8 — Staff Phase 1 task C5**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.staff.models import StaffRosterViewToken
from app.modules.staff.roster_tokens import get_or_create_viewer_token


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_db(*, existing: StaffRosterViewToken | None = None) -> AsyncMock:
    """Build an AsyncMock DB whose ``execute()`` returns ``existing``.

    The helper only issues one SELECT per invocation (the
    ``(staff_id, week_start)`` lookup); subsequent ``flush`` /
    ``refresh`` calls are awaitable no-ops on the mock.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    async def fake_execute(stmt):  # noqa: ARG001 - we don't introspect the SQL
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        return result

    db.execute = fake_execute
    db._added: list[object] = []  # type: ignore[attr-defined]

    def fake_add(obj):
        db._added.append(obj)  # type: ignore[attr-defined]

    db.add.side_effect = fake_add
    return db


def _make_existing_token(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    expires_at: datetime,
    token: str = "existing-token-value",
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


def _added_tokens(db: AsyncMock) -> list[StaffRosterViewToken]:
    return [
        obj for obj in db._added  # type: ignore[attr-defined]
        if isinstance(obj, StaffRosterViewToken)
    ]


# ---------------------------------------------------------------------------
# 1+2. Idempotent on (staff, week) — same call twice → same token, one row
# ---------------------------------------------------------------------------


class TestIdempotentOnStaffWeek:

    @pytest.mark.asyncio
    async def test_first_call_creates_row(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        db = _make_db(existing=None)

        result = await get_or_create_viewer_token(
            db, org_id=org_id, staff_id=staff_id, week_start=week_start,
        )

        # A new row was added to the session.
        rows = _added_tokens(db)
        assert len(rows) == 1
        added = rows[0]
        assert added is result
        assert added.staff_id == staff_id
        assert added.org_id == org_id
        assert added.week_start == week_start
        # secrets.token_urlsafe(32) → 43-char URL-safe base64 string.
        # Spec verify step says "at least 40 chars" — keep some slack.
        assert isinstance(result.token, str)
        assert len(result.token) >= 40
        # flush() + refresh() were awaited so created_at would be hydrated.
        assert db.flush.await_count >= 1
        assert db.refresh.await_count >= 1

    @pytest.mark.asyncio
    async def test_second_call_reuses_existing_token(self):
        """Same (staff, week) twice → identical token returned, no new row."""
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        # Existing row, valid for another 25 days.
        existing = _make_existing_token(
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start,
            expires_at=datetime.now(timezone.utc) + timedelta(days=25),
            token="reused-token-abc",
        )
        db = _make_db(existing=existing)

        result = await get_or_create_viewer_token(
            db, org_id=org_id, staff_id=staff_id, week_start=week_start,
        )

        # Same row, same token string.
        assert result is existing
        assert result.token == "reused-token-abc"
        # No new row was added — the unique (staff_id, week_start)
        # constraint would forbid a second INSERT.
        assert _added_tokens(db) == []
        # And no flush/refresh was needed for the reuse path — the row
        # is already attached and unchanged.
        assert db.flush.await_count == 0


# ---------------------------------------------------------------------------
# 3. Expired row → token re-minted in place
# ---------------------------------------------------------------------------


class TestExpiredTokenIsReminted:

    @pytest.mark.asyncio
    async def test_expired_row_is_updated_not_replaced(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        # Existing row but expired 1 day ago — could be natural TTL OR
        # the C11 deactivation revocation (R9.7/G4).
        existing = _make_existing_token(
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            token="stale-token-xyz",
        )
        original_id = existing.id
        db = _make_db(existing=existing)

        result = await get_or_create_viewer_token(
            db, org_id=org_id, staff_id=staff_id, week_start=week_start,
        )

        # Same row id (the unique constraint forces in-place update),
        # but a fresh token string.
        assert result.id == original_id
        assert result is existing  # mutated in place
        assert result.token != "stale-token-xyz"
        assert len(result.token) >= 40
        # expires_at bumped to ~30 days in the future.
        delta = result.expires_at - datetime.now(timezone.utc)
        assert delta > timedelta(days=29, hours=23, minutes=58)
        assert delta < timedelta(days=30, hours=0, minutes=2)
        # No new row added.
        assert _added_tokens(db) == []
        # flush + refresh happened to persist the in-place update.
        assert db.flush.await_count == 1
        assert db.refresh.await_count == 1


# ---------------------------------------------------------------------------
# 4. expires_at is approximately 30 days from now (R9.4)
# ---------------------------------------------------------------------------


class TestExpiryWindow:

    @pytest.mark.asyncio
    async def test_new_token_expires_in_about_30_days(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        week_start = date(2026, 6, 1)
        db = _make_db(existing=None)

        before = datetime.now(timezone.utc)
        result = await get_or_create_viewer_token(
            db, org_id=org_id, staff_id=staff_id, week_start=week_start,
        )
        after = datetime.now(timezone.utc)

        # expires_at must fall in [before + 30d, after + 30d].
        assert result.expires_at >= before + timedelta(days=30) - timedelta(seconds=1)
        assert result.expires_at <= after + timedelta(days=30) + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# 5. Different (staff, week) tuples each get their own token
# ---------------------------------------------------------------------------


class TestDistinctTuplesGetDistinctTokens:

    @pytest.mark.asyncio
    async def test_distinct_staff_get_distinct_tokens(self):
        """Two staff in the same week each get their own row + token.

        With the existing-row lookup returning ``None`` for both calls
        (different staff_ids → no row yet), each call mints a fresh
        random token. The probability of collision is negligible
        (~1 in 2^256).
        """
        org_id = uuid.uuid4()
        week_start = date(2026, 6, 1)

        db1 = _make_db(existing=None)
        db2 = _make_db(existing=None)
        first = await get_or_create_viewer_token(
            db1, org_id=org_id, staff_id=uuid.uuid4(), week_start=week_start,
        )
        second = await get_or_create_viewer_token(
            db2, org_id=org_id, staff_id=uuid.uuid4(), week_start=week_start,
        )

        assert first.token != second.token

    @pytest.mark.asyncio
    async def test_distinct_weeks_get_distinct_tokens(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()

        db1 = _make_db(existing=None)
        db2 = _make_db(existing=None)
        first = await get_or_create_viewer_token(
            db1, org_id=org_id, staff_id=staff_id, week_start=date(2026, 6, 1),
        )
        second = await get_or_create_viewer_token(
            db2, org_id=org_id, staff_id=staff_id, week_start=date(2026, 6, 8),
        )

        assert first.token != second.token

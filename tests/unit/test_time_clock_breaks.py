"""Unit tests for ``app.modules.time_clock.breaks`` (task B4).

Covers task B4 from `.kiro/specs/staff-management-p3`:

1. ``start_break`` / ``end_break`` round-trip with
   ``break_type='rest_paid'`` — minutes computed, parent
   ``break_minutes`` NOT bumped (rests are paid).
2. ``start_break`` / ``end_break`` round-trip with
   ``break_type='meal_unpaid'`` — minutes computed, parent
   ``break_minutes`` bumped by that count (R7.3 — meal-unpaid
   deducts from worked time on clock-out close).
3. ``start_break`` validates ``break_type`` against the CHECK enum.
4. ``start_break`` refuses when the parent entry doesn't exist or is
   already closed.
5. ``end_break`` refuses when the break is already ended.
6. ``suggest_break_windows`` for 4h, 6h, 10h, and 12h shifts produces
   the documented R7.2 suggestions.
7. ERA s69ZD validation (R7.4):
   - ``< 4h`` shift with no breaks → compliant.
   - ``6h`` shift with only a rest → non-compliant; missing meal.
   - ``6h`` shift with rest + meal → compliant.
   - ``10h`` shift requires 2 rests + 1 meal.
   - In-progress break (no ``minutes``) counts toward the requirement.
   - Short break (e.g. 3-min rest) doesn't discharge the 10-min legal
     minimum.

The DB session is mocked with ``AsyncMock`` following the same pattern
used by ``tests/unit/test_time_clock_service.py``.

**Validates: Requirements R7 — Staff Management Phase 3 task B4**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import the auth + admin model modules so SQLAlchemy resolves the
# string-name relationship targets (``Organisation``, ``User``) when
# instantiating ``TimeClockEntry`` / ``BreakRecord`` ORM objects in the
# tests below. Mirrors the block at the top of
# ``tests/unit/test_time_clock_service.py``.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401

from app.modules.time_clock.breaks import (
    BreakAlreadyEndedError,
    BreakNotFoundError,
    InvalidBreakTypeError,
    end_break,
    start_break,
    suggest_break_windows,
    validate_era_s69zd_breaks,
)
from app.modules.time_clock.models import BreakRecord, TimeClockEntry
from app.modules.time_clock.service import (
    InvalidActionError,
    TimeClockEntryNotFoundError,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID | None = None,
    closed: bool = False,
    break_minutes: int = 0,
    clock_in_at: datetime | None = None,
    clock_out_at: datetime | None = None,
) -> TimeClockEntry:
    """Build a minimal :class:`TimeClockEntry` for break tests."""
    in_at = clock_in_at or datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    out_at = clock_out_at
    if closed and out_at is None:
        out_at = in_at + timedelta(hours=8)
    return TimeClockEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id or uuid.uuid4(),
        clock_in_at=in_at,
        clock_out_at=out_at,
        source="kiosk",
        clock_in_photo_url="key",
        break_minutes=break_minutes,
        flags={},
    )


def _make_break(
    *,
    org_id: uuid.UUID,
    parent_id: uuid.UUID,
    break_type: str = "rest_paid",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    minutes: int | None = None,
) -> BreakRecord:
    return BreakRecord(
        id=uuid.uuid4(),
        org_id=org_id,
        time_clock_entry_id=parent_id,
        break_type=break_type,
        start_at=start_at or datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        end_at=end_at,
        minutes=minutes,
    )


def _make_db(
    *,
    entries: dict[uuid.UUID, TimeClockEntry] | None = None,
    breaks: dict[uuid.UUID, BreakRecord] | None = None,
) -> AsyncMock:
    """Build an :class:`AsyncMock` DB session that resolves
    ``db.get(TimeClockEntry, id)`` / ``db.get(BreakRecord, id)`` from
    the supplied dicts and tracks ``db.add`` / ``db.flush`` /
    ``db.refresh`` calls.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db._added: list = []
    db.add.side_effect = lambda obj: db._added.append(obj)

    entries = entries or {}
    breaks = breaks or {}

    async def _fake_get(model, key):
        if model is TimeClockEntry:
            return entries.get(key)
        if model is BreakRecord:
            return breaks.get(key)
        return None

    db.get = AsyncMock(side_effect=_fake_get)
    return db


@pytest.fixture
def captured_audit():
    """Capture ``write_audit_log`` calls for assertion."""
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.breaks.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


# ---------------------------------------------------------------------------
# start_break + end_break round-trip
# ---------------------------------------------------------------------------


class TestStartEndBreakRoundTrip:

    @pytest.mark.asyncio
    async def test_rest_paid_round_trip_does_not_bump_parent_break_minutes(
        self, captured_audit
    ):
        """Rest breaks are paid time — they don't deduct from
        worked_minutes (R7.3), so the parent's ``break_minutes``
        aggregator stays at 0.
        """
        org_id = uuid.uuid4()
        entry = _make_entry(org_id=org_id)
        db = _make_db(entries={entry.id: entry})

        # Start the break at a known time.
        start_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        break_record = await start_break(
            db,
            org_id=org_id,
            time_clock_entry_id=entry.id,
            break_type="rest_paid",
            start_at=start_at,
        )

        assert break_record.break_type == "rest_paid"
        assert break_record.start_at == start_at
        assert break_record.end_at is None
        assert break_record.minutes is None
        # Audit row written.
        actions = [a.get("action") for a in captured_audit]
        assert "break.started" in actions

        # Manually register the new break in the db mock so end_break
        # can resolve it via db.get(BreakRecord, ...).
        db_with_break = _make_db(
            entries={entry.id: entry},
            breaks={break_record.id: break_record},
        )

        end_at = start_at + timedelta(minutes=10)
        ended = await end_break(
            db_with_break,
            org_id=org_id,
            break_record_id=break_record.id,
            end_at=end_at,
        )

        assert ended.end_at == end_at
        assert ended.minutes == 10
        # Parent break_minutes NOT bumped — rest breaks are paid.
        assert entry.break_minutes == 0
        # Audit ended row.
        actions2 = [a.get("action") for a in captured_audit]
        assert "break.ended" in actions2

    @pytest.mark.asyncio
    async def test_meal_unpaid_round_trip_bumps_parent_break_minutes(
        self, captured_audit
    ):
        """Meal-unpaid breaks deduct from worked_minutes per R7.3 —
        the parent entry's ``break_minutes`` aggregator must be
        bumped by the meal duration on break-end.
        """
        org_id = uuid.uuid4()
        entry = _make_entry(org_id=org_id, break_minutes=0)
        db = _make_db(entries={entry.id: entry})

        start_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        break_record = await start_break(
            db,
            org_id=org_id,
            time_clock_entry_id=entry.id,
            break_type="meal_unpaid",
            start_at=start_at,
        )

        db_with_break = _make_db(
            entries={entry.id: entry},
            breaks={break_record.id: break_record},
        )

        end_at = start_at + timedelta(minutes=30)
        ended = await end_break(
            db_with_break,
            org_id=org_id,
            break_record_id=break_record.id,
            end_at=end_at,
        )

        assert ended.minutes == 30
        # Parent now reflects the meal break for the worked-minutes
        # deduction at clock-out time.
        assert entry.break_minutes == 30

    @pytest.mark.asyncio
    async def test_multiple_meal_breaks_accumulate_on_parent(
        self, captured_audit
    ):
        """Two meal_unpaid breaks → parent break_minutes is the sum."""
        org_id = uuid.uuid4()
        entry = _make_entry(org_id=org_id, break_minutes=0)

        # First meal break.
        start_a = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        end_a = start_a + timedelta(minutes=30)
        db_a = _make_db(entries={entry.id: entry})
        rec_a = await start_break(
            db_a,
            org_id=org_id,
            time_clock_entry_id=entry.id,
            break_type="meal_unpaid",
            start_at=start_a,
        )
        db_a_end = _make_db(
            entries={entry.id: entry}, breaks={rec_a.id: rec_a},
        )
        await end_break(
            db_a_end,
            org_id=org_id,
            break_record_id=rec_a.id,
            end_at=end_a,
        )
        assert entry.break_minutes == 30

        # Second meal break.
        start_b = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
        end_b = start_b + timedelta(minutes=20)
        db_b = _make_db(entries={entry.id: entry})
        rec_b = await start_break(
            db_b,
            org_id=org_id,
            time_clock_entry_id=entry.id,
            break_type="meal_unpaid",
            start_at=start_b,
        )
        db_b_end = _make_db(
            entries={entry.id: entry}, breaks={rec_b.id: rec_b},
        )
        await end_break(
            db_b_end,
            org_id=org_id,
            break_record_id=rec_b.id,
            end_at=end_b,
        )
        assert entry.break_minutes == 50

    @pytest.mark.asyncio
    async def test_end_break_on_closed_parent_recomputes_worked_minutes(
        self, captured_audit
    ):
        """Admin back-dates a meal break onto a closed entry — the
        parent's ``worked_minutes`` is re-computed so the deduction
        flows through.
        """
        org_id = uuid.uuid4()
        in_at = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        out_at = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)
        entry = _make_entry(
            org_id=org_id,
            clock_in_at=in_at,
            clock_out_at=out_at,
            break_minutes=0,
        )
        # Pre-set a worked_minutes consistent with no breaks.
        entry.worked_minutes = 480
        # An open break already started before clock-out; we close it
        # after the entry has been closed (back-dated edit).
        existing_break = _make_break(
            org_id=org_id,
            parent_id=entry.id,
            break_type="meal_unpaid",
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        db = _make_db(
            entries={entry.id: entry},
            breaks={existing_break.id: existing_break},
        )
        end_at = datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc)
        await end_break(
            db,
            org_id=org_id,
            break_record_id=existing_break.id,
            end_at=end_at,
        )
        assert entry.break_minutes == 30
        # 480 elapsed - 30 break = 450.
        assert entry.worked_minutes == 450


# ---------------------------------------------------------------------------
# start_break validation
# ---------------------------------------------------------------------------


class TestStartBreakValidation:

    @pytest.mark.asyncio
    async def test_invalid_break_type_raises(self, captured_audit):
        org_id = uuid.uuid4()
        entry = _make_entry(org_id=org_id)
        db = _make_db(entries={entry.id: entry})

        with pytest.raises(InvalidBreakTypeError):
            await start_break(
                db,
                org_id=org_id,
                time_clock_entry_id=entry.id,
                break_type="lunch",  # not in CHECK enum
            )

    @pytest.mark.asyncio
    async def test_unknown_parent_entry_raises(self, captured_audit):
        org_id = uuid.uuid4()
        db = _make_db(entries={})

        with pytest.raises(TimeClockEntryNotFoundError):
            await start_break(
                db,
                org_id=org_id,
                time_clock_entry_id=uuid.uuid4(),
                break_type="rest_paid",
            )

    @pytest.mark.asyncio
    async def test_parent_entry_in_other_org_raises(self, captured_audit):
        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()
        entry = _make_entry(org_id=other_org_id)
        db = _make_db(entries={entry.id: entry})

        with pytest.raises(TimeClockEntryNotFoundError):
            await start_break(
                db,
                org_id=org_id,
                time_clock_entry_id=entry.id,
                break_type="rest_paid",
            )

    @pytest.mark.asyncio
    async def test_closed_parent_entry_raises(self, captured_audit):
        org_id = uuid.uuid4()
        entry = _make_entry(org_id=org_id, closed=True)
        db = _make_db(entries={entry.id: entry})

        with pytest.raises(InvalidActionError, match="entry_already_closed"):
            await start_break(
                db,
                org_id=org_id,
                time_clock_entry_id=entry.id,
                break_type="rest_paid",
            )


# ---------------------------------------------------------------------------
# end_break validation
# ---------------------------------------------------------------------------


class TestEndBreakValidation:

    @pytest.mark.asyncio
    async def test_unknown_break_raises(self, captured_audit):
        org_id = uuid.uuid4()
        db = _make_db(breaks={})

        with pytest.raises(BreakNotFoundError):
            await end_break(
                db,
                org_id=org_id,
                break_record_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_already_ended_break_raises(self, captured_audit):
        org_id = uuid.uuid4()
        entry = _make_entry(org_id=org_id)
        ended_break = _make_break(
            org_id=org_id,
            parent_id=entry.id,
            start_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 6, 1, 12, 10, tzinfo=timezone.utc),
            minutes=10,
        )
        db = _make_db(
            entries={entry.id: entry},
            breaks={ended_break.id: ended_break},
        )

        with pytest.raises(BreakAlreadyEndedError):
            await end_break(
                db,
                org_id=org_id,
                break_record_id=ended_break.id,
            )

    @pytest.mark.asyncio
    async def test_break_in_other_org_raises(self, captured_audit):
        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()
        entry = _make_entry(org_id=other_org_id)
        rec = _make_break(org_id=other_org_id, parent_id=entry.id)
        db = _make_db(breaks={rec.id: rec})

        with pytest.raises(BreakNotFoundError):
            await end_break(
                db,
                org_id=org_id,
                break_record_id=rec.id,
            )


# ---------------------------------------------------------------------------
# suggest_break_windows (R7.2)
# ---------------------------------------------------------------------------


class TestSuggestBreakWindows:

    def _shift(self, hours: float) -> tuple[datetime, datetime]:
        start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=hours)
        return start, end

    def test_under_4h_returns_empty_list(self):
        start, end = self._shift(3.5)
        assert suggest_break_windows(start, end) == []

    def test_4h_shift_yields_one_paid_rest(self):
        start, end = self._shift(4)
        suggestions = suggest_break_windows(start, end)
        assert len(suggestions) == 1
        assert suggestions[0]["type"] == "rest_paid"
        assert suggestions[0]["minutes"] == 10
        # Centred on the midpoint (start + 2h).
        midpoint = start + timedelta(hours=2)
        assert suggestions[0]["start"] == midpoint - timedelta(minutes=5)
        assert suggestions[0]["end"] == midpoint + timedelta(minutes=5)

    def test_6h_shift_yields_one_rest_one_meal(self):
        start, end = self._shift(6)
        suggestions = suggest_break_windows(start, end)
        # 1 paid rest + 1 unpaid meal, sorted by start.
        assert [s["type"] for s in suggestions] == [
            "rest_paid", "meal_unpaid",
        ]
        assert [s["minutes"] for s in suggestions] == [10, 30]

    def test_10h_shift_yields_two_rests_one_meal(self):
        start, end = self._shift(10)
        suggestions = suggest_break_windows(start, end)
        assert len(suggestions) == 3
        types = [s["type"] for s in suggestions]
        # 2 paid rests + 1 unpaid meal, sorted by start.
        assert types.count("rest_paid") == 2
        assert types.count("meal_unpaid") == 1
        # Meal is in the middle.
        assert types[1] == "meal_unpaid"
        assert [s["minutes"] for s in suggestions] == [10, 30, 10]

    def test_12h_shift_uses_long_band(self):
        """A 12h shift triggers the 10h+ band — 2 rests + meal — not
        a stacked combination of all bands.
        """
        start, end = self._shift(12)
        suggestions = suggest_break_windows(start, end)
        types = [s["type"] for s in suggestions]
        assert types.count("rest_paid") == 2
        assert types.count("meal_unpaid") == 1
        assert len(suggestions) == 3

    def test_zero_or_negative_duration_returns_empty(self):
        start, end = self._shift(0)
        assert suggest_break_windows(start, end) == []
        assert suggest_break_windows(end, start) == []

    def test_suggestions_are_in_chronological_order(self):
        start, end = self._shift(10)
        suggestions = suggest_break_windows(start, end)
        starts = [s["start"] for s in suggestions]
        assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# validate_era_s69zd_breaks (R7.4)
# ---------------------------------------------------------------------------


class TestValidateEraS69ZDBreaks:

    def test_short_shift_no_breaks_compliant(self):
        result = validate_era_s69zd_breaks(180, [])  # 3h
        assert result["compliant"] is True
        assert result["missing_breaks"] == []

    def test_4h_shift_with_rest_compliant(self):
        recorded = [{"break_type": "rest_paid", "minutes": 10}]
        result = validate_era_s69zd_breaks(240, recorded)
        assert result["compliant"] is True
        assert result["missing_breaks"] == []

    def test_4h_shift_without_rest_non_compliant(self):
        result = validate_era_s69zd_breaks(240, [])
        assert result["compliant"] is False
        assert result["missing_breaks"] == ["rest_paid"]
        assert "rest" in result["message"]

    def test_6h_shift_with_only_rest_non_compliant(self):
        """Documented case: a 6h shift with only a rest break is
        non-compliant — meal_unpaid is also required.
        """
        recorded = [{"break_type": "rest_paid", "minutes": 10}]
        result = validate_era_s69zd_breaks(360, recorded)
        assert result["compliant"] is False
        assert result["missing_breaks"] == ["meal_unpaid"]
        assert "meal" in result["message"]

    def test_6h_shift_with_rest_and_meal_compliant(self):
        """Documented case: a 6h shift with rest + meal is compliant."""
        recorded = [
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "meal_unpaid", "minutes": 30},
        ]
        result = validate_era_s69zd_breaks(360, recorded)
        assert result["compliant"] is True
        assert result["missing_breaks"] == []

    def test_10h_shift_requires_two_rests_and_meal(self):
        # Only one rest + meal — still missing one rest.
        recorded = [
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "meal_unpaid", "minutes": 30},
        ]
        result = validate_era_s69zd_breaks(600, recorded)
        assert result["compliant"] is False
        assert result["missing_breaks"] == ["rest_paid"]

    def test_10h_shift_with_full_complement_compliant(self):
        recorded = [
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "meal_unpaid", "minutes": 30},
        ]
        result = validate_era_s69zd_breaks(600, recorded)
        assert result["compliant"] is True

    def test_short_recorded_break_does_not_discharge_minimum(self):
        """A 3-minute "rest" doesn't discharge the 10-min legal
        minimum — the chip flags the shift as still missing the rest.
        """
        recorded = [{"break_type": "rest_paid", "minutes": 3}]
        result = validate_era_s69zd_breaks(240, recorded)
        assert result["compliant"] is False
        assert result["missing_breaks"] == ["rest_paid"]

    def test_in_progress_break_counts_toward_requirement(self):
        """A break record without ``minutes`` (in-progress) counts as
        meeting the minimum so the chip doesn't false-flag a shift
        whose break is currently underway.
        """
        recorded = [{"break_type": "rest_paid", "minutes": None}]
        result = validate_era_s69zd_breaks(240, recorded)
        assert result["compliant"] is True

    def test_accepts_orm_like_objects(self):
        """The validator accepts attr-bearing objects (e.g. ORM rows)
        as well as dicts so callers don't have to serialise first.
        """
        records = [
            SimpleNamespace(break_type="rest_paid", minutes=10),
            SimpleNamespace(break_type="meal_unpaid", minutes=30),
        ]
        result = validate_era_s69zd_breaks(360, records)
        assert result["compliant"] is True

    def test_unknown_break_type_ignored(self):
        """Unknown break types are silently skipped — they don't
        count as fulfilment but also don't crash the validator.
        """
        recorded = [{"break_type": "tea", "minutes": 30}]
        result = validate_era_s69zd_breaks(360, recorded)
        # 6h shift still missing both rest_paid and meal_unpaid.
        assert result["compliant"] is False
        assert sorted(result["missing_breaks"]) == [
            "meal_unpaid", "rest_paid",
        ]

    def test_extra_breaks_do_not_create_false_compliance_drift(self):
        """3 rests + 2 meals on a 6h shift is still compliant — extra
        breaks beyond the minimum don't break the check.
        """
        recorded = [
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "rest_paid", "minutes": 10},
            {"break_type": "meal_unpaid", "minutes": 30},
            {"break_type": "meal_unpaid", "minutes": 30},
        ]
        result = validate_era_s69zd_breaks(360, recorded)
        assert result["compliant"] is True

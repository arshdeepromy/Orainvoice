"""Unit tests for ``StaffService.create_staff`` / ``update_staff`` Phase 1.

Covers task B4 from `.kiro/specs/staff-management-p1`:

1. Plaintext IRD on create → ``ird_number_encrypted`` is non-None bytes
   that decrypt back to the submitted value.
2. Plaintext bank on create → ``bank_account_number_encrypted`` is
   non-None bytes that decrypt back to the submitted value.
3. Update with masked IRD → existing ciphertext is unchanged (mask
   round-trip never overwrites real ciphertext).
4. Update with new plaintext IRD → ciphertext changes.
5. Create with employment_start_date but no probation_end_date →
   ``probation_end_date`` auto-set to start + 90 days.
6. Create with hourly_rate set → a ``StaffPayRate`` row with
   ``change_reason='initial_rate'`` is inserted.
7. Update changing hourly_rate → new ``StaffPayRate`` row with
   ``change_reason='rate_change'`` inserted, ``last_pay_review_date``
   bumped to today.
8. Create with ``hourly_rate < threshold`` and no override →
   ``MinimumWageBelowThresholdError`` raised with the threshold attached.
9. Create with ``hourly_rate < threshold`` and override=True → succeeds.
10. P1-N15 regression: ``staff.location_assignments`` is accessible on
    the returned object after both create and update without raising
    ``MissingGreenlet`` (proves ``await db.refresh(staff)`` is called).

The tests stub the DB session with ``AsyncMock``; they don't hit a real
PostgreSQL instance because the focus is the service-layer branching
logic. The encryption path uses the real ``app.core.encryption`` module
so the round-trip assertions are end-to-end.

**Validates: Requirements R2, R3, R4 — Staff Phase 1 task B4**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.encryption import envelope_decrypt_str
from app.modules.staff.models import StaffMember, StaffPayRate
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
from app.modules.staff.service import (
    MinimumWageBelowThresholdError,
    StaffService,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_db(
    *,
    existing_staff: StaffMember | None = None,
    duplicate_match: StaffMember | None = None,
    org_settings: dict | None = None,
) -> AsyncMock:
    """Build an AsyncMock DB session for the service under test.

    The service makes the following execute() calls per code path:

    create_staff:
        - 0..3 ``_check_duplicates`` (one per non-empty email/phone/
          employee_id field) → all return None (no duplicate).

    update_staff:
        - 1 ``get_staff`` → returns ``existing_staff``.
        - 0..3 ``_check_duplicates`` → all return None.

    The minimum-wage check uses :func:`app.modules.staff.service.get_org_settings`
    which is patched per-test via the ``org_settings`` knob (see
    :func:`_patch_org_settings`).
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()

    # The first execute() call from ``update_staff`` is the ``get_staff``
    # lookup that should return ``existing_staff``. Subsequent calls
    # (``_check_duplicates``) must return ``None`` so the update path
    # doesn't think it's hitting a stale duplicate of itself.
    state = {"first_call_consumed": existing_staff is None}

    async def fake_execute(stmt):  # noqa: ARG001 - stmt inspection unnecessary
        result = MagicMock()
        scalars = MagicMock()
        scalars.unique.return_value.all.return_value = []
        scalars.all.return_value = []
        result.scalars.return_value = scalars

        if not state["first_call_consumed"]:
            state["first_call_consumed"] = True
            result.scalar_one_or_none.return_value = existing_staff
        else:
            result.scalar_one_or_none.return_value = duplicate_match
        return result

    db.execute = fake_execute
    db._added: list[object] = []  # type: ignore[attr-defined]

    def fake_add(obj):
        db._added.append(obj)  # type: ignore[attr-defined]

    db.add.side_effect = fake_add
    return db


@pytest.fixture
def patched_org_settings(monkeypatch):
    """Patch ``StaffService._resolve_minimum_wage_threshold`` to return a
    fixed value, sidestepping the org-settings lookup (which would touch
    Redis + the DB in a live system).
    """
    def _patch(threshold: Decimal | None = None):
        async def fake_resolve(self, org_id):  # noqa: ARG001
            return threshold if threshold is not None else Decimal("23.15")

        monkeypatch.setattr(
            "app.modules.staff.service.StaffService._resolve_minimum_wage_threshold",
            fake_resolve,
        )

    return _patch


def _make_existing_staff(org_id: uuid.UUID, **kwargs) -> StaffMember:
    """Build an in-memory ``StaffMember`` instance for update tests.

    The existing ciphertext is already populated with a sentinel value
    so we can assert it stayed the same after a masked-update round
    trip.
    """
    defaults: dict = {
        "id": uuid.uuid4(),
        "org_id": org_id,
        "name": "Jane Doe",
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@example.com",
        "role_type": "employee",
        "is_active": True,
        "availability_schedule": {},
        "skills": [],
        "ird_number_encrypted": b"\x00" * 16 + b"sentinel-ciphertext",
        "bank_account_number_encrypted": b"\x00" * 16 + b"sentinel-bank",
        "hourly_rate": Decimal("28.50"),
        "overtime_rate": Decimal("42.75"),
    }
    defaults.update(kwargs)
    return StaffMember(**defaults)


# ---------------------------------------------------------------------------
# 1+2. Encryption round-trip on create
# ---------------------------------------------------------------------------


class TestCreateEncryptsPii:
    """Plaintext IRD + bank get envelope-encrypted on create."""

    @pytest.mark.asyncio
    async def test_plaintext_ird_is_encrypted(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            ird_number="123456789",
            hourly_rate=Decimal("30.00"),  # above threshold
        )
        staff = await svc.create_staff(org_id, payload)

        assert staff.ird_number_encrypted is not None
        assert isinstance(staff.ird_number_encrypted, (bytes, bytearray))
        # Round-trip via decrypt confirms the bytes are real ciphertext.
        assert envelope_decrypt_str(staff.ird_number_encrypted) == "123456789"

    @pytest.mark.asyncio
    async def test_plaintext_bank_is_encrypted(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            bank_account_number="02-1234-56789012-23",
            hourly_rate=Decimal("30.00"),
        )
        staff = await svc.create_staff(org_id, payload)

        assert staff.bank_account_number_encrypted is not None
        assert envelope_decrypt_str(
            staff.bank_account_number_encrypted,
        ) == "02-1234-56789012-23"

    @pytest.mark.asyncio
    async def test_no_ird_no_ciphertext(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")
        staff = await svc.create_staff(org_id, payload)

        assert staff.ird_number_encrypted is None
        assert staff.bank_account_number_encrypted is None


# ---------------------------------------------------------------------------
# 3+4. Mask round-trip vs plaintext update
# ---------------------------------------------------------------------------


class TestUpdateMaskRoundTrip:
    """Mask values are skipped; plaintext values are re-encrypted."""

    @pytest.mark.asyncio
    async def test_masked_ird_does_not_overwrite_ciphertext(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        original_cipher = existing.ird_number_encrypted
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        # Schema rejects mask values on UPDATE — bypass via raw construction.
        payload = StaffMemberUpdate.model_construct(
            ird_number="***789",
        )
        staff = await svc.update_staff(org_id, existing.id, payload)

        assert staff is not None
        # Ciphertext is unchanged — the masked value was correctly skipped.
        assert staff.ird_number_encrypted == original_cipher

    @pytest.mark.asyncio
    async def test_plaintext_ird_replaces_ciphertext(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        original_cipher = existing.ird_number_encrypted
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        payload = StaffMemberUpdate(ird_number="987654321")
        staff = await svc.update_staff(org_id, existing.id, payload)

        assert staff is not None
        assert staff.ird_number_encrypted is not None
        assert staff.ird_number_encrypted != original_cipher
        assert envelope_decrypt_str(staff.ird_number_encrypted) == "987654321"

    @pytest.mark.asyncio
    async def test_masked_bank_does_not_overwrite_ciphertext(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        original_cipher = existing.bank_account_number_encrypted
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        payload = StaffMemberUpdate.model_construct(
            bank_account_number="**-****-****12-**",
        )
        staff = await svc.update_staff(org_id, existing.id, payload)

        assert staff is not None
        assert staff.bank_account_number_encrypted == original_cipher


# ---------------------------------------------------------------------------
# 5. Auto-set probation_end_date
# ---------------------------------------------------------------------------


class TestAutoSetProbationEndDate:
    """When start_date is supplied and probation_end is omitted, set +90d."""

    @pytest.mark.asyncio
    async def test_probation_auto_set(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        start = date(2024, 1, 15)
        payload = StaffMemberCreate(
            first_name="Jane",
            employment_start_date=start,
            # probation_end_date omitted -> defaults to None on the schema.
        )
        staff = await svc.create_staff(org_id, payload)

        assert staff.probation_end_date == start + timedelta(days=90)

    @pytest.mark.asyncio
    async def test_explicit_probation_preserved(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        start = date(2024, 1, 15)
        explicit = date(2024, 6, 30)  # different from start+90
        payload = StaffMemberCreate(
            first_name="Jane",
            employment_start_date=start,
            probation_end_date=explicit,
        )
        staff = await svc.create_staff(org_id, payload)

        assert staff.probation_end_date == explicit

    @pytest.mark.asyncio
    async def test_no_start_no_probation(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")
        staff = await svc.create_staff(org_id, payload)

        assert staff.probation_end_date is None


# ---------------------------------------------------------------------------
# 6+7. Pay rate ledger writes
# ---------------------------------------------------------------------------


def _added_pay_rates(db: AsyncMock) -> list[StaffPayRate]:
    return [obj for obj in db._added if isinstance(obj, StaffPayRate)]  # type: ignore[attr-defined]


class TestPayRateLedger:
    """Initial-rate + rate-change rows land in ``staff_pay_rates``."""

    @pytest.mark.asyncio
    async def test_initial_rate_row_inserted_on_create(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("30.00"),
            overtime_rate=Decimal("45.00"),
        )
        staff = await svc.create_staff(org_id, payload)

        rows = _added_pay_rates(db)
        assert len(rows) == 1
        row = rows[0]
        assert row.staff_id == staff.id
        assert row.org_id == org_id
        assert row.change_reason == "initial_rate"
        assert row.hourly_rate == Decimal("30.00")
        assert row.overtime_rate == Decimal("45.00")
        assert row.effective_from == date.today()

    @pytest.mark.asyncio
    async def test_no_pay_rate_row_when_no_rate_supplied(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")
        await svc.create_staff(org_id, payload)

        assert _added_pay_rates(db) == []

    @pytest.mark.asyncio
    async def test_rate_change_inserts_row_and_bumps_review_date(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        existing.last_pay_review_date = None
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        payload = StaffMemberUpdate(hourly_rate=Decimal("32.00"))
        staff = await svc.update_staff(org_id, existing.id, payload)
        assert staff is not None

        rows = _added_pay_rates(db)
        assert len(rows) == 1
        row = rows[0]
        assert row.change_reason == "rate_change"
        assert row.hourly_rate == Decimal("32.00")
        # Overtime is unchanged so the audit row preserves the prior value.
        assert row.overtime_rate == Decimal("42.75")
        assert staff.last_pay_review_date == date.today()

    @pytest.mark.asyncio
    async def test_no_rate_change_no_row(self, patched_org_settings):
        patched_org_settings()
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        existing.last_pay_review_date = date(2023, 1, 1)
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        # Submit the same hourly_rate that's already on the record.
        payload = StaffMemberUpdate(hourly_rate=existing.hourly_rate)
        staff = await svc.update_staff(org_id, existing.id, payload)
        assert staff is not None

        assert _added_pay_rates(db) == []
        # last_pay_review_date is NOT bumped when nothing changed.
        assert staff.last_pay_review_date == date(2023, 1, 1)


# ---------------------------------------------------------------------------
# 8+9. Minimum-wage gate
# ---------------------------------------------------------------------------


class TestMinimumWageGate:
    """Below-threshold without override → 422; with override → succeeds."""

    @pytest.mark.asyncio
    async def test_below_threshold_no_override_raises(
        self, patched_org_settings,
    ):
        patched_org_settings(threshold=Decimal("23.15"))
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=False,
        )
        with pytest.raises(MinimumWageBelowThresholdError) as exc_info:
            await svc.create_staff(org_id, payload)

        # Threshold attached so the router can include it in the 422 body.
        assert exc_info.value.threshold == Decimal("23.15")

    @pytest.mark.asyncio
    async def test_below_threshold_with_override_succeeds(
        self, patched_org_settings,
    ):
        patched_org_settings(threshold=Decimal("23.15"))
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=True,
        )
        staff = await svc.create_staff(org_id, payload)

        assert staff.hourly_rate == Decimal("20.00")

    @pytest.mark.asyncio
    async def test_at_threshold_passes(self, patched_org_settings):
        patched_org_settings(threshold=Decimal("23.15"))
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("23.15"),
        )
        staff = await svc.create_staff(org_id, payload)

        assert staff.hourly_rate == Decimal("23.15")

    @pytest.mark.asyncio
    async def test_no_rate_no_check(self, patched_org_settings):
        # Even if the threshold would fail a hypothetical zero rate, an
        # absent ``hourly_rate`` must not trip the gate.
        patched_org_settings(threshold=Decimal("23.15"))
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")  # no hourly_rate
        staff = await svc.create_staff(org_id, payload)

        assert staff.hourly_rate is None

    @pytest.mark.asyncio
    async def test_update_below_threshold_raises(self, patched_org_settings):
        patched_org_settings(threshold=Decimal("23.15"))
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        payload = StaffMemberUpdate(hourly_rate=Decimal("18.00"))
        with pytest.raises(MinimumWageBelowThresholdError):
            await svc.update_staff(org_id, existing.id, payload)


# ---------------------------------------------------------------------------
# 10. P1-N15 regression — db.refresh keeps relationships hydrated
# ---------------------------------------------------------------------------


class TestRefreshAfterFlushP1N15:
    """``db.refresh(staff)`` is awaited so lazy relationships work post-flush.

    The bug class (``MissingGreenlet``) appears in production when the
    ORM tries to lazily load a relationship from inside an async context
    that doesn't have a greenlet — typical when the caller serialises
    the model to a Pydantic response *after* the session's ``flush()``
    closed the underlying greenlet bridge. ``await db.refresh(obj)``
    pre-loads the relationship state on the model so subsequent
    attribute access works without a fresh DB round-trip.

    Here we don't reproduce ``MissingGreenlet`` directly (the AsyncMock
    DB doesn't have greenlets either) — we assert the call surface that
    prevents it: ``db.refresh`` is awaited at least once and the
    returned ORM object's ``location_assignments`` attribute is
    accessible without raising.
    """

    @pytest.mark.asyncio
    async def test_create_calls_refresh_and_relationship_is_accessible(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        db = _make_db()
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")
        staff = await svc.create_staff(org_id, payload)

        # ``db.refresh`` was awaited at least once on the new staff.
        assert db.refresh.await_count >= 1
        refreshed_args = [c.args for c in db.refresh.await_args_list]
        assert any(args and args[0] is staff for args in refreshed_args), (
            "db.refresh was never called with the new staff instance"
        )

        # Accessing the relationship does not raise — proves the
        # attribute is materialised (in this in-memory test it's the
        # default empty list from ``cascade='all, delete-orphan'``).
        assert staff.location_assignments == []

    @pytest.mark.asyncio
    async def test_update_calls_refresh_and_relationship_is_accessible(
        self, patched_org_settings,
    ):
        patched_org_settings()
        org_id = uuid.uuid4()
        existing = _make_existing_staff(org_id)
        # Pre-populate the relationship to prove access doesn't trigger
        # an additional DB round-trip after refresh.
        existing.location_assignments = []
        db = _make_db(existing_staff=existing)
        svc = StaffService(db)

        payload = StaffMemberUpdate(emergency_contact_name="John Doe")
        staff = await svc.update_staff(org_id, existing.id, payload)
        assert staff is not None

        assert db.refresh.await_count >= 1
        refreshed_args = [c.args for c in db.refresh.await_args_list]
        assert any(args and args[0] is staff for args in refreshed_args), (
            "db.refresh was never called with the updated staff instance"
        )

        assert staff.location_assignments == []

"""Cross-phase test for ``StaffService.create_staff`` default-channel
resolution (Phase 3 task B3a / R6b / G9).

Behaviour under test:

1. Org with ``clock_in_policy.default_channel='kiosk_only'`` and a
   payload that **omits** ``self_service_clock_enabled`` → new staff
   row has ``self_service_clock_enabled=False``.

2. Same org, payload that **explicitly sets** ``self_service_clock_enabled=True``
   → new staff row has ``self_service_clock_enabled=True`` (the org
   policy is overridden by the explicit caller value, per R6b.2).

3. Org with ``clock_in_policy.default_channel='kiosk_and_self_service'``
   and a payload that **omits** the flag → new staff row has
   ``self_service_clock_enabled=True``.

4. Existing staff records are NEVER mutated when the org policy
   changes — the policy only applies on NEW staff insertion (R6b.3).
   Modelled here by toggling the policy mid-test and confirming a
   pre-existing in-memory ``StaffMember`` object retains its original
   value while a freshly-created staff picks up the new default.

The test stubs the DB session with ``AsyncMock``; it does not hit a
real PostgreSQL instance because the focus is on the service-layer
resolution branch. The mock ``execute()`` recognises the literal
``SELECT clock_in_policy FROM organisations`` query (used by the new
``StaffService._resolve_default_clock_channel`` helper) and returns a
configurable JSONB dict so each test can pick its policy.

**Validates: Requirement R6b — Phase 3 task B3a (G9)**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.elements import TextClause

from app.modules.staff.models import StaffMember
from app.modules.staff.schemas import StaffMemberCreate
from app.modules.staff.service import StaffService


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_db(*, default_channel: str | None) -> AsyncMock:
    """Build an AsyncMock DB session whose ``execute()`` simulates the
    ``SELECT clock_in_policy FROM organisations`` lookup added in B3a.

    ``default_channel`` selects what the simulated org row holds:
      - ``'kiosk_only'`` → ``{"default_channel": "kiosk_only"}`` JSONB.
      - ``'kiosk_and_self_service'`` → ``{"default_channel": "kiosk_and_self_service"}``.
      - ``None`` → JSONB column is NULL (org row absent or default
        block missing). The helper falls back to ``'kiosk_only'``.

    All other ``execute()`` calls (the duplicate-checks fired by
    ``_check_duplicates``) return a ``scalar_one_or_none() -> None``
    result so the create path proceeds without thinking it's a dup.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()

    db._added: list[object] = []  # type: ignore[attr-defined]

    def fake_add(obj):
        db._added.append(obj)  # type: ignore[attr-defined]

    db.add.side_effect = fake_add

    async def fake_execute(stmt, params=None):  # noqa: ARG001
        result = MagicMock()
        scalars = MagicMock()
        scalars.unique.return_value.all.return_value = []
        scalars.all.return_value = []
        result.scalars.return_value = scalars

        # Detect the clock_in_policy lookup by the literal SQL fragment.
        is_clock_policy_query = (
            isinstance(stmt, TextClause)
            and "clock_in_policy" in str(stmt)
        )
        if is_clock_policy_query:
            if default_channel is None:
                result.scalar_one_or_none.return_value = None
            else:
                # The real driver returns the JSONB value as a Python
                # dict via psycopg2/asyncpg's JSON adapter.
                result.scalar_one_or_none.return_value = {
                    "default_channel": default_channel,
                }
        else:
            # Duplicate-check + any other lookup → no row.
            result.scalar_one_or_none.return_value = None
        return result

    db.execute = fake_execute
    return db


@pytest.fixture
def patched_min_wage(monkeypatch):
    """Stub the minimum-wage threshold lookup so create_staff doesn't
    chase down ``get_org_settings()`` (which would hit the real DB).
    """
    async def fake_resolve(self, org_id):  # noqa: ARG001
        return Decimal("23.15")

    monkeypatch.setattr(
        "app.modules.staff.service.StaffService._resolve_minimum_wage_threshold",
        fake_resolve,
    )


# ---------------------------------------------------------------------------
# Tests — R6b.1 / R6b.2 / R6b.3
# ---------------------------------------------------------------------------


class TestDefaultChannelResolution:
    """The four scenarios spelled out in task B3a's verify list."""

    @pytest.mark.asyncio
    async def test_kiosk_only_omitted_flag_yields_false(
        self, patched_min_wage,  # noqa: ARG002
    ) -> None:
        """R6b.1 — ``default_channel='kiosk_only'`` + omitted flag → False."""
        org_id = uuid.uuid4()
        db = _make_db(default_channel="kiosk_only")
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")
        # Sanity check the schema tri-state is the documented default.
        assert payload.self_service_clock_enabled is None

        staff = await svc.create_staff(org_id, payload)

        assert staff.self_service_clock_enabled is False

    @pytest.mark.asyncio
    async def test_kiosk_only_explicit_true_overrides_policy(
        self, patched_min_wage,  # noqa: ARG002
    ) -> None:
        """R6b.2 — explicit ``True`` is respected even when policy is kiosk_only."""
        org_id = uuid.uuid4()
        db = _make_db(default_channel="kiosk_only")
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            self_service_clock_enabled=True,
        )

        staff = await svc.create_staff(org_id, payload)

        assert staff.self_service_clock_enabled is True

    @pytest.mark.asyncio
    async def test_kiosk_and_self_service_omitted_flag_yields_true(
        self, patched_min_wage,  # noqa: ARG002
    ) -> None:
        """R6b.1 — ``default_channel='kiosk_and_self_service'`` + omitted → True."""
        org_id = uuid.uuid4()
        db = _make_db(default_channel="kiosk_and_self_service")
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")

        staff = await svc.create_staff(org_id, payload)

        assert staff.self_service_clock_enabled is True

    @pytest.mark.asyncio
    async def test_kiosk_and_self_service_explicit_false_overrides_policy(
        self, patched_min_wage,  # noqa: ARG002
    ) -> None:
        """R6b.2 — explicit ``False`` is respected even when policy is kiosk_and_self_service.

        Bonus coverage: confirms the tri-state ``None`` vs ``False``
        distinction actually flows through the service. Without the
        ``Optional[bool]`` schema change, an explicit ``False`` would
        be indistinguishable from the default and would silently get
        flipped to ``True`` by the policy.
        """
        org_id = uuid.uuid4()
        db = _make_db(default_channel="kiosk_and_self_service")
        svc = StaffService(db)

        payload = StaffMemberCreate(
            first_name="Jane",
            self_service_clock_enabled=False,
        )

        staff = await svc.create_staff(org_id, payload)

        assert staff.self_service_clock_enabled is False

    @pytest.mark.asyncio
    async def test_missing_policy_falls_back_to_kiosk_only(
        self, patched_min_wage,  # noqa: ARG002
    ) -> None:
        """When the org row has no ``clock_in_policy`` JSONB (or the
        column is NULL), the helper falls back to the documented
        system default — ``'kiosk_only'`` → False.
        """
        org_id = uuid.uuid4()
        db = _make_db(default_channel=None)
        svc = StaffService(db)

        payload = StaffMemberCreate(first_name="Jane")

        staff = await svc.create_staff(org_id, payload)

        assert staff.self_service_clock_enabled is False


class TestExistingStaffNotMutatedByPolicyChange:
    """R6b.3 — the policy only applies on NEW staff insertion.

    Pre-existing staff records keep whatever value was on them at the
    moment of their original insertion, regardless of what the org
    admin later sets ``clock_in_policy.default_channel`` to.
    """

    @pytest.mark.asyncio
    async def test_policy_change_does_not_mutate_existing_records(
        self, patched_min_wage,  # noqa: ARG002
    ) -> None:
        org_id = uuid.uuid4()

        # 1. Create staff A under ``kiosk_only`` — flag derives to False.
        db_a = _make_db(default_channel="kiosk_only")
        svc_a = StaffService(db_a)
        existing = await svc_a.create_staff(
            org_id, StaffMemberCreate(first_name="Alice"),
        )
        assert existing.self_service_clock_enabled is False

        # 2. Org policy flips to ``kiosk_and_self_service``. Simulate
        #    by spinning up a NEW DB session under the new policy.
        db_b = _make_db(default_channel="kiosk_and_self_service")
        svc_b = StaffService(db_b)

        # Hand the previously-created object back to the new session
        # untouched. (Real DBs do this implicitly via row identity.)
        # The flag on the existing row must NOT change just because
        # the policy did — assert this directly.
        assert existing.self_service_clock_enabled is False

        # 3. Create staff B under the new policy — flag derives to True.
        new_staff = await svc_b.create_staff(
            org_id, StaffMemberCreate(first_name="Bob"),
        )
        assert new_staff.self_service_clock_enabled is True

        # 4. The existing record is still untouched.
        assert existing.self_service_clock_enabled is False
        assert isinstance(existing, StaffMember)

"""Cross-phase test for ``create_branch`` geofence-default propagation
(Phase 3 task B12 / R6.4 / G17).

Behaviour under test:

1. Org with ``clock_in_policy.branch_radius_metres=500`` and a payload
   that **omits** ``geofence_radius_metres`` → new branch row has
   ``geofence_radius_metres=500``.

2. Same org, payload that **explicitly sets** ``geofence_radius_metres=300``
   → new branch row has ``geofence_radius_metres=300`` (the org policy
   is overridden by the explicit caller value).

3. Org with no ``clock_in_policy`` JSONB column populated → falls
   back to 200 (the migration-0207 column default).

4. Once a branch row exists, changing the org-level
   ``clock_in_policy.branch_radius_metres`` does NOT mass-update
   existing branches (the column is the source of truth post-creation).

The DB session is mocked with ``AsyncMock``; the service-layer
``create_branch`` is exercised end-to-end (build the Branch ORM
object, call audit log, return dict).

**Validates: Requirement R6.4 / G17 — Phase 3 task B12 (X5)**
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import ORM modules to avoid mapper init errors.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401

from app.modules.admin.models import Organisation
from app.modules.organisations.models import Branch
from app.modules.organisations.service import create_branch


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_org(*, id: uuid.UUID | None = None) -> Organisation:
    """Create a minimal Organisation ORM stub for the create_branch
    org-existence check.
    """
    return Organisation(
        id=id or uuid.uuid4(),
        name="Test Org",
        plan_id=uuid.uuid4(),
        storage_quota_gb=10,
    )


def _make_db(
    *,
    org: Organisation | None,
    clock_in_policy: dict | None,
) -> tuple[AsyncMock, list]:
    """Build an :class:`AsyncMock` DB session for create_branch.

    Returns ``(db, added)`` where ``added`` is the list of objects
    passed to ``db.add(...)`` so the test can read back the inserted
    Branch.
    """
    added: list = []

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: added.append(obj))

    async def _fake_execute(stmt, params=None):
        result = MagicMock()
        rendered = str(stmt).lower()
        try:
            text_repr = (stmt.text or "").lower()
        except AttributeError:
            text_repr = ""

        # text("SELECT clock_in_policy ...") — returns the JSONB dict.
        if "clock_in_policy" in text_repr:
            result.scalar_one_or_none.return_value = clock_in_policy
            return result
        # select(Organisation) — returns the org or None.
        if "organisations" in rendered:
            result.scalar_one_or_none.return_value = org
            return result
        # Default — empty.
        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db, added


@pytest.fixture
def patched_audit():
    """Stub ``write_audit_log`` so create_branch doesn't try to write
    a real audit row (the audit serialiser would need a real DB).
    """
    async def _fake_audit(session, **kwargs):
        return uuid.uuid4()

    with patch(
        "app.modules.organisations.service.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateBranchGeofenceDefault:

    @pytest.mark.asyncio
    async def test_omit_radius_uses_org_policy(self, patched_audit):
        """R6.4 — ``branch_radius_metres=500`` in policy + omitted →
        new branch has ``geofence_radius_metres=500``.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org = _make_org(id=org_id)
        db, added = _make_db(
            org=org,
            clock_in_policy={"branch_radius_metres": 500},
        )

        result = await create_branch(
            db,
            org_id=org_id,
            user_id=user_id,
            name="Pick & Pack",
        )

        assert result["geofence_radius_metres"] == 500
        # Confirm the Branch ORM object got the value too.
        assert isinstance(added[0], Branch)
        assert added[0].geofence_radius_metres == 500

    @pytest.mark.asyncio
    async def test_explicit_radius_overrides_policy(self, patched_audit):
        """R6.4 — explicit ``geofence_radius_metres`` is respected even
        when policy is set to a different value.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org = _make_org(id=org_id)
        db, added = _make_db(
            org=org,
            clock_in_policy={"branch_radius_metres": 800},
        )

        result = await create_branch(
            db,
            org_id=org_id,
            user_id=user_id,
            name="Workshop",
            geofence_radius_metres=300,
        )

        assert result["geofence_radius_metres"] == 300
        assert added[0].geofence_radius_metres == 300

    @pytest.mark.asyncio
    async def test_no_policy_falls_back_to_200(self, patched_audit):
        """When the org row has no ``clock_in_policy`` JSONB (or the
        column is NULL), falls back to the documented system default
        — 200.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org = _make_org(id=org_id)
        db, added = _make_db(
            org=org,
            clock_in_policy=None,
        )

        result = await create_branch(
            db,
            org_id=org_id,
            user_id=user_id,
            name="HQ",
        )

        assert result["geofence_radius_metres"] == 200
        assert added[0].geofence_radius_metres == 200

    @pytest.mark.asyncio
    async def test_existing_branch_not_mutated_when_policy_changes(
        self, patched_audit,
    ):
        """R6.4 — existing branch records keep their value when the
        org-level policy changes. We model this by creating one branch
        under policy=500, swapping the policy to 800, and creating
        another. The first branch's stored value stays at 500.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org = _make_org(id=org_id)

        # Step 1 — create with policy=500.
        db_a, added_a = _make_db(
            org=org,
            clock_in_policy={"branch_radius_metres": 500},
        )
        result_a = await create_branch(
            db_a,
            org_id=org_id,
            user_id=user_id,
            name="Branch A",
        )
        existing_branch = added_a[0]
        assert result_a["geofence_radius_metres"] == 500

        # Step 2 — flip policy to 800 (simulated via a fresh DB session).
        db_b, added_b = _make_db(
            org=org,
            clock_in_policy={"branch_radius_metres": 800},
        )
        result_b = await create_branch(
            db_b,
            org_id=org_id,
            user_id=user_id,
            name="Branch B",
        )

        # The new branch picks up the new policy.
        assert result_b["geofence_radius_metres"] == 800
        assert added_b[0].geofence_radius_metres == 800
        # The pre-existing branch's stored value is unchanged.
        assert existing_branch.geofence_radius_metres == 500

    @pytest.mark.asyncio
    async def test_missing_org_raises(self, patched_audit):
        """When the org doesn't exist, the service raises ValueError —
        same error contract as before B12.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db, _ = _make_db(org=None, clock_in_policy=None)

        with pytest.raises(ValueError, match="Organisation not found"):
            await create_branch(
                db,
                org_id=org_id,
                user_id=user_id,
                name="Branch",
            )

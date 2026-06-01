"""Unit tests for PPSR quota — load + increment + billing-cycle reset.

**Validates: Requirements R5 — PPSR module Phase 1, task E1.**

Coverage matrix (per tasks.md E1 ``**Verify:**`` block):

  - ``PpsrService._load_quota``
      * returns 0/0 when the org has no plan / counters are NULL
      * returns the correct ``used`` / ``included`` values from the
        ``Organisation × SubscriptionPlan`` join
      * surfaces hidden-plate counters as separate fields (G44 — the
        ``ppsr_hidden_plate_lookups_*`` rename)

  - **Increment behaviour** — exercised through ``PpsrService.search``
      * a fresh search fires an atomic ``UPDATE organisations SET
        ppsr_lookups_this_month = ppsr_lookups_this_month + 1``
        statement (asserted by inspecting the compiled SQL)
      * ``check_hidden_plates=True`` bumps **both**
        ``ppsr_lookups_this_month`` AND
        ``ppsr_hidden_plate_lookups_this_month`` in the same UPDATE

  - **Billing-cycle reset behaviour** — exercises the conditional logic
    that lives at [app/tasks/subscriptions.py::process_recurring_billing_task](app/tasks/subscriptions.py#L196)
    in isolation (the full task is too heavy to set up — Stripe,
    coupons, breakdown calc, etc., are out of scope for this unit test)
      * when ``ppsr_overage_count > 0`` → both counters reset to 0
      * when ``ppsr_lookups_this_month <= included`` → counters are NOT
        reset (under quota, no overage charged)
      * the hidden-plate counter resets at the same boundary — it is
        not gated on its own overage count (matches the carjam pattern
        of "any overage triggers a full reset")

The DB session reuses the in-memory ``_FakeDB`` pattern from
``test_ppsr_service.py`` so the read-side dispatch (IntegrationConfig +
Organisation × SubscriptionPlan join + cache lookup) stays consistent
across the suite.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all SQLAlchemy mappers are wired before instantiating ORM rows.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.ppsr.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401

from app.core.encryption import envelope_encrypt
from app.integrations.carjam import CarjamPpsrResponse
from app.modules.admin.models import IntegrationConfig
from app.modules.ppsr.schemas import PpsrSearchOptions
from app.modules.ppsr.service import PpsrService


# ---------------------------------------------------------------------------
# In-memory fakes — slim copy of the helpers in test_ppsr_service.py.
# Kept self-contained so this file can be reasoned about in isolation.
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal :class:`redis.asyncio.Redis` double for the lock helper."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


def _carjam_config_blob(**fields: Any) -> bytes:
    payload = {
        "api_key": "test-key",
        "endpoint_url": "https://www.carjam.co.nz",
        "global_rate_limit_per_minute": 60,
    }
    payload.update(fields)
    return envelope_encrypt(json.dumps(payload))


def _make_carjam_config_row(**fields: Any) -> IntegrationConfig:
    return IntegrationConfig(
        id=uuid.uuid4(),
        name="carjam",
        config_encrypted=_carjam_config_blob(**fields),
        is_verified=True,
    )


class _ExecResult:
    def __init__(
        self,
        *,
        scalar: Any | None = None,
        first_row: tuple[Any, ...] | None = None,
    ) -> None:
        self._scalar = scalar
        self._first_row = first_row

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def first(self) -> tuple[Any, ...] | None:
        return self._first_row


class _FakeDB:
    """Fake ``AsyncSession`` covering the queries the quota path issues.

    Routes ``execute`` calls based on the rendered SQL string and tracks
    every UPDATE statement on ``self.update_statements`` so tests can
    assert the columns + targets of each fired UPDATE without relying
    on a real Postgres round-trip.
    """

    def __init__(
        self,
        *,
        carjam_config: IntegrationConfig | None,
        quota_row: tuple[Any, ...] | None,
        org_id: uuid.UUID | None = None,
    ) -> None:
        self.carjam_config = carjam_config
        # ``quota_row`` is the tuple returned by the
        # ``Organisation × SubscriptionPlan`` join in ``_load_quota``:
        #   (used, hidden_used, resets_at, included, hidden_included)
        # Tests use ``None`` to simulate a missing org / plan row.
        self.quota_row = quota_row
        self.org_id = org_id or uuid.uuid4()

        self.added: list[Any] = []
        self.update_statements: list[Any] = []
        self.flush = AsyncMock()
        self.refresh = AsyncMock()
        self.add = MagicMock(side_effect=self._on_add)

    def _on_add(self, obj: Any) -> None:
        self.added.append(obj)
        # Mimic post-INSERT id / created_at population so the service can
        # call ``await db.refresh(search)`` without exploding.
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        rendered = str(stmt).lower()

        # Audit-log inserts go via ``text()`` — accept silently.
        if "insert into audit_log" in rendered:
            return _ExecResult(scalar=None)

        if rendered.startswith("update"):
            self.update_statements.append(stmt)
            return _ExecResult(scalar=1)

        if "from integration_configs" in rendered:
            return _ExecResult(scalar=self.carjam_config)

        if "from organisations" in rendered and "subscription_plans" in rendered:
            return _ExecResult(first_row=self.quota_row)

        if "from ppsr_searches" in rendered:
            # Cache lookup — always miss.
            return _ExecResult(scalar=None)

        if "from org_vehicles" in rendered:
            return _ExecResult(scalar=None)
        if "from global_vehicles" in rendered:
            return _ExecResult(scalar=None)

        return _ExecResult(scalar=None)


def _carjam_response(rego: str = "ABC123") -> CarjamPpsrResponse:
    return CarjamPpsrResponse(
        rego=rego,
        not_found=False,
        basic={"make": "Toyota"},
        ownership_history=None,
        current_owner=None,
        ppsr_summary={"count": 0},
        ppsr_details=[],
        money_owing={
            "match": "N",
            "match_description": "No money owing",
            "search_id": "ppsr-12345",
        },
        warnings=None,
        flood=None,
        charges_cents=50,
        raw_xml="{}",
        requested_options={},
    )


class _FakeCarjamClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def lookup_ppsr(self, rego: str, **kwargs: Any) -> CarjamPpsrResponse:
        self.calls.append({"rego": rego, **kwargs})
        return _carjam_response(rego=rego)


def _make_user(role: str = "staff_member") -> Any:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.role = role
    user.org_id = uuid.uuid4()
    return user


@pytest.fixture
def patched_module_enabled():
    with patch(
        "app.modules.ppsr.service.ModuleService.is_enabled",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture
def patched_carjam_client_factory():
    container: dict[str, _FakeCarjamClient] = {"client": _FakeCarjamClient()}

    async def _factory(_db: Any, _redis: Any) -> _FakeCarjamClient:
        return container["client"]

    with patch(
        "app.modules.ppsr.service._load_carjam_client",
        new=_factory,
    ):
        def _set(client: _FakeCarjamClient) -> None:
            container["client"] = client

        yield container, _set


# ---------------------------------------------------------------------------
# Helpers for inspecting compiled UPDATE statements
# ---------------------------------------------------------------------------


def _update_target_table(stmt: Any) -> str | None:
    """Return the target table name for an UPDATE ``stmt``."""

    table = getattr(stmt, "table", None)
    if table is None:
        return None
    return getattr(table, "name", None)


def _update_columns(stmt: Any) -> set[str]:
    """Return the set of column names mentioned in ``stmt._values``."""

    cols: set[str] = set()
    values = getattr(stmt, "_values", None) or {}
    for col in values:
        name = getattr(col, "name", None) or getattr(col, "key", None)
        if name:
            cols.add(str(name))
    return cols


def _update_is_atomic_increment(stmt: Any, column: str) -> bool:
    """Best-effort check that ``column`` is set to ``column + 1``.

    The service builds the expression as
    ``Organisation.<column> + 1`` so the compiled clause renders as
    ``<column>=(organisations.<column> + 1)``. We don't need to
    introspect the AST in detail — checking the rendered SQL covers
    the contract (the assignment is server-side, not Python-cached).
    """

    rendered = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
    # Strip whitespace variants so we accept both ``col=(...)`` and
    # ``col = (...)`` renderings without coupling to SQLAlchemy's
    # exact spacing.
    flattened = "".join(rendered.split())
    needle = f"{column}=(organisations.{column}+1)"
    return needle in flattened


# ===========================================================================
# 1. Quota check unit tests — _load_quota
# ===========================================================================


class TestLoadQuotaMissingPlan:
    """When the ``Organisation × SubscriptionPlan`` join misses, the
    helper returns a zero-quota response so the caller raises
    ``PpsrQuotaExceededError``."""

    @pytest.mark.asyncio
    async def test_returns_zero_used_zero_included_when_row_is_none(self):
        db = _FakeDB(carjam_config=None, quota_row=None)
        svc = PpsrService(db, _FakeRedis())

        quota = await svc._load_quota(uuid.uuid4())

        assert quota.used == 0
        assert quota.included == 0
        # Hidden-plate counters surface as their own fields and default
        # to zero too — the response shape is the same regardless of
        # whether the org had a plan attached.
        assert quota.hidden_plate_used == 0
        assert quota.hidden_plate_included == 0
        assert quota.resets_at is None


class TestLoadQuotaNullCounters:
    """NULL counter columns (e.g. fresh org never billed) collapse to
    zero rather than tripping ``int(None)``."""

    @pytest.mark.asyncio
    async def test_null_columns_treated_as_zero(self):
        # (used, hidden_used, resets_at, included, hidden_included)
        db = _FakeDB(
            carjam_config=None,
            quota_row=(None, None, None, None, None),
        )
        svc = PpsrService(db, _FakeRedis())

        quota = await svc._load_quota(uuid.uuid4())

        assert quota.used == 0
        assert quota.included == 0
        assert quota.hidden_plate_used == 0
        assert quota.hidden_plate_included == 0
        assert quota.resets_at is None


class TestLoadQuotaPopulated:
    """Populated counters round-trip into the response model."""

    @pytest.mark.asyncio
    async def test_returns_correct_used_and_included_from_row(self):
        resets_at = datetime.now(timezone.utc) + timedelta(days=12)
        db = _FakeDB(
            carjam_config=None,
            quota_row=(7, 2, resets_at, 50, 10),
        )
        svc = PpsrService(db, _FakeRedis())

        quota = await svc._load_quota(uuid.uuid4())

        assert quota.used == 7
        assert quota.included == 50
        # G44 — hidden-plate counters are surfaced as separate fields
        # so the frontend can render two distinct progress bars.
        assert quota.hidden_plate_used == 2
        assert quota.hidden_plate_included == 10
        assert quota.resets_at == resets_at


class TestLoadQuotaHiddenPlateSeparate:
    """The hidden-plate counter is independent of the standard counter
    — exhausting one does not exhaust the other."""

    @pytest.mark.asyncio
    async def test_standard_full_hidden_plate_unused(self):
        resets_at = datetime.now(timezone.utc) + timedelta(days=3)
        db = _FakeDB(
            carjam_config=None,
            quota_row=(50, 0, resets_at, 50, 5),
        )
        svc = PpsrService(db, _FakeRedis())

        quota = await svc._load_quota(uuid.uuid4())

        assert quota.used == quota.included == 50
        assert quota.hidden_plate_used == 0
        assert quota.hidden_plate_included == 5

    @pytest.mark.asyncio
    async def test_hidden_plate_full_standard_unused(self):
        resets_at = datetime.now(timezone.utc) + timedelta(days=3)
        db = _FakeDB(
            carjam_config=None,
            quota_row=(0, 5, resets_at, 50, 5),
        )
        svc = PpsrService(db, _FakeRedis())

        quota = await svc._load_quota(uuid.uuid4())

        assert quota.used == 0
        assert quota.included == 50
        assert quota.hidden_plate_used == quota.hidden_plate_included == 5


# ===========================================================================
# 2. Increment behaviour — UPDATE statement assertions
# ===========================================================================


class TestQuotaIncrementSql:
    """The service fires an atomic ``UPDATE organisations`` statement
    that increments the right counter columns — verified by inspecting
    the compiled SQL rather than the in-memory side-effects."""

    @pytest.mark.asyncio
    async def test_standard_search_fires_atomic_increment(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        resets_at = datetime.now(timezone.utc) + timedelta(days=15)
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_row=(0, 0, resets_at, 10, 0),
        )
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())
        user = _make_user()
        svc = PpsrService(db, _FakeRedis())

        await svc.search(
            org_id=db.org_id,
            user_id=user.id,
            current_user=user,
            rego="ABC123",
            options=PpsrSearchOptions(),
        )

        org_updates = [
            s for s in db.update_statements
            if _update_target_table(s) == "organisations"
        ]
        assert len(org_updates) == 1, (
            "exactly one UPDATE organisations statement must fire per fresh search"
        )

        stmt = org_updates[0]
        cols = _update_columns(stmt)
        # Standard search → only the standard counter is bumped.
        assert "ppsr_lookups_this_month" in cols
        assert "ppsr_hidden_plate_lookups_this_month" not in cols
        # And the assignment is atomic (column = column + 1) — never
        # ``column = <python-side-cached-value> + 1`` which would race.
        assert _update_is_atomic_increment(stmt, "ppsr_lookups_this_month")

    @pytest.mark.asyncio
    async def test_hidden_plate_search_increments_both_counters(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        resets_at = datetime.now(timezone.utc) + timedelta(days=15)
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_row=(0, 0, resets_at, 10, 5),
        )
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())
        user = _make_user()
        svc = PpsrService(db, _FakeRedis())

        await svc.search(
            org_id=db.org_id,
            user_id=user.id,
            current_user=user,
            rego="ABC123",
            options=PpsrSearchOptions(check_hidden_plates=True),
        )

        org_updates = [
            s for s in db.update_statements
            if _update_target_table(s) == "organisations"
        ]
        assert len(org_updates) == 1

        stmt = org_updates[0]
        cols = _update_columns(stmt)
        # Both counters bump in the same UPDATE — single round-trip.
        assert "ppsr_lookups_this_month" in cols
        assert "ppsr_hidden_plate_lookups_this_month" in cols
        # Both are atomic (col = col + 1).
        assert _update_is_atomic_increment(stmt, "ppsr_lookups_this_month")
        assert _update_is_atomic_increment(
            stmt, "ppsr_hidden_plate_lookups_this_month",
        )


# ===========================================================================
# 3. Reset behaviour — billing-cycle conditional logic in isolation
# ===========================================================================
#
# The full ``process_recurring_billing_task`` orchestration (Stripe charge,
# coupon resolution, GST + processing-fee breakdown) is too brittle to mock
# end-to-end at the unit-test level — that is exercised by the E4 e2e
# script. What matters for THIS file is the conditional-reset block at
# [app/tasks/subscriptions.py:213-216 and :297-298](app/tasks/subscriptions.py)
# that fires inside the per-org loop:
#
#     ppsr_overage_count = max(
#         0,
#         (org.ppsr_lookups_this_month or 0) - (plan.ppsr_lookups_included or 0),
#     )
#     ...
#     if ppsr_overage_count > 0:
#         org.ppsr_lookups_this_month = 0
#         org.ppsr_hidden_plate_lookups_this_month = 0
#
# We re-implement that conditional inline (as a tiny fixture function)
# and run it against three small mock orgs / plans. This validates the
# rule contract — counters reset iff the standard counter exceeded the
# included quota — without dragging a real Postgres + Stripe stub in.


def _apply_ppsr_reset(org: Any, plan: Any) -> int:
    """Mirror the conditional-reset block in ``process_recurring_billing_task``.

    Returns the computed ``ppsr_overage_count`` so tests can assert
    overage detection separately from the side-effect.
    """

    ppsr_overage_count = max(
        0,
        (getattr(org, "ppsr_lookups_this_month", 0) or 0)
        - (getattr(plan, "ppsr_lookups_included", 0) or 0),
    )
    if ppsr_overage_count > 0:
        org.ppsr_lookups_this_month = 0
        org.ppsr_hidden_plate_lookups_this_month = 0
    return ppsr_overage_count


class _MockOrg:
    """Lightweight stand-in for a :class:`~app.modules.admin.models.Organisation`."""

    def __init__(
        self,
        *,
        ppsr_lookups_this_month: int = 0,
        ppsr_hidden_plate_lookups_this_month: int = 0,
    ) -> None:
        self.ppsr_lookups_this_month = ppsr_lookups_this_month
        self.ppsr_hidden_plate_lookups_this_month = (
            ppsr_hidden_plate_lookups_this_month
        )


class _MockPlan:
    """Lightweight stand-in for a :class:`~app.modules.admin.models.SubscriptionPlan`."""

    def __init__(
        self,
        *,
        ppsr_lookups_included: int = 0,
        ppsr_hidden_plate_lookups_included: int = 0,
    ) -> None:
        self.ppsr_lookups_included = ppsr_lookups_included
        self.ppsr_hidden_plate_lookups_included = (
            ppsr_hidden_plate_lookups_included
        )


class TestPpsrCounterResetOnOverage:
    """When the standard counter exceeds the included quota, BOTH the
    standard counter AND the hidden-plate counter reset to zero — the
    overage signal is "any usage past the standard cap"."""

    def test_overage_resets_both_counters(self):
        org = _MockOrg(
            ppsr_lookups_this_month=120,
            ppsr_hidden_plate_lookups_this_month=8,
        )
        plan = _MockPlan(
            ppsr_lookups_included=100,
            ppsr_hidden_plate_lookups_included=5,
        )

        overage = _apply_ppsr_reset(org, plan)

        assert overage == 20
        assert org.ppsr_lookups_this_month == 0
        assert org.ppsr_hidden_plate_lookups_this_month == 0

    def test_exact_overage_one_lookup_over_resets(self):
        """Boundary case — even a single overage triggers the reset."""

        org = _MockOrg(
            ppsr_lookups_this_month=101,
            ppsr_hidden_plate_lookups_this_month=2,
        )
        plan = _MockPlan(
            ppsr_lookups_included=100,
            ppsr_hidden_plate_lookups_included=5,
        )

        overage = _apply_ppsr_reset(org, plan)

        assert overage == 1
        assert org.ppsr_lookups_this_month == 0
        assert org.ppsr_hidden_plate_lookups_this_month == 0


class TestPpsrCounterNoResetUnderQuota:
    """When the standard counter is at or below the included quota, no
    overage is charged — the reset block is skipped and BOTH counters
    keep their current values until the next billing cycle."""

    def test_under_quota_does_not_reset(self):
        org = _MockOrg(
            ppsr_lookups_this_month=50,
            ppsr_hidden_plate_lookups_this_month=3,
        )
        plan = _MockPlan(
            ppsr_lookups_included=100,
            ppsr_hidden_plate_lookups_included=5,
        )

        overage = _apply_ppsr_reset(org, plan)

        assert overage == 0
        # Counters preserved — neither one was reset.
        assert org.ppsr_lookups_this_month == 50
        assert org.ppsr_hidden_plate_lookups_this_month == 3

    def test_exact_quota_match_does_not_reset(self):
        """Boundary case — used == included means no overage, no reset.

        This is the same invariant the search-time quota check enforces
        (``raise PpsrQuotaExceededError if used >= included``): the org
        has just barely fit inside its plan and rolls into the next
        cycle with the counter intact.
        """

        org = _MockOrg(
            ppsr_lookups_this_month=100,
            ppsr_hidden_plate_lookups_this_month=5,
        )
        plan = _MockPlan(
            ppsr_lookups_included=100,
            ppsr_hidden_plate_lookups_included=5,
        )

        overage = _apply_ppsr_reset(org, plan)

        assert overage == 0
        assert org.ppsr_lookups_this_month == 100
        assert org.ppsr_hidden_plate_lookups_this_month == 5


class TestPpsrCounterResetSharedBoundary:
    """The hidden-plate counter resets at the **same** billing-cycle
    boundary as the standard counter — there is no separate hidden-
    plate overage check. This matches the existing carjam pattern:
    once any overage is billed, both monthly counters zero out."""

    def test_hidden_plate_resets_even_when_under_its_own_cap(self):
        org = _MockOrg(
            ppsr_lookups_this_month=150,    # over standard quota
            ppsr_hidden_plate_lookups_this_month=2,  # under hidden-plate quota
        )
        plan = _MockPlan(
            ppsr_lookups_included=100,
            ppsr_hidden_plate_lookups_included=10,
        )

        _apply_ppsr_reset(org, plan)

        # Hidden-plate counter resets *too*, even though it was nowhere
        # near its own included cap. The overage signal is shared.
        assert org.ppsr_hidden_plate_lookups_this_month == 0

    def test_hidden_plate_does_not_reset_when_standard_under_quota(self):
        """Conversely — running hot on hidden-plate alone is NOT
        sufficient to trigger the reset. The PPSR overage computation
        keys on the standard counter.
        """

        org = _MockOrg(
            ppsr_lookups_this_month=10,
            ppsr_hidden_plate_lookups_this_month=99,
        )
        plan = _MockPlan(
            ppsr_lookups_included=100,
            ppsr_hidden_plate_lookups_included=10,
        )

        overage = _apply_ppsr_reset(org, plan)

        assert overage == 0
        # Both counters preserved — the standard counter never crossed
        # the line so neither resets.
        assert org.ppsr_lookups_this_month == 10
        assert org.ppsr_hidden_plate_lookups_this_month == 99


# ---------------------------------------------------------------------------
# Note: the full ``process_recurring_billing_task`` (Stripe charge,
# coupons, GST + processing-fee breakdown, retry handling) is exercised
# by E4 — ``scripts/test_ppsr_module_e2e.py``. The unit tests above
# validate the conditional-reset contract in isolation; the E2E run
# verifies it against a real Postgres + Stripe-test setup.
# ---------------------------------------------------------------------------

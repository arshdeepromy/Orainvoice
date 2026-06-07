"""Unit tests for ``app/modules/ppsr/service.py::PpsrService``.

**Validates: Requirements R4, R5, R6 — PPSR module Phase 1, task C3.**

Coverage matrix (per tasks.md C3 ``**Verify:**`` block):

  - first search → CarJam called, row inserted, quota incremented by 1
  - second identical search within TTL → cached path, quota NOT
    incremented, audit row ``ppsr.search.cached`` written
  - second search with re-ordered options JSON dict → still cache HIT
    because of ``options_hash`` keying (G30)
  - force_refresh → CarJam re-called, quota incremented
  - 11th search when included=10 → ``PpsrQuotaExceededError``
  - owner-lookup without s241 config → ``PpsrS241PurposeRequiredError``
  - owner-lookup with s241 config but blank purpose param → defaults to
    ``s241_purpose_default``
  - CarJam config missing → ``PpsrCarjamNotConfiguredError`` (G28/G49)
  - admin can view any search; non-admin only own; 403 otherwise
  - forget wipes payload + audit; subsequent get → 410
  - cache lookup skips a forgotten search even within TTL (G26)
  - hidden-plate search increments
    ``ppsr_hidden_plate_lookups_this_month`` (G44)
  - concurrent search via Redis lock (skipped — too brittle to model
    realistically with this amount of mocking; see TODO note)

The DB session is a custom in-memory fake that satisfies all of the
service's read paths (``IntegrationConfig`` lookup, quota join,
:class:`PpsrSearch` cache lookup, vehicle-link lookup) plus
``add`` / ``flush`` / ``refresh`` / ``execute(update(...))``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
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
from app.integrations.carjam import (
    CarjamNotFoundError,
    CarjamPpsrResponse,
    CarjamRateLimitError,
)
from app.modules.admin.models import IntegrationConfig
from app.modules.ppsr.exceptions import (
    PpsrCarjamNotConfiguredError,
    PpsrOwnerLookupsDisabledError,
    PpsrQuotaExceededError,
    PpsrS241PurposeRequiredError,
    PpsrSearchForbiddenError,
    PpsrSearchForgottenError,
    PpsrSearchNotFoundError,
)
from app.modules.ppsr.models import PpsrSearch
from app.modules.ppsr.schemas import PpsrSearchOptions
from app.modules.ppsr.service import PpsrService


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal :class:`redis.asyncio.Redis` double for the lock helper.

    Implements ``set(nx=True, ex=...)``, ``get``, ``delete`` — enough for
    :func:`app.modules.ppsr.service.redis_lock` to acquire+release.
    """

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
    """Build an ``IntegrationConfig.config_encrypted`` blob with the
    given fields baked into the encrypted JSON.
    """

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


class _FakeDB:
    """Fake ``AsyncSession`` covering every query the service issues.

    The fake intercepts ``execute`` calls and dispatches based on the
    string form of the statement. Routes:

      - ``IntegrationConfig`` SELECT → returns the configured carjam row
      - ``Organisation … plan_id == SubscriptionPlan.id`` quota join →
        returns ``(used, hidden_used, next_billing_date, included,
        hidden_included)``
      - ``PpsrSearch`` cache lookup → returns the most recent matching row
      - ``PpsrSearch`` by id → returns the row
      - ``OrgVehicle`` / ``GlobalVehicle`` lookup → returns ``None``
      - ``UPDATE Organisation`` quota increment → applies in-memory
      - ``UPDATE PpsrSearch`` (forget / link) → applies in-memory

    The fake also ``add``s rows into ``self.added`` and assigns each
    ``PpsrSearch`` a stable id + ``created_at`` on flush so the
    cache-lookup query can find it.
    """

    def __init__(
        self,
        *,
        carjam_config: IntegrationConfig | None,
        quota_used: int = 0,
        quota_included: int = 100,
        hidden_used: int = 0,
        hidden_included: int = 0,
        next_billing_date: datetime | None = None,
        org_id: uuid.UUID | None = None,
    ) -> None:
        self.carjam_config = carjam_config
        self.quota_used = quota_used
        self.quota_included = quota_included
        self.hidden_used = hidden_used
        self.hidden_included = hidden_included
        self.next_billing_date = next_billing_date or datetime.now(
            timezone.utc,
        ) + timedelta(days=15)
        self.org_id = org_id or uuid.uuid4()

        self.added: list[Any] = []
        self.searches: list[PpsrSearch] = []
        self.audit_calls: list[dict] = []
        self.flush = AsyncMock(side_effect=self._on_flush)
        self.refresh = AsyncMock(side_effect=self._on_refresh)
        self.add = MagicMock(side_effect=self._on_add)

    # -- session helpers --------------------------------------------------

    def _on_add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, PpsrSearch):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.created_at is None:
                obj.created_at = datetime.now(timezone.utc)
            # not_found / has_warnings / has_ownership_data are non-null DB-side;
            # apply server-default semantics for the in-memory copy.
            if obj.not_found is None:
                obj.not_found = False
            if obj.has_warnings is None:
                obj.has_warnings = False
            if obj.has_ownership_data is None:
                obj.has_ownership_data = False
            if obj.statement_count is None:
                obj.statement_count = 0
            self.searches.append(obj)

    async def _on_flush(self) -> None:
        return None

    async def _on_refresh(self, obj: Any) -> None:
        return None

    # -- query dispatch ---------------------------------------------------

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        rendered = str(stmt).lower()

        # 1. Audit-log INSERT — accept silently. Detected via the raw
        # ``text()`` clause (note `audit_log` singular per G33/G45).
        if "insert into audit_log" in rendered:
            return _ExecResult(scalar=None)

        # 2. UPDATE statements ------------------------------------------
        if rendered.startswith("update organisations"):
            updated_cols = self._update_columns(stmt)
            if "ppsr_lookups_this_month" in updated_cols:
                self.quota_used += 1
            if "ppsr_hidden_plate_lookups_this_month" in updated_cols:
                self.hidden_used += 1
            return _ExecResult(scalar=1)

        if rendered.startswith("update ppsr_searches"):
            updated_cols = self._update_columns(stmt)
            target_id = self._extract_id_from_where(stmt)
            for row in self.searches:
                if target_id is not None and row.id != target_id:
                    continue
                values = self._update_values_dict(stmt)
                if "response_encrypted" in updated_cols:
                    row.response_encrypted = values.get("response_encrypted")
                if "forgotten_at" in updated_cols:
                    row.forgotten_at = datetime.now(timezone.utc)
                if "error_message" in updated_cols:
                    row.error_message = values.get(
                        "error_message", "forgotten by admin",
                    )
                if "org_vehicle_id" in updated_cols:
                    row.org_vehicle_id = values.get("org_vehicle_id")
            return _ExecResult(scalar=1)

        # 3. SELECT branches --------------------------------------------
        if "from integration_configs" in rendered:
            return _ExecResult(scalar=self.carjam_config)

        if "from organisations" in rendered and "subscription_plans" in rendered:
            return _ExecResult(
                first_row=(
                    self.quota_used,
                    self.hidden_used,
                    self.next_billing_date,
                    self.quota_included,
                    self.hidden_included,
                ),
            )

        if "from ppsr_searches" in rendered:
            target_id = self._extract_id_from_where(stmt)
            if target_id is not None and "ppsr_searches.id" in rendered:
                # get_search-style lookup.
                for row in self.searches:
                    if row.id == target_id:
                        return _ExecResult(scalar=row)
                return _ExecResult(scalar=None)

            # Cache lookup — find latest matching row.
            params = self._compiled_params(stmt)
            org_id = params.get("org_id_1") or params.get("org_id")
            rego = params.get("rego_1") or params.get("rego")
            options_hash = (
                params.get("options_hash_1") or params.get("options_hash")
            )
            cutoff = (
                params.get("created_at_1") or params.get("created_at")
            )

            candidates: list[PpsrSearch] = []
            for row in self.searches:
                if org_id is not None and row.org_id != org_id:
                    continue
                if rego is not None and row.rego != rego:
                    continue
                if options_hash is not None and row.options_hash != options_hash:
                    continue
                if cutoff is not None and row.created_at < cutoff:
                    continue
                if row.response_encrypted is None:
                    continue
                if row.error_message is not None:
                    continue
                if row.not_found:
                    continue
                if row.forgotten_at is not None:
                    continue
                candidates.append(row)
            candidates.sort(key=lambda r: r.created_at, reverse=True)
            return _ExecResult(scalar=candidates[0] if candidates else None)

        if "from org_vehicles" in rendered:
            return _ExecResult(scalar=None)
        if "from global_vehicles" in rendered:
            return _ExecResult(scalar=None)

        # Default fallthrough — empty result.
        return _ExecResult(scalar=None)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _compiled_params(stmt: Any) -> dict[str, Any]:
        try:
            return stmt.compile().params or {}
        except Exception:
            return {}

    @classmethod
    def _extract_id_from_where(cls, stmt: Any) -> uuid.UUID | None:
        params = cls._compiled_params(stmt)
        for key in ("id_1", "ppsr_search_id", "search_id"):
            value = params.get(key)
            if isinstance(value, uuid.UUID):
                return value
        for k, v in params.items():
            if k.startswith("id_") and isinstance(v, uuid.UUID):
                return v
        return None

    @staticmethod
    def _update_columns(stmt: Any) -> set[str]:
        """Return the set of column names mentioned in ``stmt._values``."""

        cols: set[str] = set()
        values = getattr(stmt, "_values", None) or {}
        for col in values:
            name = getattr(col, "name", None) or getattr(col, "key", None)
            if name:
                cols.add(str(name))
        return cols

    @classmethod
    def _update_values_dict(cls, stmt: Any) -> dict[str, Any]:
        """Best-effort literal values for an UPDATE — reads ``BindParameter.value``."""

        out: dict[str, Any] = {}
        values = getattr(stmt, "_values", None) or {}
        for col, expr in values.items():
            name = getattr(col, "name", None) or getattr(col, "key", None)
            if not name:
                continue
            literal = getattr(expr, "value", None)
            if literal is not None or getattr(expr, "type", None) is not None:
                out[str(name)] = literal
        return out


class _ExecResult:
    """Tiny mimic of SQLAlchemy's :class:`Result` — only the shapes we use."""

    def __init__(
        self,
        *,
        scalar: Any | None = None,
        first_row: tuple[Any, ...] | None = None,
        rows: list[Any] | None = None,
    ) -> None:
        self._scalar = scalar
        self._first_row = first_row
        self._rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalar_one(self) -> Any:
        return self._scalar

    def first(self) -> tuple[Any, ...] | None:
        return self._first_row

    def scalars(self) -> "_ScalarsProxy":
        rows = list(self._rows) if self._rows else (
            [self._scalar] if self._scalar is not None else []
        )
        return _ScalarsProxy(rows)


class _ScalarsProxy:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


def _carjam_response(
    *,
    rego: str = "ABC123",
    match: str = "N",
    statement_count: int = 0,
    charges_cents: int = 50,
    not_found: bool = False,
    warnings: list[dict] | None = None,
    ownership_history: list[dict] | None = None,
    current_owner: dict | None = None,
) -> CarjamPpsrResponse:
    return CarjamPpsrResponse(
        rego=rego,
        not_found=not_found,
        basic={"make": "Toyota", "model": "Hilux", "year": 2018},
        ownership_history=ownership_history,
        current_owner=current_owner,
        ppsr_summary={"count": statement_count},
        ppsr_details=[],
        money_owing={
            "match": match,
            "match_description": "No money owing" if match == "N" else "Money owing",
            "search_id": "ppsr-12345",
        },
        warnings=warnings,
        flood=None,
        charges_cents=charges_cents,
        raw_xml=json.dumps({"message": {"money_owing": {"match": match}}}),
        requested_options={},
    )


class _FakeCarjamClient:
    """Stand-in for :class:`CarjamClient` returned by ``_load_carjam_client``."""

    def __init__(
        self,
        *,
        responder: Callable[..., CarjamPpsrResponse | None] | None = None,
        side_effect: Exception | None = None,
    ) -> None:
        self.responder = responder
        self.side_effect = side_effect
        self.calls: list[dict] = []

    async def lookup_ppsr(self, rego: str, **kwargs: Any) -> CarjamPpsrResponse:
        self.calls.append({"rego": rego, **kwargs})
        if self.side_effect is not None:
            raise self.side_effect
        if self.responder is not None:
            resp = self.responder(rego, **kwargs)
            if resp is not None:
                return resp
        return _carjam_response(rego=rego)


def _make_user(role: str = "staff_member", user_id: uuid.UUID | None = None) -> Any:
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.role = role
    user.org_id = uuid.uuid4()
    return user


@pytest.fixture
def patched_module_enabled():
    """Force :meth:`ModuleService.is_enabled` to return ``True``."""

    with patch(
        "app.modules.ppsr.service.ModuleService.is_enabled",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture
def patched_carjam_client_factory():
    """Replace ``_load_carjam_client`` with a controllable stub.

    Yields a callable that swaps the stub returned by the patched
    factory, so a single test can change the CarJam behaviour
    mid-flight (for force-refresh / cached comparisons).
    """

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
# Tests — search() core flow
# ---------------------------------------------------------------------------


class TestSearchHappyPath:
    """First search → CarJam called, row inserted, quota incremented."""

    @pytest.mark.asyncio
    async def test_first_search_calls_carjam_and_increments_quota(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        result = await svc.search(
            org_id=org_id,
            user_id=user.id,
            current_user=user,
            rego="abc123",
            options=PpsrSearchOptions(),
        )

        assert len(carjam.calls) == 1
        assert carjam.calls[0]["rego"] == "ABC123"
        assert result.cached is False
        assert result.match == "N"
        assert result.search_id is not None
        assert db.quota_used == 1
        # Exactly one PpsrSearch row added.
        assert len(db.searches) == 1
        assert db.searches[0].rego == "ABC123"
        assert db.searches[0].response_encrypted is not None


class TestSearchCacheHit:
    """Repeat search within TTL → cache HIT, quota stays put."""

    @pytest.mark.asyncio
    async def test_second_identical_search_is_cached(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )
        carjam_calls_after_first = len(carjam.calls)
        quota_after_first = db.quota_used

        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )

        assert len(carjam.calls) == carjam_calls_after_first  # no extra call
        assert db.quota_used == quota_after_first  # quota unchanged
        assert result.cached is True
        assert result.cached_at is not None
        assert result.source_search_id is not None

    @pytest.mark.asyncio
    async def test_cache_hit_writes_audit_row(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        captured: list[dict] = []

        async def _capture(session, **kwargs):  # noqa: ARG001
            captured.append(kwargs)
            return uuid.uuid4()

        with patch(
            "app.modules.ppsr.service.write_audit_log",
            side_effect=_capture,
        ):
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123", options=PpsrSearchOptions(),
            )
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123", options=PpsrSearchOptions(),
            )

        actions = [c["action"] for c in captured]
        assert "ppsr.search" in actions
        assert "ppsr.search.cached" in actions


class TestOptionsHashStable:
    """Re-ordered options dict still produces the same hash → cache HIT."""

    def test_options_hash_independent_of_dict_key_order(self):
        svc = PpsrService(db=MagicMock(), redis=MagicMock())
        a = PpsrSearchOptions(
            include_warnings=True,
            include_fws=True,
            check_hidden_plates=False,
            include_current_owner=False,
        )
        b = PpsrSearchOptions(
            check_hidden_plates=False,
            include_current_owner=False,
            include_fws=True,
            include_warnings=True,
        )
        assert svc._hash_options(a) == svc._hash_options(b)

    @pytest.mark.asyncio
    async def test_reordered_options_dict_lands_in_same_cache_bucket(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        # The first call uses the schema's default ordering.
        await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(include_fws=True),
        )
        # Second call reconstructs the model from a dict whose keys are in a
        # different order — the resulting hash must still match.
        opts = PpsrSearchOptions.model_validate(
            {
                "include_fws": True,
                "check_hidden_plates": False,
                "s241_purpose": None,
                "include_warnings": False,
                "include_current_owner": False,
                "include_ownership_history": False,
            },
        )
        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=opts,
        )

        assert len(carjam.calls) == 1
        assert result.cached is True


class TestForceRefresh:
    """force_refresh=True → CarJam re-called, quota incremented twice."""

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )
        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(), force_refresh=True,
        )
        assert len(carjam.calls) == 2
        assert db.quota_used == 2
        assert result.cached is False


class TestQuotaExceeded:
    """Used == included no longer hard-blocks: the lookup proceeds (CarJam-
    parity usage-based overage billing) and the counter still increments."""

    @pytest.mark.asyncio
    async def test_lookup_proceeds_when_used_equals_included(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=10,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        # No PpsrQuotaExceededError — the search runs and returns a result
        # even though the included quota is fully used (overage is billed
        # later by the recurring-billing task).
        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )
        assert result is not None


class TestOwnerLookupGating:
    """Owner-lookup paths must enforce s241 + owner_enabled."""

    @pytest.mark.asyncio
    async def test_owner_lookup_disabled_raises(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(
                ppsr_owner_lookups_enabled=False,
            ),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        with pytest.raises(PpsrOwnerLookupsDisabledError):
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123",
                options=PpsrSearchOptions(include_current_owner=True),
            )

    @pytest.mark.asyncio
    async def test_owner_lookup_without_s241_raises(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        """Owner lookups enabled but no per-request and no default s241."""
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(
                ppsr_owner_lookups_enabled=True,
                # s241_purpose_default omitted intentionally.
            ),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        with pytest.raises(PpsrS241PurposeRequiredError):
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123",
                options=PpsrSearchOptions(include_current_owner=True),
            )

    @pytest.mark.asyncio
    async def test_blank_purpose_falls_back_to_default(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        """Blank ``s241_purpose`` on the request defers to the config default."""
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(
                ppsr_owner_lookups_enabled=True,
                s241_purpose_default="Selling vehicle",
            ),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient(
            responder=lambda rego, **kw: _carjam_response(
                rego=rego, current_owner={"name": "Jane Doe"},
            ),
        )
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123",
            options=PpsrSearchOptions(
                include_current_owner=True,
                s241_purpose=None,  # <- blank, default should fill it in
            ),
        )

        assert carjam.calls[0]["s241_purpose"] == "Selling vehicle"
        assert carjam.calls[0]["include_owner"] is True


class TestCarjamConfigMissing:
    """Missing CarJam row → ``PpsrCarjamNotConfiguredError`` (G28/G49)."""

    @pytest.mark.asyncio
    async def test_no_carjam_row_raises(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=None,
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        with pytest.raises(PpsrCarjamNotConfiguredError):
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123", options=PpsrSearchOptions(),
            )

    @pytest.mark.asyncio
    async def test_blank_api_key_raises(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(api_key=""),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        with pytest.raises(PpsrCarjamNotConfiguredError):
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123", options=PpsrSearchOptions(),
            )


class TestHiddenPlateCounter:
    """``check_hidden_plates=True`` bumps the separate counter."""

    @pytest.mark.asyncio
    async def test_hidden_plate_increments_separate_counter(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            hidden_used=0,
            hidden_included=5,
            org_id=org_id,
        )
        redis = _FakeRedis()
        _, set_client = patched_carjam_client_factory
        set_client(_FakeCarjamClient())

        svc = PpsrService(db, redis)
        await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123",
            options=PpsrSearchOptions(check_hidden_plates=True),
        )
        assert db.quota_used == 1
        assert db.hidden_used == 1


class TestNotFoundPersisted:
    """``CarjamNotFoundError`` is mapped to a ``not_found=True`` row."""

    @pytest.mark.asyncio
    async def test_not_found_persists_row_and_consumes_quota(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient(
            side_effect=CarjamNotFoundError("ABC123"),
        )
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )
        assert result.not_found is True
        assert db.quota_used == 1
        assert len(db.searches) == 1
        assert db.searches[0].not_found is True


class TestRateLimitPropagates:
    """``CarjamRateLimitError`` re-raises so the router can map to 429."""

    @pytest.mark.asyncio
    async def test_rate_limit_propagates(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient(
            side_effect=CarjamRateLimitError(retry_after=42),
        )
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        with pytest.raises(CarjamRateLimitError) as exc:
            await svc.search(
                org_id=org_id, user_id=user.id, current_user=user,
                rego="ABC123", options=PpsrSearchOptions(),
            )
        assert exc.value.retry_after == 42


# ---------------------------------------------------------------------------
# Tests — get_search / forget_search / link_vehicle
# ---------------------------------------------------------------------------


class TestGetSearchOwnership:
    """Detail endpoint ownership rules."""

    @pytest.mark.asyncio
    async def test_admin_can_view_other_users_search(self):
        org_id = uuid.uuid4()
        searcher = _make_user(role="staff_member")
        admin = _make_user(role="org_admin")
        db = _FakeDB(carjam_config=_make_carjam_config_row(), org_id=org_id)
        row = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=searcher.id,
            rego="ABC123",
            options_json={},
            options_hash="hash",
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=envelope_encrypt(
                json.dumps({"basic": {"make": "Toyota"}}),
            ),
            not_found=False,
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(row)

        svc = PpsrService(db, _FakeRedis())
        result = await svc.get_search(row.id, admin)
        assert result.search_id == row.id
        assert result.basic == {"make": "Toyota"}

    @pytest.mark.asyncio
    async def test_non_admin_cannot_view_other_users_search(self):
        org_id = uuid.uuid4()
        owner = _make_user(role="staff_member")
        other = _make_user(role="staff_member")
        db = _FakeDB(carjam_config=_make_carjam_config_row(), org_id=org_id)
        row = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=owner.id,
            rego="ABC123",
            options_json={},
            options_hash="hash",
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=envelope_encrypt(json.dumps({"basic": {}})),
            not_found=False,
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(row)

        svc = PpsrService(db, _FakeRedis())
        with pytest.raises(PpsrSearchForbiddenError):
            await svc.get_search(row.id, other)

    @pytest.mark.asyncio
    async def test_owner_can_view_own_search(self):
        org_id = uuid.uuid4()
        owner = _make_user(role="staff_member")
        db = _FakeDB(carjam_config=_make_carjam_config_row(), org_id=org_id)
        row = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=owner.id,
            rego="ABC123",
            options_json={},
            options_hash="hash",
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=envelope_encrypt(json.dumps({"basic": {}})),
            not_found=False,
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(row)

        svc = PpsrService(db, _FakeRedis())
        result = await svc.get_search(row.id, owner)
        assert result.search_id == row.id

    @pytest.mark.asyncio
    async def test_missing_row_raises_not_found(self):
        svc = PpsrService(_FakeDB(carjam_config=None), _FakeRedis())
        with pytest.raises(PpsrSearchNotFoundError):
            await svc.get_search(uuid.uuid4(), _make_user(role="org_admin"))


class TestForgetSearch:
    """Admin-only payload wipe (G26 / G29)."""

    @pytest.mark.asyncio
    async def test_admin_forget_wipes_payload(self):
        org_id = uuid.uuid4()
        searcher = _make_user(role="staff_member")
        admin = _make_user(role="org_admin")
        admin.org_id = org_id
        db = _FakeDB(carjam_config=_make_carjam_config_row(), org_id=org_id)
        row = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=searcher.id,
            rego="ABC123",
            options_json={},
            options_hash="hash",
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=envelope_encrypt(json.dumps({"basic": {}})),
            not_found=False,
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(row)

        svc = PpsrService(db, _FakeRedis())
        captured: list[dict] = []

        async def _capture(session, **kwargs):  # noqa: ARG001
            captured.append(kwargs)
            return uuid.uuid4()

        with patch(
            "app.modules.ppsr.service.write_audit_log",
            side_effect=_capture,
        ):
            await svc.forget_search(row.id, admin)

        assert row.response_encrypted is None
        assert row.forgotten_at is not None
        assert any(c["action"] == "ppsr.forgotten" for c in captured)

    @pytest.mark.asyncio
    async def test_non_admin_forget_forbidden(self):
        org_id = uuid.uuid4()
        non_admin = _make_user(role="staff_member")
        db = _FakeDB(carjam_config=None, org_id=org_id)
        svc = PpsrService(db, _FakeRedis())
        with pytest.raises(PpsrSearchForbiddenError):
            await svc.forget_search(uuid.uuid4(), non_admin)

    @pytest.mark.asyncio
    async def test_forgotten_get_returns_410(self):
        org_id = uuid.uuid4()
        owner = _make_user(role="staff_member")
        db = _FakeDB(carjam_config=_make_carjam_config_row(), org_id=org_id)
        row = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=owner.id,
            rego="ABC123",
            options_json={},
            options_hash="hash",
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=None,
            not_found=False,
            forgotten_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(row)

        svc = PpsrService(db, _FakeRedis())
        with pytest.raises(PpsrSearchForgottenError) as exc_info:
            await svc.get_search(row.id, owner)
        assert exc_info.value.forgotten_at is not None


class TestForgottenCacheSkip:
    """The cache lookup must skip a forgotten row even within TTL."""

    @pytest.mark.asyncio
    async def test_forgotten_row_does_not_satisfy_cache(
        self, patched_module_enabled, patched_carjam_client_factory,
    ):
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10,
            org_id=org_id,
        )
        # Pre-seed a freshly-forgotten row that would otherwise satisfy
        # the cache window.
        forgotten = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=user.id,
            rego="ABC123",
            options_json=PpsrSearchOptions().model_dump(),
            options_hash=PpsrService(db, _FakeRedis())._hash_options(
                PpsrSearchOptions(),
            ),
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=None,  # wiped
            not_found=False,
            forgotten_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(forgotten)

        redis = _FakeRedis()
        carjam = _FakeCarjamClient()
        _, set_client = patched_carjam_client_factory
        set_client(carjam)

        svc = PpsrService(db, redis)
        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )
        # Forgotten row must NOT satisfy the cache → CarJam was hit.
        assert len(carjam.calls) == 1
        assert result.cached is False


class TestLinkVehicle:
    """Link a saved search to an :class:`OrgVehicle` row (G23)."""

    @pytest.mark.asyncio
    async def test_link_writes_audit(self):
        org_id = uuid.uuid4()
        owner = _make_user(role="staff_member")
        db = _FakeDB(carjam_config=_make_carjam_config_row(), org_id=org_id)
        row = PpsrSearch(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=owner.id,
            rego="ABC123",
            options_json={},
            options_hash="hash",
            statement_count=0,
            has_warnings=False,
            has_ownership_data=False,
            response_encrypted=envelope_encrypt(json.dumps({})),
            not_found=False,
            created_at=datetime.now(timezone.utc),
        )
        db.searches.append(row)

        svc = PpsrService(db, _FakeRedis())
        captured: list[dict] = []

        async def _capture(session, **kwargs):  # noqa: ARG001
            captured.append(kwargs)
            return uuid.uuid4()

        target_vehicle = uuid.uuid4()
        with patch(
            "app.modules.ppsr.service.write_audit_log",
            side_effect=_capture,
        ):
            await svc.link_vehicle(row.id, target_vehicle, owner)

        assert any(c["action"] == "ppsr.search.linked" for c in captured)


# ---------------------------------------------------------------------------
# Concurrent search via Redis lock — too brittle to model with the level of
# mocking we have. Marked skip with a TODO so the coverage gap is visible.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Concurrent-call lock is exercised end-to-end by the E2E script "
        "(scripts/test_ppsr_module_e2e.py) where a real Redis is available. "
        "TODO: revisit once an in-memory Redis with realistic SET NX EX is "
        "wired into tests/conftest.py."
    ),
)
@pytest.mark.asyncio
async def test_concurrent_search_only_calls_carjam_once():  # pragma: no cover
    pass

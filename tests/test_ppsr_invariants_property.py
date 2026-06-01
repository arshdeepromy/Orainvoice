"""Hypothesis property tests for the PPSR module.

**Validates: Requirements R4, R5, R6 — PPSR module Phase 1, task E3.**

Three correctness properties from ``.kiro/specs/ppsr-module/tasks.md`` E3:

1. **Quota-call equivalence (R5):** For any sequence of (search, cache-hit,
   force-refresh) events, ``quota_used == count_of_carjam_calls``. Cache
   hits never increment the quota.
2. **Forget-then-fetch (R6 / G29):** For any forget-then-fetch sequence,
   the detail endpoint raises ``PpsrSearchForgottenError`` (mapped to
   HTTP 410 by the router).
3. **Options-hash stability (R5 / G30):** For any reordered options dict,
   ``_hash_options`` returns the same digest, so cache hits land on the
   same row.

The state-based properties (1 & 2) reuse the in-memory ``_FakeDB`` /
``_FakeRedis`` doubles from :mod:`tests.unit.test_ppsr_service` rather
than duplicating ~300 lines of mock plumbing. Property 3 is a pure
function exercise of :meth:`PpsrService._hash_options`.

Hypothesis settings: ``max_examples=50, deadline=None`` per the spec
guidance — async DB ops through the fakes are slow enough that the
default deadline trips.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.encryption import envelope_encrypt
from app.modules.ppsr.exceptions import PpsrSearchForgottenError
from app.modules.ppsr.models import PpsrSearch
from app.modules.ppsr.schemas import PpsrSearchOptions
from app.modules.ppsr.service import PpsrService
from tests.unit.test_ppsr_service import (
    _FakeCarjamClient,
    _FakeDB,
    _FakeRedis,
    _make_carjam_config_row,
    _make_user,
)


# ---------------------------------------------------------------------------
# Hypothesis settings — the in-memory fakes still issue real SQL compile()
# calls, so each example takes a few milliseconds. 50 examples keeps total
# runtime CI-friendly while still exploring a meaningful slice of the space.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A short rego pool. Property 1 needs cache hits to land on the same row,
# so the strategy must reuse plates — a pool of 3 plates gives a healthy
# mix of repeats and misses across a sequence of 10 events.
_REGO_POOL: list[str] = ["ABC123", "XYZ789", "DEF456"]

# Each event is a single search call. ``force`` toggles ``force_refresh``,
# which is the second axis the property has to span.
event_strategy = st.fixed_dictionaries(
    {
        "rego": st.sampled_from(_REGO_POOL),
        "force": st.booleans(),
    },
)

event_sequence_strategy = st.lists(
    event_strategy, min_size=1, max_size=10,
)

# All six PpsrSearchOptions fields are independently toggle-able. We hold
# ``include_current_owner`` / ``include_ownership_history`` to ``False``
# so the test never trips the s241 / owner-lookup gates (those have their
# own dedicated unit tests). The hash-stability property is unaffected by
# those flags' values — only that *some* combination round-trips through
# canonical JSON.
options_payload_strategy = st.fixed_dictionaries(
    {
        "include_warnings": st.booleans(),
        "include_fws": st.booleans(),
        "check_hidden_plates": st.booleans(),
        "include_current_owner": st.just(False),
        "include_ownership_history": st.just(False),
        "s241_purpose": st.none(),
    },
)


# ---------------------------------------------------------------------------
# Patch helpers — the unit-test fixtures aren't shareable across files,
# so wrap the same patches in plain context managers.
# ---------------------------------------------------------------------------


class _PatchedEnv:
    """Patches ``ModuleService.is_enabled`` + ``_load_carjam_client``.

    The carjam client returned by the patched factory is the
    :class:`_FakeCarjamClient` instance passed in, so each test can
    inspect ``calls`` directly.
    """

    def __init__(self, carjam: _FakeCarjamClient) -> None:
        self.carjam = carjam
        self._patches: list[Any] = []

    def __enter__(self) -> "_PatchedEnv":
        async def _factory(_db: Any, _redis: Any) -> _FakeCarjamClient:
            return self.carjam

        self._patches.append(
            patch(
                "app.modules.ppsr.service.ModuleService.is_enabled",
                new=AsyncMock(return_value=True),
            ),
        )
        self._patches.append(
            patch(
                "app.modules.ppsr.service._load_carjam_client",
                new=_factory,
            ),
        )
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._patches.clear()


# ===========================================================================
# Property 1: Quota-call equivalence
# Feature: ppsr-module, Property 1: Quota-call equivalence
# ===========================================================================


class TestProperty1QuotaCallEquivalence:
    """Feature: ppsr-module, Property 1: Quota-call equivalence

    For any sequence of search events on the same set of regos, the
    final quota counter SHALL equal the number of CarJam HTTP calls.
    Cache hits MUST NOT increment the quota; force-refresh MUST always
    consume a quota unit.

    **Validates: Requirements R5 (quota), R5/G30 (cache).**
    """

    @PBT_SETTINGS
    @given(events=event_sequence_strategy)
    @pytest.mark.asyncio
    async def test_quota_used_equals_carjam_call_count(
        self, events: list[dict[str, Any]],
    ) -> None:
        """``db.quota_used == len(carjam.calls)`` after any event sequence.

        **Validates: Requirements R5 (G30).**
        """
        org_id = uuid.uuid4()
        user = _make_user()
        # Big enough quota to never trip the gate; the property here is
        # the equivalence relation, not the cap.
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10_000,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()

        with _PatchedEnv(carjam):
            svc = PpsrService(db, redis)
            for event in events:
                await svc.search(
                    org_id=org_id,
                    user_id=user.id,
                    current_user=user,
                    rego=event["rego"],
                    options=PpsrSearchOptions(),
                    force_refresh=event["force"],
                )

        # Core invariant — quota counter is incremented exactly when CarJam
        # was called.
        assert db.quota_used == len(carjam.calls), (
            f"quota_used={db.quota_used} but carjam.calls={len(carjam.calls)} "
            f"for events={events}"
        )

    @PBT_SETTINGS
    @given(
        first_event=event_strategy,
        repeats=st.integers(min_value=1, max_value=5),
    )
    @pytest.mark.asyncio
    async def test_repeated_search_without_force_refresh_is_one_carjam_call(
        self, first_event: dict[str, Any], repeats: int,
    ) -> None:
        """N identical searches (no force) → exactly one CarJam call.

        **Validates: Requirements R5 (cache hit doesn't bill).**
        """
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10_000,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()

        with _PatchedEnv(carjam):
            svc = PpsrService(db, redis)
            for _ in range(repeats):
                await svc.search(
                    org_id=org_id,
                    user_id=user.id,
                    current_user=user,
                    rego=first_event["rego"],
                    options=PpsrSearchOptions(),
                    force_refresh=False,
                )

        assert len(carjam.calls) == 1, (
            f"expected exactly 1 CarJam call after {repeats} cache-hit "
            f"searches, got {len(carjam.calls)}"
        )
        assert db.quota_used == 1


# ===========================================================================
# Property 2: Forget-then-fetch returns 410
# Feature: ppsr-module, Property 2: Forget-then-fetch returns 410
# ===========================================================================


class TestProperty2ForgetThenFetch:
    """Feature: ppsr-module, Property 2: Forget-then-fetch returns 410

    For any sequence (search → forget → get_search), the final
    ``get_search`` call SHALL raise :class:`PpsrSearchForgottenError`
    so the router maps to HTTP 410.

    **Validates: Requirements R6 (G29).**
    """

    @PBT_SETTINGS
    @given(rego=st.sampled_from(_REGO_POOL))
    @pytest.mark.asyncio
    async def test_get_search_after_forget_raises_410(self, rego: str) -> None:
        """search → forget → get_search must raise PpsrSearchForgottenError.

        **Validates: Requirements R6 (G29).**
        """
        org_id = uuid.uuid4()
        searcher = _make_user(role="staff_member")
        admin = _make_user(role="org_admin")
        admin.org_id = org_id

        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10_000,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()

        # Patch write_audit_log so the audit calls during forget don't
        # need the real audit_log table.
        async def _noop_audit(session, **kwargs):  # noqa: ARG001
            return uuid.uuid4()

        with _PatchedEnv(carjam), patch(
            "app.modules.ppsr.service.write_audit_log",
            side_effect=_noop_audit,
        ):
            svc = PpsrService(db, redis)
            result = await svc.search(
                org_id=org_id,
                user_id=searcher.id,
                current_user=searcher,
                rego=rego,
                options=PpsrSearchOptions(),
            )
            search_id = result.search_id
            assert search_id is not None

            await svc.forget_search(search_id, admin)

            with pytest.raises(PpsrSearchForgottenError) as exc_info:
                await svc.get_search(search_id, admin)

        assert exc_info.value.forgotten_at is not None

    @PBT_SETTINGS
    @given(rego=st.sampled_from(_REGO_POOL))
    @pytest.mark.asyncio
    async def test_get_search_after_forget_raises_410_for_searcher(
        self, rego: str,
    ) -> None:
        """A non-admin original searcher also gets 410 (not 200) post-forget.

        Confirms the 410 path is independent of caller role — the gate is
        the ``forgotten_at`` column, not the ownership check.

        **Validates: Requirements R6 (G29).**
        """
        org_id = uuid.uuid4()
        searcher = _make_user(role="staff_member")
        admin = _make_user(role="org_admin")
        admin.org_id = org_id

        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10_000,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()

        async def _noop_audit(session, **kwargs):  # noqa: ARG001
            return uuid.uuid4()

        with _PatchedEnv(carjam), patch(
            "app.modules.ppsr.service.write_audit_log",
            side_effect=_noop_audit,
        ):
            svc = PpsrService(db, redis)
            result = await svc.search(
                org_id=org_id,
                user_id=searcher.id,
                current_user=searcher,
                rego=rego,
                options=PpsrSearchOptions(),
            )
            search_id = result.search_id
            assert search_id is not None

            await svc.forget_search(search_id, admin)

            with pytest.raises(PpsrSearchForgottenError):
                # The original searcher (non-admin) also hits the 410 gate.
                await svc.get_search(search_id, searcher)


# ===========================================================================
# Property 3: Options-hash stability under key reordering
# Feature: ppsr-module, Property 3: Options-hash stability
# ===========================================================================


class TestProperty3OptionsHashStability:
    """Feature: ppsr-module, Property 3: Options-hash stability

    For any options payload, ``_hash_options`` is invariant under dict
    key reordering — canonical JSON (``sort_keys=True``) ensures the
    cache lookup lands on the same row regardless of front-end JSON
    ordering.

    **Validates: Requirements R5 (G30).**
    """

    @PBT_SETTINGS
    @given(payload=options_payload_strategy)
    def test_hash_invariant_under_key_reordering(
        self, payload: dict[str, Any],
    ) -> None:
        """``_hash_options(a) == _hash_options(b)`` when a and b have the
        same key/value pairs in any order.

        **Validates: Requirements R5 (G30).**
        """
        svc = PpsrService(db=MagicMock(), redis=MagicMock())

        a = PpsrSearchOptions.model_validate(payload)
        # Re-serialise + reload from a deterministically-rotated dict —
        # Python preserves insertion order, so a list of ``(key, value)``
        # pairs in a different order makes a genuinely different dict.
        items = list(payload.items())
        # Rotate by 3 — gives a different ordering in every example
        # without depending on Python's hash randomisation.
        rotated = items[3:] + items[:3]
        b = PpsrSearchOptions.model_validate(dict(rotated))

        assert svc._hash_options(a) == svc._hash_options(b)

    @PBT_SETTINGS
    @given(payload=options_payload_strategy)
    def test_hash_matches_for_dict_round_trip(
        self, payload: dict[str, Any],
    ) -> None:
        """Hash of model built from the dict equals hash of model built
        from ``json.dumps`` round-trip — guards against accidental
        non-determinism in canonical-JSON encoding.

        **Validates: Requirements R5 (G30).**
        """
        svc = PpsrService(db=MagicMock(), redis=MagicMock())
        a = PpsrSearchOptions.model_validate(payload)
        # Round-trip through JSON — values that survive ``json.loads`` of
        # ``json.dumps`` should hash identically.
        round_tripped = json.loads(json.dumps(payload, sort_keys=True))
        b = PpsrSearchOptions.model_validate(round_tripped)
        assert svc._hash_options(a) == svc._hash_options(b)

    @PBT_SETTINGS
    @given(payload=options_payload_strategy, rego=st.sampled_from(_REGO_POOL))
    @pytest.mark.asyncio
    async def test_reordered_options_lands_in_same_cache_bucket(
        self, payload: dict[str, Any], rego: str,
    ) -> None:
        """Concrete consequence of the hash invariant: a search whose
        options dict was JSON-reordered hits the cache from the original
        search.

        **Validates: Requirements R5 (G30).**
        """
        org_id = uuid.uuid4()
        user = _make_user()
        db = _FakeDB(
            carjam_config=_make_carjam_config_row(),
            quota_used=0,
            quota_included=10_000,
            org_id=org_id,
        )
        redis = _FakeRedis()
        carjam = _FakeCarjamClient()

        async def _noop_audit(session, **kwargs):  # noqa: ARG001
            return uuid.uuid4()

        with _PatchedEnv(carjam), patch(
            "app.modules.ppsr.service.write_audit_log",
            side_effect=_noop_audit,
        ):
            svc = PpsrService(db, redis)

            first_options = PpsrSearchOptions.model_validate(payload)
            await svc.search(
                org_id=org_id,
                user_id=user.id,
                current_user=user,
                rego=rego,
                options=first_options,
            )

            # Build the second options model from a re-ordered dict.
            items = list(payload.items())
            rotated = items[2:] + items[:2]
            second_options = PpsrSearchOptions.model_validate(dict(rotated))
            result = await svc.search(
                org_id=org_id,
                user_id=user.id,
                current_user=user,
                rego=rego,
                options=second_options,
            )

        assert len(carjam.calls) == 1, (
            "Re-ordered options must hit cache — observed "
            f"{len(carjam.calls)} CarJam calls"
        )
        assert result.cached is True
        assert db.quota_used == 1


# ---------------------------------------------------------------------------
# Bonus: a sanity test confirming the in-memory cache lookup actually fires
# inside the property tests (guards against the fakes silently returning
# ``None`` from execute and making Property 1 vacuously hold).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_db_records_search_for_cache_lookup() -> None:
    """Smoke test — a single search adds one row that the cache lookup
    can subsequently find.

    Without this, a regression in :class:`_FakeDB` could cause every
    repeat search to miss cache, making Property 1 trivially true.
    """
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

    with _PatchedEnv(carjam):
        svc = PpsrService(db, redis)
        await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )
        # Repeat → must hit cache (no extra carjam call).
        result = await svc.search(
            org_id=org_id, user_id=user.id, current_user=user,
            rego="ABC123", options=PpsrSearchOptions(),
        )

    assert len(carjam.calls) == 1
    assert result.cached is True
    # The fake DB stored the original row.
    assert len(db.searches) == 1
    assert db.searches[0].rego == "ABC123"


# Module-level reference to satisfy linters that would otherwise complain
# about ``PpsrSearch`` / ``envelope_encrypt`` being imported but unused —
# they're available for follow-up properties without re-importing.
_ = (PpsrSearch, envelope_encrypt)

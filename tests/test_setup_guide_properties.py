"""Property-based tests for Setup Guide module filtering (Task 2.3).

# Feature: setup-guide, Property 1: Module filtering returns only eligible modules

Properties tested:
- Property 1: Module filtering returns only eligible modules

For any set of modules in the registry and any subscription plan, the
``filter_eligible_modules`` function SHALL return only modules where:
  (a) the module slug is in the plan's ``enabled_modules`` list (or plan has "all"),
  (b) ``is_core`` is false,
  (c) the module is not in the ``TRADE_GATED_MODULES`` set,
  (d) ``setup_question`` is not null.
Furthermore, every module satisfying all four conditions SHALL appear in the result.

**Validates: Requirements 1.3, 1.4, 1.5, 2.1, 2.5**

Uses Hypothesis to generate random test data and verify universal properties.
"""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.setup_guide.router import filter_eligible_modules, TRADE_GATED_MODULES


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Lightweight module stub for pure-function testing
# ---------------------------------------------------------------------------


@dataclass
class ModuleStub:
    """Minimal stand-in for ``ModuleRegistry`` rows — just the fields
    that ``filter_eligible_modules`` inspects."""

    slug: str
    is_core: bool
    setup_question: str | None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Pool of realistic slugs (superset of what the real registry has)
_ALL_SLUGS = [
    "invoicing", "customers", "notifications",  # core
    "vehicles",  # trade-gated
    "quotes", "jobs", "projects", "time_tracking", "expenses",
    "inventory", "purchase_orders", "pos", "tipping", "tables",
    "kitchen_display", "scheduling", "staff", "bookings",
    "progress_claims", "retentions", "variations", "compliance_docs",
    "multi_currency", "recurring", "loyalty", "franchise", "ecommerce",
    "alpha_module", "beta_module", "gamma_module",
]

slug_strategy = st.sampled_from(_ALL_SLUGS)

# A single module with randomised eligibility attributes
module_strategy = st.builds(
    ModuleStub,
    slug=slug_strategy,
    is_core=st.booleans(),
    setup_question=st.one_of(st.none(), st.text(min_size=1, max_size=80)),
)


@st.composite
def modules_and_plan(draw):
    """Generate a list of unique-slug modules and a plan_modules set.

    Returns ``(modules, plan_modules, trade_gated)`` where:
    - ``modules`` is a list of ``ModuleStub`` with unique slugs
    - ``plan_modules`` is a set of slugs (may include ``"all"``)
    - ``trade_gated`` is a set of slugs treated as trade-gated
    """
    # Draw a unique subset of slugs for the registry
    slugs = draw(
        st.lists(slug_strategy, min_size=1, max_size=20, unique=True)
    )

    # Build a module for each slug with random attributes
    modules = []
    for slug in slugs:
        mod = draw(
            st.builds(
                ModuleStub,
                slug=st.just(slug),
                is_core=st.booleans(),
                setup_question=st.one_of(
                    st.none(),
                    st.text(min_size=1, max_size=80),
                ),
            )
        )
        modules.append(mod)

    # Plan modules: pick a subset of slugs, optionally include "all"
    plan_slugs = draw(
        st.lists(slug_strategy, min_size=0, max_size=15, unique=True)
    )
    include_all = draw(st.booleans())
    plan_modules = set(plan_slugs)
    if include_all:
        plan_modules.add("all")

    # Trade-gated: use the real set most of the time, but occasionally
    # add extra slugs to exercise the filter more broadly.
    extra_trade_gated = draw(
        st.lists(slug_strategy, min_size=0, max_size=3, unique=True)
    )
    trade_gated = TRADE_GATED_MODULES | set(extra_trade_gated)

    return modules, plan_modules, trade_gated


# ---------------------------------------------------------------------------
# Property 1: Module filtering returns only eligible modules
# **Validates: Requirements 1.3, 1.4, 1.5, 2.1, 2.5**
# ---------------------------------------------------------------------------


class TestModuleFilteringProperty:
    """Property 1 — filter_eligible_modules returns exactly the set of
    modules satisfying all four eligibility conditions."""

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_only_eligible_modules_returned(self, data):
        """Every returned module satisfies all four conditions.

        **Validates: Requirements 1.3, 1.4, 1.5, 2.1, 2.5**
        """
        modules, plan_modules, trade_gated = data
        all_available = "all" in plan_modules

        result = filter_eligible_modules(modules, plan_modules, trade_gated)

        for mod in result:
            # Condition (b): not core
            assert mod.is_core is False, (
                f"Core module {mod.slug!r} should not appear in results"
            )
            # Condition (d): has setup_question
            assert mod.setup_question is not None, (
                f"Module {mod.slug!r} with null setup_question should not appear"
            )
            # Condition (c): not trade-gated
            assert mod.slug not in trade_gated, (
                f"Trade-gated module {mod.slug!r} should not appear"
            )
            # Condition (a): in plan or plan has "all"
            assert all_available or mod.slug in plan_modules, (
                f"Module {mod.slug!r} not in plan and plan does not have 'all'"
            )

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_every_eligible_module_appears(self, data):
        """Completeness: every module satisfying all four conditions is
        present in the result (no false negatives).

        **Validates: Requirements 1.3, 1.4, 1.5, 2.1, 2.5**
        """
        modules, plan_modules, trade_gated = data
        all_available = "all" in plan_modules

        result = filter_eligible_modules(modules, plan_modules, trade_gated)
        result_slugs = {mod.slug for mod in result}

        for mod in modules:
            is_eligible = (
                not mod.is_core
                and mod.setup_question is not None
                and mod.slug not in trade_gated
                and (all_available or mod.slug in plan_modules)
            )
            if is_eligible:
                assert mod.slug in result_slugs, (
                    f"Eligible module {mod.slug!r} missing from results "
                    f"(is_core={mod.is_core}, question={mod.setup_question!r}, "
                    f"trade_gated={mod.slug in trade_gated}, "
                    f"in_plan={mod.slug in plan_modules}, all={all_available})"
                )

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_result_is_subset_of_input(self, data):
        """The result set is always a subset of the input modules.

        **Validates: Requirements 1.3, 1.4, 1.5, 2.1, 2.5**
        """
        modules, plan_modules, trade_gated = data

        result = filter_eligible_modules(modules, plan_modules, trade_gated)

        input_ids = {id(mod) for mod in modules}
        for mod in result:
            assert id(mod) in input_ids, (
                f"Result contains module {mod.slug!r} not in the input list"
            )

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_plan_all_bypasses_slug_check(self, data):
        """When plan contains "all", every non-core, non-trade-gated module
        with a setup_question is eligible regardless of slug membership.

        **Validates: Requirements 2.1, 2.5**
        """
        modules, _, trade_gated = data
        plan_with_all: set[str] = {"all"}

        result = filter_eligible_modules(modules, plan_with_all, trade_gated)
        result_slugs = {mod.slug for mod in result}

        for mod in modules:
            should_appear = (
                not mod.is_core
                and mod.setup_question is not None
                and mod.slug not in trade_gated
            )
            if should_appear:
                assert mod.slug in result_slugs, (
                    f"With plan='all', eligible module {mod.slug!r} should appear"
                )

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_empty_plan_returns_nothing(self, data):
        """An empty plan (no slugs, no "all") yields zero eligible modules.

        **Validates: Requirements 2.1, 2.5**
        """
        modules, _, trade_gated = data
        empty_plan: set[str] = set()

        result = filter_eligible_modules(modules, empty_plan, trade_gated)

        assert result == [], (
            f"Expected no modules with empty plan, got {[m.slug for m in result]}"
        )


# ---------------------------------------------------------------------------
# Property 2: Rerun filtering returns only previously-skipped modules
# # Feature: setup-guide, Property 2: Rerun filtering returns only previously-skipped modules
# **Validates: Requirements 2.2, 8.2**
# ---------------------------------------------------------------------------

from app.modules.setup_guide.router import filter_rerun_modules


@st.composite
def eligible_modules_and_enabled_slugs(draw):
    """Generate a list of base-eligible modules and a set of enabled slugs.

    First generates modules + plan via ``modules_and_plan``, runs them
    through ``filter_eligible_modules`` to get the base-eligible set,
    then randomly marks a subset of those as "enabled" (simulating
    ``org_modules.is_enabled = true``).

    Returns ``(eligible_modules, enabled_slugs)`` where:
    - ``eligible_modules`` is the output of ``filter_eligible_modules``
    - ``enabled_slugs`` is a subset of eligible slugs treated as enabled
    """
    modules, plan_modules, trade_gated = draw(modules_and_plan())

    eligible = filter_eligible_modules(modules, plan_modules, trade_gated)

    # For each eligible module, randomly decide if it's "enabled" in org_modules
    eligible_slug_list = [mod.slug for mod in eligible]
    enabled_flags = draw(
        st.lists(
            st.booleans(),
            min_size=len(eligible_slug_list),
            max_size=len(eligible_slug_list),
        )
    )
    enabled_slugs = {
        slug for slug, flag in zip(eligible_slug_list, enabled_flags) if flag
    }

    return eligible, enabled_slugs


class TestRerunFilteringProperty:
    """Property 2 — filter_rerun_modules returns exactly the base-eligible
    modules whose slug is NOT in the enabled set (i.e. is_enabled = false).

    **Validates: Requirements 2.2, 8.2**
    """

    @PBT_SETTINGS
    @given(data=eligible_modules_and_enabled_slugs())
    def test_rerun_returns_only_non_enabled_modules(self, data):
        """Every module returned by rerun filtering has is_enabled = false
        (its slug is NOT in the enabled set).

        **Validates: Requirements 2.2, 8.2**
        """
        eligible, enabled_slugs = data

        result = filter_rerun_modules(eligible, enabled_slugs)

        for mod in result:
            assert mod.slug not in enabled_slugs, (
                f"Module {mod.slug!r} has is_enabled=true but appeared in "
                f"rerun results (enabled_slugs={enabled_slugs!r})"
            )

    @PBT_SETTINGS
    @given(data=eligible_modules_and_enabled_slugs())
    def test_rerun_includes_every_skipped_module(self, data):
        """Completeness: every base-eligible module with is_enabled = false
        appears in the rerun result (no false negatives).

        **Validates: Requirements 2.2, 8.2**
        """
        eligible, enabled_slugs = data

        result = filter_rerun_modules(eligible, enabled_slugs)
        result_slugs = {mod.slug for mod in result}

        for mod in eligible:
            if mod.slug not in enabled_slugs:
                assert mod.slug in result_slugs, (
                    f"Skipped module {mod.slug!r} (not in enabled_slugs) "
                    f"missing from rerun results"
                )

    @PBT_SETTINGS
    @given(data=eligible_modules_and_enabled_slugs())
    def test_rerun_excludes_every_enabled_module(self, data):
        """No module with is_enabled = true appears in the rerun result.

        **Validates: Requirements 2.2, 8.2**
        """
        eligible, enabled_slugs = data

        result = filter_rerun_modules(eligible, enabled_slugs)
        result_slugs = {mod.slug for mod in result}

        for slug in enabled_slugs:
            assert slug not in result_slugs, (
                f"Enabled module {slug!r} should not appear in rerun results"
            )

    @PBT_SETTINGS
    @given(data=eligible_modules_and_enabled_slugs())
    def test_rerun_result_is_subset_of_eligible(self, data):
        """The rerun result is always a subset of the base-eligible modules.

        **Validates: Requirements 2.2, 8.2**
        """
        eligible, enabled_slugs = data

        result = filter_rerun_modules(eligible, enabled_slugs)

        eligible_ids = {id(mod) for mod in eligible}
        for mod in result:
            assert id(mod) in eligible_ids, (
                f"Rerun result contains module {mod.slug!r} not in "
                f"the base-eligible list"
            )

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_rerun_all_enabled_returns_empty(self, data):
        """When every eligible module is enabled, rerun returns nothing.

        **Validates: Requirements 2.2, 8.2**
        """
        modules, plan_modules, trade_gated = data

        eligible = filter_eligible_modules(modules, plan_modules, trade_gated)
        all_enabled = {mod.slug for mod in eligible}

        result = filter_rerun_modules(eligible, all_enabled)

        assert result == [], (
            f"Expected empty rerun result when all modules enabled, "
            f"got {[m.slug for m in result]}"
        )

    @PBT_SETTINGS
    @given(data=modules_and_plan())
    def test_rerun_none_enabled_returns_all_eligible(self, data):
        """When no modules are enabled, rerun returns all eligible modules.

        **Validates: Requirements 2.2, 8.2**
        """
        modules, plan_modules, trade_gated = data

        eligible = filter_eligible_modules(modules, plan_modules, trade_gated)
        none_enabled: set[str] = set()

        result = filter_rerun_modules(eligible, none_enabled)

        assert len(result) == len(eligible), (
            f"Expected all {len(eligible)} eligible modules in rerun result "
            f"when none enabled, got {len(result)}"
        )


# ---------------------------------------------------------------------------
# Property 3: Topological ordering of questions
# # Feature: setup-guide, Property 3: Topological ordering of questions
# **Validates: Requirements 2.4, 9.3**
# ---------------------------------------------------------------------------

from unittest.mock import patch

from app.modules.setup_guide.router import _topological_sort


@st.composite
def dag_and_module_set(draw):
    """Generate a random DAG (dependency graph) and a subset of slugs.

    Strategy for guaranteeing acyclicity: fix an arbitrary ordering of
    slugs, then for each slug only allow dependencies from slugs that
    appear *earlier* in that ordering.

    Returns ``(dep_graph, module_slugs)`` where:
    - ``dep_graph`` is a ``dict[str, list[str]]`` mapping slug → deps
    - ``module_slugs`` is a ``set[str]`` subset to pass to ``_topological_sort``
    """
    # Draw a unique list of slugs (the node universe)
    all_slugs = draw(
        st.lists(slug_strategy, min_size=1, max_size=15, unique=True)
    )

    # Build a random DAG: for each slug at index i, pick deps from
    # slugs at indices 0..i-1 (guarantees no cycles).
    dep_graph: dict[str, list[str]] = {}
    for i, slug in enumerate(all_slugs):
        if i == 0:
            dep_graph[slug] = []
        else:
            predecessors = all_slugs[:i]
            deps = draw(
                st.lists(
                    st.sampled_from(predecessors),
                    min_size=0,
                    max_size=min(3, i),
                    unique=True,
                )
            )
            dep_graph[slug] = deps

    # Pick a random subset of slugs to sort (at least 1)
    module_slugs = draw(
        st.lists(
            st.sampled_from(all_slugs),
            min_size=1,
            max_size=len(all_slugs),
            unique=True,
        )
    )

    return dep_graph, set(module_slugs)


class TestTopologicalOrderingProperty:
    """Property 3 — _topological_sort orders modules so that dependencies
    appear before dependents for any valid DAG.

    **Validates: Requirements 2.4, 9.3**
    """

    @PBT_SETTINGS
    @given(data=dag_and_module_set())
    def test_dependencies_appear_before_dependents(self, data):
        """For every pair (A depends on B) where both are in the input set,
        B appears at an earlier index than A in the sorted result.

        **Validates: Requirements 2.4, 9.3**
        """
        dep_graph, module_slugs = data

        # Monkeypatch DEPENDENCY_GRAPH in the router module so
        # _topological_sort uses our generated DAG.
        with patch(
            "app.modules.setup_guide.router.DEPENDENCY_GRAPH", dep_graph
        ):
            result = _topological_sort(module_slugs)

        # Build index lookup for O(1) position checks
        index_of = {slug: idx for idx, slug in enumerate(result)}

        # Verify: for every slug in the result, each of its deps that
        # is also in the input set must appear earlier.
        for slug in module_slugs:
            for dep in dep_graph.get(slug, []):
                if dep in module_slugs:
                    assert dep in index_of, (
                        f"Dependency {dep!r} of {slug!r} missing from result"
                    )
                    assert slug in index_of, (
                        f"Module {slug!r} missing from result"
                    )
                    assert index_of[dep] < index_of[slug], (
                        f"Dependency {dep!r} (index {index_of[dep]}) should "
                        f"appear before {slug!r} (index {index_of[slug]}) "
                        f"in topological order. Result: {result}"
                    )

    @PBT_SETTINGS
    @given(data=dag_and_module_set())
    def test_result_contains_all_input_slugs(self, data):
        """The sorted result contains exactly the input slugs (no additions,
        no omissions).

        **Validates: Requirements 2.4, 9.3**
        """
        dep_graph, module_slugs = data

        with patch(
            "app.modules.setup_guide.router.DEPENDENCY_GRAPH", dep_graph
        ):
            result = _topological_sort(module_slugs)

        assert set(result) == module_slugs, (
            f"Result slugs {set(result)} != input slugs {module_slugs}"
        )

    @PBT_SETTINGS
    @given(data=dag_and_module_set())
    def test_result_has_no_duplicates(self, data):
        """The sorted result contains no duplicate slugs.

        **Validates: Requirements 2.4, 9.3**
        """
        dep_graph, module_slugs = data

        with patch(
            "app.modules.setup_guide.router.DEPENDENCY_GRAPH", dep_graph
        ):
            result = _topological_sort(module_slugs)

        assert len(result) == len(set(result)), (
            f"Result contains duplicates: {result}"
        )


# ---------------------------------------------------------------------------
# Property 4: Answer dispatch correctness
# # Feature: setup-guide, Property 4: Answer dispatch correctness
# **Validates: Requirements 3.2, 3.3, 8.4**
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.modules.setup_guide.router import _dispatch_answers
from app.modules.setup_guide.schemas import SetupGuideAnswer


@st.composite
def unique_answer_list(draw):
    """Generate a list of ``SetupGuideAnswer`` objects with unique slugs.

    Each answer has a random ``enabled`` boolean.  Slugs are drawn from
    the shared ``_ALL_SLUGS`` pool and de-duplicated so every slug
    appears at most once (matching real submission semantics).

    Returns ``list[SetupGuideAnswer]``.
    """
    slugs = draw(
        st.lists(slug_strategy, min_size=1, max_size=20, unique=True)
    )
    answers = []
    for slug in slugs:
        enabled = draw(st.booleans())
        answers.append(SetupGuideAnswer(slug=slug, enabled=enabled))
    return answers


class TestAnswerDispatchProperty:
    """Property 4 — _dispatch_answers calls enable_module exactly once for
    each answer with enabled=true, and force_disable_module exactly once
    for each answer with enabled=false.

    **Validates: Requirements 3.2, 3.3, 8.4**
    """

    @PBT_SETTINGS
    @given(answers=unique_answer_list())
    def test_enable_called_once_per_enabled_answer(self, answers):
        """``enable_module`` is called exactly once for each answer where
        ``enabled`` is true, with the correct org_id and slug.

        **Validates: Requirements 3.2, 8.4**
        """
        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(return_value=[])
        mock_svc.force_disable_module = AsyncMock(return_value=None)

        org_id = "test-org-id"

        asyncio.get_event_loop().run_until_complete(
            _dispatch_answers(mock_svc, org_id, answers)
        )

        expected_enabled_slugs = [a.slug for a in answers if a.enabled]

        # Exactly one call per enabled answer
        assert mock_svc.enable_module.call_count == len(expected_enabled_slugs), (
            f"Expected {len(expected_enabled_slugs)} enable_module calls, "
            f"got {mock_svc.enable_module.call_count}"
        )

        # Each enabled slug was called with the right args
        actual_calls = [
            call.args[1] for call in mock_svc.enable_module.call_args_list
        ]
        assert actual_calls == expected_enabled_slugs, (
            f"enable_module called with slugs {actual_calls}, "
            f"expected {expected_enabled_slugs}"
        )

        # Verify org_id passed correctly for every call
        for call in mock_svc.enable_module.call_args_list:
            assert call.args[0] == org_id, (
                f"enable_module called with org_id={call.args[0]!r}, "
                f"expected {org_id!r}"
            )

    @PBT_SETTINGS
    @given(answers=unique_answer_list())
    def test_disable_called_once_per_disabled_answer(self, answers):
        """``force_disable_module`` is called exactly once for each answer
        where ``enabled`` is false, with the correct org_id and slug.

        **Validates: Requirements 3.3, 8.4**
        """
        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(return_value=[])
        mock_svc.force_disable_module = AsyncMock(return_value=None)

        org_id = "test-org-id"

        asyncio.get_event_loop().run_until_complete(
            _dispatch_answers(mock_svc, org_id, answers)
        )

        expected_disabled_slugs = [a.slug for a in answers if not a.enabled]

        # Exactly one call per disabled answer
        assert mock_svc.force_disable_module.call_count == len(expected_disabled_slugs), (
            f"Expected {len(expected_disabled_slugs)} force_disable_module calls, "
            f"got {mock_svc.force_disable_module.call_count}"
        )

        # Each disabled slug was called with the right args
        actual_calls = [
            call.args[1] for call in mock_svc.force_disable_module.call_args_list
        ]
        assert actual_calls == expected_disabled_slugs, (
            f"force_disable_module called with slugs {actual_calls}, "
            f"expected {expected_disabled_slugs}"
        )

        # Verify org_id passed correctly for every call
        for call in mock_svc.force_disable_module.call_args_list:
            assert call.args[0] == org_id, (
                f"force_disable_module called with org_id={call.args[0]!r}, "
                f"expected {org_id!r}"
            )

    @PBT_SETTINGS
    @given(answers=unique_answer_list())
    def test_total_calls_equals_answer_count(self, answers):
        """The total number of ModuleService calls (enable + disable) equals
        the number of answers — every answer is dispatched exactly once.

        **Validates: Requirements 3.2, 3.3, 8.4**
        """
        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(return_value=[])
        mock_svc.force_disable_module = AsyncMock(return_value=None)

        org_id = "test-org-id"

        asyncio.get_event_loop().run_until_complete(
            _dispatch_answers(mock_svc, org_id, answers)
        )

        total_calls = (
            mock_svc.enable_module.call_count
            + mock_svc.force_disable_module.call_count
        )
        assert total_calls == len(answers), (
            f"Total ModuleService calls ({total_calls}) != "
            f"number of answers ({len(answers)})"
        )

    @PBT_SETTINGS
    @given(answers=unique_answer_list())
    def test_auto_enabled_deps_collected(self, answers):
        """Auto-enabled dependency slugs returned by ``enable_module`` are
        collected and returned by ``_dispatch_answers``.

        **Validates: Requirements 3.2, 8.4**
        """
        # Make enable_module return a fake dep for each enabled slug
        def fake_enable(org_id, slug):
            return [f"{slug}_dep"]

        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(side_effect=fake_enable)
        mock_svc.force_disable_module = AsyncMock(return_value=None)

        org_id = "test-org-id"

        result = asyncio.get_event_loop().run_until_complete(
            _dispatch_answers(mock_svc, org_id, answers)
        )

        expected_deps = [f"{a.slug}_dep" for a in answers if a.enabled]
        assert result == expected_deps, (
            f"Auto-enabled deps {result} != expected {expected_deps}"
        )


# ---------------------------------------------------------------------------
# Property 5: First-run marks wizard Step 5 complete
# # Feature: setup-guide, Property 5: First-run marks wizard Step 5 complete
# **Validates: Requirements 3.5**
# ---------------------------------------------------------------------------

import uuid

from app.modules.setup_guide.router import _mark_step_5_complete


# Strategy: generate random org UUIDs for each test run
org_id_strategy = st.builds(uuid.uuid4)


@dataclass
class ProgressStub:
    """Lightweight stand-in for ``SetupWizardProgress`` — avoids triggering
    SQLAlchemy mapper configuration during property-based tests."""

    org_id: uuid.UUID | None = None
    step_5_complete: bool = False


@st.composite
def org_id_and_existing_progress(draw):
    """Generate an org_id and optionally an existing progress stub.

    Returns ``(org_id, existing_progress)`` where:
    - ``org_id`` is a random UUID
    - ``existing_progress`` is either ``None`` (no record exists yet)
      or a ``ProgressStub`` with ``step_5_complete`` randomly set to
      ``True`` or ``False`` (simulating a pre-existing record).
    """
    org_id = draw(org_id_strategy)
    has_existing = draw(st.booleans())

    if has_existing:
        progress = ProgressStub(
            org_id=org_id,
            step_5_complete=draw(st.booleans()),
        )
        return org_id, progress
    else:
        return org_id, None


def _make_mock_db(existing_progress, added_objects=None):
    """Build a mock async DB session for ``_mark_step_5_complete`` tests.

    The mock's ``execute`` returns a result whose ``scalar_one_or_none``
    yields *existing_progress*.  ``add`` appends to *added_objects*.
    """
    if added_objects is None:
        added_objects = []

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_progress

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    return mock_db, added_objects


def _step5_patches():
    """Context manager that patches both ``SetupWizardProgress`` and
    ``select`` inside the router module so ``_mark_step_5_complete``
    can run without touching real SQLAlchemy internals.

    ``select`` is replaced with a mock that returns a chainable mock
    statement (the actual SQL is never executed — ``db.execute`` is
    already mocked).  ``SetupWizardProgress`` is replaced with
    ``ProgressStub`` so the constructor creates a plain dataclass.
    """
    # Mock select() to return a chainable mock (select(...).where(...))
    mock_stmt = MagicMock()
    mock_select = MagicMock(return_value=mock_stmt)

    return patch.multiple(
        "app.modules.setup_guide.router",
        SetupWizardProgress=ProgressStub,
        select=mock_select,
    )


class TestStep5CompletionProperty:
    """Property 5 — _mark_step_5_complete sets step_5_complete = True on
    the SetupWizardProgress record for any organisation, regardless of
    whether a progress record already exists.

    **Validates: Requirements 3.5**
    """

    @PBT_SETTINGS
    @given(data=org_id_and_existing_progress())
    def test_step_5_marked_complete_after_submission(self, data):
        """After calling ``_mark_step_5_complete``, the progress record
        SHALL have ``step_5_complete = True``.

        **Validates: Requirements 3.5**
        """
        org_id, existing_progress = data

        added_objects: list = []
        mock_db, added_objects = _make_mock_db(existing_progress, added_objects)

        with _step5_patches():
            asyncio.get_event_loop().run_until_complete(
                _mark_step_5_complete(mock_db, org_id)
            )

        if existing_progress is not None:
            # Existing record should have step_5_complete set to True
            assert existing_progress.step_5_complete is True, (
                f"Existing progress record for org {org_id} should have "
                f"step_5_complete=True after submission, got "
                f"{existing_progress.step_5_complete!r}"
            )
            # db.add should NOT have been called (record already exists)
            assert len(added_objects) == 0, (
                f"db.add should not be called when progress record exists, "
                f"but was called {len(added_objects)} time(s)"
            )
        else:
            # A new record should have been created and added
            assert len(added_objects) == 1, (
                f"Expected exactly 1 object added to session when no "
                f"progress record exists, got {len(added_objects)}"
            )
            new_progress = added_objects[0]
            assert new_progress.org_id == org_id, (
                f"New progress record org_id={new_progress.org_id} "
                f"does not match expected {org_id}"
            )
            assert new_progress.step_5_complete is True, (
                f"New progress record should have step_5_complete=True, "
                f"got {new_progress.step_5_complete!r}"
            )

    @PBT_SETTINGS
    @given(data=org_id_and_existing_progress())
    def test_db_flush_called(self, data):
        """``db.flush()`` is called at least once to persist the change.

        **Validates: Requirements 3.5**
        """
        org_id, existing_progress = data

        mock_db, _ = _make_mock_db(existing_progress)

        with _step5_patches():
            asyncio.get_event_loop().run_until_complete(
                _mark_step_5_complete(mock_db, org_id)
            )

        # flush must be called at least once (to persist step_5_complete = True)
        assert mock_db.flush.call_count >= 1, (
            f"db.flush() should be called at least once, "
            f"got {mock_db.flush.call_count} calls"
        )

    @PBT_SETTINGS
    @given(org_id=org_id_strategy)
    def test_new_record_created_when_none_exists(self, org_id):
        """When no SetupWizardProgress record exists for the org, a new
        one is created with the correct org_id and step_5_complete=True.

        **Validates: Requirements 3.5**
        """
        added_objects: list = []
        mock_db, added_objects = _make_mock_db(None, added_objects)

        with _step5_patches():
            asyncio.get_event_loop().run_until_complete(
                _mark_step_5_complete(mock_db, org_id)
            )

        assert len(added_objects) == 1, (
            f"Expected 1 new progress record, got {len(added_objects)}"
        )
        new_progress = added_objects[0]
        assert new_progress.org_id == org_id, (
            f"New record org_id={new_progress.org_id} != {org_id}"
        )
        assert new_progress.step_5_complete is True, (
            f"New record step_5_complete should be True, "
            f"got {new_progress.step_5_complete!r}"
        )

    @PBT_SETTINGS
    @given(org_id=org_id_strategy)
    def test_existing_record_updated_not_replaced(self, org_id):
        """When a SetupWizardProgress record already exists, it is updated
        in-place (not replaced with a new object).

        **Validates: Requirements 3.5**
        """
        existing = ProgressStub(org_id=org_id, step_5_complete=False)
        original_id = id(existing)

        mock_db, _ = _make_mock_db(existing)

        with _step5_patches():
            asyncio.get_event_loop().run_until_complete(
                _mark_step_5_complete(mock_db, org_id)
            )

        # Same object should be mutated, not replaced
        assert id(existing) == original_id, "Progress object was replaced"
        assert existing.step_5_complete is True, (
            f"Existing record step_5_complete should be True after update"
        )
        # db.add should NOT be called for existing records
        mock_db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Property 6: Invalid slug rejection
# # Feature: setup-guide, Property 6: Invalid slug rejection
# **Validates: Requirements 3.6**
# ---------------------------------------------------------------------------

from fastapi import HTTPException

from app.modules.setup_guide.router import validate_slugs


@st.composite
def submitted_and_valid_slugs_with_invalid(draw):
    """Generate a set of valid slugs and a set of submitted slugs where
    at least one submitted slug is NOT in the valid set.

    Returns ``(submitted_slugs, valid_slugs)`` where:
    - ``valid_slugs`` is a set of slugs simulating what exists in module_registry
    - ``submitted_slugs`` is a set of slugs where at least one is invalid
    """
    # Draw valid slugs from the shared pool (simulating module_registry)
    valid_slug_list = draw(
        st.lists(slug_strategy, min_size=0, max_size=15, unique=True)
    )
    valid_slugs = set(valid_slug_list)

    # Draw some submitted slugs that ARE valid (may be empty)
    if valid_slug_list:
        valid_submitted = draw(
            st.lists(
                st.sampled_from(valid_slug_list),
                min_size=0,
                max_size=len(valid_slug_list),
                unique=True,
            )
        )
    else:
        valid_submitted = []

    # Generate at least one slug that is NOT in valid_slugs.
    # Use a text strategy filtered to exclude valid slugs.
    invalid_slug = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
            min_size=1,
            max_size=30,
        ).filter(lambda s: s not in valid_slugs)
    )

    # Optionally generate more invalid slugs
    extra_invalid = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
                min_size=1,
                max_size=30,
            ).filter(lambda s: s not in valid_slugs),
            min_size=0,
            max_size=3,
            unique=True,
        )
    )

    all_invalid = {invalid_slug} | set(extra_invalid)
    submitted_slugs = set(valid_submitted) | all_invalid

    return submitted_slugs, valid_slugs


class TestInvalidSlugRejectionProperty:
    """Property 6 — validate_slugs raises HTTPException with status 400
    when any submitted slug does not exist in the valid set, and the
    error message identifies the invalid slug(s).

    **Validates: Requirements 3.6**
    """

    @PBT_SETTINGS
    @given(data=submitted_and_valid_slugs_with_invalid())
    def test_invalid_slug_raises_400(self, data):
        """When at least one submitted slug is not in the valid set,
        ``validate_slugs`` SHALL raise HTTPException with status 400.

        **Validates: Requirements 3.6**
        """
        submitted_slugs, valid_slugs = data

        try:
            validate_slugs(submitted_slugs, valid_slugs)
            assert False, (
                f"Expected HTTPException for invalid slugs but none was raised. "
                f"submitted={submitted_slugs}, valid={valid_slugs}"
            )
        except HTTPException as exc:
            assert exc.status_code == 400, (
                f"Expected status 400, got {exc.status_code}"
            )

    @PBT_SETTINGS
    @given(data=submitted_and_valid_slugs_with_invalid())
    def test_error_message_identifies_invalid_slugs(self, data):
        """The error detail SHALL mention every invalid slug.

        **Validates: Requirements 3.6**
        """
        submitted_slugs, valid_slugs = data
        expected_invalid = submitted_slugs - valid_slugs

        try:
            validate_slugs(submitted_slugs, valid_slugs)
            assert False, "Expected HTTPException but none was raised"
        except HTTPException as exc:
            for slug in expected_invalid:
                assert slug in exc.detail, (
                    f"Invalid slug {slug!r} not mentioned in error detail: "
                    f"{exc.detail!r}"
                )

    @PBT_SETTINGS
    @given(data=submitted_and_valid_slugs_with_invalid())
    def test_error_message_starts_with_expected_prefix(self, data):
        """The error detail SHALL start with 'Invalid module slug:'.

        **Validates: Requirements 3.6**
        """
        submitted_slugs, valid_slugs = data

        try:
            validate_slugs(submitted_slugs, valid_slugs)
            assert False, "Expected HTTPException but none was raised"
        except HTTPException as exc:
            assert exc.detail.startswith("Invalid module slug:"), (
                f"Error detail should start with 'Invalid module slug:', "
                f"got: {exc.detail!r}"
            )

    @PBT_SETTINGS
    @given(
        valid_slugs=st.lists(slug_strategy, min_size=1, max_size=15, unique=True).map(set)
    )
    def test_all_valid_slugs_does_not_raise(self, valid_slugs):
        """When all submitted slugs exist in the valid set,
        ``validate_slugs`` SHALL NOT raise any exception.

        **Validates: Requirements 3.6**
        """
        # Submit a subset of valid slugs (including possibly all of them)
        submitted_slugs = valid_slugs

        # Should not raise
        validate_slugs(submitted_slugs, valid_slugs)

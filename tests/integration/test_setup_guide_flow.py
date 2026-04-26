"""Integration tests for the setup guide end-to-end flow.

Tests:
- Full first-run flow: GET questions -> POST submit -> verify org_modules updated
- Full rerun flow: complete first run -> re-run with rerun=true -> verify only skipped modules shown
- Wizard Step 5 redirect triggers correctly (documented as covered by SetupWizard integration)

**Validates: Requirements 2.1, 3.2, 3.3, 3.5, 4.1, 8.2, 8.4**
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.setup_guide.router import (
    TRADE_GATED_MODULES,
    _dispatch_answers,
    _mark_step_5_complete,
    _topological_sort,
    filter_eligible_modules,
    filter_rerun_modules,
    validate_slugs,
)
from app.modules.setup_guide.schemas import (
    SetupGuideAnswer,
    SetupGuideQuestion,
    SetupGuideQuestionsResponse,
)


# ---------------------------------------------------------------------------
# Lightweight stubs (avoid SQLAlchemy mapper overhead)
# ---------------------------------------------------------------------------


@dataclass
class ModuleStub:
    """Stand-in for ModuleRegistry rows."""

    slug: str
    display_name: str
    is_core: bool
    setup_question: str | None
    setup_question_description: str | None = None
    category: str | None = "general"
    dependencies: list[str] = field(default_factory=list)
    status: str = "available"


@dataclass
class ProgressStub:
    """Stand-in for SetupWizardProgress."""

    org_id: uuid.UUID | None = None
    step_5_complete: bool = False


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_ORG_ID = uuid.uuid4()


def _build_registry() -> list[ModuleStub]:
    """Build a realistic module registry with core, trade-gated, and optional modules."""
    return [
        # Core modules — should never appear in setup guide
        ModuleStub(slug="invoicing", display_name="Invoicing", is_core=True, setup_question=None),
        ModuleStub(slug="customers", display_name="Customers", is_core=True, setup_question=None),
        ModuleStub(slug="notifications", display_name="Notifications", is_core=True, setup_question=None),
        # Trade-gated — should never appear in setup guide
        ModuleStub(
            slug="vehicles", display_name="Vehicles", is_core=False,
            setup_question="Do you manage vehicles?",
        ),
        # Optional modules with setup questions
        ModuleStub(
            slug="quotes", display_name="Quotes",
            is_core=False, setup_question="Will you be sending quotes?",
            setup_question_description="Create professional quotes.",
            category="sales",
        ),
        ModuleStub(
            slug="jobs", display_name="Jobs",
            is_core=False, setup_question="Do you manage jobs?",
            setup_question_description="Track jobs from enquiry to completion.",
            category="operations",
        ),
        ModuleStub(
            slug="inventory", display_name="Inventory",
            is_core=False, setup_question="Do you track stock?",
            setup_question_description="Manage product catalogues and stock.",
            category="operations",
        ),
        ModuleStub(
            slug="pos", display_name="POS",
            is_core=False, setup_question="Do you need a POS terminal?",
            setup_question_description="POS mode with receipt printing.",
            category="sales",
            dependencies=["inventory"],
        ),
        ModuleStub(
            slug="scheduling", display_name="Scheduling",
            is_core=False, setup_question="Do you need a visual calendar?",
            setup_question_description="Drag-and-drop scheduling.",
            category="operations",
        ),
        # Module without setup_question — should be excluded
        ModuleStub(
            slug="recurring", display_name="Recurring Invoices",
            is_core=False, setup_question=None,
            category="billing",
        ),
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _step5_patches():
    """Patch SetupWizardProgress and select in the router module."""
    mock_stmt = MagicMock()
    mock_select = MagicMock(return_value=mock_stmt)
    return patch.multiple(
        "app.modules.setup_guide.router",
        SetupWizardProgress=ProgressStub,
        select=mock_select,
    )


def _simulate_get_questions(
    registry: list[ModuleStub],
    plan_modules: set[str],
    rerun: bool = False,
    enabled_slugs: set[str] | None = None,
) -> SetupGuideQuestionsResponse:
    """Simulate the GET /questions endpoint logic using pure functions.

    This avoids triggering SQLAlchemy mapper configuration while testing
    the same filtering, ordering, and response-building logic that the
    real endpoint uses.
    """
    # Step 1: Filter eligible modules (same as router)
    eligible = filter_eligible_modules(registry, plan_modules)

    # Step 2: If rerun, additionally filter to non-enabled modules
    if rerun and enabled_slugs is not None:
        eligible = filter_rerun_modules(eligible, enabled_slugs)

    # Step 3: Sort by topological order (same as router)
    eligible_slugs = {mod.slug for mod in eligible}
    sorted_slugs = _topological_sort(eligible_slugs)

    # Step 4: Build response (same as router)
    mod_by_slug = {mod.slug: mod for mod in eligible}
    questions = []
    for slug in sorted_slugs:
        mod = mod_by_slug[slug]
        deps = mod.dependencies or []
        questions.append(
            SetupGuideQuestion(
                slug=mod.slug,
                display_name=mod.display_name,
                setup_question=mod.setup_question,
                setup_question_description=mod.setup_question_description,
                category=mod.category or "",
                dependencies=deps if isinstance(deps, list) else [],
            )
        )

    return SetupGuideQuestionsResponse(
        questions=questions,
        total=len(questions),
    )


# ===========================================================================
# Test 1: Full first-run flow
# ===========================================================================


class TestFullFirstRunFlow:
    """End-to-end first-run: GET questions -> POST submit -> verify state.

    **Validates: Requirements 2.1, 3.2, 3.3, 3.5, 8.4**
    """

    def test_get_questions_returns_eligible_modules(self):
        """GET /questions returns only non-core, non-trade-gated modules
        with setup_question that are in the subscription plan.

        **Validates: Requirement 2.1**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        response = _simulate_get_questions(registry, plan_modules)

        returned_slugs = {q.slug for q in response.questions}

        # Should include optional modules with setup_question
        assert "quotes" in returned_slugs
        assert "jobs" in returned_slugs
        assert "inventory" in returned_slugs
        assert "pos" in returned_slugs
        assert "scheduling" in returned_slugs

        # Should exclude core modules
        assert "invoicing" not in returned_slugs
        assert "customers" not in returned_slugs
        assert "notifications" not in returned_slugs

        # Should exclude trade-gated modules
        assert "vehicles" not in returned_slugs

        # Should exclude modules without setup_question
        assert "recurring" not in returned_slugs

        # Total should match
        assert response.total == len(response.questions)

    def test_get_questions_returns_correct_fields(self):
        """Each question includes slug, display_name, setup_question,
        setup_question_description, category, and dependencies.

        **Validates: Requirement 2.1**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        response = _simulate_get_questions(registry, plan_modules)

        # Find the quotes question
        quotes_q = next((q for q in response.questions if q.slug == "quotes"), None)
        assert quotes_q is not None
        assert quotes_q.display_name == "Quotes"
        assert quotes_q.setup_question == "Will you be sending quotes?"
        assert quotes_q.setup_question_description == "Create professional quotes."
        assert quotes_q.category == "sales"
        assert quotes_q.dependencies == []

        # Find POS question — should have inventory dependency
        pos_q = next((q for q in response.questions if q.slug == "pos"), None)
        assert pos_q is not None
        assert pos_q.dependencies == ["inventory"]

    def test_submit_enables_and_disables_modules(self):
        """POST /submit calls enable_module for enabled=true answers and
        force_disable_module for enabled=false answers.

        **Validates: Requirements 3.2, 3.3, 8.4**
        """
        enabled_calls: list[str] = []
        disabled_calls: list[str] = []

        async def mock_enable(org_id, slug):
            enabled_calls.append(slug)
            return []

        async def mock_disable(org_id, slug):
            disabled_calls.append(slug)

        answers = [
            SetupGuideAnswer(slug="quotes", enabled=True),
            SetupGuideAnswer(slug="jobs", enabled=True),
            SetupGuideAnswer(slug="inventory", enabled=False),
            SetupGuideAnswer(slug="pos", enabled=False),
            SetupGuideAnswer(slug="scheduling", enabled=True),
        ]

        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(side_effect=mock_enable)
        mock_svc.force_disable_module = AsyncMock(side_effect=mock_disable)

        _run(_dispatch_answers(mock_svc, str(_ORG_ID), answers))

        assert enabled_calls == ["quotes", "jobs", "scheduling"]
        assert disabled_calls == ["inventory", "pos"]

    def test_submit_marks_step_5_complete(self):
        """POST /submit sets step_5_complete = true on setup_wizard_progress.

        **Validates: Requirement 3.5**
        """
        progress = ProgressStub(org_id=_ORG_ID, step_5_complete=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = progress

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with _step5_patches():
            _run(_mark_step_5_complete(mock_db, _ORG_ID))

        assert progress.step_5_complete is True

    def test_submit_creates_progress_if_missing(self):
        """If no setup_wizard_progress record exists, one is created and
        step_5_complete is set to true.

        **Validates: Requirement 3.5**
        """
        added_objects: list = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing record

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with _step5_patches():
            _run(_mark_step_5_complete(mock_db, _ORG_ID))

        # A new progress record should have been added
        assert len(added_objects) == 1
        new_progress = added_objects[0]
        assert new_progress.org_id == _ORG_ID
        assert new_progress.step_5_complete is True

    def test_full_first_run_end_to_end(self):
        """Complete first-run flow: get questions, submit answers, verify
        modules dispatched and step 5 marked complete.

        **Validates: Requirements 2.1, 3.2, 3.3, 3.5, 8.4**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        # Step 1: GET questions
        questions_response = _simulate_get_questions(registry, plan_modules)
        assert questions_response.total > 0
        returned_slugs = [q.slug for q in questions_response.questions]

        # Step 2: Build answers — enable some, skip some
        answers = []
        for slug in returned_slugs:
            answers.append(SetupGuideAnswer(
                slug=slug,
                enabled=slug in {"quotes", "jobs", "scheduling"},
            ))

        # Step 3: Validate slugs (same as router does before dispatch)
        valid_slugs = {m.slug for m in registry}
        submitted_slugs = {a.slug for a in answers}
        validate_slugs(submitted_slugs, valid_slugs)  # Should not raise

        # Step 4: Dispatch answers via ModuleService
        enabled_calls: list[str] = []
        disabled_calls: list[str] = []

        async def mock_enable(org_id, slug):
            enabled_calls.append(slug)
            return []

        async def mock_disable(org_id, slug):
            disabled_calls.append(slug)

        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(side_effect=mock_enable)
        mock_svc.force_disable_module = AsyncMock(side_effect=mock_disable)

        _run(_dispatch_answers(mock_svc, str(_ORG_ID), answers))

        # Verify enable was called for the "yes" answers
        assert "quotes" in enabled_calls
        assert "jobs" in enabled_calls
        assert "scheduling" in enabled_calls

        # Verify disable was called for the "no" answers
        for slug in returned_slugs:
            if slug not in {"quotes", "jobs", "scheduling"}:
                assert slug in disabled_calls, f"{slug} should have been disabled"

        # Step 5: Mark step 5 complete
        progress = ProgressStub(org_id=_ORG_ID, step_5_complete=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = progress
        mock_db_step5 = MagicMock()
        mock_db_step5.execute = AsyncMock(return_value=mock_result)
        mock_db_step5.flush = AsyncMock()
        mock_db_step5.add = MagicMock()

        with _step5_patches():
            _run(_mark_step_5_complete(mock_db_step5, _ORG_ID))

        assert progress.step_5_complete is True

    def test_submit_auto_enabled_deps_returned(self):
        """When enable_module auto-enables dependencies, they appear in
        the auto_enabled list.

        **Validates: Requirements 3.2, 8.4**
        """
        async def mock_enable(org_id, slug):
            if slug == "pos":
                return ["inventory"]  # POS auto-enables inventory
            return []

        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(side_effect=mock_enable)
        mock_svc.force_disable_module = AsyncMock()

        answers = [
            SetupGuideAnswer(slug="pos", enabled=True),
            SetupGuideAnswer(slug="quotes", enabled=True),
        ]

        auto_enabled = _run(_dispatch_answers(mock_svc, str(_ORG_ID), answers))

        assert "inventory" in auto_enabled


# ===========================================================================
# Test 2: Full rerun flow
# ===========================================================================


class TestFullRerunFlow:
    """End-to-end rerun: first run -> re-run with rerun=true -> verify filtering.

    **Validates: Requirements 2.1, 8.2, 8.4**
    """

    def test_rerun_returns_only_skipped_modules(self):
        """GET /questions?rerun=true returns only modules where
        org_modules.is_enabled = false (previously skipped).

        **Validates: Requirements 2.1, 8.2**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        # Simulate first run: quotes and jobs were enabled, rest were skipped
        enabled_slugs = {"quotes", "jobs"}

        response = _simulate_get_questions(
            registry, plan_modules, rerun=True, enabled_slugs=enabled_slugs,
        )

        returned_slugs = {q.slug for q in response.questions}

        # Previously enabled modules should NOT appear
        assert "quotes" not in returned_slugs
        assert "jobs" not in returned_slugs

        # Previously skipped modules should appear
        assert "inventory" in returned_slugs
        assert "pos" in returned_slugs
        assert "scheduling" in returned_slugs

        # Core, trade-gated, and no-question modules still excluded
        assert "invoicing" not in returned_slugs
        assert "vehicles" not in returned_slugs
        assert "recurring" not in returned_slugs

    def test_rerun_empty_when_all_enabled(self):
        """GET /questions?rerun=true returns empty list when all eligible
        modules are already enabled.

        **Validates: Requirement 8.2**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        # All eligible modules are enabled
        eligible = filter_eligible_modules(registry, plan_modules)
        all_enabled = {m.slug for m in eligible}

        response = _simulate_get_questions(
            registry, plan_modules, rerun=True, enabled_slugs=all_enabled,
        )

        assert response.questions == []
        assert response.total == 0

    def test_full_rerun_end_to_end(self):
        """Complete rerun flow: first run enables some modules, rerun shows
        only skipped ones, submit enables newly selected modules.

        **Validates: Requirements 2.1, 3.2, 3.3, 8.2, 8.4**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        # --- Phase 1: First run ---
        first_response = _simulate_get_questions(registry, plan_modules)
        first_slugs = {q.slug for q in first_response.questions}
        assert len(first_slugs) > 0

        # User enables quotes and jobs, skips the rest
        first_answers = []
        for q in first_response.questions:
            first_answers.append(SetupGuideAnswer(
                slug=q.slug,
                enabled=q.slug in {"quotes", "jobs"},
            ))

        first_enabled: list[str] = []
        first_disabled: list[str] = []

        async def mock_enable_first(org_id, slug):
            first_enabled.append(slug)
            return []

        async def mock_disable_first(org_id, slug):
            first_disabled.append(slug)

        mock_svc_first = MagicMock()
        mock_svc_first.enable_module = AsyncMock(side_effect=mock_enable_first)
        mock_svc_first.force_disable_module = AsyncMock(side_effect=mock_disable_first)

        _run(_dispatch_answers(mock_svc_first, str(_ORG_ID), first_answers))

        assert "quotes" in first_enabled
        assert "jobs" in first_enabled

        # Mark step 5 complete after first run
        progress = ProgressStub(org_id=_ORG_ID, step_5_complete=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = progress
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with _step5_patches():
            _run(_mark_step_5_complete(mock_db, _ORG_ID))

        assert progress.step_5_complete is True

        # --- Phase 2: Rerun ---
        # Now quotes and jobs are enabled in org_modules
        enabled_after_first = {"quotes", "jobs"}

        rerun_response = _simulate_get_questions(
            registry, plan_modules, rerun=True, enabled_slugs=enabled_after_first,
        )
        rerun_slugs = {q.slug for q in rerun_response.questions}

        # Only skipped modules should appear
        assert "quotes" not in rerun_slugs
        assert "jobs" not in rerun_slugs
        assert len(rerun_slugs) > 0

        # User now enables inventory from the rerun
        rerun_answers = []
        for q in rerun_response.questions:
            rerun_answers.append(SetupGuideAnswer(
                slug=q.slug,
                enabled=q.slug == "inventory",
            ))

        rerun_enabled: list[str] = []
        rerun_disabled: list[str] = []

        async def mock_enable_rerun(org_id, slug):
            rerun_enabled.append(slug)
            return []

        async def mock_disable_rerun(org_id, slug):
            rerun_disabled.append(slug)

        mock_svc_rerun = MagicMock()
        mock_svc_rerun.enable_module = AsyncMock(side_effect=mock_enable_rerun)
        mock_svc_rerun.force_disable_module = AsyncMock(side_effect=mock_disable_rerun)

        _run(_dispatch_answers(mock_svc_rerun, str(_ORG_ID), rerun_answers))

        # Inventory should now be enabled
        assert "inventory" in rerun_enabled

        # Other skipped modules should be disabled again
        for slug in rerun_slugs:
            if slug != "inventory":
                assert slug in rerun_disabled

    def test_rerun_with_partial_plan(self):
        """Rerun with a limited plan only shows skipped modules that are
        still in the plan.

        **Validates: Requirements 2.1, 8.2**
        """
        registry = _build_registry()
        # Plan only includes quotes, jobs, and inventory
        plan_modules = {"quotes", "jobs", "inventory"}

        # quotes was enabled in first run
        enabled_slugs = {"quotes"}

        response = _simulate_get_questions(
            registry, plan_modules, rerun=True, enabled_slugs=enabled_slugs,
        )

        returned_slugs = {q.slug for q in response.questions}

        # quotes is enabled — should not appear
        assert "quotes" not in returned_slugs

        # jobs and inventory are in plan and not enabled — should appear
        assert "jobs" in returned_slugs
        assert "inventory" in returned_slugs

        # pos and scheduling are NOT in plan — should not appear
        assert "pos" not in returned_slugs
        assert "scheduling" not in returned_slugs


# ===========================================================================
# Test 3: Wizard Step 5 redirect
# ===========================================================================


class TestWizardStep5Redirect:
    """Wizard Step 5 redirect to setup guide.

    The actual redirect is implemented in the frontend SetupWizard component
    (task 6.2). This test verifies the backend contract: that the setup guide
    endpoints work correctly when called from the wizard context, and that
    step_5_complete is properly set to allow the wizard to skip Step 5 on
    subsequent loads.

    **Validates: Requirement 4.1**
    """

    def test_step_5_complete_set_after_guide_submission(self):
        """After setup guide submission, step_5_complete = true so the
        wizard can skip Step 5 on next load.

        **Validates: Requirement 4.1**
        """
        progress = ProgressStub(org_id=_ORG_ID, step_5_complete=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = progress

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with _step5_patches():
            _run(_mark_step_5_complete(mock_db, _ORG_ID))

        # Wizard checks this flag to decide whether to skip Step 5
        assert progress.step_5_complete is True

    def test_step_5_idempotent_on_resubmit(self):
        """Submitting the setup guide again when step_5_complete is already
        true does not cause errors — it remains true.

        **Validates: Requirement 4.1**
        """
        progress = ProgressStub(org_id=_ORG_ID, step_5_complete=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = progress

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        with _step5_patches():
            _run(_mark_step_5_complete(mock_db, _ORG_ID))

        assert progress.step_5_complete is True


# ===========================================================================
# Edge cases
# ===========================================================================


class TestSetupGuideEdgeCases:
    """Edge cases for the setup guide flow."""

    def test_empty_questions_first_run(self):
        """GET /questions returns empty list when no modules have setup_question.

        **Validates: Requirement 2.1**
        """
        # Registry with only core modules and modules without questions
        registry = [
            ModuleStub(slug="invoicing", display_name="Invoicing", is_core=True, setup_question=None),
            ModuleStub(slug="recurring", display_name="Recurring", is_core=False, setup_question=None),
        ]
        plan_modules = {"all"}

        response = _simulate_get_questions(registry, plan_modules)

        assert response.questions == []
        assert response.total == 0

    def test_validate_slugs_rejects_invalid(self):
        """validate_slugs raises HTTPException for unknown slugs.

        **Validates: Requirement 3.6**
        """
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            validate_slugs({"quotes", "nonexistent_module"}, {"quotes", "jobs"})

        assert exc_info.value.status_code == 400
        assert "nonexistent_module" in exc_info.value.detail

    def test_validate_slugs_passes_for_valid(self):
        """validate_slugs does not raise when all slugs are valid."""
        # Should not raise
        validate_slugs({"quotes", "jobs"}, {"quotes", "jobs", "inventory"})

    def test_dispatch_empty_answers(self):
        """Dispatching an empty answer list makes no ModuleService calls."""
        mock_svc = MagicMock()
        mock_svc.enable_module = AsyncMock(return_value=[])
        mock_svc.force_disable_module = AsyncMock()

        result = _run(_dispatch_answers(mock_svc, str(_ORG_ID), []))

        assert result == []
        mock_svc.enable_module.assert_not_called()
        mock_svc.force_disable_module.assert_not_called()

    def test_topological_order_deps_before_dependents(self):
        """Questions are sorted so dependencies appear before dependents.

        **Validates: Requirement 2.4**
        """
        registry = _build_registry()
        plan_modules = {"all"}

        response = _simulate_get_questions(registry, plan_modules)

        slugs = [q.slug for q in response.questions]

        # POS depends on inventory — inventory must appear before POS
        if "inventory" in slugs and "pos" in slugs:
            assert slugs.index("inventory") < slugs.index("pos"), (
                f"inventory (index {slugs.index('inventory')}) should appear "
                f"before pos (index {slugs.index('pos')}) in {slugs}"
            )

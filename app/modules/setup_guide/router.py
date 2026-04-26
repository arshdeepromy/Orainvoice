"""Setup guide API router.

Endpoints:
- GET  /questions  — return eligible setup guide questions for the org
- POST /submit     — process user answers, enable/disable modules

Logic lives directly in route handlers — no service class needed.

**Validates: Requirements 2.1, 2.2, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.3**
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.modules import DEPENDENCY_GRAPH, ModuleService
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.rbac import require_role
from app.modules.module_management.models import ModuleRegistry, OrgModule
from app.modules.setup_guide.schemas import (
    SetupGuideQuestion,
    SetupGuideQuestionsResponse,
    SetupGuideSubmitRequest,
    SetupGuideSubmitResponse,
)
from app.modules.setup_wizard.models import SetupWizardProgress

logger = logging.getLogger(__name__)

router = APIRouter()

# Modules auto-enabled by trade family — excluded from setup guide questions.
# Matches the CORE_MODULES pattern in app/core/modules.py (small, rarely-changing set).
TRADE_GATED_MODULES: set[str] = {"vehicles"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def filter_eligible_modules(
    registry_modules: list,
    plan_modules: set[str],
    trade_gated: set[str] | None = None,
) -> list:
    """Return modules satisfying all four eligibility conditions.

    Pure function — no DB access. Suitable for property-based testing.

    Conditions:
    1. Module slug is in *plan_modules* (or plan has "all")
    2. ``is_core`` is false
    3. Module slug is NOT in *trade_gated*
    4. ``setup_question`` is not None

    Args:
        registry_modules: Full list of module objects (must have ``.slug``,
            ``.is_core``, ``.setup_question`` attributes).
        plan_modules: Set of module slugs enabled by the subscription plan.
            If the set contains ``"all"``, every module passes the plan check.
        trade_gated: Set of module slugs that are trade-family-gated.
            Defaults to ``TRADE_GATED_MODULES``.

    Returns:
        Filtered list of module objects satisfying all four conditions.
    """
    if trade_gated is None:
        trade_gated = TRADE_GATED_MODULES

    all_available = "all" in plan_modules

    eligible = []
    for mod in registry_modules:
        if mod.is_core:
            continue
        if mod.setup_question is None:
            continue
        if mod.slug in trade_gated:
            continue
        if not all_available and mod.slug not in plan_modules:
            continue
        eligible.append(mod)

    return eligible


def filter_rerun_modules(
    eligible_modules: list,
    enabled_slugs: set[str],
) -> list:
    """Return only modules that are NOT currently enabled for the org.

    Pure function — no DB access. Suitable for property-based testing.

    In rerun mode the guide should only show modules the org previously
    skipped (i.e. modules whose slug is **not** in *enabled_slugs*).

    Args:
        eligible_modules: Modules that already passed base eligibility
            filtering (output of ``filter_eligible_modules``).
        enabled_slugs: Set of module slugs where ``org_modules.is_enabled``
            is ``True`` for the organisation.

    Returns:
        Filtered list containing only modules whose slug is absent from
        *enabled_slugs* (i.e. ``is_enabled = false`` or no record).
    """
    return [mod for mod in eligible_modules if mod.slug not in enabled_slugs]


def validate_slugs(submitted_slugs: set[str], valid_slugs: set[str]) -> None:
    """Validate that all submitted slugs exist in the valid set.

    Pure function — no DB access. Suitable for property-based testing.

    Args:
        submitted_slugs: Set of slugs from the user's submission.
        valid_slugs: Set of slugs that exist in the module registry.

    Raises:
        HTTPException: 400 if any submitted slug is not in *valid_slugs*.
    """
    invalid_slugs = submitted_slugs - valid_slugs
    if invalid_slugs:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid module slug: {', '.join(sorted(invalid_slugs))}",
        )


def _get_org_id(request: Request) -> uuid.UUID:
    """Extract org_id from the request state (set by auth/tenant middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return uuid.UUID(str(org_id))


async def _mark_step_5_complete(
    db: "AsyncSession",
    org_id: uuid.UUID,
) -> None:
    """Mark Step 5 as complete on the org's ``setup_wizard_progress`` record.

    Performs an upsert: if no progress record exists for the org, one is
    created first.  Then ``step_5_complete`` is set to ``True``.

    Suitable for property-based testing with a mocked ``AsyncSession``.

    Args:
        db: An ``AsyncSession`` (or mock).
        org_id: The organisation UUID.
    """
    stmt_progress = select(SetupWizardProgress).where(
        SetupWizardProgress.org_id == org_id
    )
    result_progress = await db.execute(stmt_progress)
    progress = result_progress.scalar_one_or_none()

    if progress is None:
        progress = SetupWizardProgress(org_id=org_id)
        db.add(progress)
        await db.flush()

    progress.step_5_complete = True
    await db.flush()


async def _dispatch_answers(
    svc: "ModuleService",
    org_id_str: str,
    answers: list,
) -> list[str]:
    """Dispatch each answer to the appropriate ModuleService method.

    Pure dispatch logic — no DB queries, no validation. Suitable for
    property-based testing with a mocked ``ModuleService``.

    For each answer:
    - ``enabled = True``  → ``svc.enable_module(org_id_str, slug)``
    - ``enabled = False`` → ``svc.force_disable_module(org_id_str, slug)``

    Args:
        svc: A ``ModuleService`` instance (or mock).
        org_id_str: The organisation ID as a string.
        answers: List of objects with ``.slug`` and ``.enabled`` attributes.

    Returns:
        Flat list of auto-enabled dependency slugs (from ``enable_module`` calls).
    """
    all_auto_enabled: list[str] = []
    for answer in answers:
        if answer.enabled:
            auto_deps = await svc.enable_module(org_id_str, answer.slug)
            all_auto_enabled.extend(auto_deps)
        else:
            await svc.force_disable_module(org_id_str, answer.slug)
    return all_auto_enabled


def _topological_sort(slugs: set[str]) -> list[str]:
    """Sort module slugs so dependencies appear before dependents.

    Uses Kahn's algorithm over the subset of DEPENDENCY_GRAPH that
    intersects with *slugs*. Modules not in the graph are appended at
    the end in alphabetical order for determinism.
    """
    # Build adjacency and in-degree for the relevant subset
    in_degree: dict[str, int] = {s: 0 for s in slugs}
    adj: dict[str, list[str]] = {s: [] for s in slugs}

    for slug in slugs:
        for dep in DEPENDENCY_GRAPH.get(slug, []):
            if dep in slugs:
                adj[dep].append(slug)
                in_degree[slug] += 1

    # Kahn's algorithm — use sorted() on the queue seed for determinism
    queue = sorted(s for s in slugs if in_degree[s] == 0)
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbour in sorted(adj[node]):
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)
                queue.sort()

    # Any remaining slugs (cycle or disconnected) — append alphabetically
    remaining = sorted(slugs - set(result))
    result.extend(remaining)

    return result


# ---------------------------------------------------------------------------
# GET /questions
# ---------------------------------------------------------------------------


@router.get(
    "/questions",
    response_model=SetupGuideQuestionsResponse,
    summary="Get setup guide questions for the organisation",
    dependencies=[require_role("org_admin")],
)
async def get_questions(
    request: Request,
    rerun: bool = Query(False, description="If true, only show previously-skipped modules"),
    db: AsyncSession = Depends(get_db_session),
) -> SetupGuideQuestionsResponse:
    """Return eligible setup guide questions for the authenticated org.

    Filters: non-core, has setup_question, not trade-gated, in subscription plan.
    If rerun=true, additionally filters to modules with is_enabled=false.
    Results are sorted in topological (dependency) order.
    """
    org_id = _get_org_id(request)

    # 1. Get the org's subscription plan enabled_modules
    stmt_org = select(Organisation.plan_id).where(Organisation.id == org_id)
    result_org = await db.execute(stmt_org)
    plan_id = result_org.scalar_one_or_none()

    plan_modules: set[str] = set()
    if plan_id:
        stmt_plan = select(SubscriptionPlan.enabled_modules).where(
            SubscriptionPlan.id == plan_id
        )
        result_plan = await db.execute(stmt_plan)
        enabled_modules_raw = result_plan.scalar_one_or_none()
        if enabled_modules_raw and isinstance(enabled_modules_raw, list):
            plan_modules = set(enabled_modules_raw)

    # 2. Query module_registry for all modules (filter in Python for testability)
    stmt_modules = select(ModuleRegistry)
    result_modules = await db.execute(stmt_modules)
    registry_modules = result_modules.scalars().all()

    # 3. Filter using the pure helper (non-core, has question, not trade-gated, in plan)
    eligible = filter_eligible_modules(registry_modules, plan_modules)

    # 4. If rerun=true, additionally filter to modules where org_modules.is_enabled = false
    if rerun:
        # Get all enabled module slugs for this org
        stmt_enabled = select(OrgModule.module_slug).where(
            and_(
                OrgModule.org_id == org_id,
                OrgModule.is_enabled == True,  # noqa: E712
            )
        )
        result_enabled = await db.execute(stmt_enabled)
        enabled_slugs = {row for row in result_enabled.scalars().all()}

        eligible = filter_rerun_modules(eligible, enabled_slugs)

    # 5. Sort by topological order
    eligible_slugs = {mod.slug for mod in eligible}
    sorted_slugs = _topological_sort(eligible_slugs)

    # Build a lookup for quick access
    mod_by_slug = {mod.slug: mod for mod in eligible}

    # 6. Build response
    questions = []
    for slug in sorted_slugs:
        mod = mod_by_slug[slug]
        deps = mod.dependencies or []
        if isinstance(deps, str):
            import json
            try:
                deps = json.loads(deps)
            except (ValueError, TypeError):
                deps = []
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


# ---------------------------------------------------------------------------
# POST /submit
# ---------------------------------------------------------------------------


@router.post(
    "/submit",
    response_model=SetupGuideSubmitResponse,
    summary="Submit setup guide answers",
    dependencies=[require_role("org_admin")],
)
async def submit_answers(
    request: Request,
    payload: SetupGuideSubmitRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SetupGuideSubmitResponse:
    """Process setup guide answers: enable/disable modules and mark Step 5 complete.

    Validates all slugs exist in module_registry, then delegates to
    ModuleService for enable/disable with dependency resolution.
    """
    org_id = _get_org_id(request)
    org_id_str = str(org_id)

    # 1. Validate all slugs exist in module_registry
    submitted_slugs = {answer.slug for answer in payload.answers}
    stmt_registry = select(ModuleRegistry.slug).where(
        ModuleRegistry.slug.in_(submitted_slugs)
    )
    result_registry = await db.execute(stmt_registry)
    valid_slugs = {row for row in result_registry.scalars().all()}

    validate_slugs(submitted_slugs, valid_slugs)

    # 2. Process answers via ModuleService
    svc = ModuleService(db)
    all_auto_enabled = await _dispatch_answers(svc, org_id_str, payload.answers)

    # 3. Mark step_5_complete on setup_wizard_progress (upsert)
    await _mark_step_5_complete(db, org_id)

    # Deduplicate auto-enabled list
    unique_auto_enabled = list(dict.fromkeys(all_auto_enabled))

    return SetupGuideSubmitResponse(
        completed=True,
        auto_enabled=unique_auto_enabled,
        message="Setup guide completed successfully",
    )

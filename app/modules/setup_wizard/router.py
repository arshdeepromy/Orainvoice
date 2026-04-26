"""Setup wizard API router.

Endpoints:
- POST /api/v2/setup-wizard/step/{step_number}  — submit or skip a step
- GET  /api/v2/setup-wizard/progress             — get wizard progress

**Validates: Requirement 5.1, 5.6, 5.8**
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.setup_wizard.schemas import (
    StepResult,
    WizardProgressResponse,
    WizardStepRequest,
)
from app.modules.setup_wizard.service import SetupWizardService

router = APIRouter()


def _get_org_id(request: Request) -> uuid.UUID:
    """Extract org_id from the request state (set by auth/tenant middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return uuid.UUID(str(org_id))


@router.post(
    "/step/{step_number}",
    response_model=StepResult,
    summary="Submit or skip a wizard step",
)
async def submit_wizard_step(
    step_number: int,
    payload: WizardStepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StepResult:
    """Process a setup wizard step.

    Send ``skip: true`` to skip the step with defaults.
    """
    org_id = _get_org_id(request)
    svc = SetupWizardService(db)

    try:
        if payload.skip:
            return await svc.skip_step(org_id, step_number)
        return await svc.process_step(org_id, step_number, payload.data)
    except ValueError as exc:
        import logging
        logging.getLogger(__name__).error(
            "Wizard step %s ValueError for org %s: %s", step_number, org_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Wizard step %s unexpected error for org %s: %s", step_number, org_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/progress",
    response_model=WizardProgressResponse | None,
    summary="Get wizard completion state",
)
async def get_wizard_progress(
    request: Request,
    create: bool = True,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current wizard progress for the authenticated org.

    If ``create=false``, returns 404 when no progress record exists
    instead of auto-creating one. Useful for checking whether the org
    has ever interacted with the wizard.
    """
    org_id = _get_org_id(request)
    svc = SetupWizardService(db)

    if not create:
        progress = await svc.get_progress(org_id)
        if progress is None:
            raise HTTPException(status_code=404, detail="No wizard progress found")
    else:
        progress = await svc.get_or_create_progress(org_id)

    return WizardProgressResponse(
        org_id=progress.org_id,
        steps={
            f"step_{i}": getattr(progress, f"step_{i}_complete")
            for i in range(1, 8)
        },
        wizard_completed=progress.wizard_completed,
        completed_at=progress.completed_at,
        created_at=progress.created_at,
        updated_at=progress.updated_at,
    )

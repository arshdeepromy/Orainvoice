"""Checklist template lifecycle and submission lifecycle.

Implements: B2B Fleet Portal tasks 8.1, 9.1 — Requirements 8.1–8.8,
9.1–9.10.

Property 18 (NZTA seed idempotency), Property 19 (one default per
fleet), Property 20 (template resolution precedence: vehicle override
→ fleet default → NZTA seed), Property 22 (no hard-delete when
submissions reference the template), Property 23 (photo evidence at
completion), Property 24 (counts finalised at complete).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import (
    FleetChecklistSubmission,
    FleetChecklistSubmissionItem,
    FleetChecklistTemplate,
    FleetChecklistTemplateItem,
    FleetDriverAssignment,
)
from app.modules.fleet_portal.nzta_template import nzta_items


# ---------------------------------------------------------------------------
# Seeding (Property 18)
# ---------------------------------------------------------------------------


async def seed_nzta_default_for_fleet(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    fleet_account_id: uuid.UUID,
) -> FleetChecklistTemplate:
    """Idempotently seed the NZTA default template for a fleet.

    Property 18: any number of repeated calls produces exactly one
    ``is_system_seeded = true`` template per fleet, with the canonical
    item set.
    """
    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.org_id == org_id,
            FleetChecklistTemplate.fleet_account_id == fleet_account_id,
            FleetChecklistTemplate.is_system_seeded.is_(True),
        )
    )
    existing = res.scalars().first()
    if existing is not None:
        return existing

    template = FleetChecklistTemplate(
        org_id=org_id,
        fleet_account_id=fleet_account_id,
        name="NZTA Pre-Trip Inspection (Default)",
        description="System-seeded NZTA-compliant pre-trip safety items.",
        is_default=True,
        is_system_seeded=True,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    # Seed items in canonical order.
    for item in nzta_items():
        db.add(
            FleetChecklistTemplateItem(
                org_id=org_id,
                template_id=template.id,
                category=item.category,
                label=item.label,
                requires_photo_on_fail=item.requires_photo_on_fail,
                display_order=item.display_order,
            )
        )
    await db.flush()
    return template


# ---------------------------------------------------------------------------
# Default template (Property 19)
# ---------------------------------------------------------------------------


async def set_default_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    fleet_account_id: uuid.UUID,
    template_id: uuid.UUID,
) -> None:
    """Move the ``is_default`` flag onto a single template.

    Property 19: at most one default per fleet. The function clears
    every existing default in the same transaction before setting the
    new one — this is safe because the partial unique index
    ``(fleet_account_id) WHERE is_default = true`` would otherwise
    reject the second update.
    """
    # Clear existing defaults
    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.org_id == org_id,
            FleetChecklistTemplate.fleet_account_id == fleet_account_id,
            FleetChecklistTemplate.is_default.is_(True),
        )
    )
    for t in res.scalars().all():
        t.is_default = False
    await db.flush()

    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.id == template_id,
            FleetChecklistTemplate.org_id == org_id,
            FleetChecklistTemplate.fleet_account_id == fleet_account_id,
        )
    )
    target = res.scalars().first()
    if target is None:
        raise ValueError("Template not found")
    target.is_default = True
    await db.flush()


# ---------------------------------------------------------------------------
# Resolution (Property 20)
# ---------------------------------------------------------------------------


async def resolve_template_for_vehicle(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    fleet_account_id: uuid.UUID,
    customer_vehicle_id: uuid.UUID,
) -> FleetChecklistTemplate | None:
    """Property 20 precedence: vehicle override → fleet default → NZTA seed."""
    from app.modules.vehicles.models import CustomerVehicle

    res = await db.execute(
        select(CustomerVehicle).where(
            CustomerVehicle.id == customer_vehicle_id,
            CustomerVehicle.org_id == org_id,
        )
    )
    cv = res.scalars().first()
    if cv is None:
        return None

    # 1) Per-vehicle override
    if cv.fleet_checklist_template_id is not None:
        res = await db.execute(
            select(FleetChecklistTemplate).where(
                FleetChecklistTemplate.id == cv.fleet_checklist_template_id,
                FleetChecklistTemplate.archived_at.is_(None),
            )
        )
        t = res.scalars().first()
        if t is not None:
            return t

    # 2) Fleet default
    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.org_id == org_id,
            FleetChecklistTemplate.fleet_account_id == fleet_account_id,
            FleetChecklistTemplate.is_default.is_(True),
            FleetChecklistTemplate.archived_at.is_(None),
        )
    )
    t = res.scalars().first()
    if t is not None:
        return t

    # 3) NZTA seed (also serves as fallback)
    return await seed_nzta_default_for_fleet(
        db, org_id=org_id, fleet_account_id=fleet_account_id
    )


# ---------------------------------------------------------------------------
# Submission lifecycle
# ---------------------------------------------------------------------------


async def start_submission(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
) -> FleetChecklistSubmission:
    """Open a new submission, snapshotting items from the resolved template."""
    if ctx.fleet_account_id is None:
        raise ValueError("No fleet account context")

    # Drivers must have an assignment (Property 13).
    if ctx.portal_user_role == "driver":
        res = await db.execute(
            select(FleetDriverAssignment).where(
                FleetDriverAssignment.portal_account_id == ctx.portal_account_id,
                FleetDriverAssignment.customer_vehicle_id == customer_vehicle_id,
            )
        )
        if res.scalars().first() is None:
            raise PermissionError("Driver is not assigned to this vehicle")

    template = await resolve_template_for_vehicle(
        db,
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        customer_vehicle_id=customer_vehicle_id,
    )
    if template is None:
        raise ValueError("No checklist template resolvable for this vehicle")

    submission = FleetChecklistSubmission(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        customer_vehicle_id=customer_vehicle_id,
        template_id=template.id,
        portal_account_id=ctx.portal_account_id,
        status="in_progress",
        started_at=datetime.now(timezone.utc),
    )
    db.add(submission)
    await db.flush()

    # Snapshot items
    template_items = (
        await db.execute(
            select(FleetChecklistTemplateItem).where(
                FleetChecklistTemplateItem.template_id == template.id
            ).order_by(FleetChecklistTemplateItem.display_order)
        )
    ).scalars().all()
    for ti in template_items:
        db.add(
            FleetChecklistSubmissionItem(
                org_id=ctx.org_id,
                submission_id=submission.id,
                template_item_id=ti.id,
                category=ti.category,
                label=ti.label,
                requires_photo_on_fail=ti.requires_photo_on_fail,
            )
        )
    await db.flush()
    await db.refresh(submission)
    return submission


def submission_can_complete(items: list[FleetChecklistSubmissionItem]) -> tuple[bool, str | None]:
    """Property 23 — every failed item with requires_photo_on_fail must
    have at least one photo. Returns ``(ok, reason_or_none)``.
    """
    for item in items:
        if (
            item.requires_photo_on_fail
            and item.result == "fail"
            and not (item.photo_urls or [])
        ):
            return False, f"Photo required for failed item: {item.label}"
    return True, None


async def complete_submission(
    db: AsyncSession,
    *,
    submission_id: uuid.UUID,
    org_id: uuid.UUID,
) -> FleetChecklistSubmission:
    """Finalise a submission and write Property 24 counts."""
    res = await db.execute(
        select(FleetChecklistSubmission).where(
            FleetChecklistSubmission.id == submission_id,
            FleetChecklistSubmission.org_id == org_id,
        )
    )
    s = res.scalars().first()
    if s is None:
        raise ValueError("Submission not found")
    if s.status != "in_progress":
        raise ValueError("Submission is not in progress")

    items = (
        await db.execute(
            select(FleetChecklistSubmissionItem).where(
                FleetChecklistSubmissionItem.submission_id == s.id
            )
        )
    ).scalars().all()

    ok, reason = submission_can_complete(list(items))
    if not ok:
        raise ValueError(reason or "Submission cannot be completed")

    s.passed_item_count = sum(1 for i in items if i.result == "pass")
    s.failed_item_count = sum(1 for i in items if i.result == "fail")
    s.na_item_count = sum(1 for i in items if i.result == "na")
    s.status = "completed"
    s.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(s)

    # Emit fleet_checklist_failure notification if any items failed (Req 9.7)
    if s.failed_item_count > 0:
        try:
            from app.modules.fleet_portal.services import audit_service
            await audit_service.log_event(
                db,
                org_id=org_id,
                action="fleet_checklist_failure",
                portal_account_id=s.portal_account_id,
                details={
                    "submission_id": str(s.id),
                    "vehicle_id": str(s.customer_vehicle_id),
                    "failed_count": s.failed_item_count,
                },
            )
        except Exception:
            pass  # Non-critical

        # In-app notification to workshop admins + fleet admin (Req 9.7)
        try:
            from app.modules.in_app_notifications.service import create_in_app_notification
            await create_in_app_notification(
                db,
                org_id=org_id,
                category="fleet_checklist_failure",
                severity="warning",
                title=f"Pre-trip checklist failed ({s.failed_item_count} item{'s' if s.failed_item_count != 1 else ''})",
                body=f"A fleet vehicle failed its pre-trip inspection with {s.failed_item_count} failed item(s).",
                link_url="/fleet-portal-admin/bookings",
                entity_type="fleet_checklist_submission",
                entity_id=s.id,
                audience_roles=["org_admin", "admin", "fleet_admin"],
            )
        except Exception:
            pass  # Non-critical — notification failure must not break submission

    return s


__all__ = [
    "seed_nzta_default_for_fleet",
    "set_default_template",
    "resolve_template_for_vehicle",
    "start_submission",
    "submission_can_complete",
    "complete_submission",
]

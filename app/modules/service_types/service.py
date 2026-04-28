"""Business logic for Service Types CRUD.

All functions use ``db.flush()`` (not ``db.commit()``) — the
``session.begin()`` context manager auto-commits.

Requirements: 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 6.3, 7.1, 7.2, 7.4
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.job_cards.models import JobCard
from app.modules.service_types.models import (
    JobCardServiceTypeValue,
    ServiceType,
    ServiceTypeField,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service_type_to_dict(service_type: ServiceType) -> dict:
    """Convert a ServiceType ORM instance (with eager-loaded fields) to a
    serialisable dict suitable for Pydantic response models.
    """
    return {
        "id": str(service_type.id),
        "name": service_type.name,
        "description": service_type.description,
        "is_active": service_type.is_active,
        "fields": [
            {
                "id": str(f.id),
                "label": f.label,
                "field_type": f.field_type,
                "display_order": f.display_order,
                "is_required": f.is_required,
                "options": f.options,
            }
            for f in service_type.fields
        ],
        "created_at": (
            service_type.created_at.isoformat()
            if service_type.created_at
            else None
        ),
        "updated_at": (
            service_type.updated_at.isoformat()
            if service_type.updated_at
            else None
        ),
    }


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


async def create_service_type(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    description: str | None = None,
    is_active: bool = True,
    fields: list[dict] | None = None,
) -> dict:
    """Create a new service type with optional field definitions.

    Requirements: 1.4, 2.1
    """
    service_type = ServiceType(
        org_id=org_id,
        name=name,
        description=description,
        is_active=is_active,
    )
    db.add(service_type)
    await db.flush()

    if fields:
        for f in fields:
            field = ServiceTypeField(
                service_type_id=service_type.id,
                label=f["label"],
                field_type=f["field_type"],
                display_order=f.get("display_order", 0),
                is_required=f.get("is_required", False),
                options=f.get("options"),
            )
            db.add(field)
        await db.flush()

    await db.refresh(service_type, ["fields"])
    return _service_type_to_dict(service_type)


async def list_service_types(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List service types for an organisation with pagination.

    Requirements: 2.2
    """
    filters = [ServiceType.org_id == org_id]

    if active_only:
        filters.append(ServiceType.is_active.is_(True))

    # Total count
    count_stmt = select(func.count(ServiceType.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginated query with eager-loaded fields
    stmt = (
        select(ServiceType)
        .options(selectinload(ServiceType.fields))
        .where(*filters)
        .order_by(ServiceType.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    service_types = result.scalars().unique().all()

    return {
        "service_types": [_service_type_to_dict(st) for st in service_types],
        "total": total,
    }


async def get_service_type(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    service_type_id: uuid.UUID,
) -> dict:
    """Fetch a single service type with its field definitions.

    Raises ``ValueError`` if not found.

    Requirements: 2.3
    """
    stmt = (
        select(ServiceType)
        .options(selectinload(ServiceType.fields))
        .where(
            ServiceType.id == service_type_id,
            ServiceType.org_id == org_id,
        )
    )
    result = await db.execute(stmt)
    service_type = result.scalar_one_or_none()

    if service_type is None:
        raise ValueError("Service type not found")

    return _service_type_to_dict(service_type)


async def update_service_type(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    service_type_id: uuid.UUID,
    **kwargs,
) -> dict:
    """Update a service type. Only provided kwargs are applied.

    If ``fields`` key is present and not None, performs full replacement
    of field definitions (Requirement 2.5).

    Requirements: 2.4, 2.5
    """
    stmt = (
        select(ServiceType)
        .options(selectinload(ServiceType.fields))
        .where(
            ServiceType.id == service_type_id,
            ServiceType.org_id == org_id,
        )
    )
    result = await db.execute(stmt)
    service_type = result.scalar_one_or_none()

    if service_type is None:
        raise ValueError("Service type not found")

    # Update scalar fields
    for attr in ("name", "description", "is_active"):
        if attr in kwargs and kwargs[attr] is not None:
            setattr(service_type, attr, kwargs[attr])

    # Full replacement of field definitions when fields key is present
    if "fields" in kwargs and kwargs["fields"] is not None:
        # Delete all existing fields
        await db.execute(
            delete(ServiceTypeField).where(
                ServiceTypeField.service_type_id == service_type_id
            )
        )
        # Insert new fields
        for f in kwargs["fields"]:
            field = ServiceTypeField(
                service_type_id=service_type_id,
                label=f["label"],
                field_type=f["field_type"],
                display_order=f.get("display_order", 0),
                is_required=f.get("is_required", False),
                options=f.get("options"),
            )
            db.add(field)

    await db.flush()
    await db.refresh(service_type, ["fields"])
    return _service_type_to_dict(service_type)


async def delete_service_type(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    service_type_id: uuid.UUID,
) -> dict | None:
    """Delete a service type if it is not referenced by any job cards.

    Returns ``None`` on success.
    Returns ``{"status": 409, "detail": "..."}`` if referenced by job cards.
    Raises ``ValueError`` if not found.

    Requirements: 2.6, 2.7
    """
    # Fetch the service type
    stmt = select(ServiceType).where(
        ServiceType.id == service_type_id,
        ServiceType.org_id == org_id,
    )
    result = await db.execute(stmt)
    service_type = result.scalar_one_or_none()

    if service_type is None:
        raise ValueError("Service type not found")

    # Check for FK references in job_cards
    ref_count_stmt = select(func.count(JobCard.id)).where(
        JobCard.service_type_id == service_type_id
    )
    ref_count = (await db.execute(ref_count_stmt)).scalar() or 0

    if ref_count > 0:
        return {
            "status": 409,
            "detail": (
                "Cannot delete: this service type is referenced by "
                "existing job cards. Deactivate it instead."
            ),
        }

    await db.delete(service_type)
    await db.flush()
    return None


# ---------------------------------------------------------------------------
# Job card field value storage / retrieval
# ---------------------------------------------------------------------------


async def save_service_type_values(
    db: AsyncSession,
    *,
    job_card_id: uuid.UUID,
    service_type_id: uuid.UUID,
    values: list[dict],
) -> None:
    """Store field values for a service type on a job card.

    Uses upsert pattern: deletes existing values for the job card first,
    then inserts the new set.

    Each dict in ``values`` has:
      - ``field_id`` (str | UUID): the ServiceTypeField ID
      - ``value_text`` (str | None): text/number value
      - ``value_array`` (list | None): array value for multi_select

    Requirements: 6.3, 7.1, 7.2
    """
    # Delete existing values for this job card
    await db.execute(
        delete(JobCardServiceTypeValue).where(
            JobCardServiceTypeValue.job_card_id == job_card_id
        )
    )

    # Insert new values
    for v in values:
        field_id = v.get("field_id")
        if not field_id:
            continue
        val = JobCardServiceTypeValue(
            job_card_id=job_card_id,
            field_id=uuid.UUID(str(field_id)) if not isinstance(field_id, uuid.UUID) else field_id,
            value_text=v.get("value_text"),
            value_array=v.get("value_array"),
        )
        db.add(val)

    await db.flush()


async def get_service_type_values(
    db: AsyncSession,
    *,
    job_card_id: uuid.UUID,
) -> list[dict]:
    """Return field values for a job card with field label and type info.

    Joins ``job_card_service_type_values`` with ``service_type_fields``
    to include the field label and field_type for display.

    Requirements: 7.4
    """
    stmt = (
        select(
            JobCardServiceTypeValue.id,
            JobCardServiceTypeValue.field_id,
            JobCardServiceTypeValue.value_text,
            JobCardServiceTypeValue.value_array,
            ServiceTypeField.label,
            ServiceTypeField.field_type,
        )
        .join(
            ServiceTypeField,
            JobCardServiceTypeValue.field_id == ServiceTypeField.id,
        )
        .where(JobCardServiceTypeValue.job_card_id == job_card_id)
        .order_by(ServiceTypeField.display_order)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(row.id),
            "field_id": str(row.field_id),
            "value_text": row.value_text,
            "value_array": row.value_array,
            "label": row.label,
            "field_type": row.field_type,
        }
        for row in rows
    ]

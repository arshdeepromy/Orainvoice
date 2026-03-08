"""Append-only audit log helper.

Writes entries to the ``audit_log`` table.  The table is configured at the
database level with ``REVOKE UPDATE, DELETE`` on the application role, making
it tamper-evident.  This module only ever INSERTs.

Usage::

    from app.core.audit import write_audit_log

    await write_audit_log(
        session=db,
        org_id=request.state.org_id,
        user_id=request.state.user_id,
        action="invoice.issued",
        entity_type="invoice",
        entity_id=invoice.id,
        before_value=None,
        after_value={"status": "issued", "number": "INV-0042"},
        ip_address=request.client.host,
        device_info=request.headers.get("user-agent"),
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def write_audit_log(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    org_id: str | uuid.UUID | None = None,
    user_id: str | uuid.UUID | None = None,
    entity_id: str | uuid.UUID | None = None,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
    ip_address: str | None = None,
    device_info: str | None = None,
) -> uuid.UUID:
    """Insert a single audit log entry and return its ID.

    Parameters
    ----------
    session:
        An active ``AsyncSession`` (typically from ``get_db_session``).
    action:
        A dot-separated verb describing what happened, e.g.
        ``"invoice.issued"``, ``"auth.login_success"``.
    entity_type:
        The kind of entity affected (``"invoice"``, ``"user"``, …).
    org_id:
        Organisation context (``None`` for global admin actions).
    user_id:
        The acting user (``None`` for system-initiated actions).
    entity_id:
        Primary key of the affected entity.
    before_value / after_value:
        JSON-serialisable dicts capturing the state change.
    ip_address:
        Client IP address.
    device_info:
        User-Agent or similar device descriptor.
    """
    import json

    entry_id = uuid.uuid4()

    await session.execute(
        text(
            """
            INSERT INTO audit_log (
                id, org_id, user_id, action, entity_type, entity_id,
                before_value, after_value, ip_address, device_info, created_at
            ) VALUES (
                :id, :org_id, :user_id, :action, :entity_type, :entity_id,
                :before_value, :after_value, CAST(:ip_address AS inet), :device_info, :created_at
            )
            """
        ),
        {
            "id": str(entry_id),
            "org_id": str(org_id) if org_id else None,
            "user_id": str(user_id) if user_id else None,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "before_value": json.dumps(before_value) if before_value else None,
            "after_value": json.dumps(after_value) if after_value else None,
            "ip_address": ip_address,
            "device_info": device_info,
            "created_at": datetime.now(timezone.utc),
        },
    )

    return entry_id

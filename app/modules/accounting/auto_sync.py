"""Fire-and-forget background helpers for auto-syncing entities to Xero/MYOB.

Each helper creates its own DB session (via async_session_factory) since
BackgroundTasks / asyncio.create_task run after the response is sent and
the request session is closed.

Usage in routers:
    import asyncio
    from app.modules.accounting.auto_sync import sync_invoice_bg, sync_payment_bg, sync_credit_note_bg, sync_refund_bg
    asyncio.create_task(sync_invoice_bg(org_id, invoice_data))
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def _has_active_xero_connection(session, org_id: uuid.UUID) -> bool:
    """Check if the org has an active Xero connection (lightweight query)."""
    from sqlalchemy import select
    from app.modules.accounting.models import AccountingIntegration

    stmt = select(AccountingIntegration.id).where(
        AccountingIntegration.org_id == org_id,
        AccountingIntegration.provider == "xero",
        AccountingIntegration.is_connected == True,  # noqa: E712
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def sync_invoice_bg(org_id: uuid.UUID, invoice_data: dict[str, Any]) -> None:
    """Background: sync a newly created invoice to Xero if connected."""
    from app.core.database import async_session_factory
    from app.modules.accounting.service import sync_entity

    try:
        async with async_session_factory() as session:
            async with session.begin():
                if not await _has_active_xero_connection(session, org_id):
                    return
                entity_id = (
                    uuid.UUID(invoice_data["id"])
                    if isinstance(invoice_data.get("id"), str)
                    else invoice_data.get("id", uuid.uuid4())
                )
                await sync_entity(
                    session,
                    org_id=org_id,
                    provider="xero",
                    entity_type="invoice",
                    entity_id=entity_id,
                    entity_data=invoice_data,
                )
    except Exception as exc:
        logger.exception("Background Xero invoice sync failed for org %s", org_id)
        # Log the failure to the sync log so it appears in the UI and can be retried
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    from app.modules.accounting.service import _log_sync
                    eid = uuid.UUID(invoice_data["id"]) if isinstance(invoice_data.get("id"), str) else uuid.uuid4()
                    await _log_sync(
                        session, org_id=org_id, provider="xero", entity_type="invoice",
                        entity_id=eid, status="failed", error_message=str(exc)[:500],
                    )
        except Exception:
            logger.exception("Failed to log invoice sync failure for org %s", org_id)


async def sync_payment_bg(org_id: uuid.UUID, payment_data: dict[str, Any]) -> None:
    """Background: sync a newly recorded payment to Xero if connected."""
    from app.core.database import async_session_factory
    from app.modules.accounting.service import sync_entity

    try:
        async with async_session_factory() as session:
            async with session.begin():
                if not await _has_active_xero_connection(session, org_id):
                    return
                entity_id = (
                    uuid.UUID(payment_data["id"])
                    if isinstance(payment_data.get("id"), str)
                    else payment_data.get("id", uuid.uuid4())
                )
                await sync_entity(
                    session,
                    org_id=org_id,
                    provider="xero",
                    entity_type="payment",
                    entity_id=entity_id,
                    entity_data=payment_data,
                )
    except Exception as exc:
        logger.exception("Background Xero payment sync failed for org %s", org_id)
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    from app.modules.accounting.service import _log_sync
                    eid = uuid.UUID(payment_data["id"]) if isinstance(payment_data.get("id"), str) else uuid.uuid4()
                    await _log_sync(
                        session, org_id=org_id, provider="xero", entity_type="payment",
                        entity_id=eid, status="failed", error_message=str(exc)[:500],
                    )
        except Exception:
            logger.exception("Failed to log payment sync failure for org %s", org_id)


async def sync_credit_note_bg(org_id: uuid.UUID, cn_data: dict[str, Any]) -> None:
    """Background: sync a newly created credit note to Xero if connected."""
    from app.core.database import async_session_factory
    from app.modules.accounting.service import sync_entity

    try:
        async with async_session_factory() as session:
            async with session.begin():
                if not await _has_active_xero_connection(session, org_id):
                    return
                entity_id = (
                    uuid.UUID(cn_data["id"])
                    if isinstance(cn_data.get("id"), str)
                    else cn_data.get("id", uuid.uuid4())
                )
                await sync_entity(
                    session,
                    org_id=org_id,
                    provider="xero",
                    entity_type="credit_note",
                    entity_id=entity_id,
                    entity_data=cn_data,
                )
    except Exception as exc:
        logger.exception("Background Xero credit note sync failed for org %s", org_id)
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    from app.modules.accounting.service import _log_sync
                    eid = uuid.UUID(cn_data["id"]) if isinstance(cn_data.get("id"), str) else uuid.uuid4()
                    await _log_sync(
                        session, org_id=org_id, provider="xero", entity_type="credit_note",
                        entity_id=eid, status="failed", error_message=str(exc)[:500],
                    )
        except Exception:
            logger.exception("Failed to log credit note sync failure for org %s", org_id)


async def sync_refund_bg(org_id: uuid.UUID, refund_data: dict[str, Any]) -> None:
    """Background: sync a newly processed refund to Xero if connected."""
    from app.core.database import async_session_factory
    from app.modules.accounting.service import sync_entity

    try:
        async with async_session_factory() as session:
            async with session.begin():
                if not await _has_active_xero_connection(session, org_id):
                    return
                entity_id = (
                    uuid.UUID(refund_data["id"])
                    if isinstance(refund_data.get("id"), str)
                    else refund_data.get("id", uuid.uuid4())
                )
                await sync_entity(
                    session,
                    org_id=org_id,
                    provider="xero",
                    entity_type="refund",
                    entity_id=entity_id,
                    entity_data=refund_data,
                )
    except Exception as exc:
        logger.exception("Background Xero refund sync failed for org %s", org_id)
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    from app.modules.accounting.service import _log_sync
                    eid = uuid.UUID(refund_data["id"]) if isinstance(refund_data.get("id"), str) else uuid.uuid4()
                    await _log_sync(
                        session, org_id=org_id, provider="xero", entity_type="refund",
                        entity_id=eid, status="failed", error_message=str(exc)[:500],
                    )
        except Exception:
            logger.exception("Failed to log refund sync failure for org %s", org_id)

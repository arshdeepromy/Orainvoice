"""Async accounting software sync — Xero and MYOB.

All functions are plain async — called directly from the app layer.

Requirements: 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("xero", "myob")
MAX_RETRIES = 3
RETRY_BACKOFF = 60


async def sync_invoice_to_accounting_task(*, org_id: str, entity_id: str, provider: str, invoice_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sync an invoice to Xero or MYOB. Requirements: 68.3"""
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "entity_id": entity_id}
    try:
        from app.core.database import async_session_factory, _set_rls_org_id
        from app.modules.accounting.service import sync_entity
        async with async_session_factory() as session:
            async with session.begin():
                await _set_rls_org_id(session, org_id)
                return await sync_entity(session, org_id=uuid.UUID(org_id), provider=provider, entity_type="invoice", entity_id=uuid.UUID(entity_id), entity_data=invoice_data or {})
    except Exception as exc:
        logger.exception("Invoice sync error for %s: %s", entity_id, exc)
        return {"error": str(exc), "entity_id": entity_id}


async def sync_payment_to_accounting_task(*, org_id: str, entity_id: str, provider: str, payment_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sync a payment to Xero or MYOB. Requirements: 68.4"""
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "entity_id": entity_id}
    try:
        from app.core.database import async_session_factory, _set_rls_org_id
        from app.modules.accounting.service import sync_entity
        async with async_session_factory() as session:
            async with session.begin():
                await _set_rls_org_id(session, org_id)
                return await sync_entity(session, org_id=uuid.UUID(org_id), provider=provider, entity_type="payment", entity_id=uuid.UUID(entity_id), entity_data=payment_data or {})
    except Exception as exc:
        logger.exception("Payment sync error for %s: %s", entity_id, exc)
        return {"error": str(exc), "entity_id": entity_id}


async def sync_credit_note_to_accounting_task(*, org_id: str, entity_id: str, provider: str, credit_note_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sync a credit note to Xero or MYOB. Requirements: 68.5"""
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "entity_id": entity_id}
    try:
        from app.core.database import async_session_factory, _set_rls_org_id
        from app.modules.accounting.service import sync_entity
        async with async_session_factory() as session:
            async with session.begin():
                await _set_rls_org_id(session, org_id)
                return await sync_entity(session, org_id=uuid.UUID(org_id), provider=provider, entity_type="credit_note", entity_id=uuid.UUID(entity_id), entity_data=credit_note_data or {})
    except Exception as exc:
        logger.exception("Credit note sync error for %s: %s", entity_id, exc)
        return {"error": str(exc), "entity_id": entity_id}


async def retry_failed_sync_task(*, org_id: str, provider: str) -> dict[str, Any]:
    """Retry all failed sync operations for a provider. Requirements: 68.6"""
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "org_id": org_id}
    try:
        from app.core.database import async_session_factory, _set_rls_org_id
        from app.modules.accounting.service import retry_failed_syncs
        async with async_session_factory() as session:
            async with session.begin():
                await _set_rls_org_id(session, org_id)
                return await retry_failed_syncs(session, org_id=uuid.UUID(org_id), provider=provider)
    except Exception as exc:
        logger.exception("Retry failed sync error for %s: %s", org_id, exc)
        return {"error": str(exc), "org_id": org_id}

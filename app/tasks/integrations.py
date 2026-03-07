"""Celery tasks for accounting software sync — Xero and MYOB.

Provides background tasks for syncing invoices, payments, and credit notes
to connected accounting providers. Each task sets up the RLS context,
delegates to the accounting service layer, and logs results.

Queue: ``integrations`` (routed via ``app.tasks.integrations.*`` in __init__.py)

Requirements: 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from app.tasks import celery_app

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ("xero", "myob")

# Max automatic retries for transient failures
MAX_RETRIES = 3
RETRY_BACKOFF = 60  # seconds base delay (exponential: 60, 120, 240)


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Sync invoice to accounting (Req 68.3)
# ---------------------------------------------------------------------------


async def _sync_invoice_async(
    org_id: str,
    entity_id: str,
    provider: str,
    invoice_data: dict[str, Any],
) -> dict[str, Any]:
    """Sync a single invoice to the connected accounting provider."""
    from app.core.database import async_session_factory, _set_rls_org_id
    from app.modules.accounting.service import sync_entity

    org_uuid = uuid.UUID(org_id)
    entity_uuid = uuid.UUID(entity_id)

    async with async_session_factory() as session:
        async with session.begin():
            await _set_rls_org_id(session, org_id)
            result = await sync_entity(
                session,
                org_id=org_uuid,
                provider=provider,
                entity_type="invoice",
                entity_id=entity_uuid,
                entity_data=invoice_data,
            )

    return result


@celery_app.task(
    name="app.tasks.integrations.sync_invoice_to_accounting_task",
    bind=True,
    acks_late=True,
    max_retries=MAX_RETRIES,
    default_retry_delay=RETRY_BACKOFF,
)
def sync_invoice_to_accounting_task(
    self,
    *,
    org_id: str,
    entity_id: str,
    provider: str,
    invoice_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Celery task: sync an invoice to Xero or MYOB.

    Requirements: 68.3
    """
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "entity_id": entity_id}

    try:
        result = _run_async(
            _sync_invoice_async(org_id, entity_id, provider, invoice_data or {})
        )
        status = result.get("status", "unknown")
        if status == "synced":
            logger.info(
                "Invoice %s synced to %s for org %s", entity_id, provider, org_id,
            )
        elif status == "failed":
            logger.warning(
                "Invoice %s sync to %s failed for org %s: %s",
                entity_id, provider, org_id, result.get("error_message", ""),
            )
        return result
    except Exception as exc:
        logger.exception(
            "Invoice sync task error for %s (org %s, %s): %s",
            entity_id, org_id, provider, exc,
        )
        try:
            self.retry(exc=exc, countdown=RETRY_BACKOFF * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            return {
                "error": f"Max retries exceeded: {exc}",
                "entity_type": "invoice",
                "entity_id": entity_id,
                "provider": provider,
                "org_id": org_id,
            }


# ---------------------------------------------------------------------------
# 2. Sync payment to accounting (Req 68.4)
# ---------------------------------------------------------------------------


async def _sync_payment_async(
    org_id: str,
    entity_id: str,
    provider: str,
    payment_data: dict[str, Any],
) -> dict[str, Any]:
    """Sync a single payment to the connected accounting provider."""
    from app.core.database import async_session_factory, _set_rls_org_id
    from app.modules.accounting.service import sync_entity

    org_uuid = uuid.UUID(org_id)
    entity_uuid = uuid.UUID(entity_id)

    async with async_session_factory() as session:
        async with session.begin():
            await _set_rls_org_id(session, org_id)
            result = await sync_entity(
                session,
                org_id=org_uuid,
                provider=provider,
                entity_type="payment",
                entity_id=entity_uuid,
                entity_data=payment_data,
            )

    return result


@celery_app.task(
    name="app.tasks.integrations.sync_payment_to_accounting_task",
    bind=True,
    acks_late=True,
    max_retries=MAX_RETRIES,
    default_retry_delay=RETRY_BACKOFF,
)
def sync_payment_to_accounting_task(
    self,
    *,
    org_id: str,
    entity_id: str,
    provider: str,
    payment_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Celery task: sync a payment to Xero or MYOB.

    Requirements: 68.4
    """
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "entity_id": entity_id}

    try:
        result = _run_async(
            _sync_payment_async(org_id, entity_id, provider, payment_data or {})
        )
        status = result.get("status", "unknown")
        if status == "synced":
            logger.info(
                "Payment %s synced to %s for org %s", entity_id, provider, org_id,
            )
        elif status == "failed":
            logger.warning(
                "Payment %s sync to %s failed for org %s: %s",
                entity_id, provider, org_id, result.get("error_message", ""),
            )
        return result
    except Exception as exc:
        logger.exception(
            "Payment sync task error for %s (org %s, %s): %s",
            entity_id, org_id, provider, exc,
        )
        try:
            self.retry(exc=exc, countdown=RETRY_BACKOFF * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            return {
                "error": f"Max retries exceeded: {exc}",
                "entity_type": "payment",
                "entity_id": entity_id,
                "provider": provider,
                "org_id": org_id,
            }


# ---------------------------------------------------------------------------
# 3. Sync credit note to accounting (Req 68.5)
# ---------------------------------------------------------------------------


async def _sync_credit_note_async(
    org_id: str,
    entity_id: str,
    provider: str,
    credit_note_data: dict[str, Any],
) -> dict[str, Any]:
    """Sync a single credit note to the connected accounting provider."""
    from app.core.database import async_session_factory, _set_rls_org_id
    from app.modules.accounting.service import sync_entity

    org_uuid = uuid.UUID(org_id)
    entity_uuid = uuid.UUID(entity_id)

    async with async_session_factory() as session:
        async with session.begin():
            await _set_rls_org_id(session, org_id)
            result = await sync_entity(
                session,
                org_id=org_uuid,
                provider=provider,
                entity_type="credit_note",
                entity_id=entity_uuid,
                entity_data=credit_note_data,
            )

    return result


@celery_app.task(
    name="app.tasks.integrations.sync_credit_note_to_accounting_task",
    bind=True,
    acks_late=True,
    max_retries=MAX_RETRIES,
    default_retry_delay=RETRY_BACKOFF,
)
def sync_credit_note_to_accounting_task(
    self,
    *,
    org_id: str,
    entity_id: str,
    provider: str,
    credit_note_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Celery task: sync a credit note to Xero or MYOB.

    Requirements: 68.5
    """
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "entity_id": entity_id}

    try:
        result = _run_async(
            _sync_credit_note_async(org_id, entity_id, provider, credit_note_data or {})
        )
        status = result.get("status", "unknown")
        if status == "synced":
            logger.info(
                "Credit note %s synced to %s for org %s", entity_id, provider, org_id,
            )
        elif status == "failed":
            logger.warning(
                "Credit note %s sync to %s failed for org %s: %s",
                entity_id, provider, org_id, result.get("error_message", ""),
            )
        return result
    except Exception as exc:
        logger.exception(
            "Credit note sync task error for %s (org %s, %s): %s",
            entity_id, org_id, provider, exc,
        )
        try:
            self.retry(exc=exc, countdown=RETRY_BACKOFF * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            return {
                "error": f"Max retries exceeded: {exc}",
                "entity_type": "credit_note",
                "entity_id": entity_id,
                "provider": provider,
                "org_id": org_id,
            }


# ---------------------------------------------------------------------------
# 4. Retry failed sync operations (Req 68.6)
# ---------------------------------------------------------------------------


async def _retry_failed_sync_async(
    org_id: str,
    provider: str,
) -> dict[str, Any]:
    """Retry all failed sync entries for a provider."""
    from app.core.database import async_session_factory, _set_rls_org_id
    from app.modules.accounting.service import retry_failed_syncs

    org_uuid = uuid.UUID(org_id)

    async with async_session_factory() as session:
        async with session.begin():
            await _set_rls_org_id(session, org_id)
            result = await retry_failed_syncs(
                session,
                org_id=org_uuid,
                provider=provider,
            )

    return result


@celery_app.task(
    name="app.tasks.integrations.retry_failed_sync_task",
    bind=True,
    acks_late=True,
    max_retries=1,
    default_retry_delay=120,
)
def retry_failed_sync_task(
    self,
    *,
    org_id: str,
    provider: str,
) -> dict[str, Any]:
    """Celery task: retry all failed sync operations for a provider.

    Requirements: 68.6
    """
    if provider not in VALID_PROVIDERS:
        return {"error": f"Invalid provider: {provider}", "org_id": org_id}

    try:
        result = _run_async(_retry_failed_sync_async(org_id, provider))
        synced = result.get("synced", 0)
        failed = result.get("failed", 0)
        if synced > 0 or failed > 0:
            logger.info(
                "Retry failed syncs for %s (org %s): %d synced, %d still failed",
                provider, org_id, synced, failed,
            )
        return result
    except Exception as exc:
        logger.exception(
            "Retry failed sync task error for %s (org %s): %s",
            provider, org_id, exc,
        )
        try:
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "error": f"Max retries exceeded: {exc}",
                "provider": provider,
                "org_id": org_id,
            }

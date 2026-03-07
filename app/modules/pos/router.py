"""POS API router.

Endpoints:
- POST /sessions/open       — Open POS session
- POST /sessions/close      — Close POS session
- POST /transactions        — Complete POS transaction
- POST /transactions/sync   — Sync offline transactions (batch)
- GET  /sync-status         — Get sync status

**Validates: Requirement 22 — POS Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.transactions import TransactionalOperation
from app.modules.pos.schemas import (
    OfflineSyncRequest,
    SessionCloseRequest,
    SessionOpenRequest,
    SessionResponse,
    SyncReport,
    SyncStatusResponse,
    TransactionCreateRequest,
    TransactionResponse,
)
from app.modules.pos.service import POSService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UUID(str(user_id))


@router.post(
    "/sessions/open",
    response_model=SessionResponse,
    status_code=201,
    summary="Open POS session",
)
async def open_session(
    payload: SessionOpenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = POSService(db)
    session = await svc.open_session(org_id, user_id, payload)
    return SessionResponse.model_validate(session)


@router.post(
    "/sessions/close",
    response_model=SessionResponse,
    summary="Close POS session",
)
async def close_session(
    payload: SessionCloseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = POSService(db)
    try:
        session = await svc.close_session(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return SessionResponse.model_validate(session)


@router.post(
    "/transactions",
    response_model=TransactionResponse,
    status_code=201,
    summary="Complete POS transaction",
)
async def complete_transaction(
    payload: TransactionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = POSService(db)
    txn = await svc.complete_transaction(org_id, user_id, payload)
    return TransactionResponse.model_validate(txn)


@router.post(
    "/transactions/sync",
    response_model=SyncReport,
    summary="Sync offline transactions",
)
async def sync_offline_transactions(
    payload: OfflineSyncRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = POSService(db)
    report = await svc.sync_offline_transactions(org_id, user_id, payload.transactions)
    return report


@router.get(
    "/sync-status",
    response_model=SyncStatusResponse,
    summary="Get sync status",
)
async def get_sync_status(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = POSService(db)
    status = await svc.get_sync_status(org_id)
    return SyncStatusResponse(**status)

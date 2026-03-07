"""Ecommerce API router — WooCommerce, sync log, SKU mappings, API keys.

Endpoints (all under /api/v2/ecommerce):
- POST /woocommerce/connect — connect WooCommerce store
- POST /woocommerce/sync — trigger manual sync
- GET  /sync-log — list sync log entries
- GET  /sku-mappings — list SKU mappings
- POST /sku-mappings — create SKU mapping
- PUT  /sku-mappings/{id} — update SKU mapping
- DELETE /sku-mappings/{id} — delete SKU mapping
- GET  /api-keys — list API credentials
- POST /api-keys — create API credential
- DELETE /api-keys/{id} — revoke API credential
- POST /webhook/{org_id} — inbound webhook receiver

**Validates: Requirement — Ecommerce Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ecommerce.models import SkuMapping
from app.modules.ecommerce.schemas import (
    ApiCredentialCreate,
    ApiCredentialCreatedResponse,
    ApiCredentialListResponse,
    ApiCredentialResponse,
    SkuMappingCreate,
    SkuMappingListResponse,
    SkuMappingResponse,
    SyncLogListResponse,
    SyncLogResponse,
    SyncTriggerResponse,
    WooCommerceConnectRequest,
    WooCommerceConnectionResponse,
)
from app.modules.ecommerce.woocommerce_service import WooCommerceService
from app.modules.ecommerce.api_service import ApiKeyService
from app.modules.ecommerce.webhook_receiver import webhook_router

router = APIRouter()
# Include the webhook sub-router
router.include_router(webhook_router)


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# --- WooCommerce endpoints ---

@router.post(
    "/woocommerce/connect",
    response_model=WooCommerceConnectionResponse,
    status_code=201,
    summary="Connect WooCommerce store",
)
async def connect_woocommerce(
    payload: WooCommerceConnectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = WooCommerceService(db)
    conn = await svc.connect(org_id, payload)
    return WooCommerceConnectionResponse.model_validate(conn)


@router.post(
    "/woocommerce/sync",
    response_model=SyncTriggerResponse,
    summary="Trigger manual WooCommerce sync",
)
async def trigger_sync(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = WooCommerceService(db)
    conn = await svc.get_connection(org_id)
    if conn is None or not conn.is_active:
        raise HTTPException(status_code=404, detail="No active WooCommerce connection")
    log = await svc.sync_orders_inbound(org_id)
    return SyncTriggerResponse(message="Sync triggered", sync_log_id=log.id)


# --- Sync log ---

@router.get("/sync-log", response_model=SyncLogListResponse, summary="List sync log")
async def list_sync_log(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = WooCommerceService(db)
    logs, total = await svc.get_sync_log(org_id, skip=skip, limit=limit)
    return SyncLogListResponse(
        logs=[SyncLogResponse.model_validate(l) for l in logs],
        total=total,
    )


# --- SKU mappings ---

@router.get("/sku-mappings", response_model=SkuMappingListResponse, summary="List SKU mappings")
async def list_sku_mappings(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    from sqlalchemy import func as sa_func

    count_stmt = (
        select(sa_func.count()).select_from(SkuMapping).where(SkuMapping.org_id == org_id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(SkuMapping)
        .where(SkuMapping.org_id == org_id)
        .order_by(SkuMapping.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return SkuMappingListResponse(
        mappings=[SkuMappingResponse.model_validate(m) for m in rows],
        total=int(total),
    )


@router.post(
    "/sku-mappings",
    response_model=SkuMappingResponse,
    status_code=201,
    summary="Create SKU mapping",
)
async def create_sku_mapping(
    payload: SkuMappingCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    mapping = SkuMapping(
        org_id=org_id,
        external_sku=payload.external_sku,
        internal_product_id=payload.internal_product_id,
        platform=payload.platform,
    )
    db.add(mapping)
    await db.flush()
    return SkuMappingResponse.model_validate(mapping)


@router.put(
    "/sku-mappings/{mapping_id}",
    response_model=SkuMappingResponse,
    summary="Update SKU mapping",
)
async def update_sku_mapping(
    mapping_id: UUID,
    payload: SkuMappingCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    stmt = select(SkuMapping).where(
        SkuMapping.id == mapping_id,
        SkuMapping.org_id == org_id,
    )
    result = await db.execute(stmt)
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=404, detail="SKU mapping not found")
    mapping.external_sku = payload.external_sku
    mapping.internal_product_id = payload.internal_product_id
    mapping.platform = payload.platform
    await db.flush()
    return SkuMappingResponse.model_validate(mapping)


@router.delete("/sku-mappings/{mapping_id}", status_code=204, summary="Delete SKU mapping")
async def delete_sku_mapping(
    mapping_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    stmt = select(SkuMapping).where(
        SkuMapping.id == mapping_id,
        SkuMapping.org_id == org_id,
    )
    result = await db.execute(stmt)
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=404, detail="SKU mapping not found")
    await db.delete(mapping)
    await db.flush()


# --- API key management ---

@router.get("/api-keys", response_model=ApiCredentialListResponse, summary="List API credentials")
async def list_api_keys(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ApiKeyService(db)
    creds, total = await svc.list_credentials(org_id)
    return ApiCredentialListResponse(
        credentials=[ApiCredentialResponse.model_validate(c) for c in creds],
        total=total,
    )


@router.post(
    "/api-keys",
    response_model=ApiCredentialCreatedResponse,
    status_code=201,
    summary="Create API credential",
)
async def create_api_key(
    payload: ApiCredentialCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ApiKeyService(db)
    cred, raw_key = await svc.create_credential(org_id, payload)
    resp = ApiCredentialCreatedResponse.model_validate(cred)
    resp.api_key = raw_key
    return resp


@router.delete("/api-keys/{credential_id}", status_code=204, summary="Revoke API credential")
async def revoke_api_key(
    credential_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ApiKeyService(db)
    revoked = await svc.revoke_credential(org_id, credential_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API credential not found")

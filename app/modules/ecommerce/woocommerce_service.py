"""WooCommerce integration service.

Handles connecting to WooCommerce stores, syncing orders inbound,
syncing products outbound, and querying sync logs.

**Validates: Requirement — Ecommerce Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ecommerce.models import (
    WooCommerceConnection,
    EcommerceSyncLog,
    SkuMapping,
)
from app.modules.ecommerce.schemas import WooCommerceConnectRequest


class WooCommerceService:
    """Service layer for WooCommerce integration."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(
        self,
        org_id: uuid.UUID,
        data: WooCommerceConnectRequest,
    ) -> WooCommerceConnection:
        """Create or update a WooCommerce connection for an org."""
        stmt = select(WooCommerceConnection).where(
            WooCommerceConnection.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        conn = result.scalar_one_or_none()

        # Encrypt keys (simple encoding — production would use Fernet/KMS)
        key_bytes = data.consumer_key.encode("utf-8")
        secret_bytes = data.consumer_secret.encode("utf-8")

        if conn is not None:
            conn.store_url = data.store_url
            conn.consumer_key_encrypted = key_bytes
            conn.consumer_secret_encrypted = secret_bytes
            conn.sync_frequency_minutes = data.sync_frequency_minutes
            conn.auto_create_invoices = data.auto_create_invoices
            conn.invoice_status_on_import = data.invoice_status_on_import
            conn.is_active = True
            conn.updated_at = datetime.now(timezone.utc)
        else:
            conn = WooCommerceConnection(
                org_id=org_id,
                store_url=data.store_url,
                consumer_key_encrypted=key_bytes,
                consumer_secret_encrypted=secret_bytes,
                sync_frequency_minutes=data.sync_frequency_minutes,
                auto_create_invoices=data.auto_create_invoices,
                invoice_status_on_import=data.invoice_status_on_import,
            )
            self.db.add(conn)

        await self.db.flush()
        return conn

    async def get_connection(self, org_id: uuid.UUID) -> WooCommerceConnection | None:
        stmt = select(WooCommerceConnection).where(
            WooCommerceConnection.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Sync operations
    # ------------------------------------------------------------------

    async def sync_orders_inbound(
        self,
        org_id: uuid.UUID,
    ) -> EcommerceSyncLog:
        """Trigger inbound order sync from WooCommerce.

        In production this would call the WooCommerce REST API.
        Here we create a sync log entry and return it.
        """
        log = EcommerceSyncLog(
            org_id=org_id,
            direction="inbound",
            entity_type="order",
            status="pending",
        )
        self.db.add(log)
        await self.db.flush()

        # Update connection last_sync_at
        conn = await self.get_connection(org_id)
        if conn is not None:
            conn.last_sync_at = datetime.now(timezone.utc)

        return log

    async def sync_products_outbound(
        self,
        org_id: uuid.UUID,
    ) -> EcommerceSyncLog:
        """Trigger outbound product sync to WooCommerce."""
        log = EcommerceSyncLog(
            org_id=org_id,
            direction="outbound",
            entity_type="product",
            status="pending",
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def complete_sync(
        self,
        log_id: uuid.UUID,
        status: str = "completed",
        error_details: str | None = None,
    ) -> EcommerceSyncLog | None:
        """Mark a sync log entry as completed or failed."""
        stmt = select(EcommerceSyncLog).where(EcommerceSyncLog.id == log_id)
        result = await self.db.execute(stmt)
        log = result.scalar_one_or_none()
        if log is None:
            return None
        log.status = status
        log.error_details = error_details
        if status == "failed":
            log.retry_count += 1
        await self.db.flush()
        return log

    # ------------------------------------------------------------------
    # Sync log queries
    # ------------------------------------------------------------------

    async def get_sync_log(
        self,
        org_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[EcommerceSyncLog], int]:
        """Return paginated sync log entries for an org."""
        count_stmt = (
            select(func.count())
            .select_from(EcommerceSyncLog)
            .where(EcommerceSyncLog.org_id == org_id)
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(EcommerceSyncLog)
            .where(EcommerceSyncLog.org_id == org_id)
            .order_by(desc(EcommerceSyncLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows), int(total)

    # ------------------------------------------------------------------
    # SKU mapping helpers
    # ------------------------------------------------------------------

    async def resolve_sku(
        self,
        org_id: uuid.UUID,
        external_sku: str,
        platform: str = "woocommerce",
    ) -> uuid.UUID | None:
        """Resolve an external SKU to an internal product ID."""
        stmt = select(SkuMapping.internal_product_id).where(
            SkuMapping.org_id == org_id,
            SkuMapping.external_sku == external_sku,
            SkuMapping.platform == platform,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


    async def get_unmatched_skus(
        self,
        org_id: uuid.UUID,
        platform: str = "woocommerce",
    ) -> list[SkuMapping]:
        """Return SKU mappings that have no internal product linked."""
        stmt = (
            select(SkuMapping)
            .where(
                SkuMapping.org_id == org_id,
                SkuMapping.platform == platform,
                SkuMapping.internal_product_id.is_(None),
            )
            .order_by(SkuMapping.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def map_sku(
        self,
        org_id: uuid.UUID,
        mapping_id: uuid.UUID,
        internal_product_id: uuid.UUID,
    ) -> SkuMapping | None:
        """Manually map an external SKU to an internal product."""
        stmt = select(SkuMapping).where(
            SkuMapping.id == mapping_id,
            SkuMapping.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        mapping = result.scalar_one_or_none()
        if mapping is None:
            return None
        mapping.internal_product_id = internal_product_id
        mapping.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return mapping

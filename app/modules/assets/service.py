"""Asset tracking service — CRUD, service history, linking, Carjam lookup.

**Validates: Extended Asset Tracking — Task 45.3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.models import Asset
from app.modules.assets.schemas import (
    AssetServiceHistory,
    ServiceHistoryEntry,
    is_automotive_trade,
)


class AssetService:
    """Service layer for extended asset tracking."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_assets(
        self,
        org_id: uuid.UUID,
        *,
        customer_id: uuid.UUID | None = None,
        asset_type: str | None = None,
        active_only: bool = True,
    ) -> list[Asset]:
        stmt = select(Asset).where(Asset.org_id == org_id)
        if customer_id is not None:
            stmt = stmt.where(Asset.customer_id == customer_id)
        if asset_type is not None:
            stmt = stmt.where(Asset.asset_type == asset_type)
        if active_only:
            stmt = stmt.where(Asset.is_active.is_(True))
        stmt = stmt.order_by(Asset.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_asset(
        self, org_id: uuid.UUID, asset_id: uuid.UUID,
    ) -> Asset | None:
        stmt = select(Asset).where(
            Asset.id == asset_id, Asset.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_asset(
        self, org_id: uuid.UUID, **kwargs: Any,
    ) -> Asset:
        asset = Asset(id=uuid.uuid4(), org_id=org_id, **kwargs)
        self.db.add(asset)
        await self.db.flush()
        return asset

    async def update_asset(
        self,
        org_id: uuid.UUID,
        asset_id: uuid.UUID,
        **kwargs: Any,
    ) -> Asset | None:
        # Filter out None values so we only update provided fields
        updates = {k: v for k, v in kwargs.items() if v is not None}
        if not updates:
            return await self.get_asset(org_id, asset_id)
        updates["updated_at"] = datetime.now(timezone.utc)
        stmt = (
            update(Asset)
            .where(Asset.id == asset_id, Asset.org_id == org_id)
            .values(**updates)
            .returning(Asset)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_asset(
        self, org_id: uuid.UUID, asset_id: uuid.UUID,
    ) -> bool:
        """Soft-delete an asset by setting is_active=False."""
        stmt = (
            update(Asset)
            .where(Asset.id == asset_id, Asset.org_id == org_id)
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )
        result = await self.db.execute(stmt)
        return result.rowcount > 0  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Service history — linked invoices, jobs, quotes
    # ------------------------------------------------------------------

    async def get_service_history(
        self, org_id: uuid.UUID, asset_id: uuid.UUID,
    ) -> AssetServiceHistory:
        """Return all invoices, jobs, and quotes linked to this asset."""
        entries: list[ServiceHistoryEntry] = []

        # Jobs linked via asset_id
        from sqlalchemy import text as sa_text
        job_rows = await self.db.execute(
            sa_text(
                "SELECT id, job_number, description, status, created_at "
                "FROM jobs WHERE asset_id = :aid AND org_id = :oid "
                "ORDER BY created_at DESC"
            ),
            {"aid": str(asset_id), "oid": str(org_id)},
        )
        for row in job_rows:
            entries.append(ServiceHistoryEntry(
                reference_type="job",
                reference_id=row[0],
                reference_number=row[1],
                description=row[2],
                status=row[3],
                date=row[4],
            ))

        # Invoices linked via jobs (jobs.asset_id → invoices via converted_invoice)
        inv_rows = await self.db.execute(
            sa_text(
                "SELECT DISTINCT i.id, i.invoice_number, i.status, i.created_at "
                "FROM invoices i "
                "INNER JOIN jobs j ON j.id = i.job_id "
                "WHERE j.asset_id = :aid AND j.org_id = :oid "
                "ORDER BY i.created_at DESC"
            ),
            {"aid": str(asset_id), "oid": str(org_id)},
        )
        for row in inv_rows:
            entries.append(ServiceHistoryEntry(
                reference_type="invoice",
                reference_id=row[0],
                reference_number=row[1],
                status=row[2],
                date=row[3],
            ))

        # Quotes linked via jobs
        quote_rows = await self.db.execute(
            sa_text(
                "SELECT DISTINCT q.id, q.quote_number, q.status, q.created_at "
                "FROM quotes q "
                "INNER JOIN jobs j ON j.quote_id = q.id "
                "WHERE j.asset_id = :aid AND j.org_id = :oid "
                "ORDER BY q.created_at DESC"
            ),
            {"aid": str(asset_id), "oid": str(org_id)},
        )
        for row in quote_rows:
            entries.append(ServiceHistoryEntry(
                reference_type="quote",
                reference_id=row[0],
                reference_number=row[1],
                status=row[2],
                date=row[3],
            ))

        # Sort all entries by date descending
        entries.sort(key=lambda e: e.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return AssetServiceHistory(asset_id=asset_id, entries=entries)

    # ------------------------------------------------------------------
    # Linking helpers
    # ------------------------------------------------------------------

    async def link_to_job(
        self, org_id: uuid.UUID, asset_id: uuid.UUID, job_id: uuid.UUID,
    ) -> bool:
        """Set asset_id on a job record."""
        from sqlalchemy import text as sa_text
        result = await self.db.execute(
            sa_text(
                "UPDATE jobs SET asset_id = :aid "
                "WHERE id = :jid AND org_id = :oid"
            ),
            {"aid": str(asset_id), "jid": str(job_id), "oid": str(org_id)},
        )
        return result.rowcount > 0  # type: ignore[union-attr]

    async def link_to_invoice(
        self, org_id: uuid.UUID, asset_id: uuid.UUID, invoice_id: uuid.UUID,
    ) -> bool:
        """Link an asset to an invoice via the job relationship.

        This is a convenience method — in practice, assets are linked to
        invoices through jobs. If the invoice has a job_id, we set the
        asset_id on that job.
        """
        from sqlalchemy import text as sa_text
        result = await self.db.execute(
            sa_text(
                "UPDATE jobs SET asset_id = :aid "
                "WHERE id = (SELECT job_id FROM invoices WHERE id = :iid AND org_id = :oid) "
                "AND org_id = :oid"
            ),
            {"aid": str(asset_id), "iid": str(invoice_id), "oid": str(org_id)},
        )
        return result.rowcount > 0  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Carjam lookup (automotive trades only)
    # ------------------------------------------------------------------

    async def carjam_lookup(
        self,
        org_id: uuid.UUID,
        asset_id: uuid.UUID,
        trade_family_slug: str | None,
    ) -> dict[str, Any] | None:
        """Perform a Carjam lookup for an asset.

        Only available for automotive trade categories. Returns None and
        raises ValueError for non-automotive trades.
        """
        if not is_automotive_trade(trade_family_slug):
            raise ValueError(
                "Carjam integration is only available for automotive trade categories"
            )

        asset = await self.get_asset(org_id, asset_id)
        if asset is None or not asset.identifier:
            return None

        # Delegate to the existing V1 Carjam service
        from app.modules.vehicles.service import lookup_vehicle
        try:
            result = await lookup_vehicle(
                self.db, org_id=org_id, plate=asset.identifier,
            )
            # Store the Carjam data on the asset
            if result:
                carjam_data = result.get("carjam_data", result)
                stmt = (
                    update(Asset)
                    .where(Asset.id == asset_id, Asset.org_id == org_id)
                    .values(
                        carjam_data=carjam_data,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await self.db.execute(stmt)
                return carjam_data
        except Exception:
            pass
        return None

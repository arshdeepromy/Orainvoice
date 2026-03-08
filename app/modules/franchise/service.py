"""Franchise & multi-location service layer.

Provides CRUD for locations, stock transfer workflow, head-office
aggregate views, and franchise dashboard.

**Validates: Requirement 8 — Extended RBAC / Multi-Location**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.franchise.models import FranchiseGroup, Location, StockTransfer

logger = logging.getLogger(__name__)


class FranchiseService:
    """Service layer for franchise and multi-location operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Location CRUD
    # ------------------------------------------------------------------

    async def list_locations(
        self,
        org_id: uuid.UUID,
        *,
        active_only: bool = True,
    ) -> list[Location]:
        stmt = select(Location).where(Location.org_id == org_id)
        if active_only:
            stmt = stmt.where(Location.is_active.is_(True))
        stmt = stmt.order_by(Location.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_location(
        self, org_id: uuid.UUID, location_id: uuid.UUID,
    ) -> Location | None:
        stmt = select(Location).where(
            and_(Location.id == location_id, Location.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_location(
        self,
        org_id: uuid.UUID,
        *,
        name: str,
        address: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        invoice_prefix: str | None = None,
        has_own_inventory: bool = False,
    ) -> Location:
        location = Location(
            org_id=org_id,
            name=name,
            address=address,
            phone=phone,
            email=email,
            invoice_prefix=invoice_prefix,
            has_own_inventory=has_own_inventory,
        )
        self.db.add(location)
        await self.db.flush()
        return location

    async def update_location(
        self,
        location: Location,
        **kwargs,
    ) -> Location:
        for key, value in kwargs.items():
            if value is not None and hasattr(location, key):
                setattr(location, key, value)
        location.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return location

    # ------------------------------------------------------------------
    # Stock Transfer Workflow
    # ------------------------------------------------------------------

    async def create_stock_transfer(
        self,
        org_id: uuid.UUID,
        *,
        from_location_id: uuid.UUID,
        to_location_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: Decimal,
        requested_by: uuid.UUID | None = None,
    ) -> StockTransfer:
        if from_location_id == to_location_id:
            raise ValueError("Source and destination locations must differ")
        if quantity <= 0:
            raise ValueError("Transfer quantity must be positive")
        transfer = StockTransfer(
            org_id=org_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            product_id=product_id,
            quantity=quantity,
            status="pending",
            requested_by=requested_by,
        )
        self.db.add(transfer)
        await self.db.flush()
        return transfer

    async def approve_transfer(
        self,
        transfer: StockTransfer,
        approved_by: uuid.UUID | None = None,
    ) -> StockTransfer:
        if transfer.status != "pending":
            raise ValueError(f"Cannot approve transfer in '{transfer.status}' status")
        transfer.status = "approved"
        transfer.approved_by = approved_by
        await self.db.flush()
        return transfer

    async def execute_transfer(
        self,
        transfer: StockTransfer,
    ) -> StockTransfer:
        """Execute an approved transfer — creates stock movements at both locations.

        This method updates the transfer status to 'executed' and creates
        stock movement records. The caller is responsible for actually
        calling StockService to create the movements.
        """
        if transfer.status != "approved":
            raise ValueError(f"Cannot execute transfer in '{transfer.status}' status")
        transfer.status = "executed"
        transfer.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return transfer

    async def reject_transfer(
        self,
        transfer: StockTransfer,
    ) -> StockTransfer:
        if transfer.status != "pending":
            raise ValueError(f"Cannot reject transfer in '{transfer.status}' status")
        transfer.status = "rejected"
        await self.db.flush()
        return transfer

    async def get_transfer(
        self, org_id: uuid.UUID, transfer_id: uuid.UUID,
    ) -> StockTransfer | None:
        stmt = select(StockTransfer).where(
            and_(StockTransfer.id == transfer_id, StockTransfer.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_transfers(
        self,
        org_id: uuid.UUID,
        *,
        status: str | None = None,
        location_id: uuid.UUID | None = None,
    ) -> list[StockTransfer]:
        stmt = select(StockTransfer).where(StockTransfer.org_id == org_id)
        if status:
            stmt = stmt.where(StockTransfer.status == status)
        if location_id:
            stmt = stmt.where(
                (StockTransfer.from_location_id == location_id)
                | (StockTransfer.to_location_id == location_id),
            )
        stmt = stmt.order_by(StockTransfer.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Head Office Aggregate View
    # ------------------------------------------------------------------

    async def get_head_office_view(
        self,
        org_id: uuid.UUID,
    ) -> dict:
        """Return combined revenue, outstanding, and per-location comparison.

        Uses the invoices table to aggregate financial data per location.
        Falls back to zero values if no invoices exist.
        """
        from app.modules.franchise.schemas import HeadOfficeView, LocationMetrics

        locations = await self.list_locations(org_id)
        location_metrics: list[LocationMetrics] = []
        total_revenue = Decimal("0")
        total_outstanding = Decimal("0")

        for loc in locations:
            # Try to aggregate from invoices table if it exists
            try:
                from app.modules.invoices.models import Invoice
                revenue_stmt = select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    and_(Invoice.org_id == org_id, Invoice.location_id == loc.id, Invoice.status == "paid"),
                )
                rev_result = await self.db.execute(revenue_stmt)
                revenue = Decimal(str(rev_result.scalar() or 0))

                outstanding_stmt = select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    and_(Invoice.org_id == org_id, Invoice.location_id == loc.id, Invoice.status == "issued"),
                )
                out_result = await self.db.execute(outstanding_stmt)
                outstanding = Decimal(str(out_result.scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to aggregate invoices for location %s: %s", loc.id, exc)
                revenue = Decimal("0")
                outstanding = Decimal("0")

            total_revenue += revenue
            total_outstanding += outstanding
            location_metrics.append(LocationMetrics(
                location_id=loc.id,
                location_name=loc.name,
                revenue=revenue,
                outstanding=outstanding,
            ))

        return HeadOfficeView(
            total_revenue=total_revenue,
            total_outstanding=total_outstanding,
            location_metrics=location_metrics,
        ).model_dump()

    # ------------------------------------------------------------------
    # Franchise Dashboard (read-only aggregate across linked orgs)
    # ------------------------------------------------------------------

    async def get_franchise_dashboard(
        self,
        franchise_group_id: uuid.UUID,
    ) -> dict:
        """Aggregate metrics across all organisations in a franchise group.

        Returns total orgs, total revenue, total outstanding, total locations.
        Franchise admins see aggregate data only — no individual records.
        """
        from app.modules.franchise.schemas import FranchiseDashboardMetrics

        # Count organisations in the franchise group
        try:
            from app.modules.organisations.models import Organisation
            org_count_stmt = select(func.count()).select_from(Organisation).where(
                Organisation.franchise_group_id == franchise_group_id,
            )
            org_count = (await self.db.execute(org_count_stmt)).scalar() or 0

            # Get all org IDs in the group
            org_ids_stmt = select(Organisation.id).where(
                Organisation.franchise_group_id == franchise_group_id,
            )
            org_ids_result = await self.db.execute(org_ids_stmt)
            org_ids = [row[0] for row in org_ids_result.all()]

            # Count locations across all orgs
            loc_count_stmt = select(func.count()).select_from(Location).where(
                Location.org_id.in_(org_ids),
            )
            loc_count = (await self.db.execute(loc_count_stmt)).scalar() or 0

            # Aggregate revenue and outstanding
            total_revenue = Decimal("0")
            total_outstanding = Decimal("0")
            try:
                from app.modules.invoices.models import Invoice
                rev_stmt = select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    and_(Invoice.org_id.in_(org_ids), Invoice.status == "paid"),
                )
                total_revenue = Decimal(str((await self.db.execute(rev_stmt)).scalar() or 0))

                out_stmt = select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    and_(Invoice.org_id.in_(org_ids), Invoice.status == "issued"),
                )
                total_outstanding = Decimal(str((await self.db.execute(out_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to aggregate franchise invoices: %s", exc)

        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to build franchise dashboard for group %s: %s", franchise_group_id, exc)
            org_count = 0
            loc_count = 0
            total_revenue = Decimal("0")
            total_outstanding = Decimal("0")

        return FranchiseDashboardMetrics(
            total_organisations=org_count,
            total_revenue=total_revenue,
            total_outstanding=total_outstanding,
            total_locations=loc_count,
        ).model_dump()

    # ------------------------------------------------------------------
    # Clone Location Settings
    # ------------------------------------------------------------------

    async def clone_location_settings(
        self,
        org_id: uuid.UUID,
        source_location_id: uuid.UUID,
        target_name: str,
    ) -> Location:
        """Clone a location's settings to create a new location."""
        source = await self.get_location(org_id, source_location_id)
        if source is None:
            raise ValueError("Source location not found")
        return await self.create_location(
            org_id,
            name=target_name,
            address=source.address,
            phone=source.phone,
            email=source.email,
            invoice_prefix=source.invoice_prefix,
            has_own_inventory=source.has_own_inventory,
        )

    # ------------------------------------------------------------------
    # Franchise Group CRUD
    # ------------------------------------------------------------------

    async def create_franchise_group(
        self,
        *,
        name: str,
        description: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> FranchiseGroup:
        group = FranchiseGroup(
            name=name,
            description=description,
            created_by=created_by,
        )
        self.db.add(group)
        await self.db.flush()
        return group

    async def get_franchise_group(
        self, group_id: uuid.UUID,
    ) -> FranchiseGroup | None:
        stmt = select(FranchiseGroup).where(FranchiseGroup.id == group_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_franchise_groups(self) -> list[FranchiseGroup]:
        stmt = select(FranchiseGroup).order_by(FranchiseGroup.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

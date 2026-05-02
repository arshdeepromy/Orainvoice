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
from app.modules.franchise.transfer_action_model import TransferAction

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
    # Transfer Audit Trail
    # ------------------------------------------------------------------

    async def _log_transfer_action(
        self,
        transfer_id: uuid.UUID,
        action: str,
        performed_by: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> TransferAction:
        """Record an audit trail entry for a transfer status transition."""
        entry = TransferAction(
            transfer_id=transfer_id,
            action=action,
            performed_by=performed_by,
            notes=notes,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def get_transfer_actions(
        self,
        transfer_id: uuid.UUID,
    ) -> list[TransferAction]:
        """Return the audit trail for a transfer, ordered chronologically."""
        stmt = (
            select(TransferAction)
            .where(TransferAction.transfer_id == transfer_id)
            .order_by(TransferAction.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Transfer Event Notifications
    # ------------------------------------------------------------------

    async def _notify_transfer_event(
        self,
        transfer: StockTransfer,
        action: str,
        performed_by: uuid.UUID | None = None,
    ) -> None:
        """Send in-app + optional email notifications for transfer events.

        - ``created``: notify destination branch manager(s)
        - ``approved`` / ``executed``: notify both source and destination managers

        Uses the existing ``log_email_sent`` + ``send_email_task`` pattern.

        **Validates: Requirements 55.1, 55.2, 55.3**
        """
        from app.modules.auth.models import User
        from app.modules.notifications.service import log_email_sent
        from app.modules.organisations.models import Branch
        from app.tasks.notifications import send_email_task

        org_id = transfer.org_id

        # Resolve branch names for the notification body
        source_branch = await self.db.get(Branch, transfer.from_branch_id)
        dest_branch = await self.db.get(Branch, transfer.to_branch_id)
        source_name = source_branch.name if source_branch else "Unknown"
        dest_name = dest_branch.name if dest_branch else "Unknown"

        # Determine which branch IDs to notify
        if action == "created":
            branch_ids_to_notify = [transfer.to_branch_id]
        else:
            # approved, executed — notify both sides
            branch_ids_to_notify = [transfer.from_branch_id, transfer.to_branch_id]

        # Find users who manage the target branches:
        # - location_manager / org_admin with the branch in their branch_ids
        recipients: list[User] = []
        for branch_id in branch_ids_to_notify:
            branch_id_str = str(branch_id)
            stmt = (
                select(User)
                .where(
                    User.org_id == org_id,
                    User.is_active.is_(True),
                    User.role.in_(["org_admin", "location_manager"]),
                )
            )
            result = await self.db.execute(stmt)
            users = list(result.scalars().all())
            for user in users:
                # org_admin gets all branch notifications
                if user.role == "org_admin":
                    if user not in recipients:
                        recipients.append(user)
                    continue
                # location_manager — check branch_ids JSONB array
                user_branches = user.branch_ids or []
                if branch_id_str in [str(b) for b in user_branches]:
                    if user not in recipients:
                        recipients.append(user)

        if not recipients:
            logger.info(
                "No recipients found for transfer %s %s notification",
                transfer.id, action,
            )
            return

        # Build notification content
        qty = transfer.quantity
        action_label = {
            "created": "New transfer request",
            "approved": "Transfer approved",
            "executed": "Transfer executed",
        }.get(action, f"Transfer {action}")

        subject = f"{action_label}: {source_name} → {dest_name} (qty {qty})"

        html_body = (
            f"<p>Hi,</p>"
            f"<p>A stock transfer event has occurred:</p>"
            f"<ul>"
            f"<li><strong>Action:</strong> {action_label}</li>"
            f"<li><strong>From:</strong> {source_name}</li>"
            f"<li><strong>To:</strong> {dest_name}</li>"
            f"<li><strong>Quantity:</strong> {qty}</li>"
            f"<li><strong>Status:</strong> {transfer.status}</li>"
            f"</ul>"
            f"<p>Please review the transfer in your dashboard.</p>"
        )

        text_body = (
            f"Hi,\n\n"
            f"A stock transfer event has occurred:\n\n"
            f"  Action: {action_label}\n"
            f"  From: {source_name}\n"
            f"  To: {dest_name}\n"
            f"  Quantity: {qty}\n"
            f"  Status: {transfer.status}\n\n"
            f"Please review the transfer in your dashboard.\n"
        )

        for recipient in recipients:
            if not recipient.email:
                continue
            try:
                log_entry = await log_email_sent(
                    self.db,
                    org_id=org_id,
                    recipient=recipient.email,
                    template_type=f"transfer_{action}",
                    subject=subject,
                    status="queued",
                )
                await send_email_task(
                    org_id=str(org_id),
                    log_id=str(log_entry["id"]),
                    to_email=recipient.email,
                    to_name=f"{recipient.first_name or ''} {recipient.last_name or ''}".strip(),
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    template_type=f"transfer_{action}",
                )
            except Exception:
                logger.exception(
                    "Failed to send transfer %s notification to %s",
                    action, recipient.email,
                )

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
        await self._log_transfer_action(
            transfer.id, "created", performed_by=requested_by,
        )
        # Req 55.1: Notify destination branch manager on create
        await self._notify_transfer_event(transfer, "created", performed_by=requested_by)
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
        await self._log_transfer_action(
            transfer.id, "approved", performed_by=approved_by,
        )
        # Req 55.2: Notify both source and destination managers on approve
        await self._notify_transfer_event(transfer, "approved", performed_by=approved_by)
        return transfer

    async def execute_transfer(
        self,
        transfer: StockTransfer,
        executed_by: uuid.UUID | None = None,
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
        await self._log_transfer_action(
            transfer.id, "executed", performed_by=executed_by,
        )
        # Req 55.2: Notify both source and destination managers on execute
        await self._notify_transfer_event(transfer, "executed", performed_by=executed_by)
        return transfer

    async def reject_transfer(
        self,
        transfer: StockTransfer,
        rejected_by: uuid.UUID | None = None,
    ) -> StockTransfer:
        if transfer.status != "pending":
            raise ValueError(f"Cannot reject transfer in '{transfer.status}' status")
        transfer.status = "rejected"
        await self.db.flush()
        await self._log_transfer_action(
            transfer.id, "rejected", performed_by=rejected_by,
        )
        return transfer

    async def receive_transfer(
        self,
        transfer: StockTransfer,
        received_by: uuid.UUID | None = None,
        received_quantity: Decimal | None = None,
    ) -> StockTransfer:
        """Mark an executed transfer as received, with optional partial receive.

        If ``received_quantity`` is provided and is less than the transfer
        quantity, the status is set to ``partially_received`` and the
        discrepancy is recorded.  When ``received_quantity`` is omitted or
        equals the transfer quantity, the status is set to ``received``.

        Stock movement already occurred at the execute step — this is
        a confirmation that goods physically arrived at the destination.

        **Validates: Requirements 54.1, 54.2, 54.3**
        """
        if transfer.status != "executed":
            raise ValueError(f"Cannot receive transfer in '{transfer.status}' status")

        transfer_qty = transfer.quantity

        if received_quantity is not None:
            if received_quantity > transfer_qty:
                raise ValueError(
                    "Received quantity cannot exceed the transfer quantity",
                )
            transfer.received_quantity = received_quantity
            discrepancy = transfer_qty - received_quantity
            transfer.discrepancy_quantity = discrepancy

            if discrepancy > 0:
                transfer.status = "partially_received"
            else:
                transfer.status = "received"
        else:
            # No received_quantity provided — default to full receive
            transfer.received_quantity = transfer_qty
            transfer.discrepancy_quantity = Decimal("0")
            transfer.status = "received"

        transfer.received_at = datetime.now(timezone.utc)
        await self.db.flush()

        notes = None
        if received_quantity is not None and received_quantity < transfer_qty:
            notes = (
                f"Partial receive: {received_quantity} of {transfer_qty} "
                f"(discrepancy: {transfer_qty - received_quantity})"
            )
        await self._log_transfer_action(
            transfer.id, transfer.status, performed_by=received_by, notes=notes,
        )
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

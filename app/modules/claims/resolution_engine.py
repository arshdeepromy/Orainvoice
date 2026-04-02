"""Resolution Engine for Customer Claims & Returns.

Orchestrates downstream actions based on resolution type:
- full_refund / partial_refund → PaymentService.process_refund
- credit_note → InvoiceService.create_credit_note
- exchange → StockService.increment_stock (return movement)
- redo_service → JobCardService.create_job_card (zero charge)
- no_action → status update only

Requirements: 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8,
              4.1, 4.2, 4.3, 4.4, 4.5, 12.3
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.claims.models import (
    ClaimStatus,
    CustomerClaim,
    ResolutionType,
)
from app.modules.invoices.models import Invoice


@dataclass
class ResolutionResult:
    """Container for all entity references created during resolution."""

    resolution_type: str
    refund_id: uuid.UUID | None = None
    credit_note_id: uuid.UUID | None = None
    return_movement_ids: list[dict] = field(default_factory=list)
    warranty_job_id: uuid.UUID | None = None
    write_off_cost: Decimal = Decimal("0")


class ResolutionEngine:
    """Orchestrates downstream actions for claim resolution."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def execute_resolution(
        self,
        *,
        claim: CustomerClaim,
        resolution_type: ResolutionType,
        resolution_amount: Decimal | None = None,
        return_stock_item_ids: list[uuid.UUID] | None = None,
        user_id: uuid.UUID,
        ip_address: str | None = None,
    ) -> ResolutionResult:
        """Execute resolution actions and return created entity references.

        Validates claim is in 'approved' status (or 'rejected' for no_action),
        dispatches to the appropriate handler, stores downstream references on
        the claim, updates status to 'resolved', and writes an audit log entry.

        Requirements: 2.4, 3.1, 3.8, 12.3
        """
        rt = resolution_type.value if isinstance(resolution_type, ResolutionType) else resolution_type

        # --- Status guard ---
        if rt == ResolutionType.NO_ACTION.value:
            if claim.status not in (ClaimStatus.APPROVED.value, ClaimStatus.REJECTED.value):
                raise ValueError(
                    "Claim must be in 'approved' or 'rejected' status for no_action resolution"
                )
        else:
            if claim.status != ClaimStatus.APPROVED.value:
                raise ValueError("Claim must be in 'approved' status before resolution")

        # --- Dispatch to handler ---
        handlers = {
            ResolutionType.FULL_REFUND.value: self._process_full_refund,
            ResolutionType.PARTIAL_REFUND.value: self._process_partial_refund,
            ResolutionType.CREDIT_NOTE.value: self._process_credit_note,
            ResolutionType.EXCHANGE.value: self._process_exchange,
            ResolutionType.REDO_SERVICE.value: self._process_redo_service,
            ResolutionType.NO_ACTION.value: self._process_no_action,
        }

        handler = handlers.get(rt)
        if handler is None:
            raise ValueError(f"Unknown resolution type: {rt}")

        if rt == ResolutionType.PARTIAL_REFUND.value:
            result = await handler(claim, resolution_amount, user_id, ip_address)
        elif rt == ResolutionType.CREDIT_NOTE.value:
            result = await handler(claim, resolution_amount, user_id, ip_address)
        elif rt == ResolutionType.EXCHANGE.value:
            result = await handler(claim, return_stock_item_ids or [], user_id, ip_address)
        else:
            result = await handler(claim, user_id, ip_address)

        # --- Store downstream references on claim ---
        if result.refund_id is not None:
            claim.refund_id = result.refund_id
        if result.credit_note_id is not None:
            claim.credit_note_id = result.credit_note_id
        if result.return_movement_ids:
            claim.return_movement_ids = [
                str(m["movement_id"]) for m in result.return_movement_ids
            ]
        if result.warranty_job_id is not None:
            claim.warranty_job_id = result.warranty_job_id

        # --- Update write-off cost if applicable ---
        if result.write_off_cost > 0:
            breakdown = dict(claim.cost_breakdown) if claim.cost_breakdown else {
                "labour_cost": 0, "parts_cost": 0, "write_off_cost": 0,
            }
            breakdown["write_off_cost"] = float(
                Decimal(str(breakdown.get("write_off_cost", 0))) + result.write_off_cost
            )
            claim.cost_breakdown = breakdown
            claim.cost_to_business = (
                Decimal(str(breakdown.get("labour_cost", 0)))
                + Decimal(str(breakdown.get("parts_cost", 0)))
                + Decimal(str(breakdown["write_off_cost"]))
            )

        # --- Update claim resolution fields and status ---
        now = datetime.now(timezone.utc)
        claim.resolution_type = rt
        if resolution_amount is not None:
            claim.resolution_amount = resolution_amount
        claim.resolved_at = now
        claim.resolved_by = user_id
        claim.status = ClaimStatus.RESOLVED.value
        claim.updated_at = now

        await self.db.flush()

        # --- Audit log (Req 12.3) ---
        await write_audit_log(
            session=self.db,
            org_id=claim.org_id,
            user_id=user_id,
            action="claim.resolution_action",
            entity_type="claim",
            entity_id=claim.id,
            before_value={"status": ClaimStatus.APPROVED.value},
            after_value={
                "status": ClaimStatus.RESOLVED.value,
                "resolution_type": rt,
                "resolution_amount": str(resolution_amount) if resolution_amount else None,
                "refund_id": str(result.refund_id) if result.refund_id else None,
                "credit_note_id": str(result.credit_note_id) if result.credit_note_id else None,
                "return_movement_ids": [str(m["movement_id"]) for m in result.return_movement_ids],
                "warranty_job_id": str(result.warranty_job_id) if result.warranty_job_id else None,
            },
            ip_address=ip_address,
        )

        return result

    # ------------------------------------------------------------------
    # Task 5.2: Full refund handler (Req 3.2)
    # ------------------------------------------------------------------

    async def _process_full_refund(
        self,
        claim: CustomerClaim,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> ResolutionResult:
        """Call PaymentService.process_refund for the full invoice amount.

        Requirements: 3.2
        """
        from app.modules.payments.service import process_refund

        if claim.invoice_id is None:
            raise ValueError("Cannot process refund without a linked invoice")

        # Fetch invoice to get the total amount
        inv_result = await self.db.execute(
            select(Invoice).where(
                Invoice.id == claim.invoice_id,
                Invoice.org_id == claim.org_id,
            )
        )
        invoice = inv_result.scalar_one_or_none()
        if invoice is None:
            raise ValueError("Linked invoice not found")

        refund_amount = invoice.amount_paid if invoice.amount_paid > 0 else invoice.total

        result = await process_refund(
            self.db,
            org_id=claim.org_id,
            user_id=user_id,
            invoice_id=claim.invoice_id,
            amount=refund_amount,
            method="cash",
            notes=f"Full refund for claim: {claim.description[:100]}",
            ip_address=ip_address,
        )

        return ResolutionResult(
            resolution_type=ResolutionType.FULL_REFUND.value,
            refund_id=result["refund"].id,
        )

    # ------------------------------------------------------------------
    # Task 5.3: Partial refund handler (Req 3.3)
    # ------------------------------------------------------------------

    async def _process_partial_refund(
        self,
        claim: CustomerClaim,
        amount: Decimal | None,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> ResolutionResult:
        """Call PaymentService.process_refund for the specified amount.

        Requirements: 3.3
        """
        from app.modules.payments.service import process_refund

        if claim.invoice_id is None:
            raise ValueError("Cannot process refund without a linked invoice")
        if amount is None or amount <= 0:
            raise ValueError("resolution_amount is required for partial refund and must be > 0")

        result = await process_refund(
            self.db,
            org_id=claim.org_id,
            user_id=user_id,
            invoice_id=claim.invoice_id,
            amount=amount,
            method="cash",
            notes=f"Partial refund for claim: {claim.description[:100]}",
            ip_address=ip_address,
        )

        return ResolutionResult(
            resolution_type=ResolutionType.PARTIAL_REFUND.value,
            refund_id=result["refund"].id,
        )

    # ------------------------------------------------------------------
    # Task 5.4: Credit note handler (Req 3.4)
    # ------------------------------------------------------------------

    async def _process_credit_note(
        self,
        claim: CustomerClaim,
        amount: Decimal | None,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> ResolutionResult:
        """Create a credit note linked to the original invoice.

        Requirements: 3.4
        """
        from app.modules.invoices.service import create_credit_note

        if claim.invoice_id is None:
            raise ValueError("Cannot create credit note without a linked invoice")

        # Fetch invoice to determine amount if not specified
        inv_result = await self.db.execute(
            select(Invoice).where(
                Invoice.id == claim.invoice_id,
                Invoice.org_id == claim.org_id,
            )
        )
        invoice = inv_result.scalar_one_or_none()
        if invoice is None:
            raise ValueError("Linked invoice not found")

        credit_amount = amount if amount is not None else invoice.total

        result = await create_credit_note(
            self.db,
            org_id=claim.org_id,
            user_id=user_id,
            invoice_id=claim.invoice_id,
            amount=credit_amount,
            reason=f"Claim resolution: {claim.description[:200]}",
            items=[],
            ip_address=ip_address,
        )

        return ResolutionResult(
            resolution_type=ResolutionType.CREDIT_NOTE.value,
            credit_note_id=result["credit_note"]["id"],
        )

    # ------------------------------------------------------------------
    # Task 5.5: Exchange handler (Req 3.5, 4.1-4.5)
    # ------------------------------------------------------------------

    async def _process_exchange(
        self,
        claim: CustomerClaim,
        return_stock_item_ids: list[uuid.UUID],
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> ResolutionResult:
        """Create stock return movements for exchanged items.

        For each stock item:
        - Create a StockMovement with movement_type "return",
          reference_type "claim", reference_id = claim.id
        - Check if catalogue entry is archived (is_active=False) or
          has zero resale value
        - Flag as write-off if applicable

        Requirements: 3.5, 4.1, 4.2, 4.3, 4.4, 4.5
        """
        from app.modules.catalogue.models import PartsCatalogue
        from app.modules.inventory.models import StockItem
        from app.modules.stock.service import StockService
        from app.modules.products.models import Product

        stock_service = StockService(self.db)
        movements: list[dict] = []
        total_write_off = Decimal("0")

        for stock_item_id in return_stock_item_ids:
            # Try to find as a StockItem first
            si_result = await self.db.execute(
                select(StockItem).where(
                    StockItem.id == stock_item_id,
                    StockItem.org_id == claim.org_id,
                )
            )
            stock_item = si_result.scalar_one_or_none()

            is_write_off = False
            write_off_amount = Decimal("0")
            product = None

            if stock_item is not None:
                # Check catalogue entry for archived status
                cost_price = stock_item.cost_per_unit or stock_item.purchase_price or Decimal("0")
                sell_price = stock_item.sell_price or Decimal("0")

                # Check if catalogue entry is archived
                if stock_item.catalogue_type == "part":
                    cat_result = await self.db.execute(
                        select(PartsCatalogue).where(
                            PartsCatalogue.id == stock_item.catalogue_item_id,
                        )
                    )
                    catalogue_entry = cat_result.scalar_one_or_none()
                    if catalogue_entry is not None and not catalogue_entry.is_active:
                        is_write_off = True

                # Zero resale value check
                if sell_price <= 0:
                    is_write_off = True

                if is_write_off:
                    write_off_amount = cost_price

                # Find linked product for stock movement
                prod_result = await self.db.execute(
                    select(Product).where(
                        Product.org_id == claim.org_id,
                        Product.id == stock_item.catalogue_item_id,
                    )
                )
                product = prod_result.scalar_one_or_none()

            if product is None:
                # Fallback: try as a Product ID directly
                prod_result = await self.db.execute(
                    select(Product).where(
                        Product.id == stock_item_id,
                        Product.org_id == claim.org_id,
                    )
                )
                product = prod_result.scalar_one_or_none()

                if product is not None:
                    cost_price = product.cost_price or Decimal("0")
                    if not product.is_active or product.sale_price <= 0:
                        is_write_off = True
                        write_off_amount = cost_price

            if product is not None:
                movement = await stock_service.increment_stock(
                    product,
                    Decimal("1"),
                    movement_type="return",
                    reference_type="claim",
                    reference_id=claim.id,
                    performed_by=user_id,
                )

                movements.append({
                    "movement_id": movement.id,
                    "is_write_off": is_write_off,
                    "write_off_amount": write_off_amount,
                })

                if is_write_off:
                    total_write_off += write_off_amount

        return ResolutionResult(
            resolution_type=ResolutionType.EXCHANGE.value,
            return_movement_ids=movements,
            write_off_cost=total_write_off,
        )

    # ------------------------------------------------------------------
    # Task 5.6: Redo service handler (Req 3.6)
    # ------------------------------------------------------------------

    async def _process_redo_service(
        self,
        claim: CustomerClaim,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> ResolutionResult:
        """Create a JobCard with zero charge linked to the original claim.

        Requirements: 3.6
        """
        from app.modules.job_cards.service import create_job_card, get_job_card

        vehicle_rego = None
        description = f"Warranty redo for claim: {claim.description[:200]}"

        # Pull vehicle_rego from original job card if available
        if claim.job_card_id is not None:
            try:
                original_job = await get_job_card(
                    self.db,
                    org_id=claim.org_id,
                    job_card_id=claim.job_card_id,
                )
                vehicle_rego = original_job.get("vehicle_rego")
                orig_desc = original_job.get("description") or ""
                if orig_desc:
                    description = f"Warranty redo: {orig_desc}"
            except ValueError:
                pass  # Original job card not found, continue without it

        result = await create_job_card(
            self.db,
            org_id=claim.org_id,
            user_id=user_id,
            customer_id=claim.customer_id,
            vehicle_rego=vehicle_rego,
            description=description,
            notes=f"Linked to claim ID: {claim.id}",
            branch_id=claim.branch_id,
            line_items_data=[],  # Zero charge
            ip_address=ip_address,
        )

        return ResolutionResult(
            resolution_type=ResolutionType.REDO_SERVICE.value,
            warranty_job_id=result["id"],
        )

    # ------------------------------------------------------------------
    # no_action handler (Req 3.7)
    # ------------------------------------------------------------------

    async def _process_no_action(
        self,
        claim: CustomerClaim,
        user_id: uuid.UUID,
        ip_address: str | None,
    ) -> ResolutionResult:
        """No downstream actions — just mark as resolved.

        Requirements: 3.7
        """
        return ResolutionResult(
            resolution_type=ResolutionType.NO_ACTION.value,
        )

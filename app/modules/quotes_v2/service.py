"""Quote service — CRUD, send, accept, convert, revise, expiry check.

**Validates: Requirement 12.1–12.7**
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quotes_v2.models import Quote
from app.modules.quotes_v2.schemas import QuoteCreate, QuoteUpdate


class QuoteService:
    """Service layer for quote lifecycle management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _next_quote_number(self, org_id: uuid.UUID) -> str:
        """Generate the next sequential quote number for an org."""
        result = await self.db.execute(
            select(func.count()).select_from(Quote).where(Quote.org_id == org_id)
        )
        count = result.scalar() or 0
        return f"QT-{count + 1:05d}"

    @staticmethod
    def _compute_totals(line_items: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
        """Compute subtotal, tax_amount, total from line items."""
        subtotal = Decimal("0")
        tax_total = Decimal("0")
        for item in line_items:
            qty = Decimal(str(item.get("quantity", 1)))
            price = Decimal(str(item.get("unit_price", 0)))
            line_total = qty * price
            subtotal += line_total
            tax_rate = Decimal(str(item.get("tax_rate", 0)))
            tax_total += line_total * tax_rate / Decimal("100")
        total = subtotal + tax_total
        return subtotal.quantize(Decimal("0.01")), tax_total.quantize(Decimal("0.01")), total.quantize(Decimal("0.01"))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_quotes(
        self,
        org_id: uuid.UUID,
        *,
        status: str | None = None,
        customer_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List quotes with optional filters."""
        base = select(Quote).where(Quote.org_id == org_id)
        if status:
            base = base.where(Quote.status == status)
        if customer_id:
            base = base.where(Quote.customer_id == customer_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar() or 0

        query = base.order_by(Quote.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        quotes = list(result.scalars().all())
        return {"quotes": quotes, "total": total, "page": page, "page_size": page_size}

    async def create_quote(
        self,
        org_id: uuid.UUID,
        data: QuoteCreate,
        *,
        created_by: uuid.UUID | None = None,
    ) -> Quote:
        """Create a new draft quote."""
        quote_number = await self._next_quote_number(org_id)
        subtotal, tax_amount, total = self._compute_totals(data.line_items)

        quote = Quote(
            org_id=org_id,
            quote_number=quote_number,
            customer_id=data.customer_id,
            project_id=data.project_id,
            expiry_date=data.expiry_date,
            terms=data.terms,
            internal_notes=data.internal_notes,
            line_items=data.line_items,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total=total,
            currency=data.currency,
            acceptance_token=secrets.token_urlsafe(32),
            created_by=created_by,
        )
        self.db.add(quote)
        await self.db.flush()
        return quote

    async def get_quote(self, org_id: uuid.UUID, quote_id: uuid.UUID) -> Quote | None:
        """Get a single quote by ID."""
        result = await self.db.execute(
            select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def update_quote(
        self,
        org_id: uuid.UUID,
        quote_id: uuid.UUID,
        data: QuoteUpdate,
    ) -> Quote | None:
        """Update a draft quote."""
        quote = await self.get_quote(org_id, quote_id)
        if quote is None:
            return None
        if quote.status != "draft":
            raise ValueError("Only draft quotes can be updated")

        update_data = data.model_dump(exclude_unset=True)
        if "line_items" in update_data and update_data["line_items"] is not None:
            subtotal, tax_amount, total = self._compute_totals(update_data["line_items"])
            update_data["subtotal"] = subtotal
            update_data["tax_amount"] = tax_amount
            update_data["total"] = total

        for key, value in update_data.items():
            setattr(quote, key, value)
        await self.db.flush()
        return quote

    # ------------------------------------------------------------------
    # Send to customer
    # ------------------------------------------------------------------

    async def send_to_customer(
        self, org_id: uuid.UUID, quote_id: uuid.UUID,
    ) -> Quote:
        """Mark quote as sent (email dispatch handled by Celery task)."""
        quote = await self.get_quote(org_id, quote_id)
        if quote is None:
            raise ValueError("Quote not found")
        if quote.status not in ("draft",):
            raise ValueError("Only draft quotes can be sent")
        quote.status = "sent"
        if not quote.acceptance_token:
            quote.acceptance_token = secrets.token_urlsafe(32)
        await self.db.flush()
        return quote

    # ------------------------------------------------------------------
    # Accept quote (public endpoint)
    # ------------------------------------------------------------------

    async def accept_quote(self, token: str) -> Quote:
        """Accept a quote via its public acceptance token."""
        result = await self.db.execute(
            select(Quote).where(Quote.acceptance_token == token)
        )
        quote = result.scalar_one_or_none()
        if quote is None:
            raise ValueError("Invalid or expired acceptance token")
        if quote.status != "sent":
            raise ValueError(f"Quote cannot be accepted (current status: {quote.status})")
        if quote.expiry_date and quote.expiry_date < date.today():
            quote.status = "expired"
            await self.db.flush()
            raise ValueError("Quote has expired")

        quote.status = "accepted"
        quote.accepted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return quote

    # ------------------------------------------------------------------
    # Convert to invoice
    # ------------------------------------------------------------------

    async def convert_to_invoice(
        self, org_id: uuid.UUID, quote_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Convert an accepted quote to a draft invoice.

        Creates a placeholder invoice ID and stores the bidirectional reference.
        In production the invoice module would create the actual invoice record.
        """
        quote = await self.get_quote(org_id, quote_id)
        if quote is None:
            raise ValueError("Quote not found")
        if quote.status != "accepted":
            raise ValueError("Only accepted quotes can be converted to invoices")
        if quote.converted_invoice_id is not None:
            raise ValueError("Quote has already been converted")

        invoice_id = uuid.uuid4()
        quote.converted_invoice_id = invoice_id
        quote.status = "converted"
        await self.db.flush()

        return {
            "quote_id": quote.id,
            "invoice_id": invoice_id,
            "line_items": quote.line_items,
            "line_items_count": len(quote.line_items),
        }

    # ------------------------------------------------------------------
    # Create revision (versioning)
    # ------------------------------------------------------------------

    async def create_revision(
        self,
        org_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        created_by: uuid.UUID | None = None,
    ) -> Quote:
        """Create a new revision of a quote linked to the previous version.

        The new quote gets version_number + 1 and previous_version_id
        pointing to the original quote.
        """
        original = await self.get_quote(org_id, quote_id)
        if original is None:
            raise ValueError("Quote not found")
        if original.status in ("converted",):
            raise ValueError("Cannot revise a converted quote")

        quote_number = await self._next_quote_number(org_id)
        revision = Quote(
            org_id=org_id,
            quote_number=quote_number,
            customer_id=original.customer_id,
            project_id=original.project_id,
            expiry_date=original.expiry_date,
            terms=original.terms,
            internal_notes=original.internal_notes,
            line_items=list(original.line_items),
            subtotal=original.subtotal,
            tax_amount=original.tax_amount,
            total=original.total,
            currency=original.currency,
            version_number=original.version_number + 1,
            previous_version_id=original.id,
            acceptance_token=secrets.token_urlsafe(32),
            created_by=created_by,
        )
        self.db.add(revision)

        # Mark original as declined since a new version supersedes it
        if original.status in ("draft", "sent"):
            original.status = "declined"

        await self.db.flush()
        return revision

    # ------------------------------------------------------------------
    # Expiry check
    # ------------------------------------------------------------------

    @staticmethod
    async def check_expiry(db: AsyncSession) -> int:
        """Mark all sent quotes past their expiry_date as expired.

        Returns the number of quotes updated.
        """
        today = date.today()
        result = await db.execute(
            update(Quote)
            .where(Quote.status == "sent", Quote.expiry_date < today)
            .values(status="expired")
            .returning(Quote.id)
        )
        expired_ids = result.scalars().all()
        return len(expired_ids)

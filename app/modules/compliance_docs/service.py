"""Compliance document service: upload, link, expiry check, dashboard.

Business rules:
- upload_document(): creates a ComplianceDocument record for an org.
- link_to_invoice(): associates an existing document with an invoice.
- check_expiry(): returns documents expiring within a given number of days.
- get_dashboard(): returns summary counts and document list for an org.
- get_documents_for_invoice(): returns all compliance docs linked to an invoice.

**Validates: Requirement — Compliance Module**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance_docs.models import ComplianceDocument
from app.modules.compliance_docs.schemas import ComplianceDocumentCreate


class ComplianceService:
    """Service layer for compliance document management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upload_document(
        self,
        org_id: uuid.UUID,
        payload: ComplianceDocumentCreate,
        uploaded_by: uuid.UUID | None = None,
    ) -> ComplianceDocument:
        """Create a new compliance document record."""
        doc = ComplianceDocument(
            org_id=org_id,
            document_type=payload.document_type,
            description=payload.description,
            file_key=payload.file_key,
            file_name=payload.file_name,
            expiry_date=payload.expiry_date,
            invoice_id=payload.invoice_id,
            job_id=payload.job_id,
            uploaded_by=uploaded_by,
        )
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def link_to_invoice(
        self,
        doc_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> ComplianceDocument:
        """Link an existing compliance document to an invoice."""
        stmt = select(ComplianceDocument).where(ComplianceDocument.id == doc_id)
        result = await self.db.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc is None:
            raise ValueError(f"Compliance document {doc_id} not found")
        doc.invoice_id = invoice_id
        await self.db.flush()
        return doc

    async def check_expiry(
        self,
        org_id: uuid.UUID,
        days_ahead: int = 30,
    ) -> list[ComplianceDocument]:
        """Return documents expiring within the given number of days."""
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        stmt = (
            select(ComplianceDocument)
            .where(
                and_(
                    ComplianceDocument.org_id == org_id,
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date <= cutoff,
                    ComplianceDocument.expiry_date >= today,
                )
            )
            .order_by(ComplianceDocument.expiry_date.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_dashboard(self, org_id: uuid.UUID) -> dict:
        """Return compliance dashboard data for an org."""
        today = date.today()
        soon_cutoff = today + timedelta(days=30)

        # Total documents
        total_stmt = select(func.count()).select_from(ComplianceDocument).where(
            ComplianceDocument.org_id == org_id,
        )
        total = (await self.db.execute(total_stmt)).scalar() or 0

        # Expiring soon (within 30 days)
        expiring_stmt = select(func.count()).select_from(ComplianceDocument).where(
            and_(
                ComplianceDocument.org_id == org_id,
                ComplianceDocument.expiry_date.isnot(None),
                ComplianceDocument.expiry_date <= soon_cutoff,
                ComplianceDocument.expiry_date >= today,
            )
        )
        expiring_soon = (await self.db.execute(expiring_stmt)).scalar() or 0

        # Expired
        expired_stmt = select(func.count()).select_from(ComplianceDocument).where(
            and_(
                ComplianceDocument.org_id == org_id,
                ComplianceDocument.expiry_date.isnot(None),
                ComplianceDocument.expiry_date < today,
            )
        )
        expired = (await self.db.execute(expired_stmt)).scalar() or 0

        # All documents
        docs_stmt = (
            select(ComplianceDocument)
            .where(ComplianceDocument.org_id == org_id)
            .order_by(ComplianceDocument.created_at.desc())
        )
        docs_result = await self.db.execute(docs_stmt)
        documents = list(docs_result.scalars().all())

        return {
            "total_documents": total,
            "expiring_soon": expiring_soon,
            "expired": expired,
            "documents": documents,
        }

    async def get_documents_for_invoice(
        self,
        org_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> list[ComplianceDocument]:
        """Return all compliance documents linked to a specific invoice."""
        stmt = (
            select(ComplianceDocument)
            .where(
                and_(
                    ComplianceDocument.org_id == org_id,
                    ComplianceDocument.invoice_id == invoice_id,
                )
            )
            .order_by(ComplianceDocument.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_documents(
        self,
        org_id: uuid.UUID,
    ) -> list[ComplianceDocument]:
        """Return all compliance documents for an org."""
        stmt = (
            select(ComplianceDocument)
            .where(ComplianceDocument.org_id == org_id)
            .order_by(ComplianceDocument.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

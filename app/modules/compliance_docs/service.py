"""Compliance document service: upload, link, expiry check, dashboard.

Business rules:
- upload_document(): creates a ComplianceDocument record for an org.
- upload_document_with_file(): validates + stores file, creates DB record.
- link_to_invoice(): associates an existing document with an invoice.
- check_expiry(): returns documents expiring within a given number of days.
- get_dashboard(): returns summary counts and document list for an org.
- get_documents_for_invoice(): returns all compliance docs linked to an invoice.
- update_document(): edits metadata for an existing document.
- delete_document(): removes a document record and its file from storage.
- list_documents_filtered(): server-side filtering, sorting, and search.
- get_badge_count(): count of expired + expiring_soon documents.
- get_categories(): predefined + org-specific custom categories.
- create_custom_category(): creates an org-specific category.
- get_document_for_download(): validates org ownership, returns document.

**Validates: Requirements 2.2, 2.3, 2.4, 2.5, 3.7, 4.2, 5.1, 5.2, 5.3,
             6.4, 6.5, 6.6, 8.5**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import HTTPException, UploadFile
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance_docs.file_storage import ComplianceFileStorage
from app.modules.compliance_docs.models import (
    ComplianceDocument,
    ComplianceDocumentCategory,
)
from app.modules.compliance_docs.schemas import ComplianceDocumentCreate


class ComplianceService:
    """Service layer for compliance document management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Existing methods (with refresh fixes)
    # ------------------------------------------------------------------

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
        await self.db.refresh(doc)
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
        await self.db.refresh(doc)
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
        """Return compliance dashboard data for an org.

        Includes valid_documents count and computed status per document.
        """
        today = date.today()
        soon_cutoff = today + timedelta(days=30)

        # Total documents
        total_stmt = (
            select(func.count())
            .select_from(ComplianceDocument)
            .where(ComplianceDocument.org_id == org_id)
        )
        total = (await self.db.execute(total_stmt)).scalar() or 0

        # Valid documents (expiry_date > today + 30 days)
        valid_stmt = (
            select(func.count())
            .select_from(ComplianceDocument)
            .where(
                and_(
                    ComplianceDocument.org_id == org_id,
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date > soon_cutoff,
                )
            )
        )
        valid_documents = (await self.db.execute(valid_stmt)).scalar() or 0

        # Expiring soon (within 30 days, not yet expired)
        expiring_stmt = (
            select(func.count())
            .select_from(ComplianceDocument)
            .where(
                and_(
                    ComplianceDocument.org_id == org_id,
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date <= soon_cutoff,
                    ComplianceDocument.expiry_date >= today,
                )
            )
        )
        expiring_soon = (await self.db.execute(expiring_stmt)).scalar() or 0

        # Expired
        expired_stmt = (
            select(func.count())
            .select_from(ComplianceDocument)
            .where(
                and_(
                    ComplianceDocument.org_id == org_id,
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date < today,
                )
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
            "valid_documents": valid_documents,
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

    # ------------------------------------------------------------------
    # New methods (Task 3.2)
    # ------------------------------------------------------------------

    async def upload_document_with_file(
        self,
        org_id: uuid.UUID,
        file: UploadFile,
        metadata: dict,
        uploaded_by: uuid.UUID | None = None,
    ) -> ComplianceDocument:
        """Validate and store an uploaded file, then create the DB record.

        *metadata* should contain keys matching ComplianceDocument columns:
        document_type, description, expiry_date, invoice_id, job_id.

        **Validates: Requirements 3.7**
        """
        storage = ComplianceFileStorage()
        file_key = await storage.save_file(org_id, file)

        doc = ComplianceDocument(
            org_id=org_id,
            document_type=metadata.get("document_type", ""),
            description=metadata.get("description"),
            file_key=file_key,
            file_name=file.filename or "unnamed",
            expiry_date=metadata.get("expiry_date"),
            invoice_id=metadata.get("invoice_id"),
            job_id=metadata.get("job_id"),
            uploaded_by=uploaded_by,
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def update_document(
        self,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        payload: dict,
    ) -> ComplianceDocument:
        """Update metadata on an existing compliance document.

        Only fields present in *payload* are updated. Validates that the
        document belongs to the requesting organisation (HTTP 403).

        **Validates: Requirements 5.1, 5.3**
        """
        doc = await self._get_org_document(org_id, doc_id)

        allowed_fields = {"document_type", "description", "expiry_date"}
        for field, value in payload.items():
            if field in allowed_fields:
                setattr(doc, field, value)

        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def delete_document(
        self,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> None:
        """Delete a compliance document record and its file from storage.

        Validates org ownership (HTTP 403).

        **Validates: Requirements 5.2, 5.3**
        """
        doc = await self._get_org_document(org_id, doc_id)

        # Remove file from storage
        storage = ComplianceFileStorage()
        await storage.delete_file(doc.file_key)

        await self.db.delete(doc)
        await self.db.flush()

    async def list_documents_filtered(
        self,
        org_id: uuid.UUID,
        search: str | None = None,
        status: str | None = None,
        category: str | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ) -> tuple[list[ComplianceDocument], int]:
        """Return filtered, sorted compliance documents for an org.

        Supports server-side text search (file_name, document_type,
        description), status filtering, category filtering, and sorting.

        **Validates: Requirements 2.2, 2.3, 2.4, 2.5**
        """
        today = date.today()
        soon_cutoff = today + timedelta(days=30)

        stmt = select(ComplianceDocument).where(
            ComplianceDocument.org_id == org_id,
        )

        # Text search across file_name, document_type, description
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    ComplianceDocument.file_name.ilike(pattern),
                    ComplianceDocument.document_type.ilike(pattern),
                    ComplianceDocument.description.ilike(pattern),
                )
            )

        # Status filtering
        if status:
            stmt = self._apply_status_filter(stmt, status, today, soon_cutoff)

        # Category filtering
        if category:
            stmt = stmt.where(ComplianceDocument.document_type == category)

        # Count before sorting (for total)
        count_stmt = (
            select(func.count())
            .select_from(stmt.subquery())
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Sorting
        stmt = self._apply_sorting(stmt, sort_by, sort_dir)

        result = await self.db.execute(stmt)
        documents = list(result.scalars().all())

        return documents, total

    async def get_badge_count(self, org_id: uuid.UUID) -> int:
        """Return count of expired + expiring_soon documents for an org.

        **Validates: Requirements 8.5**
        """
        today = date.today()
        soon_cutoff = today + timedelta(days=30)

        stmt = (
            select(func.count())
            .select_from(ComplianceDocument)
            .where(
                and_(
                    ComplianceDocument.org_id == org_id,
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date <= soon_cutoff,
                )
            )
        )
        count = (await self.db.execute(stmt)).scalar() or 0
        return count

    async def get_categories(
        self,
        org_id: uuid.UUID,
    ) -> list[ComplianceDocumentCategory]:
        """Return predefined categories + org-specific custom categories.

        Predefined categories are listed first, then org-specific custom
        categories, both sorted alphabetically by name.

        **Validates: Requirements 6.6**
        """
        stmt = (
            select(ComplianceDocumentCategory)
            .where(
                or_(
                    ComplianceDocumentCategory.is_predefined.is_(True),
                    ComplianceDocumentCategory.org_id == org_id,
                )
            )
            .order_by(
                ComplianceDocumentCategory.is_predefined.desc(),
                ComplianceDocumentCategory.name.asc(),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_custom_category(
        self,
        org_id: uuid.UUID,
        name: str,
    ) -> ComplianceDocumentCategory:
        """Create an org-specific custom category.

        Raises HTTP 409 if a category with the same name already exists
        for this organisation.

        **Validates: Requirements 6.4, 6.5**
        """
        category = ComplianceDocumentCategory(
            name=name,
            org_id=org_id,
            is_predefined=False,
        )
        self.db.add(category)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Category already exists",
            )
        await self.db.refresh(category)
        return category

    async def get_document_for_download(
        self,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> ComplianceDocument:
        """Return a compliance document after validating org ownership.

        Raises HTTP 403 if the document belongs to another org.
        Raises HTTP 404 if the document does not exist.

        **Validates: Requirements 4.2**
        """
        return await self._get_org_document(org_id, doc_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_org_document(
        self,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> ComplianceDocument:
        """Fetch a document by ID and validate org ownership.

        Raises HTTP 404 if not found, HTTP 403 if wrong org.
        """
        stmt = select(ComplianceDocument).where(ComplianceDocument.id == doc_id)
        result = await self.db.execute(stmt)
        doc = result.scalar_one_or_none()

        if doc is None:
            raise HTTPException(
                status_code=404,
                detail="Compliance document not found",
            )
        if doc.org_id != org_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )
        return doc

    @staticmethod
    def _apply_status_filter(stmt, status: str, today: date, soon_cutoff: date):
        """Apply a status filter to the query."""
        if status == "expired":
            stmt = stmt.where(
                and_(
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date < today,
                )
            )
        elif status == "expiring_soon":
            stmt = stmt.where(
                and_(
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date >= today,
                    ComplianceDocument.expiry_date <= soon_cutoff,
                )
            )
        elif status == "valid":
            stmt = stmt.where(
                and_(
                    ComplianceDocument.expiry_date.isnot(None),
                    ComplianceDocument.expiry_date > soon_cutoff,
                )
            )
        elif status == "no_expiry":
            stmt = stmt.where(ComplianceDocument.expiry_date.is_(None))
        return stmt

    @staticmethod
    def _apply_sorting(stmt, sort_by: str | None, sort_dir: str | None):
        """Apply column sorting to the query."""
        sortable_columns = {
            "document_type": ComplianceDocument.document_type,
            "file_name": ComplianceDocument.file_name,
            "expiry_date": ComplianceDocument.expiry_date,
            "created_at": ComplianceDocument.created_at,
        }

        column = sortable_columns.get(sort_by or "")
        if column is None:
            # Default sort: newest first
            return stmt.order_by(ComplianceDocument.created_at.desc())

        if sort_dir == "asc":
            return stmt.order_by(column.asc())
        return stmt.order_by(column.desc())

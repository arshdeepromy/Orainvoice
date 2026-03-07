"""Test: compliance documents appear in invoice email attachments.

**Validates: Requirement — Compliance Module, Task 38.8**
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.compliance_docs.attachments import (
    generate_compliance_pdf_section,
    get_invoice_compliance_attachments,
)
from app.modules.compliance_docs.models import ComplianceDocument


ORG_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()


def _make_doc(
    doc_type: str = "license",
    file_name: str = "license.pdf",
    expiry_date: date | None = None,
) -> ComplianceDocument:
    doc = ComplianceDocument(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        document_type=doc_type,
        file_key=f"compliance/{uuid.uuid4()}.pdf",
        file_name=file_name,
        expiry_date=expiry_date,
        invoice_id=INVOICE_ID,
    )
    return doc


class TestComplianceInvoiceAttachments:
    """Verify compliance documents are included in invoice email attachments."""

    @pytest.mark.asyncio
    async def test_attachments_returned_for_linked_docs(self) -> None:
        """Documents linked to an invoice are returned as attachments."""
        docs = [
            _make_doc("license", "trade_license.pdf", date(2025, 6, 1)),
            _make_doc("insurance", "liability_insurance.pdf", date(2025, 12, 31)),
        ]

        mock_db = AsyncMock()
        with pytest.MonkeyPatch.context() as mp:
            from app.modules.compliance_docs import service as svc_mod

            async def mock_get_docs(self, org_id, invoice_id):
                return docs

            mp.setattr(
                svc_mod.ComplianceService,
                "get_documents_for_invoice",
                mock_get_docs,
            )

            result = await get_invoice_compliance_attachments(
                mock_db, ORG_ID, INVOICE_ID,
            )

        assert len(result) == 2
        assert result[0]["file_name"] == "trade_license.pdf"
        assert result[0]["document_type"] == "license"
        assert result[1]["file_name"] == "liability_insurance.pdf"

    @pytest.mark.asyncio
    async def test_no_attachments_when_no_docs_linked(self) -> None:
        """No attachments returned when no compliance docs are linked."""
        mock_db = AsyncMock()
        with pytest.MonkeyPatch.context() as mp:
            from app.modules.compliance_docs import service as svc_mod

            async def mock_get_docs(self, org_id, invoice_id):
                return []

            mp.setattr(
                svc_mod.ComplianceService,
                "get_documents_for_invoice",
                mock_get_docs,
            )

            result = await get_invoice_compliance_attachments(
                mock_db, ORG_ID, INVOICE_ID,
            )

        assert len(result) == 0

    def test_pdf_section_contains_document_info(self) -> None:
        """PDF section includes document type, name, and expiry."""
        docs = [
            {
                "file_key": "compliance/abc.pdf",
                "file_name": "trade_license.pdf",
                "document_type": "license",
                "expiry_date": "2025-06-01",
            },
        ]
        section = generate_compliance_pdf_section(docs)
        assert "COMPLIANCE DOCUMENTS" in section
        assert "license" in section
        assert "trade_license.pdf" in section
        assert "2025-06-01" in section

    def test_pdf_section_empty_when_no_docs(self) -> None:
        """PDF section is empty string when no documents."""
        section = generate_compliance_pdf_section([])
        assert section == ""

    def test_pdf_section_handles_no_expiry(self) -> None:
        """PDF section shows 'No expiry' when expiry_date is None."""
        docs = [
            {
                "file_key": "compliance/abc.pdf",
                "file_name": "cert.pdf",
                "document_type": "certification",
                "expiry_date": None,
            },
        ]
        section = generate_compliance_pdf_section(docs)
        assert "No expiry" in section

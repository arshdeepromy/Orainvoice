"""Compliance document attachment helpers for invoice emails and PDFs.

Provides functions to:
- Gather compliance documents linked to an invoice for email attachment.
- Generate a compliance summary section for inclusion in invoice PDFs.

**Validates: Requirement — Compliance Module, Task 38.6**
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance_docs.service import ComplianceService


async def get_invoice_compliance_attachments(
    db: AsyncSession,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> list[dict]:
    """Return compliance document metadata for an invoice's email attachments.

    Each dict contains: file_key, file_name, document_type, expiry_date.
    The caller is responsible for fetching the actual file bytes from storage.
    """
    svc = ComplianceService(db)
    docs = await svc.get_documents_for_invoice(org_id, invoice_id)
    return [
        {
            "file_key": doc.file_key,
            "file_name": doc.file_name,
            "document_type": doc.document_type,
            "expiry_date": str(doc.expiry_date) if doc.expiry_date else None,
        }
        for doc in docs
    ]


def generate_compliance_pdf_section(
    compliance_docs: list[dict],
) -> str:
    """Generate a text section listing compliance documents for a PDF.

    Returns a formatted string suitable for inclusion in an invoice PDF
    template. Returns empty string if no documents are linked.
    """
    if not compliance_docs:
        return ""

    lines = ["COMPLIANCE DOCUMENTS", "=" * 40]
    for doc in compliance_docs:
        expiry = doc.get("expiry_date") or "No expiry"
        lines.append(
            f"  {doc['document_type']}: {doc['file_name']} (Expires: {expiry})"
        )
    lines.append("")
    return "\n".join(lines)

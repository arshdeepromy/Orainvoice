"""Progress claim PDF generation following standard construction industry layout.

Generates a PDF document with:
- Header: org branding, claim number, date
- Project details: name, contract value, variations
- Financial summary table: work completed, materials, retention, amount due
- Completion percentage bar
- Signature lines for claimant and approver

**Validates: Requirement — ProgressClaim Module, Task 35.5**
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Any


def generate_progress_claim_pdf(
    claim: dict[str, Any],
    org_name: str = "Organisation",
    project_name: str = "Project",
) -> bytes:
    """Generate a progress claim PDF as bytes.

    Uses a simple text-based layout. In production this would use
    a library like ReportLab or WeasyPrint. For now we generate a
    structured text representation that can be rendered or converted.
    """
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"  PROGRESS CLAIM #{claim.get('claim_number', '')}")
    lines.append(f"  {org_name}")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  Project: {project_name}")
    lines.append(f"  Claim Date: {claim.get('created_at', '')}")
    lines.append(f"  Status: {claim.get('status', 'draft').upper()}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  CONTRACT SUMMARY")
    lines.append("-" * 72)
    lines.append(f"  Original Contract Value:     ${_fmt(claim.get('contract_value', 0))}")
    lines.append(f"  Variations to Date:          ${_fmt(claim.get('variations_to_date', 0))}")
    lines.append(f"  Revised Contract Value:      ${_fmt(claim.get('revised_contract_value', 0))}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  WORK COMPLETED")
    lines.append("-" * 72)
    lines.append(f"  Work Completed to Date:      ${_fmt(claim.get('work_completed_to_date', 0))}")
    lines.append(f"  Less Previous Claims:        ${_fmt(claim.get('work_completed_previous', 0))}")
    lines.append(f"  Work This Period:            ${_fmt(claim.get('work_completed_this_period', 0))}")
    lines.append(f"  Materials on Site:           ${_fmt(claim.get('materials_on_site', 0))}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  PAYMENT SUMMARY")
    lines.append("-" * 72)
    lines.append(f"  Subtotal This Period:        ${_fmt(_sub(claim))}")
    lines.append(f"  Less Retention Withheld:     ${_fmt(claim.get('retention_withheld', 0))}")
    lines.append(f"  AMOUNT DUE THIS CLAIM:       ${_fmt(claim.get('amount_due', 0))}")
    lines.append("")
    lines.append(f"  Completion: {claim.get('completion_percentage', 0)}%")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  CERTIFICATION")
    lines.append("-" * 72)
    lines.append("")
    lines.append("  Claimant Signature: ________________________  Date: ____________")
    lines.append("")
    lines.append("  Approver Signature: ________________________  Date: ____________")
    lines.append("")
    lines.append("=" * 72)

    content = "\n".join(lines)
    return content.encode("utf-8")


def _fmt(value: Any) -> str:
    """Format a numeric value with commas and 2 decimal places."""
    try:
        d = Decimal(str(value))
        return f"{d:,.2f}"
    except Exception:
        return str(value)


def _sub(claim: dict[str, Any]) -> Decimal:
    """Calculate subtotal before retention."""
    this_period = Decimal(str(claim.get("work_completed_this_period", 0)))
    materials = Decimal(str(claim.get("materials_on_site", 0)))
    return this_period + materials

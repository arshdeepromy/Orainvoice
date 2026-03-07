"""Variation order PDF generation with org branding and signature space.

Generates a PDF document with:
- Header: org branding, variation number, date
- Project reference and variation details
- Cost impact (positive = addition, negative = deduction)
- Signature lines for contractor and client

**Validates: Requirement 29.4 — Variation Module, Task 36.5**
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def generate_variation_order_pdf(
    variation: dict[str, Any],
    org_name: str = "Organisation",
    project_name: str = "Project",
) -> bytes:
    """Generate a variation order PDF as bytes.

    Uses a structured text layout. In production this would use
    a library like ReportLab or WeasyPrint.
    """
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"  VARIATION ORDER #{variation.get('variation_number', '')}")
    lines.append(f"  {org_name}")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  Project: {project_name}")
    lines.append(f"  Date: {variation.get('created_at', '')}")
    lines.append(f"  Status: {variation.get('status', 'draft').upper()}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  VARIATION DETAILS")
    lines.append("-" * 72)
    lines.append("")
    lines.append(f"  Description:")
    lines.append(f"  {variation.get('description', '')}")
    lines.append("")

    cost = Decimal(str(variation.get("cost_impact", 0)))
    label = "ADDITION" if cost >= 0 else "DEDUCTION"
    lines.append(f"  Cost Impact ({label}):  ${_fmt(abs(cost))}")
    lines.append("")
    if variation.get("submitted_at"):
        lines.append(f"  Submitted: {variation['submitted_at']}")
    if variation.get("approved_at"):
        lines.append(f"  Approved:  {variation['approved_at']}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("  AUTHORISATION")
    lines.append("-" * 72)
    lines.append("")
    lines.append("  This variation order is submitted for approval.")
    lines.append("  Upon approval, the contract value will be adjusted accordingly.")
    lines.append("")
    lines.append("  Contractor Signature: ______________________  Date: ____________")
    lines.append("")
    lines.append("  Client Signature:     ______________________  Date: ____________")
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

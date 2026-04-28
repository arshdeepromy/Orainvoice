"""Snapshot renderer for job card appendix HTML.

Renders job card data into a self-contained HTML fragment with inline CSS
and base64-embedded images, suitable for appending to invoice PDFs via
WeasyPrint.

Requirements: 2.1–2.10, 6.1, 6.2, 6.5, NF Security 1, NF Security 2
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"
_TEMPLATE_NAME = "job_card_appendix.html"

# Image MIME types we embed as base64 data URIs
_IMAGE_MIME_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
})


def _build_customer_context(customer_data: dict | None) -> dict | None:
    """Build template-friendly customer context from raw job card customer dict."""
    if not customer_data:
        return None

    first = customer_data.get("first_name") or ""
    last = customer_data.get("last_name") or ""
    name = f"{first} {last}".strip() or None

    return {
        "name": name,
        "phone": customer_data.get("phone"),
        "email": customer_data.get("email"),
        "address": customer_data.get("address"),
    }


def _build_line_items_context(line_items: list[dict] | None) -> list[dict]:
    """Build template-friendly line items from raw job card line items."""
    if not line_items:
        return []

    return [
        {
            "item_type": li.get("item_type", ""),
            "description": li.get("description", ""),
            "quantity": li.get("quantity", 0),
            "unit_price": li.get("unit_price", 0),
            "line_total": li.get("line_total", 0),
        }
        for li in line_items
    ]


def _build_time_entries_context(time_entries: list[dict] | None) -> list[dict]:
    """Build template-friendly time entries from raw job card time entries.

    Raw entries have: started_at, stopped_at, duration_minutes, user_id, notes
    Template expects: staff_name, start_time, stop_time, duration
    """
    if not time_entries:
        return []

    result = []
    for entry in time_entries:
        started = entry.get("started_at")
        stopped = entry.get("stopped_at")
        duration_mins = entry.get("duration_minutes")

        # Format times as strings
        start_str = str(started) if started else ""
        stop_str = str(stopped) if stopped else ""

        # Format duration
        if duration_mins is not None:
            hours = int(duration_mins) // 60
            mins = int(duration_mins) % 60
            duration_str = f"{hours}h {mins}m" if hours else f"{mins}m"
        else:
            duration_str = ""

        # Use staff_name if available (from enriched data), otherwise fall back
        staff_name = entry.get("staff_name") or entry.get("user_name") or ""

        result.append({
            "staff_name": staff_name,
            "start_time": start_str,
            "stop_time": stop_str,
            "duration": duration_str,
        })

    return result


def _build_attachment_contexts(
    attachments: list[dict],
    attachment_bytes: dict[str, bytes],
) -> tuple[list[dict], list[dict]]:
    """Build image and PDF attachment contexts for the template.

    Returns:
        Tuple of (image_attachments, pdf_attachments) lists.
        Each image attachment has: filename, data_uri (or None), is_missing (bool)
        Each PDF attachment has: filename
    """
    image_attachments: list[dict] = []
    pdf_attachments: list[dict] = []

    for att in attachments:
        mime_type = att.get("mime_type", "")
        filename = att.get("file_name", "unknown")
        att_id = str(att.get("id", ""))

        if mime_type in _IMAGE_MIME_TYPES:
            raw_bytes = attachment_bytes.get(att_id)
            if raw_bytes:
                b64 = base64.b64encode(raw_bytes).decode("ascii")
                data_uri = f"data:{mime_type};base64,{b64}"
                image_attachments.append({
                    "filename": filename,
                    "data_uri": data_uri,
                    "is_missing": False,
                })
            else:
                image_attachments.append({
                    "filename": filename,
                    "data_uri": None,
                    "is_missing": True,
                })
        elif mime_type == "application/pdf":
            pdf_attachments.append({
                "filename": filename,
            })

    return image_attachments, pdf_attachments


def _format_datetime(value) -> str:
    """Format a datetime value to a string for display."""
    if value is None:
        return ""
    return str(value)


async def render_job_card_appendix_html(
    job_card_data: dict,
    attachments: list[dict],
    attachment_bytes: dict[str, bytes],
    trade_family: str | None = None,
) -> str:
    """Render job card data into a self-contained HTML fragment.

    Args:
        job_card_data: Job card dict (as returned by get_job_card(), with
            description already excluded by the caller).
        attachments: List of attachment metadata dicts from list_attachments().
        attachment_bytes: Map of str(attachment_id) -> decrypted file bytes
            (images only).
        trade_family: Organisation's trade family slug for conditional sections
            (e.g. 'automotive-transport').

    Returns:
        Self-contained HTML string with inline CSS and base64-embedded images.

    Requirements: 2.1–2.10, 6.1, 6.2, 6.5, NF Security 1, NF Security 2
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )
    template = env.get_template(_TEMPLATE_NAME)

    # Build template context
    customer = _build_customer_context(job_card_data.get("customer"))
    line_items = _build_line_items_context(job_card_data.get("line_items"))
    time_entries = _build_time_entries_context(job_card_data.get("time_entries"))
    image_attachments, pdf_attachments = _build_attachment_contexts(
        attachments, attachment_bytes
    )

    # Determine if we should show the attachments section at all (Req 6.2):
    # If all image attachments are missing and there are no PDF attachments,
    # omit the entire attachments section.
    all_images_missing = (
        len(image_attachments) > 0
        and all(img["is_missing"] for img in image_attachments)
    )
    if all_images_missing and not pdf_attachments:
        has_attachments = False
        image_attachments = []
    else:
        has_attachments = bool(image_attachments or pdf_attachments)

    # Build the reference from the job card ID
    jc_id = job_card_data.get("id")
    reference = str(jc_id) if jc_id else None

    context = {
        "reference": reference,
        "customer": customer,
        "trade_family": trade_family,
        "vehicle_rego": job_card_data.get("vehicle_rego"),
        "service_type_name": job_card_data.get("service_type_name"),
        "service_type_values": job_card_data.get("service_type_values") or [],
        "line_items": line_items,
        "time_entries": time_entries,
        "image_attachments": image_attachments,
        "pdf_attachments": pdf_attachments,
        "notes": job_card_data.get("notes"),
        "assigned_to_name": job_card_data.get("assigned_to_name"),
        "created_at": _format_datetime(job_card_data.get("created_at")),
        "updated_at": _format_datetime(job_card_data.get("updated_at")),
        "has_attachments": has_attachments,
    }

    return template.render(**context)

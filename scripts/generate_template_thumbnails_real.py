#!/usr/bin/env python3
"""Generate accurate thumbnail images by rendering real Jinja2 templates.

Renders each template with sample data using the same Jinja2 engine as the
preview endpoint, converts to PDF via WeasyPrint, then extracts the first
page as a PNG thumbnail using pdf2image (or a fallback approach).

Run inside the Docker container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
      python scripts/generate_template_thumbnails_real.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from weasyprint import HTML
from PIL import Image
import io

from app.modules.invoices.template_registry import TEMPLATES
from app.modules.invoices.template_preview import (
    _to_dot,
    _build_jinja_env,
    _DEFAULT_ORG,
    SAMPLE_INVOICE,
    SAMPLE_CUSTOMER,
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "templates"
THUMB_WIDTH = 400
# A4 aspect ratio: 210mm x 297mm = 1:1.414
THUMB_HEIGHT = int(THUMB_WIDTH * 1.414)


def render_template_html(template_meta) -> str:
    """Render a template with sample data, returning HTML string."""
    from app.modules.invoices.service import get_currency_symbol
    from app.core.i18n_pdf import get_pdf_context

    invoice = _to_dot(dict(SAMPLE_INVOICE))
    customer = _to_dot(dict(SAMPLE_CUSTOMER))
    org_context = _to_dot(dict(_DEFAULT_ORG))

    colours = {
        "primary_colour": template_meta.default_primary_colour,
        "accent_colour": template_meta.default_accent_colour,
        "header_bg_colour": template_meta.default_header_bg_colour,
    }

    currency_symbol = get_currency_symbol("NZD")
    i18n_ctx = get_pdf_context("en")

    env = _build_jinja_env()
    template = env.get_template(template_meta.template_file)

    return template.render(
        invoice=invoice,
        org=org_context,
        customer=customer,
        currency_symbol=currency_symbol,
        gst_percentage=15,
        payment_terms="Payment due within 14 days.",
        terms_and_conditions="All work guaranteed for 12 months.",
        colours=_to_dot(colours),
        **i18n_ctx,
    )


def html_to_thumbnail(html: str, output_path: Path) -> None:
    """Convert HTML to PDF, then extract first page as PNG thumbnail."""
    # Render to PDF bytes
    pdf_bytes = HTML(string=html).write_pdf()

    # Try PyMuPDF first (no external dependencies needed)
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        # Render at 2x for quality, then resize
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img = img.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)
        img.save(str(output_path), "PNG")
        doc.close()
        return
    except ImportError:
        pass

    # Fallback: pdf2image (requires poppler)
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=150)
        if images:
            img = images[0]
            img = img.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)
            img.save(str(output_path), "PNG")
            return
    except (ImportError, Exception):
        pass

    # Last fallback: white placeholder
    print(f"    ⚠ No PDF-to-image library available, using blank thumbnail")
    img = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), (255, 255, 255))
    img.save(str(output_path), "PNG")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Generating real template thumbnails...")
    print(f"Output: {OUTPUT_DIR}\n")

    for template_id, meta in TEMPLATES.items():
        print(f"  Rendering {template_id}...", end=" ", flush=True)
        try:
            html = render_template_html(meta)
            output_path = OUTPUT_DIR / f"{template_id}.png"
            html_to_thumbnail(html, output_path)
            print(f"✓ {output_path.name}")
        except Exception as exc:
            print(f"✗ {exc}")

    print(f"\nDone — {len(TEMPLATES)} thumbnails generated.")


if __name__ == "__main__":
    main()

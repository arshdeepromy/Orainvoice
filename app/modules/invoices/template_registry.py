"""Central registry of all available invoice PDF templates.

This module defines the catalogue of invoice templates as a Python dictionary,
keeping the registry importable by both the backend renderer and the API layer.
Adding new templates is a code-only change — no database table needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LogoPosition = Literal["left", "center", "side"]
LayoutType = Literal["standard", "compact"]


@dataclass(frozen=True)
class TemplateMetadata:
    """Immutable metadata for a single invoice PDF template."""

    id: str
    display_name: str
    description: str
    thumbnail_path: str  # relative to frontend/public/
    default_primary_colour: str  # hex e.g. "#2563eb"
    default_accent_colour: str
    default_header_bg_colour: str
    logo_position: LogoPosition
    layout_type: LayoutType
    template_file: str  # filename in app/templates/pdf/


# ---------------------------------------------------------------------------
# Master registry — source of truth for all templates
# 12 templates total: 9 standard + 3 compact
# Logo positions: 5 left, 3 center, 3 side (≥2 per position)
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, TemplateMetadata] = {
    "default": TemplateMetadata(
        id="default",
        display_name="Default",
        description="The original OraInvoice template — clean blue layout used since day one.",
        thumbnail_path="templates/default.png",
        default_primary_colour="#3b5bdb",
        default_accent_colour="#3b5bdb",
        default_header_bg_colour="#ffffff",
        logo_position="left",
        layout_type="standard",
        template_file="invoice.html",
    ),
    "classic": TemplateMetadata(
        id="classic",
        display_name="Classic",
        description="Clean, traditional layout with left-aligned logo and blue accents.",
        thumbnail_path="templates/classic.png",
        default_primary_colour="#2563eb",
        default_accent_colour="#1e40af",
        default_header_bg_colour="#ffffff",
        logo_position="left",
        layout_type="standard",
        template_file="classic.html",
    ),
    "modern-dark": TemplateMetadata(
        id="modern-dark",
        display_name="Modern Dark",
        description="Sleek dark header with indigo tones for a contemporary look.",
        thumbnail_path="templates/modern-dark.png",
        default_primary_colour="#6366f1",
        default_accent_colour="#4f46e5",
        default_header_bg_colour="#1e1b4b",
        logo_position="left",
        layout_type="standard",
        template_file="modern-dark.html",
    ),
    "compact-blue": TemplateMetadata(
        id="compact-blue",
        display_name="Compact Blue",
        description="Space-efficient layout with sky-blue accents for concise invoices.",
        thumbnail_path="templates/compact-blue.png",
        default_primary_colour="#0284c7",
        default_accent_colour="#0369a1",
        default_header_bg_colour="#f0f9ff",
        logo_position="left",
        layout_type="compact",
        template_file="compact-blue.html",
    ),
    "bold-header": TemplateMetadata(
        id="bold-header",
        display_name="Bold Header",
        description="Eye-catching dark header with bold red accents for maximum impact.",
        thumbnail_path="templates/bold-header.png",
        default_primary_colour="#dc2626",
        default_accent_colour="#b91c1c",
        default_header_bg_colour="#1a1a1a",
        logo_position="center",
        layout_type="standard",
        template_file="bold-header.html",
    ),
    "minimal": TemplateMetadata(
        id="minimal",
        display_name="Minimal",
        description="Understated design with neutral tones and clean typography.",
        thumbnail_path="templates/minimal.png",
        default_primary_colour="#374151",
        default_accent_colour="#6b7280",
        default_header_bg_colour="#ffffff",
        logo_position="left",
        layout_type="standard",
        template_file="minimal.html",
    ),
    "trade-pro": TemplateMetadata(
        id="trade-pro",
        display_name="Trade Pro",
        description="Professional green-themed layout designed for trade businesses.",
        thumbnail_path="templates/trade-pro.png",
        default_primary_colour="#059669",
        default_accent_colour="#047857",
        default_header_bg_colour="#ecfdf5",
        logo_position="side",
        layout_type="standard",
        template_file="trade-pro.html",
    ),
    "corporate": TemplateMetadata(
        id="corporate",
        display_name="Corporate",
        description="Formal centred layout with navy and blue corporate styling.",
        thumbnail_path="templates/corporate.png",
        default_primary_colour="#1e3a5f",
        default_accent_colour="#2563eb",
        default_header_bg_colour="#f8fafc",
        logo_position="center",
        layout_type="standard",
        template_file="corporate.html",
    ),
    "compact-green": TemplateMetadata(
        id="compact-green",
        display_name="Compact Green",
        description="Condensed green-themed layout for quick-read invoices.",
        thumbnail_path="templates/compact-green.png",
        default_primary_colour="#16a34a",
        default_accent_colour="#15803d",
        default_header_bg_colour="#f0fdf4",
        logo_position="left",
        layout_type="compact",
        template_file="compact-green.html",
    ),
    "elegant": TemplateMetadata(
        id="elegant",
        display_name="Elegant",
        description="Refined purple palette with graceful typography and spacing.",
        thumbnail_path="templates/elegant.png",
        default_primary_colour="#7c3aed",
        default_accent_colour="#6d28d9",
        default_header_bg_colour="#faf5ff",
        logo_position="center",
        layout_type="standard",
        template_file="elegant.html",
    ),
    "compact-mono": TemplateMetadata(
        id="compact-mono",
        display_name="Compact Mono",
        description="Monochrome compact layout with modern minimalist styling.",
        thumbnail_path="templates/compact-mono.png",
        default_primary_colour="#1a1a1a",
        default_accent_colour="#525252",
        default_header_bg_colour="#fafafa",
        logo_position="side",
        layout_type="compact",
        template_file="compact-mono.html",
    ),
    "sunrise": TemplateMetadata(
        id="sunrise",
        display_name="Sunrise",
        description="Warm orange tones with a side-aligned logo for a fresh feel.",
        thumbnail_path="templates/sunrise.png",
        default_primary_colour="#ea580c",
        default_accent_colour="#c2410c",
        default_header_bg_colour="#fff7ed",
        logo_position="side",
        layout_type="standard",
        template_file="sunrise.html",
    ),
    "ocean": TemplateMetadata(
        id="ocean",
        display_name="Ocean",
        description="Cool cyan palette with a clean, airy coastal-inspired design.",
        thumbnail_path="templates/ocean.png",
        default_primary_colour="#0891b2",
        default_accent_colour="#0e7490",
        default_header_bg_colour="#ecfeff",
        logo_position="left",
        layout_type="standard",
        template_file="ocean.html",
    ),
}


def list_templates() -> list[dict]:
    """Return all templates as serialisable dicts for the API."""
    return [
        {
            "id": t.id,
            "display_name": t.display_name,
            "description": t.description,
            "thumbnail_path": t.thumbnail_path,
            "default_primary_colour": t.default_primary_colour,
            "default_accent_colour": t.default_accent_colour,
            "default_header_bg_colour": t.default_header_bg_colour,
            "logo_position": t.logo_position,
            "layout_type": t.layout_type,
        }
        for t in TEMPLATES.values()
    ]


def get_template_metadata(template_id: str) -> TemplateMetadata | None:
    """Look up a template by ID. Returns None if not found."""
    return TEMPLATES.get(template_id)


def validate_template_id(template_id: str) -> None:
    """Raise ValueError if template_id is not in the registry."""
    if template_id not in TEMPLATES:
        raise ValueError(
            f"Unknown invoice template '{template_id}'. "
            f"Valid templates: {', '.join(sorted(TEMPLATES.keys()))}"
        )

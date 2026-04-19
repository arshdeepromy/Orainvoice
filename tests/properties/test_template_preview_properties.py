"""Property-based tests for template-aware invoice preview.

Property 1: Template style map completeness and backend consistency
  — For every template ID in the backend TEMPLATES registry, the frontend
    TEMPLATE_STYLES map has a matching entry with identical primaryColour,
    accentColour, headerBgColour, logoPosition, and layoutType values.
  — The two registries have identical sets of template IDs.

**Validates: Requirements 2.2, 2.3, 7.1, 7.3**
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis import HealthCheck

from app.modules.invoices.template_registry import TEMPLATES, TemplateMetadata


# ---------------------------------------------------------------------------
# Parse frontend TEMPLATE_STYLES from the TypeScript source
# ---------------------------------------------------------------------------

_FRONTEND_STYLES_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "utils"
    / "invoiceTemplateStyles.ts"
)


def _parse_frontend_template_styles() -> dict[str, dict[str, str]]:
    """Extract TEMPLATE_STYLES entries from the TypeScript source file.

    Returns a dict mapping template ID → {primaryColour, accentColour,
    headerBgColour, logoPosition, layoutType}.
    """
    source = _FRONTEND_STYLES_PATH.read_text(encoding="utf-8")

    # Extract the TEMPLATE_STYLES block between the opening { and its closing }
    # The block starts after "TEMPLATE_STYLES: Record<string, TemplateStyle> = {"
    match = re.search(
        r"TEMPLATE_STYLES:\s*Record<string,\s*TemplateStyle>\s*=\s*\{",
        source,
    )
    if not match:
        raise RuntimeError("Could not find TEMPLATE_STYLES in frontend source")

    # Find the matching closing brace by counting braces
    start = match.end() - 1  # include the opening {
    depth = 0
    end = start
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    block = source[start:end]

    # Parse each template entry
    # Pattern: key (bare word or 'quoted-word'): { ... }
    entry_pattern = re.compile(
        r"""(?:'([^']+)'|"([^"]+)"|(\w+))\s*:\s*\{([^}]+)\}""",
        re.DOTALL,
    )

    field_pattern = re.compile(
        r"""(\w+)\s*:\s*(?:'([^']*)'|"([^"]*)"|(\w+))""",
    )

    result: dict[str, dict[str, str]] = {}

    for entry_match in entry_pattern.finditer(block):
        template_id = (
            entry_match.group(1)
            or entry_match.group(2)
            or entry_match.group(3)
        )
        body = entry_match.group(4)

        fields: dict[str, str] = {}
        for field_match in field_pattern.finditer(body):
            field_name = field_match.group(1)
            field_value = (
                field_match.group(2)
                or field_match.group(3)
                or field_match.group(4)
            )
            fields[field_name] = field_value

        result[template_id] = fields

    return result


# Cache the parsed frontend styles — they don't change during a test run
FRONTEND_STYLES = _parse_frontend_template_styles()

# Backend template IDs
BACKEND_IDS = sorted(TEMPLATES.keys())

# Frontend template IDs
FRONTEND_IDS = sorted(FRONTEND_STYLES.keys())

# Fields to compare between backend and frontend
_FIELD_MAP = {
    # backend TemplateMetadata attr → frontend TemplateStyle key
    "default_primary_colour": "primaryColour",
    "default_accent_colour": "accentColour",
    "default_header_bg_colour": "headerBgColour",
    "logo_position": "logoPosition",
    "layout_type": "layoutType",
}


# ===========================================================================
# Property 1: Template style map completeness and backend consistency
# ===========================================================================


class TestP1TemplateStyleMapCompleteness:
    """For any backend template ID, the frontend TEMPLATE_STYLES map has a
    matching entry with identical colour, logo-position, and layout-type
    values. The two registries have identical ID sets.

    Feature: template-aware-invoice-preview, Property 1: Template style map
    completeness and backend consistency

    **Validates: Requirements 2.2, 2.3, 7.1, 7.3**
    """

    # -----------------------------------------------------------------------
    # Deterministic check: ID sets are equal
    # -----------------------------------------------------------------------

    def test_id_sets_are_equal(self) -> None:
        """The backend and frontend registries have the exact same template IDs."""
        backend_set = set(TEMPLATES.keys())
        frontend_set = set(FRONTEND_STYLES.keys())

        missing_in_frontend = backend_set - frontend_set
        extra_in_frontend = frontend_set - backend_set

        assert backend_set == frontend_set, (
            f"Template ID mismatch.\n"
            f"  Missing in frontend: {sorted(missing_in_frontend) or 'none'}\n"
            f"  Extra in frontend:   {sorted(extra_in_frontend) or 'none'}"
        )

    # -----------------------------------------------------------------------
    # Property test: for each backend template, frontend values match
    # -----------------------------------------------------------------------

    @given(template_id=st.sampled_from(BACKEND_IDS))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_frontend_entry_matches_backend(self, template_id: str) -> None:
        """For a sampled backend template ID, the frontend entry has identical
        primaryColour, accentColour, headerBgColour, logoPosition, and
        layoutType values."""
        backend: TemplateMetadata = TEMPLATES[template_id]
        frontend = FRONTEND_STYLES.get(template_id)

        assert frontend is not None, (
            f"Frontend TEMPLATE_STYLES missing entry for '{template_id}'"
        )

        for backend_attr, frontend_key in _FIELD_MAP.items():
            backend_value = getattr(backend, backend_attr)
            frontend_value = frontend.get(frontend_key)

            assert backend_value == frontend_value, (
                f"Template '{template_id}' field mismatch on {frontend_key}:\n"
                f"  backend ({backend_attr}): {backend_value!r}\n"
                f"  frontend ({frontend_key}): {frontend_value!r}"
            )

    # -----------------------------------------------------------------------
    # Property test: for each frontend template, backend has matching entry
    # -----------------------------------------------------------------------

    @given(template_id=st.sampled_from(FRONTEND_IDS))
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_backend_entry_exists_for_frontend(self, template_id: str) -> None:
        """For a sampled frontend template ID, the backend registry has a
        matching entry."""
        assert template_id in TEMPLATES, (
            f"Backend TEMPLATES missing entry for '{template_id}' "
            f"which exists in frontend TEMPLATE_STYLES"
        )

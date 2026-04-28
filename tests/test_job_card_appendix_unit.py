"""Unit tests for the job card appendix snapshot renderer edge cases.

Tests specific examples and edge cases for the snapshot renderer, complementing
the property-based tests in test_job_card_appendix_properties.py.

Requirements: 2.6, 2.7, 2.8, 2.9, 6.1, 6.2, 6.5, NF Security 2
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.modules.job_cards.snapshot_renderer import render_job_card_appendix_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render(job_card_data, attachments=None, attachment_bytes=None, trade_family=None):
    """Synchronous wrapper around the async renderer for test convenience."""
    return asyncio.get_event_loop().run_until_complete(
        render_job_card_appendix_html(
            job_card_data=job_card_data,
            attachments=attachments or [],
            attachment_bytes=attachment_bytes or {},
            trade_family=trade_family,
        )
    )


def _minimal_job_card(**overrides) -> dict:
    """Build a minimal job card data dict with sensible defaults.

    All fields that the renderer expects are included with empty/None defaults.
    Pass keyword arguments to override specific fields.
    """
    base = {
        "id": str(uuid.uuid4()),
        "customer": {"first_name": "Test", "last_name": "Customer"},
        "line_items": [],
        "time_entries": [],
        "notes": None,
        "service_type_name": None,
        "service_type_values": [],
        "assigned_to_name": None,
        "vehicle_rego": None,
        "created_at": "2024-06-01 10:00:00",
        "updated_at": "2024-06-01 12:00:00",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshotRendererEdgeCases:
    """Unit tests for snapshot renderer edge cases.

    Validates: Requirements 2.6, 2.7, 2.8, 2.9, 6.1, 6.2, 6.5, NF Security 2
    """

    def test_empty_job_card_renders(self):
        """Minimal job card with no line items, time entries, or attachments
        produces valid HTML.

        Validates: Requirements 2.6, 2.7, 2.8, 6.5
        """
        jc = _minimal_job_card()
        html = _render(jc)

        # Should produce non-empty HTML
        assert html is not None
        assert len(html.strip()) > 0

        # Should contain the wrapping div
        assert "jc-appendix" in html

        # Should contain the header
        assert "Job Card Summary" in html

    def test_missing_image_shows_placeholder(self):
        """Attachment metadata present but bytes missing shows
        ``[Image unavailable: {filename}]`` when at least one other
        attachment succeeds (so the section is not omitted entirely).

        Validates: Requirements 6.1
        """
        import struct
        import zlib

        # Generate a minimal valid PNG for the "good" attachment
        raw_data = b"\x00\xff\x00\x00"
        compressed = zlib.compress(raw_data)

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            return (
                struct.pack(">I", len(data))
                + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            )

        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", compressed)
            + _chunk(b"IEND", b"")
        )

        good_id = str(uuid.uuid4())
        missing_id = str(uuid.uuid4())
        missing_filename = "photo_evidence.jpg"

        jc = _minimal_job_card()
        attachments = [
            {
                "id": good_id,
                "file_name": "good_photo.png",
                "mime_type": "image/png",
                "file_key": f"encrypted/path/{good_id}",
            },
            {
                "id": missing_id,
                "file_name": missing_filename,
                "mime_type": "image/jpeg",
                "file_key": f"encrypted/path/{missing_id}",
            },
        ]
        # Only provide bytes for the first attachment; second is missing
        attachment_bytes = {good_id: png_bytes}
        html = _render(jc, attachments=attachments, attachment_bytes=attachment_bytes)

        assert f"[Image unavailable: {missing_filename}]" in html

    def test_all_images_missing_omits_section(self):
        """All attachment bytes missing omits the entire attachments section.

        Validates: Requirements 6.2
        """
        att1_id = str(uuid.uuid4())
        att2_id = str(uuid.uuid4())

        jc = _minimal_job_card()
        attachments = [
            {
                "id": att1_id,
                "file_name": "img1.png",
                "mime_type": "image/png",
                "file_key": f"encrypted/path/{att1_id}",
            },
            {
                "id": att2_id,
                "file_name": "img2.jpg",
                "mime_type": "image/jpeg",
                "file_key": f"encrypted/path/{att2_id}",
            },
        ]
        # No bytes for any attachment
        html = _render(jc, attachments=attachments, attachment_bytes={})

        # The "Attachments" section header should not appear
        assert "Attachments" not in html
        # Placeholder text should also not appear (entire section omitted)
        assert "[Image unavailable:" not in html

    def test_no_time_entries_omits_section(self):
        """Empty time_entries omits the time tracking section.

        Validates: Requirements 2.7, 6.5
        """
        jc = _minimal_job_card(time_entries=[])
        html = _render(jc)

        assert "Time Tracking" not in html

    def test_no_line_items_omits_section(self):
        """Empty line_items omits the line items section.

        Validates: Requirements 2.8, 6.5
        """
        jc = _minimal_job_card(line_items=[])
        html = _render(jc)

        assert "Line Items" not in html

    def test_no_service_type_omits_section(self):
        """service_type_name=None omits the service type section.

        Validates: Requirements 2.9, 6.5
        """
        jc = _minimal_job_card(service_type_name=None, service_type_values=[])
        html = _render(jc)

        assert "Service Type" not in html

    def test_appendix_header_text(self):
        """Output contains "Job Card Summary" header.

        Validates: Requirements 6.5
        """
        jc = _minimal_job_card()
        html = _render(jc)

        assert "Job Card Summary" in html

    def test_autoescaping_prevents_xss(self):
        """Customer name with ``<script>`` tag is escaped in the output.

        Validates: Requirements NF Security 2
        """
        jc = _minimal_job_card(
            customer={
                "first_name": "<script>alert('xss')</script>",
                "last_name": "Victim",
            }
        )
        html = _render(jc)

        # The raw <script> tag must NOT appear in the output
        assert "<script>" not in html
        assert "<script>alert('xss')</script>" not in html

        # The escaped version MUST appear
        assert "&lt;script&gt;" in html

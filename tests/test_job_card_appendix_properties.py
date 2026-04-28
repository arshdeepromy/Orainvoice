"""Property-based tests for the job card appendix snapshot renderer.

Uses Hypothesis to verify universal correctness properties across randomly
generated job card data inputs.

Feature: job-card-invoice-appendix
Properties: 1 (Round-trip content integrity)

Validates: Requirements 2.3, 5.1, 5.3, 5.4, 5.5, 5.8, 5.9, 5.10, 7.1
"""

from __future__ import annotations

import asyncio
import re
import struct
import uuid
import zlib
from datetime import datetime, timezone

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.job_cards.snapshot_renderer import render_job_card_appendix_html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
# Matches any Unicode whitespace character (including \xa0, \u2000–\u200a, etc.)
_UNICODE_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Strip HTML tags and normalise all whitespace to single ASCII spaces."""
    text = _TAG_RE.sub(" ", html)
    return _UNICODE_WS_RE.sub(" ", text).strip()


def _normalise(text: str) -> str:
    """Normalise a text value the same way _strip_html normalises whitespace."""
    return _UNICODE_WS_RE.sub(" ", text).strip()


def _minimal_png(width: int = 1, height: int = 1) -> bytes:
    """Generate a minimal valid 1×1 red PNG for testing."""
    raw_data = b"\x00\xff\x00\x00"  # filter byte + RGB
    compressed = zlib.compress(raw_data)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return (
            struct.pack(">I", len(data))
            + c
            + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe text that avoids HTML special chars (which would be escaped by Jinja2
# autoescaping, making round-trip text matching fail).
# We use only Letters (L) and Digits (N) — no whitespace category (Zs) to
# avoid non-breaking spaces and other exotic whitespace that complicates
# round-trip matching. Regular ASCII spaces are injected via st.from_regex.
_safe_text = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" "),
).filter(lambda s: s.strip())

_customer_strategy = st.fixed_dictionaries({
    "first_name": _safe_text,
    "last_name": _safe_text,
    "phone": st.one_of(st.none(), st.from_regex(r"\+?\d{7,15}", fullmatch=True)),
    "email": st.one_of(st.none(), st.emails()),
    "address": st.one_of(st.none(), _safe_text),
})

_line_item_strategy = st.fixed_dictionaries({
    "item_type": st.sampled_from(["labour", "material", "part"]),
    "description": _safe_text,
    "quantity": st.integers(min_value=1, max_value=100),
    "unit_price": st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False),
}).map(lambda li: {**li, "line_total": li["quantity"] * li["unit_price"]})

_time_entry_strategy = st.fixed_dictionaries({
    "staff_name": _safe_text,
    "started_at": st.just("2024-06-01T08:00:00"),
    "stopped_at": st.just("2024-06-01T10:00:00"),
    "duration_minutes": st.integers(min_value=1, max_value=480),
})

_service_type_value_strategy = st.fixed_dictionaries({
    "label": _safe_text,
    "value": _safe_text,
})

_datetime_str_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
).map(lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"))


def _job_card_data_strategy():
    """Custom Hypothesis strategy that generates valid job card data dicts."""
    return st.fixed_dictionaries({
        "id": st.uuids().map(str),
        "customer": _customer_strategy,
        "line_items": st.lists(_line_item_strategy, min_size=0, max_size=10),
        "time_entries": st.lists(_time_entry_strategy, min_size=0, max_size=5),
        "notes": st.one_of(st.none(), _safe_text),
        "service_type_name": st.one_of(st.none(), _safe_text),
        "service_type_values": st.lists(_service_type_value_strategy, min_size=0, max_size=5),
        "assigned_to_name": _safe_text,
        "vehicle_rego": _safe_text,
        "created_at": _datetime_str_strategy,
        "updated_at": _datetime_str_strategy,
        "description": _safe_text,
    })


# ---------------------------------------------------------------------------
# Property 1: Round-trip content integrity
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 1: Round-trip content integrity
class TestProperty1RoundTripContentIntegrity:
    """For any valid job card data dict, rendering the appendix HTML and
    extracting the text content SHALL contain the customer name, each line
    item description, each time entry staff name, assigned staff name, notes,
    and date values.

    **Validates: Requirements 2.3, 5.1, 5.3, 5.4, 5.5, 5.8, 5.9, 5.10, 7.1**
    """

    @given(data=_job_card_data_strategy())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_round_trip_content_integrity(self, data: dict) -> None:
        """Rendered HTML text contains all key job card data fields."""
        # Exclude description (as the real flow does)
        jc_data = {k: v for k, v in data.items() if k != "description"}

        # Render with no attachments (attachments tested in separate properties)
        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=[],
                attachment_bytes={},
                trade_family=None,
            )
        )

        plain = _strip_html(html)

        # --- Customer name ---
        first = _normalise(data["customer"]["first_name"])
        last = _normalise(data["customer"]["last_name"])
        full_name = f"{first} {last}".strip()
        if full_name:
            assert full_name in plain, (
                f"Customer name '{full_name}' not found in rendered text"
            )

        # --- Line item descriptions ---
        for li in data["line_items"]:
            desc = _normalise(li["description"])
            if desc:
                assert desc in plain, (
                    f"Line item description '{desc}' not found in rendered text"
                )

        # --- Time entry staff names ---
        for te in data["time_entries"]:
            staff = _normalise(te["staff_name"])
            if staff:
                assert staff in plain, (
                    f"Time entry staff name '{staff}' not found in rendered text"
                )

        # --- Assigned staff name ---
        assigned = _normalise(data["assigned_to_name"])
        if assigned:
            assert assigned in plain, (
                f"Assigned staff name '{assigned}' not found in rendered text"
            )

        # --- Notes ---
        notes = data.get("notes")
        if notes and notes.strip():
            normalised_notes = _normalise(notes)
            if normalised_notes:
                assert normalised_notes in plain, (
                    f"Notes '{normalised_notes}' not found in rendered text"
                )

        # --- Created at / Updated at dates ---
        created = data["created_at"]
        if created:
            assert created in plain, (
                f"Created date '{created}' not found in rendered text"
            )

        updated = data["updated_at"]
        if updated:
            assert updated in plain, (
                f"Updated date '{updated}' not found in rendered text"
            )


# ---------------------------------------------------------------------------
# Property 2: Description field exclusion
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 2: Description field exclusion
class TestProperty2DescriptionExclusion:
    """For any valid job card data dict with a non-empty description field,
    the rendered appendix HTML SHALL NOT contain the description field value
    anywhere in the output text.

    **Validates: Requirements 2.2, 7.2**
    """

    @given(data=_job_card_data_strategy())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_description_not_in_rendered_html(self, data: dict) -> None:
        """Rendered HTML must not contain the description value."""
        desc = data["description"]
        assume(len(desc.strip()) > 0)

        normalised_desc = _normalise(desc)
        assume(len(normalised_desc) > 0)

        # Require a minimum length to avoid false positives from short strings
        # matching CSS values, HTML attributes, or other template boilerplate.
        assume(len(normalised_desc) >= 4)

        # Filter out purely numeric descriptions — numbers appear in CSS
        # (font sizes, line-heights, margins) and date strings.
        assume(not normalised_desc.replace(" ", "").isdigit())

        # Filter out cases where the description coincidentally matches other
        # field values that ARE expected to appear in the rendered output.
        customer = data["customer"]
        assume(normalised_desc != _normalise(customer["first_name"]))
        assume(normalised_desc != _normalise(customer["last_name"]))
        full_name = f"{_normalise(customer['first_name'])} {_normalise(customer['last_name'])}".strip()
        assume(normalised_desc != full_name)

        if customer.get("phone"):
            assume(normalised_desc != customer["phone"])
        if customer.get("email"):
            assume(normalised_desc != customer["email"])
        if customer.get("address"):
            assume(normalised_desc != _normalise(customer["address"]))

        assume(normalised_desc != _normalise(data["assigned_to_name"]))
        assume(normalised_desc != _normalise(data["vehicle_rego"]))

        for li in data["line_items"]:
            assume(normalised_desc != _normalise(li["description"]))
            assume(normalised_desc != li["item_type"])

        for te in data["time_entries"]:
            assume(normalised_desc != _normalise(te["staff_name"]))

        if data.get("notes") and data["notes"].strip():
            assume(normalised_desc != _normalise(data["notes"]))

        if data.get("service_type_name"):
            assume(normalised_desc != _normalise(data["service_type_name"]))

        for stv in data.get("service_type_values", []):
            assume(normalised_desc != _normalise(stv["label"]))
            assume(normalised_desc != _normalise(stv["value"]))

        # Also filter out descriptions that are substrings of other fields
        # (or vice versa) to avoid false positives from partial matches.
        all_visible_values = []
        all_visible_values.append(full_name)
        all_visible_values.append(_normalise(data["assigned_to_name"]))
        all_visible_values.append(_normalise(data["vehicle_rego"]))
        all_visible_values.append(data["id"])  # UUID appears in the reference
        all_visible_values.append(data["created_at"])
        all_visible_values.append(data["updated_at"])
        if data.get("notes") and data["notes"].strip():
            all_visible_values.append(_normalise(data["notes"]))
        if data.get("service_type_name"):
            all_visible_values.append(_normalise(data["service_type_name"]))
        for li in data["line_items"]:
            all_visible_values.append(_normalise(li["description"]))
        for te in data["time_entries"]:
            all_visible_values.append(_normalise(te["staff_name"]))
        for stv in data.get("service_type_values", []):
            all_visible_values.append(_normalise(stv["label"]))
            all_visible_values.append(_normalise(stv["value"]))

        for val in all_visible_values:
            if val:
                assume(normalised_desc not in val)
                assume(val not in normalised_desc)

        # Pass the FULL data dict (including description) to the renderer.
        # The template does not reference the description field, so it should
        # never appear in the output.
        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=data,
                attachments=[],
                attachment_bytes={},
                trade_family=None,
            )
        )

        plain = _strip_html(html)

        assert normalised_desc not in plain, (
            f"Description '{normalised_desc}' was found in rendered HTML text, "
            f"but the description field should be excluded from the output"
        )


# ---------------------------------------------------------------------------
# Property 3: Image attachment base64 embedding
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 3: Image attachment base64 embedding
class TestProperty3ImageBase64Embedding:
    """For any valid job card data dict with N image attachments (where each
    attachment has corresponding decrypted bytes provided), the rendered
    appendix HTML SHALL contain exactly N ``<img`` tags with ``src="data:``
    base64 URIs, and each image's original filename SHALL appear in the HTML
    as a caption.

    **Validates: Requirements 2.4, 5.6, 7.3**
    """

    @given(
        data=_job_card_data_strategy(),
        n_images=st.integers(min_value=1, max_value=5),
        mime_types=st.lists(
            st.sampled_from(["image/jpeg", "image/png"]),
            min_size=5,
            max_size=5,
        ),
        filenames=st.lists(
            st.text(
                min_size=3,
                max_size=20,
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="_-",
                ),
            ).filter(lambda s: s.strip()),
            min_size=5,
            max_size=5,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_image_base64_embedding(
        self,
        data: dict,
        n_images: int,
        mime_types: list[str],
        filenames: list[str],
    ) -> None:
        """Rendered HTML contains exactly N <img> tags with data: URIs and
        each filename appears as a caption."""
        # Ensure filenames are unique by appending index
        unique_filenames = [f"{fn}_{i}.png" for i, fn in enumerate(filenames[:n_images])]

        # Build attachment metadata and bytes
        attachments: list[dict] = []
        attachment_bytes: dict[str, bytes] = {}
        png_bytes = _minimal_png()

        for i in range(n_images):
            att_id = str(uuid.uuid4())
            attachments.append({
                "id": att_id,
                "file_name": unique_filenames[i],
                "mime_type": mime_types[i],
                "file_key": f"encrypted/path/{att_id}",
            })
            attachment_bytes[att_id] = png_bytes

        # Exclude description as the real flow does
        jc_data = {k: v for k, v in data.items() if k != "description"}

        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=attachments,
                attachment_bytes=attachment_bytes,
                trade_family=None,
            )
        )

        # Count <img tags with src="data: URIs
        img_data_pattern = re.compile(r'<img\b[^>]*\bsrc="data:', re.IGNORECASE)
        img_matches = img_data_pattern.findall(html)
        assert len(img_matches) == n_images, (
            f"Expected {n_images} <img> tags with data: URIs, found {len(img_matches)}"
        )

        # Verify each filename appears in the HTML as a caption
        for fname in unique_filenames:
            assert fname in html, (
                f"Filename '{fname}' not found in rendered HTML as a caption"
            )


# ---------------------------------------------------------------------------
# Property 4: PDF attachment filename listing
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 4: PDF attachment filename listing
class TestProperty4PdfAttachmentListing:
    """For any valid job card data dict with PDF attachments, the rendered
    appendix HTML SHALL contain each PDF attachment's filename in the output
    text, and SHALL NOT contain any base64 ``data:`` URI for PDF attachments.

    **Validates: Requirements 2.5, 5.7**
    """

    @given(
        data=_job_card_data_strategy(),
        n_pdfs=st.integers(min_value=1, max_value=5),
        filenames=st.lists(
            st.text(
                min_size=3,
                max_size=20,
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="_-",
                ),
            ).filter(lambda s: s.strip()),
            min_size=5,
            max_size=5,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_pdf_attachment_filename_listing(
        self,
        data: dict,
        n_pdfs: int,
        filenames: list[str],
    ) -> None:
        """Rendered HTML lists each PDF filename and contains no base64
        data:application/pdf URIs."""
        # Ensure filenames are unique by appending index + .pdf extension
        unique_filenames = [f"{fn}_{i}.pdf" for i, fn in enumerate(filenames[:n_pdfs])]

        # Build PDF attachment metadata — no bytes provided (listed by name only)
        attachments: list[dict] = []
        for i in range(n_pdfs):
            att_id = str(uuid.uuid4())
            attachments.append({
                "id": att_id,
                "file_name": unique_filenames[i],
                "mime_type": "application/pdf",
                "file_key": f"encrypted/path/{att_id}",
            })

        # Exclude description as the real flow does
        jc_data = {k: v for k, v in data.items() if k != "description"}

        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=attachments,
                attachment_bytes={},  # No bytes for PDF attachments
                trade_family=None,
            )
        )

        # Verify each PDF filename appears in the HTML
        for fname in unique_filenames:
            assert fname in html, (
                f"PDF filename '{fname}' not found in rendered HTML"
            )

        # Verify the HTML does NOT contain any data:application/pdf base64 URIs
        assert "data:application/pdf" not in html, (
            "Rendered HTML contains a data:application/pdf base64 URI, "
            "but PDF attachments should be listed by filename only"
        )


# ---------------------------------------------------------------------------
# Property 5: Self-contained HTML output
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 5: Self-contained HTML output
class TestProperty5SelfContainedHtml:
    """For any valid job card data dict, the rendered appendix HTML SHALL NOT
    contain any ``<link`` tags, external ``http://`` or ``https://`` references
    in ``src`` or ``href`` attributes (except within base64 ``data:`` URIs),
    ensuring the HTML is fully self-contained for offline WeasyPrint rendering.

    **Validates: Requirements 2.10**
    """

    @given(
        data=_job_card_data_strategy(),
        n_images=st.integers(min_value=0, max_value=3),
        mime_types=st.lists(
            st.sampled_from(["image/jpeg", "image/png"]),
            min_size=3,
            max_size=3,
        ),
        filenames=st.lists(
            st.text(
                min_size=3,
                max_size=15,
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="_-",
                ),
            ).filter(lambda s: s.strip()),
            min_size=3,
            max_size=3,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_self_contained_html(
        self,
        data: dict,
        n_images: int,
        mime_types: list[str],
        filenames: list[str],
    ) -> None:
        """Rendered HTML has no <link> tags and no external http(s) references
        in src/href attributes.  data: URIs are allowed."""
        # Build image attachments so that base64 data: URIs are present
        unique_filenames = [f"{fn}_{i}.png" for i, fn in enumerate(filenames[:n_images])]
        attachments: list[dict] = []
        attachment_bytes: dict[str, bytes] = {}
        png_bytes = _minimal_png()

        for i in range(n_images):
            att_id = str(uuid.uuid4())
            attachments.append({
                "id": att_id,
                "file_name": unique_filenames[i],
                "mime_type": mime_types[i],
                "file_key": f"encrypted/path/{att_id}",
            })
            attachment_bytes[att_id] = png_bytes

        # Exclude description as the real flow does
        jc_data = {k: v for k, v in data.items() if k != "description"}

        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=attachments,
                attachment_bytes=attachment_bytes,
                trade_family=None,
            )
        )

        # 1. No <link tags at all
        link_pattern = re.compile(r"<link\b", re.IGNORECASE)
        assert not link_pattern.search(html), (
            "Rendered HTML contains a <link> tag — the output must be "
            "self-contained with no external stylesheet references"
        )

        # 2. No src="http://" or src="https://" (external resources)
        src_http_pattern = re.compile(
            r'\bsrc\s*=\s*["\']https?://', re.IGNORECASE
        )
        assert not src_http_pattern.search(html), (
            "Rendered HTML contains an external src=\"http(s)://\" reference — "
            "all resources must be inline or base64-embedded"
        )

        # 3. No href="http://" or href="https://" (external links)
        href_http_pattern = re.compile(
            r'\bhref\s*=\s*["\']https?://', re.IGNORECASE
        )
        assert not href_http_pattern.search(html), (
            "Rendered HTML contains an external href=\"http(s)://\" reference — "
            "the output must be self-contained with no external links"
        )

        # Sanity check: if we have images, data: URIs should be present
        if n_images > 0:
            assert "src=\"data:" in html, (
                f"Expected base64 data: URIs for {n_images} images but none found"
            )


# ---------------------------------------------------------------------------
# Property 6: No internal identifiers in output
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 6: No internal identifiers in output
class TestProperty6NoInternalIdentifiers:
    """For any valid job card data dict with attachments that have ``file_key``
    values, the rendered appendix HTML SHALL NOT contain any ``file_key`` path
    strings, encryption key material, or internal system identifiers — only
    rendered content and base64-embedded image data.

    **Validates: Requirements NF Security 1**
    """

    @given(
        data=_job_card_data_strategy(),
        n_images=st.integers(min_value=1, max_value=3),
        n_pdfs=st.integers(min_value=0, max_value=3),
        org_ids=st.lists(
            st.uuids().map(str),
            min_size=3,
            max_size=3,
        ),
        att_uuids=st.lists(
            st.uuids().map(str),
            min_size=6,
            max_size=6,
        ),
        image_filenames=st.lists(
            st.text(
                min_size=3,
                max_size=15,
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="_-",
                ),
            ).filter(lambda s: s.strip()),
            min_size=3,
            max_size=3,
        ),
        pdf_filenames=st.lists(
            st.text(
                min_size=3,
                max_size=15,
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="_-",
                ),
            ).filter(lambda s: s.strip()),
            min_size=3,
            max_size=3,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_no_internal_identifiers_in_output(
        self,
        data: dict,
        n_images: int,
        n_pdfs: int,
        org_ids: list[str],
        att_uuids: list[str],
        image_filenames: list[str],
        pdf_filenames: list[str],
    ) -> None:
        """Rendered HTML must not contain any file_key paths, encryption key
        material, or the literal attribute name 'file_key'."""
        # Build realistic file_key values like encrypted/orgs/{org_id}/attachments/{uuid}
        file_keys: list[str] = []

        # --- Image attachments ---
        attachments: list[dict] = []
        attachment_bytes: dict[str, bytes] = {}
        png_bytes = _minimal_png()

        for i in range(n_images):
            att_id = att_uuids[i]
            org_id = org_ids[i % len(org_ids)]
            file_key = f"encrypted/orgs/{org_id}/attachments/{att_id}"
            file_keys.append(file_key)
            fname = f"{image_filenames[i]}_{i}.png"
            attachments.append({
                "id": att_id,
                "file_name": fname,
                "mime_type": "image/png",
                "file_key": file_key,
            })
            attachment_bytes[att_id] = png_bytes

        # --- PDF attachments ---
        for i in range(n_pdfs):
            idx = n_images + i
            att_id = att_uuids[idx % len(att_uuids)]
            org_id = org_ids[idx % len(org_ids)]
            file_key = f"encrypted/orgs/{org_id}/attachments/{att_id}"
            file_keys.append(file_key)
            fname = f"{pdf_filenames[i]}_{i}.pdf"
            attachments.append({
                "id": att_id,
                "file_name": fname,
                "mime_type": "application/pdf",
                "file_key": file_key,
            })

        # Exclude description as the real flow does
        jc_data = {k: v for k, v in data.items() if k != "description"}

        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=attachments,
                attachment_bytes=attachment_bytes,
                trade_family=None,
            )
        )

        # --- Assert no file_key values appear in the rendered HTML ---
        for fk in file_keys:
            assert fk not in html, (
                f"file_key path '{fk}' was found in rendered HTML — "
                f"internal identifiers must not leak into the output"
            )

        # --- Assert "encrypted/" does not appear outside of base64 data URIs ---
        # Remove all base64 data URIs first (they may coincidentally contain
        # the string "encrypted" in their encoded payload), then check.
        html_without_data_uris = re.sub(
            r'data:[^"\'>\s]+',
            '',
            html,
        )
        assert "encrypted/" not in html_without_data_uris, (
            "The string 'encrypted/' was found in rendered HTML outside of "
            "base64 data URIs — internal file paths must not leak into the output"
        )

        # --- Assert the attribute name 'file_key' does not appear in the HTML ---
        assert "file_key" not in html, (
            "The attribute name 'file_key' was found in rendered HTML — "
            "internal attribute names must not leak into the output"
        )


# ---------------------------------------------------------------------------
# Property 7: Vehicle registration gated by trade family
# ---------------------------------------------------------------------------

# Feature: job-card-invoice-appendix, Property 7: Vehicle registration gated by trade family
class TestProperty7VehicleRegistrationGating:
    """For any valid job card data dict with a ``vehicle_rego`` value, the
    rendered appendix HTML SHALL contain the vehicle registration text when
    ``trade_family == 'automotive-transport'``, and SHALL NOT contain a vehicle
    registration section when ``trade_family`` is any other value.

    **Validates: Requirements 5.2**
    """

    @given(data=_job_card_data_strategy())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_vehicle_rego_shown_for_automotive_transport(self, data: dict) -> None:
        """When trade_family is 'automotive-transport' and vehicle_rego is
        non-empty, the rego value appears in the rendered HTML."""
        rego = data["vehicle_rego"]
        assume(len(rego.strip()) > 0)

        # Exclude description as the real flow does
        jc_data = {k: v for k, v in data.items() if k != "description"}

        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=[],
                attachment_bytes={},
                trade_family="automotive-transport",
            )
        )

        plain = _strip_html(html)
        normalised_rego = _normalise(rego)

        assert normalised_rego in plain, (
            f"Vehicle rego '{normalised_rego}' not found in rendered HTML "
            f"when trade_family='automotive-transport'"
        )

    @given(
        data=_job_card_data_strategy(),
        trade_family=st.sampled_from([
            "plumbing-gas",
            "electrical-mechanical",
            "construction",
            "cleaning",
            None,
        ]),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_vehicle_rego_hidden_for_other_trade_families(
        self, data: dict, trade_family: str | None
    ) -> None:
        """When trade_family is NOT 'automotive-transport', the vehicle rego
        section is not shown even if vehicle_rego has a value."""
        rego = data["vehicle_rego"]
        assume(len(rego.strip()) > 0)

        normalised_rego = _normalise(rego)
        assume(len(normalised_rego) >= 4)

        # Ensure the rego value doesn't coincidentally appear in other fields
        # that ARE expected in the rendered output.
        customer = data["customer"]
        assume(normalised_rego != _normalise(customer["first_name"]))
        assume(normalised_rego != _normalise(customer["last_name"]))
        full_name = f"{_normalise(customer['first_name'])} {_normalise(customer['last_name'])}".strip()
        assume(normalised_rego != full_name)
        assume(normalised_rego not in full_name)
        assume(full_name not in normalised_rego)

        if customer.get("phone"):
            assume(normalised_rego != customer["phone"])
            assume(normalised_rego not in customer["phone"])
        if customer.get("email"):
            assume(normalised_rego != customer["email"])
            assume(normalised_rego not in customer["email"])
        if customer.get("address"):
            addr = _normalise(customer["address"])
            assume(normalised_rego != addr)
            assume(normalised_rego not in addr)
            assume(addr not in normalised_rego)

        assume(normalised_rego != _normalise(data["assigned_to_name"]))
        assume(normalised_rego not in _normalise(data["assigned_to_name"]))
        assume(_normalise(data["assigned_to_name"]) not in normalised_rego)

        if data.get("notes") and data["notes"].strip():
            notes_norm = _normalise(data["notes"])
            assume(normalised_rego != notes_norm)
            assume(normalised_rego not in notes_norm)
            assume(notes_norm not in normalised_rego)

        if data.get("service_type_name"):
            stn = _normalise(data["service_type_name"])
            assume(normalised_rego != stn)
            assume(normalised_rego not in stn)
            assume(stn not in normalised_rego)

        for stv in data.get("service_type_values", []):
            lbl = _normalise(stv["label"])
            val = _normalise(stv["value"])
            assume(normalised_rego not in lbl)
            assume(normalised_rego not in val)
            assume(lbl not in normalised_rego)
            assume(val not in normalised_rego)

        for li in data["line_items"]:
            li_desc = _normalise(li["description"])
            assume(normalised_rego not in li_desc)
            assume(li_desc not in normalised_rego)
            assume(normalised_rego != li["item_type"])

        for te in data["time_entries"]:
            staff = _normalise(te["staff_name"])
            assume(normalised_rego not in staff)
            assume(staff not in normalised_rego)

        # Also check against the job card ID (reference) and date strings
        assume(normalised_rego not in data["id"])
        assume(normalised_rego not in data["created_at"])
        assume(normalised_rego not in data["updated_at"])

        # Exclude description as the real flow does
        jc_data = {k: v for k, v in data.items() if k != "description"}

        html = asyncio.get_event_loop().run_until_complete(
            render_job_card_appendix_html(
                job_card_data=jc_data,
                attachments=[],
                attachment_bytes={},
                trade_family=trade_family,
            )
        )

        plain = _strip_html(html)

        assert normalised_rego not in plain, (
            f"Vehicle rego '{normalised_rego}' was found in rendered HTML "
            f"when trade_family='{trade_family}' — the vehicle registration "
            f"section should only appear for 'automotive-transport'"
        )

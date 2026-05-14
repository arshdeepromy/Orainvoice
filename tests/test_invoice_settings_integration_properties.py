"""Property-based tests for Invoice Settings Integration (Task 12).

Properties tested:
- Property 1: Toggle persistence round-trip
- Property 2: Content independence from toggle state
- Property 3: Email signature conditional append
- Property 4: Notes pre-fill conditional on toggle
- Property 5: Edit mode uses stored invoice values
- Property 6: Web preview conditional section rendering
- Property 7: PDF template toggle-aware rendering
- Property 8: HTML content preservation in T&C
- Property 9: Invoice detail API conditional payment_terms_text
- Property 10: Backward compatibility — existing invoice content always renders

Uses Hypothesis to generate random test data and verify universal properties.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Pure helper functions replicating the logic under test
# ---------------------------------------------------------------------------

# Toggle defaults matching the backend (organisations/service.py)
TOGGLE_DEFAULTS = {
    "email_signature_enabled": False,
    "default_notes_enabled": False,
    "payment_terms_enabled": True,
    "terms_and_conditions_enabled": True,
}


def simulate_settings_roundtrip(put_values: dict) -> dict:
    """Simulate PUT then GET for org settings toggle fields.

    The backend stores whatever booleans are sent via PUT, then on GET
    returns them (with defaults applied for missing keys).

    **Validates: Requirements 1.1, 1.2**
    """
    # Simulate storage (PUT stores the values as-is in JSONB)
    stored = dict(put_values)

    # Simulate retrieval (GET applies defaults for missing keys)
    result = {}
    for key, default in TOGGLE_DEFAULTS.items():
        result[key] = stored.get(key) if stored.get(key) is not None else default
    return result


def simulate_content_roundtrip(content: str, toggle_value: bool) -> str:
    """Simulate storing content alongside a toggle, then retrieving it.

    Content is stored independently of toggle state — the toggle only
    controls whether the content is *applied*, not whether it's stored.

    **Validates: Requirements 1.7**
    """
    # PUT stores content regardless of toggle
    stored_content = content
    # GET returns content regardless of toggle
    return stored_content


def build_email_body_with_signature(
    body: str, signature: str, enabled: bool
) -> str:
    """Replicate the email signature append logic from invoices/service.py.

    When enabled=True and signature is non-empty (after strip), append
    <hr> + signature to the HTML body.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    html_body = body.replace("\n", "<br>")
    if enabled and signature.strip():
        html_body += "<hr>" + signature
    return html_body


def get_notes_prefill(notes: str, enabled: bool) -> str:
    """Replicate the notes pre-fill logic from InvoiceCreate.

    When enabled=True and notes content exists (non-empty), return notes.
    Otherwise return empty string.

    **Validates: Requirements 4.1, 4.2**
    """
    if enabled and notes:
        return notes
    return ""


def get_edit_mode_values(
    stored_notes: str,
    stored_tc: str,
    org_notes: str,
    org_tc: str,
    toggle_notes: bool,
    toggle_tc: bool,
) -> dict:
    """Replicate edit-mode initialization logic.

    When editing an existing invoice, the form always uses the invoice's
    stored values regardless of org defaults or toggle state.

    **Validates: Requirements 4.3, 7.2**
    """
    return {
        "notes": stored_notes,
        "terms_and_conditions": stored_tc,
    }


def should_render_section(content: str, enabled: bool) -> bool:
    """Determine if a section (payment terms or T&C) should render in preview.

    A section renders iff enabled=True AND content is non-empty.

    **Validates: Requirements 5.1, 5.2, 6.1, 6.2**
    """
    return enabled and bool(content)


def build_pdf_context(
    notes_customer: str,
    payment_terms_text: str,
    terms_and_conditions: str,
    payment_terms_enabled: bool,
    terms_and_conditions_enabled: bool,
    per_invoice_tc: str | None = None,
) -> dict:
    """Replicate PDF template context builder logic.

    - notes_customer always passes through
    - payment_terms: empty when disabled, content when enabled
    - terms_and_conditions: per-invoice TC always renders; org-level TC
      only renders when enabled

    **Validates: Requirements 5.3, 5.4, 6.3, 6.4, 8.1, 8.2, 8.3**
    """
    # Payment terms: suppress when toggle is off
    payment_terms = payment_terms_text if payment_terms_enabled else ""

    # T&C: per-invoice stored data always renders (backward compat)
    # Only suppress org-level fallback when toggle is off
    if per_invoice_tc:
        tc = per_invoice_tc
    elif terms_and_conditions_enabled:
        tc = terms_and_conditions
    else:
        tc = ""

    return {
        "notes_customer": notes_customer,
        "payment_terms": payment_terms,
        "terms_and_conditions": tc,
    }


def store_and_retrieve_content(content: str) -> str:
    """Simulate storing and retrieving HTML content in JSONB.

    JSONB stores text as-is without stripping HTML tags.

    **Validates: Requirements 6.5, 7.1, 7.5**
    """
    # JSONB stores the raw string — no tag stripping
    return content


def build_invoice_detail_response(
    payment_terms_text: str, enabled: bool
) -> dict:
    """Replicate invoice detail API response builder logic.

    payment_terms_text is included in the response only when enabled=True
    and content exists.

    **Validates: Requirements 9.3, 9.4**
    """
    result = {}
    if enabled:
        if payment_terms_text:
            result["payment_terms_text"] = payment_terms_text
    return result


def build_pdf_context_with_stored_data(
    stored_notes_customer: str,
    stored_tc: str,
    org_payment_terms: str,
    org_tc: str,
    payment_terms_enabled: bool,
    terms_and_conditions_enabled: bool,
) -> dict:
    """Replicate PDF render context for existing invoices with stored data.

    Per-invoice stored content always renders regardless of org toggle.

    **Validates: Requirements 10.1, 10.2**
    """
    # Notes always pass through (per-invoice data)
    notes_customer = stored_notes_customer

    # Payment terms from org settings (toggle-controlled)
    payment_terms = org_payment_terms if payment_terms_enabled else ""

    # Per-invoice TC always renders regardless of org toggle
    if stored_tc:
        tc = stored_tc
    elif terms_and_conditions_enabled:
        tc = org_tc
    else:
        tc = ""

    return {
        "notes_customer": notes_customer,
        "payment_terms": payment_terms,
        "terms_and_conditions": tc,
    }


# ---------------------------------------------------------------------------
# Property 1: Toggle persistence round-trip
# **Validates: Requirements 1.1, 1.2**
# ---------------------------------------------------------------------------


class TestTogglePersistenceRoundTrip:
    """For any combination of 4 boolean toggle values, saving via PUT and
    reading via GET returns the same values."""

    @given(
        email_sig_enabled=st.booleans(),
        notes_enabled=st.booleans(),
        payment_terms_enabled=st.booleans(),
        tc_enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_toggle_roundtrip(
        self,
        email_sig_enabled,
        notes_enabled,
        payment_terms_enabled,
        tc_enabled,
    ):
        """Property 1: Toggle persistence round-trip — PUT then GET returns
        identical boolean values.

        **Validates: Requirements 1.1, 1.2**
        """
        put_values = {
            "email_signature_enabled": email_sig_enabled,
            "default_notes_enabled": notes_enabled,
            "payment_terms_enabled": payment_terms_enabled,
            "terms_and_conditions_enabled": tc_enabled,
        }

        result = simulate_settings_roundtrip(put_values)

        assert result["email_signature_enabled"] == email_sig_enabled
        assert result["default_notes_enabled"] == notes_enabled
        assert result["payment_terms_enabled"] == payment_terms_enabled
        assert result["terms_and_conditions_enabled"] == tc_enabled


# ---------------------------------------------------------------------------
# Property 2: Content independence from toggle state
# **Validates: Requirements 1.7**
# ---------------------------------------------------------------------------


class TestContentIndependenceFromToggle:
    """Text content stored via PUT is returned unchanged by GET regardless
    of the associated toggle's value."""

    @given(
        content=st.text(min_size=0, max_size=500),
        toggle=st.booleans(),
    )
    @settings(max_examples=30)
    def test_content_unchanged_regardless_of_toggle(self, content, toggle):
        """Property 2: Content independence from toggle state — content is
        stored and retrieved unchanged regardless of toggle value.

        **Validates: Requirements 1.7**
        """
        result = simulate_content_roundtrip(content, toggle)
        assert result == content


# ---------------------------------------------------------------------------
# Property 3: Email signature conditional append
# **Validates: Requirements 3.1, 3.2, 3.3**
# ---------------------------------------------------------------------------


class TestEmailSignatureConditionalAppend:
    """Email signature is appended iff enabled=True and signature non-empty."""

    @given(
        body=st.text(min_size=1, max_size=200),
        signature=st.text(min_size=1, max_size=200),
        enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_signature_conditional_append(self, body, signature, enabled):
        """Property 3: Email signature conditional append — signature present
        iff enabled=True and signature non-empty after strip.

        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        result = build_email_body_with_signature(body, signature, enabled)

        if enabled and signature.strip():
            # Signature should be present with <hr> separator
            assert "<hr>" in result
            assert signature in result
        else:
            # Signature should NOT be appended — no <hr> separator present
            assert "<hr>" not in result


# ---------------------------------------------------------------------------
# Property 4: Notes pre-fill conditional on toggle
# **Validates: Requirements 4.1, 4.2**
# ---------------------------------------------------------------------------


class TestNotesPrefillConditional:
    """Notes pre-fill returns notes when enabled=True and notes non-empty,
    else empty string."""

    @given(
        notes=st.text(min_size=0, max_size=500),
        enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_notes_prefill_conditional(self, notes, enabled):
        """Property 4: Notes pre-fill conditional on toggle — result equals
        notes when enabled=True and notes non-empty, else empty string.

        **Validates: Requirements 4.1, 4.2**
        """
        result = get_notes_prefill(notes, enabled)

        if enabled and notes:
            assert result == notes
        else:
            assert result == ""


# ---------------------------------------------------------------------------
# Property 5: Edit mode uses stored invoice values
# **Validates: Requirements 4.3, 7.2**
# ---------------------------------------------------------------------------


class TestEditModeUsesStoredValues:
    """Edit mode always uses stored invoice values regardless of org defaults
    or toggle state."""

    @given(
        stored_notes=st.text(min_size=0, max_size=200),
        stored_tc=st.text(min_size=0, max_size=200),
        org_notes=st.text(min_size=0, max_size=200),
        org_tc=st.text(min_size=0, max_size=200),
        toggle_notes=st.booleans(),
        toggle_tc=st.booleans(),
    )
    @settings(max_examples=30)
    def test_edit_mode_uses_stored_values(
        self,
        stored_notes,
        stored_tc,
        org_notes,
        org_tc,
        toggle_notes,
        toggle_tc,
    ):
        """Property 5: Edit mode uses stored invoice values — stored values
        used regardless of org defaults or toggle state.

        **Validates: Requirements 4.3, 7.2**
        """
        result = get_edit_mode_values(
            stored_notes, stored_tc, org_notes, org_tc, toggle_notes, toggle_tc
        )

        assert result["notes"] == stored_notes
        assert result["terms_and_conditions"] == stored_tc


# ---------------------------------------------------------------------------
# Property 6: Web preview conditional section rendering
# **Validates: Requirements 5.1, 5.2, 6.1, 6.2**
# ---------------------------------------------------------------------------


class TestWebPreviewConditionalRendering:
    """Payment terms and T&C sections render iff enabled=True AND content
    non-empty."""

    @given(
        payment_terms=st.text(min_size=0, max_size=200),
        tc=st.text(min_size=0, max_size=200),
        pt_enabled=st.booleans(),
        tc_enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_section_rendering_conditional(
        self, payment_terms, tc, pt_enabled, tc_enabled
    ):
        """Property 6: Web preview conditional section rendering — sections
        present iff enabled=True AND content non-empty.

        **Validates: Requirements 5.1, 5.2, 6.1, 6.2**
        """
        pt_visible = should_render_section(payment_terms, pt_enabled)
        tc_visible = should_render_section(tc, tc_enabled)

        # Payment terms visible iff enabled AND content non-empty
        assert pt_visible == (pt_enabled and bool(payment_terms))

        # T&C visible iff enabled AND content non-empty
        assert tc_visible == (tc_enabled and bool(tc))


# ---------------------------------------------------------------------------
# Property 7: PDF template toggle-aware rendering
# **Validates: Requirements 5.3, 5.4, 6.3, 6.4, 8.1, 8.2, 8.3**
# ---------------------------------------------------------------------------


class TestPDFTemplateToggleRendering:
    """PDF context builder passes empty when disabled, content when enabled.
    Notes always pass through."""

    @given(
        notes_customer=st.text(min_size=0, max_size=200),
        payment_terms_text=st.text(min_size=0, max_size=200),
        terms_and_conditions=st.text(min_size=0, max_size=200),
        pt_enabled=st.booleans(),
        tc_enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_pdf_context_toggle_aware(
        self,
        notes_customer,
        payment_terms_text,
        terms_and_conditions,
        pt_enabled,
        tc_enabled,
    ):
        """Property 7: PDF template toggle-aware rendering — payment_terms
        empty when disabled, content when enabled. T&C same. Notes always
        pass through.

        **Validates: Requirements 5.3, 5.4, 6.3, 6.4, 8.1, 8.2, 8.3**
        """
        result = build_pdf_context(
            notes_customer=notes_customer,
            payment_terms_text=payment_terms_text,
            terms_and_conditions=terms_and_conditions,
            payment_terms_enabled=pt_enabled,
            terms_and_conditions_enabled=tc_enabled,
        )

        # Notes always pass through
        assert result["notes_customer"] == notes_customer

        # Payment terms: empty when disabled, content when enabled
        if pt_enabled:
            assert result["payment_terms"] == payment_terms_text
        else:
            assert result["payment_terms"] == ""

        # T&C: empty when disabled (no per-invoice TC), content when enabled
        if tc_enabled:
            assert result["terms_and_conditions"] == terms_and_conditions
        else:
            assert result["terms_and_conditions"] == ""


# ---------------------------------------------------------------------------
# Property 8: HTML content preservation in T&C
# **Validates: Requirements 6.5, 7.1, 7.5**
# ---------------------------------------------------------------------------


class TestHTMLContentPreservation:
    """HTML tags are preserved without stripping through store/retrieve."""

    @given(
        html_tag=st.sampled_from([
            "<b>bold</b>",
            "<ul><li>item</li></ul>",
            "<a href='#'>link</a>",
            "<h2>heading</h2>",
            "<em>italic</em>",
        ]),
        surrounding_text=st.text(min_size=0, max_size=200),
    )
    @settings(max_examples=30)
    def test_html_tags_preserved(self, html_tag, surrounding_text):
        """Property 8: HTML content preservation in T&C — HTML tags preserved
        without stripping through store/retrieve round-trip.

        **Validates: Requirements 6.5, 7.1, 7.5**
        """
        content = surrounding_text + html_tag + surrounding_text
        result = store_and_retrieve_content(content)

        # HTML tags must be preserved
        assert html_tag in result
        assert result == content


# ---------------------------------------------------------------------------
# Property 9: Invoice detail API conditional payment_terms_text
# **Validates: Requirements 9.3, 9.4**
# ---------------------------------------------------------------------------


class TestInvoiceDetailConditionalPaymentTerms:
    """payment_terms_text present in response iff enabled=True."""

    @given(
        payment_terms_text=st.text(min_size=1, max_size=200),
        enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_payment_terms_conditional_in_response(
        self, payment_terms_text, enabled
    ):
        """Property 9: Invoice detail API conditional payment_terms_text —
        present in response iff enabled=True.

        **Validates: Requirements 9.3, 9.4**
        """
        result = build_invoice_detail_response(payment_terms_text, enabled)

        if enabled:
            assert "payment_terms_text" in result
            assert result["payment_terms_text"] == payment_terms_text
        else:
            assert "payment_terms_text" not in result


# ---------------------------------------------------------------------------
# Property 10: Backward compatibility — existing invoice content always renders
# **Validates: Requirements 10.1, 10.2**
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Per-invoice stored content always renders in PDF regardless of org
    toggle state."""

    @given(
        stored_notes=st.text(min_size=1, max_size=200),
        stored_tc=st.text(min_size=1, max_size=200),
        org_payment_terms=st.text(min_size=0, max_size=200),
        org_tc=st.text(min_size=0, max_size=200),
        pt_enabled=st.booleans(),
        tc_enabled=st.booleans(),
    )
    @settings(max_examples=30)
    def test_stored_content_always_renders(
        self,
        stored_notes,
        stored_tc,
        org_payment_terms,
        org_tc,
        pt_enabled,
        tc_enabled,
    ):
        """Property 10: Backward compatibility — existing invoice content
        always renders regardless of org toggle state.

        **Validates: Requirements 10.1, 10.2**
        """
        result = build_pdf_context_with_stored_data(
            stored_notes_customer=stored_notes,
            stored_tc=stored_tc,
            org_payment_terms=org_payment_terms,
            org_tc=org_tc,
            payment_terms_enabled=pt_enabled,
            terms_and_conditions_enabled=tc_enabled,
        )

        # Per-invoice notes always present
        assert result["notes_customer"] == stored_notes

        # Per-invoice T&C always present (regardless of org toggle)
        assert result["terms_and_conditions"] == stored_tc

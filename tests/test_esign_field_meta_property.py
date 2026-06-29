"""Property-based test for the pure ``build_field_meta`` helper (Task 8.4).

Feature: esignature-field-placement
Property 8: Field meta carries required always, and text label/placeholder only
for text fields.

Exercises ``build_field_meta`` from ``app.modules.esignatures.field_mapping``
across many generated placed-field shapes:

- the built ``fieldMeta`` ALWAYS carries ``required`` as a plain ``bool``
  equal to ``bool(field.required)`` (R5.3);
- it carries ``label`` / ``placeholder`` **iff** the field's type is ``text``
  AND that value is present (truthy) on the field, with the value preserved
  verbatim (R5.4);
- a non-``text`` field never carries ``label`` / ``placeholder`` even when set,
  and the only keys ever present are ``required`` / ``label`` / ``placeholder``.

Validates: Requirements 5.3, 5.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.field_mapping import (
    SUPPORTED_FIELD_TYPES,
    build_field_meta,
)

# The six supported lowercase field types (signature/initials/name/date/email/text).
_FIELD_TYPES = sorted(SUPPORTED_FIELD_TYPES)

# ``required`` may arrive as anything the caller represents truthiness with;
# build_field_meta coerces it to a plain bool, so generate a mix of values.
_required_values = st.one_of(
    st.booleans(),
    st.integers(min_value=-2, max_value=2),
    st.none(),
    st.text(max_size=3),
)

# label / placeholder: absent (None), empty (falsy), or a real string (truthy).
_text_meta_values = st.one_of(
    st.none(),
    st.just(""),
    st.text(min_size=1, max_size=20),
)


@st.composite
def _fields(draw) -> dict:
    """A placed-field stub: chosen type plus required + optional text meta.

    Returned as a plain mapping (``build_field_meta`` is duck-typed over both
    mappings and attribute objects), constraining inputs to the real input
    space: a supported type, some ``required`` value, and label/placeholder
    that may be absent, empty, or present.
    """
    field: dict = {
        "type": draw(st.sampled_from(_FIELD_TYPES)),
        "required": draw(_required_values),
        "label": draw(_text_meta_values),
        "placeholder": draw(_text_meta_values),
    }
    return field


@settings(max_examples=100, deadline=None)
@given(field=_fields())
def test_field_meta_required_always_text_meta_only_for_text(field: dict):
    meta = build_field_meta(field)

    # (R5.3) required is ALWAYS present, as a plain bool matching bool(required).
    assert "required" in meta
    assert meta["required"] is bool(field["required"])

    # The only keys that may ever appear.
    assert set(meta).issubset({"required", "label", "placeholder"})

    is_text = field["type"] == "text"
    for key in ("label", "placeholder"):
        value = field[key]
        # (R5.4) present iff type is text AND the value is truthy/present.
        if is_text and value:
            assert key in meta
            assert meta[key] == value
        else:
            assert key not in meta

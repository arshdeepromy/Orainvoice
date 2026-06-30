"""Property-based test for the pure ``build_field_meta`` helper (Task 8.4).

Feature: esignature-field-placement
Property 8: Field meta carries required always; text/number carry
label/placeholder + a type discriminator; radio/checkbox/dropdown carry a
values options list + a type discriminator; the simple types carry only
required.

Exercises ``build_field_meta`` from ``app.modules.esignatures.field_mapping``
across many generated placed-field shapes:

- the built ``fieldMeta`` ALWAYS carries ``required`` as a plain ``bool``
  equal to ``bool(field.required)`` (R5.3);
- ``text`` / ``number`` carry ``label`` / ``placeholder`` **iff** that value is
  present (truthy), with the value preserved verbatim, plus a ``type``
  discriminator (R5.4);
- ``radio`` / ``checkbox`` carry ``values`` (``{id, value, checked}`` per
  option) and ``dropdown`` carries ``values`` (``{value}`` per option), each
  with a ``type`` discriminator;
- the simple types (``signature`` / ``initials`` / ``name`` / ``date`` /
  ``email``) carry **only** ``required`` — no discriminator, no label /
  placeholder / values.

Validates: Requirements 5.3, 5.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.field_mapping import (
    SUPPORTED_FIELD_TYPES,
    build_field_meta,
)

# All supported lowercase field types.
_FIELD_TYPES = sorted(SUPPORTED_FIELD_TYPES)

# The types that behave like TEXT (label/placeholder + a type discriminator).
_TEXT_LIKE = {"text", "number"}
# The types that carry a ``values`` options list + a type discriminator.
_OPTION_LIKE = {"radio", "checkbox", "dropdown"}
# The simple types whose fieldMeta is exactly {"required": ...}.
_SIMPLE = {"signature", "initials", "name", "date", "email"}

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

# options: absent (None) or a small list of strings (some possibly blank).
_options_values = st.one_of(
    st.none(),
    st.lists(st.text(max_size=8), max_size=4),
)


@st.composite
def _fields(draw) -> dict:
    """A placed-field stub: chosen type plus required + optional meta/options.

    Returned as a plain mapping (``build_field_meta`` is duck-typed over both
    mappings and attribute objects), constraining inputs to the real input
    space: a supported type, some ``required`` value, label/placeholder that may
    be absent/empty/present, and an options list that may be absent/present.
    """
    field: dict = {
        "type": draw(st.sampled_from(_FIELD_TYPES)),
        "required": draw(_required_values),
        "label": draw(_text_meta_values),
        "placeholder": draw(_text_meta_values),
        "options": draw(_options_values),
    }
    return field


@settings(max_examples=200, deadline=None)
@given(field=_fields())
def test_field_meta_shape_matches_type(field: dict):
    meta = build_field_meta(field)

    # (R5.3) required is ALWAYS present, as a plain bool matching bool(required).
    assert "required" in meta
    assert meta["required"] is bool(field["required"])

    ftype = field["type"]

    if ftype in _SIMPLE:
        # The simple types carry only ``required`` — nothing else.
        assert set(meta) == {"required"}
        return

    if ftype in _TEXT_LIKE:
        assert set(meta).issubset({"required", "label", "placeholder", "type"})
        assert meta["type"] == ftype
        for key in ("label", "placeholder"):
            value = field[key]
            # present iff the value is truthy/present.
            if value:
                assert meta[key] == value
            else:
                assert key not in meta
        return

    # Option-bearing types carry ``values`` + a ``type`` discriminator.
    assert ftype in _OPTION_LIKE
    assert meta["type"] == ftype
    assert set(meta) == {"required", "type", "values"}
    options = field["options"] or []
    if ftype == "dropdown":
        assert meta["values"] == [{"value": str(opt)} for opt in options]
    else:
        assert meta["values"] == [
            {"id": i, "value": str(opt), "checked": False}
            for i, opt in enumerate(options)
        ]

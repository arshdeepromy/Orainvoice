"""Property-based test for the pure ``map_field_type`` helper (Task 8.3).

Feature: esignature-field-placement
Property 9: Field type maps totally to the documented Documenso type.

Exercises ``map_field_type`` from ``app.modules.esignatures.field_mapping``
across both halves of its total input space:

- each of the six documented lowercase types returns EXACTLY its documented
  Documenso (UPPERCASE) type (``signature`` → ``SIGNATURE`` etc.), and the
  result is always one of the six known Documenso types (R2.4);
- any string outside the six supported keys (typos, UPPERCASE Documenso types,
  case variants, whitespace-padded variants, empty) is rejected with
  ``UnsupportedFieldType``, which carries the offending value — so an
  unsupported type can never reach the ``field/create-many`` wire (R2.4).

Validates: Requirements 2.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.field_mapping import (
    FIELD_TYPE_MAP,
    SUPPORTED_FIELD_TYPES,
    UnsupportedFieldType,
    map_field_type,
)

# The documented Documenso (UPPERCASE) types map maps onto.
_DOCUMENSO_TYPES = frozenset(FIELD_TYPE_MAP.values())


@settings(max_examples=100, deadline=None)
@given(field_type=st.sampled_from(sorted(SUPPORTED_FIELD_TYPES)))
def test_supported_type_maps_to_its_documented_documenso_type(field_type: str):
    # Each supported lowercase type maps to EXACTLY its documented Documenso
    # type, and the result is always one of the six known Documenso types.
    result = map_field_type(field_type)
    assert result == FIELD_TYPE_MAP[field_type]
    assert result in _DOCUMENSO_TYPES


@settings(max_examples=100, deadline=None)
@given(
    bad=st.text().filter(lambda s: s not in SUPPORTED_FIELD_TYPES)
)
def test_unsupported_type_string_is_rejected(bad: str):
    # Any string outside the six supported keys is rejected, and the raised
    # error carries the offending value (so it can never reach the wire).
    try:
        map_field_type(bad)
    except UnsupportedFieldType as exc:
        assert exc.field_type == bad
    else:
        raise AssertionError(f"expected UnsupportedFieldType for {bad!r}")

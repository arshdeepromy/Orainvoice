"""Unit tests for the pure field_mapping helpers (task 8.1).

Covers ``map_field_type`` and ``build_field_meta`` — both pure functions, no
I/O. Property-based coverage lives in tasks 8.3 / 8.4.

Requirements: 2.4, 5.3, 5.4
"""

from __future__ import annotations

import pytest

from app.modules.esignatures.field_mapping import (
    FIELD_TYPE_MAP,
    SUPPORTED_FIELD_TYPES,
    UnsupportedFieldType,
    build_field_meta,
    map_field_type,
)


# ---------------------------------------------------------------------------
# map_field_type (R2.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lowercase", "uppercase"),
    [
        ("signature", "SIGNATURE"),
        ("initials", "INITIALS"),
        ("name", "NAME"),
        ("date", "DATE"),
        ("email", "EMAIL"),
        ("text", "TEXT"),
    ],
)
def test_map_field_type_maps_each_supported_type(lowercase, uppercase):
    assert map_field_type(lowercase) == uppercase


def test_supported_set_matches_map_keys():
    assert SUPPORTED_FIELD_TYPES == frozenset(FIELD_TYPE_MAP)


@pytest.mark.parametrize(
    "bad",
    ["SIGNATURE", "Signature", "checkbox", "sign", "", " text", "text ", "radio"],
)
def test_map_field_type_rejects_unsupported_strings(bad):
    with pytest.raises(UnsupportedFieldType):
        map_field_type(bad)


@pytest.mark.parametrize("bad", [None, 123, ["text"], {"type": "text"}])
def test_map_field_type_rejects_non_string(bad):
    with pytest.raises(UnsupportedFieldType):
        map_field_type(bad)


def test_unsupported_field_type_is_value_error_and_carries_type():
    with pytest.raises(ValueError) as exc:
        map_field_type("nope")
    assert isinstance(exc.value, UnsupportedFieldType)
    assert exc.value.field_type == "nope"


# ---------------------------------------------------------------------------
# build_field_meta (R5.3, R5.4)
# ---------------------------------------------------------------------------


def _field(**kwargs):
    """Mapping-based field stub (build_field_meta is duck-typed)."""
    return kwargs


def test_build_field_meta_always_carries_required_true():
    meta = build_field_meta(_field(type="signature", required=True))
    assert meta == {"required": True}


def test_build_field_meta_always_carries_required_false():
    meta = build_field_meta(_field(type="date", required=False))
    assert meta == {"required": False}


def test_build_field_meta_coerces_required_to_bool():
    meta = build_field_meta(_field(type="signature", required=1))
    assert meta["required"] is True
    meta = build_field_meta(_field(type="signature", required=None))
    assert meta["required"] is False


def test_text_field_includes_label_and_placeholder_when_present():
    meta = build_field_meta(
        _field(type="text", required=False, label="Job ref", placeholder="e.g. 12345")
    )
    assert meta == {"required": False, "label": "Job ref", "placeholder": "e.g. 12345"}


def test_text_field_includes_only_present_meta():
    assert build_field_meta(_field(type="text", required=True, label="Notes")) == {
        "required": True,
        "label": "Notes",
    }
    assert build_field_meta(
        _field(type="text", required=True, placeholder="type here")
    ) == {"required": True, "placeholder": "type here"}


def test_text_field_ignores_empty_label_placeholder():
    meta = build_field_meta(_field(type="text", required=True, label="", placeholder=""))
    assert meta == {"required": True}


@pytest.mark.parametrize("ftype", ["signature", "initials", "name", "date", "email"])
def test_non_text_fields_never_carry_label_or_placeholder(ftype):
    # Even when label/placeholder are set, non-text fields drop them (R5.4).
    meta = build_field_meta(
        _field(type=ftype, required=True, label="ignored", placeholder="ignored")
    )
    assert meta == {"required": True}


def test_build_field_meta_supports_attribute_objects():
    class FieldStub:
        type = "text"
        required = True
        label = "Address"
        placeholder = None

    assert build_field_meta(FieldStub()) == {"required": True, "label": "Address"}


def test_build_field_meta_rejects_unsupported_type():
    with pytest.raises(UnsupportedFieldType):
        build_field_meta(_field(type="checkbox", required=True))

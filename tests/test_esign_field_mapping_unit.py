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
        ("number", "NUMBER"),
        ("radio", "RADIO"),
        ("checkbox", "CHECKBOX"),
        ("dropdown", "DROPDOWN"),
    ],
)
def test_map_field_type_maps_each_supported_type(lowercase, uppercase):
    assert map_field_type(lowercase) == uppercase


def test_supported_set_matches_map_keys():
    assert SUPPORTED_FIELD_TYPES == frozenset(FIELD_TYPE_MAP)


@pytest.mark.parametrize(
    "bad",
    ["SIGNATURE", "Signature", "sign", "", " text", "text ", "slider", "select"],
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
    assert meta == {
        "required": False,
        "label": "Job ref",
        "placeholder": "e.g. 12345",
        "type": "text",
    }


def test_text_field_includes_only_present_meta():
    assert build_field_meta(_field(type="text", required=True, label="Notes")) == {
        "required": True,
        "label": "Notes",
        "type": "text",
    }
    assert build_field_meta(
        _field(type="text", required=True, placeholder="type here")
    ) == {"required": True, "placeholder": "type here", "type": "text"}


def test_text_field_ignores_empty_label_placeholder():
    meta = build_field_meta(_field(type="text", required=True, label="", placeholder=""))
    assert meta == {"required": True, "type": "text"}


@pytest.mark.parametrize("ftype", ["signature", "initials", "name", "date", "email"])
def test_non_text_fields_never_carry_label_or_placeholder(ftype):
    # Even when label/placeholder are set, the simple types drop them and carry
    # no ``type`` discriminator — their fieldMeta is exactly {"required": ...}
    # (R5.4).
    meta = build_field_meta(
        _field(type=ftype, required=True, label="ignored", placeholder="ignored")
    )
    assert meta == {"required": True}


def test_number_field_behaves_like_text_with_number_discriminator():
    # NUMBER carries label/placeholder exactly like TEXT, with a ``number`` type.
    meta = build_field_meta(
        _field(type="number", required=True, label="Mileage", placeholder="e.g. 120000")
    )
    assert meta == {
        "required": True,
        "label": "Mileage",
        "placeholder": "e.g. 120000",
        "type": "number",
    }
    assert build_field_meta(_field(type="number", required=False)) == {
        "required": False,
        "type": "number",
    }


def test_radio_field_emits_checkable_values():
    meta = build_field_meta(
        _field(type="radio", required=True, options=["Yes", "No", "Maybe"])
    )
    assert meta == {
        "required": True,
        "type": "radio",
        "values": [
            {"id": 0, "value": "Yes", "checked": False},
            {"id": 1, "value": "No", "checked": False},
            {"id": 2, "value": "Maybe", "checked": False},
        ],
    }


def test_checkbox_field_emits_checkable_values():
    # CHECKBOX shares the ``values`` shape; an absent options list -> empty.
    assert build_field_meta(_field(type="checkbox", required=False)) == {
        "required": False,
        "type": "checkbox",
        "values": [],
    }
    assert build_field_meta(
        _field(type="checkbox", required=True, options=["I agree"])
    ) == {
        "required": True,
        "type": "checkbox",
        "values": [{"id": 0, "value": "I agree", "checked": False}],
    }


def test_dropdown_field_emits_value_only_options():
    meta = build_field_meta(
        _field(type="dropdown", required=True, options=["AUD", "NZD", "USD"])
    )
    assert meta == {
        "required": True,
        "type": "dropdown",
        "values": [{"value": "AUD"}, {"value": "NZD"}, {"value": "USD"}],
    }


def test_options_are_coerced_to_strings():
    meta = build_field_meta(_field(type="dropdown", required=True, options=[1, 2.5]))
    assert meta["values"] == [{"value": "1"}, {"value": "2.5"}]


def test_build_field_meta_supports_attribute_objects():
    class FieldStub:
        type = "text"
        required = True
        label = "Address"
        placeholder = None

    assert build_field_meta(FieldStub()) == {
        "required": True,
        "label": "Address",
        "type": "text",
    }


def test_build_field_meta_rejects_unsupported_type():
    with pytest.raises(UnsupportedFieldType):
        build_field_meta(_field(type="slider", required=True))

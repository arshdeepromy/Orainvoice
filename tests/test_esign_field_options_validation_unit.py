"""Unit tests for the radio/dropdown options validation rule (field placement).

Feature: esignature-field-placement — advanced field types.

``validate_field_set`` must reject a ``radio`` or ``dropdown`` field that has no
non-empty sender-authored option, with the ``field_options_missing`` code and a
humanized message naming the field type. ``checkbox`` (a single box) and
``number`` (text-like) need no options. Pure, no I/O.

Requirements: 2.4, 6.1, 6.2, 6.3
"""

from __future__ import annotations

import pytest

from app.modules.esignatures.field_validation import (
    CODE_FIELD_OPTIONS_MISSING,
    validate_field_set,
)


def _recipients():
    return [{"name": "Alex", "email": "alex@example.com", "signing_role": "signer"}]


def _field(ftype, **kwargs):
    base = {
        "type": ftype,
        "page": 1,
        "recipient_index": 0,
        "position_x": 10.0,
        "position_y": 10.0,
        "width": 20.0,
        "height": 10.0,
        "required": True,
    }
    base.update(kwargs)
    return base


# A signature field for the lone signer so the R6.1 rule never masks the
# options rule under test.
def _with_signature(*fields):
    return [_field("signature"), *fields]


@pytest.mark.parametrize("ftype", ["radio", "dropdown"])
def test_option_bearing_field_with_no_options_is_rejected(ftype):
    fields = _with_signature(_field(ftype))  # no options key
    result = validate_field_set(fields, _recipients(), [0])
    assert result.ok is False
    assert result.code == CODE_FIELD_OPTIONS_MISSING
    assert ftype in result.message
    assert result.message.strip() != ""


@pytest.mark.parametrize("ftype", ["radio", "dropdown"])
def test_option_bearing_field_with_only_blank_options_is_rejected(ftype):
    fields = _with_signature(_field(ftype, options=["", "   "]))
    result = validate_field_set(fields, _recipients(), [0])
    assert result.ok is False
    assert result.code == CODE_FIELD_OPTIONS_MISSING


@pytest.mark.parametrize("ftype", ["radio", "dropdown"])
def test_option_bearing_field_with_one_real_option_passes(ftype):
    fields = _with_signature(_field(ftype, options=["Yes"]))
    result = validate_field_set(fields, _recipients(), [0])
    assert result.ok is True
    assert result.code is None


@pytest.mark.parametrize("ftype", ["checkbox", "number"])
def test_checkbox_and_number_need_no_options(ftype):
    fields = _with_signature(_field(ftype))  # no options
    result = validate_field_set(fields, _recipients(), [0])
    assert result.ok is True

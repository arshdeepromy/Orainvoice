"""Unit tests for Payroll_Tax_Settings Pydantic schemas (spec task 2.2).

Covers the Decimal JSON-number round-trip (serialize as numbers, rehydrate via
``Decimal(str(...))``), the open-ended top-band representation, and the sparse
semantics of org overrides.
"""

import json
from decimal import Decimal

import pytest

from app.modules.payroll_tax.schemas import (
    FieldError,
    FieldInheritance,
    IETCParamsSchema,
    OrgOverridesUpdate,
    OrgTaxSettingsView,
    PAYEBracketSchema,
    PlatformTaxDefaultUpdate,
    PlatformTaxDefaultView,
    SecondaryRatesSchema,
)

_FULL_DOC = {
    "paye_brackets": [
        {"upper_limit": 15600, "rate": 0.105},
        {"upper_limit": 53500, "rate": 0.175},
        {"upper_limit": 78100, "rate": 0.30},
        {"upper_limit": 180000, "rate": 0.33},
        {"upper_limit": None, "rate": 0.39},
    ],
    "secondary_rates": {"SB": 0.105, "S": 0.175, "SH": 0.30, "ST": 0.33, "SA": 0.39},
    "acc_levy_rate": 0.016,
    "acc_max_liable_earnings": 142283,
    "student_loan_rate": 0.12,
    "student_loan_threshold": 24128,
    "ietc": {
        "amount": 520,
        "lower": 24000,
        "abatement_start": 44000,
        "abatement_rate": 0.13,
        "upper": 48000,
    },
    "default_kiwisaver_employee_rate": 3.00,
    "default_kiwisaver_employer_rate": 3.00,
    "tax_year_label": "2024/25",
}


def test_decimals_rehydrate_exactly_from_json_numbers():
    view = PlatformTaxDefaultView(**_FULL_DOC)
    assert isinstance(view.acc_levy_rate, Decimal)
    assert view.acc_levy_rate == Decimal("0.016")
    assert view.secondary_rates.S == Decimal("0.175")
    assert view.ietc.abatement_rate == Decimal("0.13")
    # No binary-float drift: exact decimal equality, not approximate.
    assert view.student_loan_rate == Decimal("0.12")


def test_decimals_serialize_as_json_numbers_not_strings():
    view = PlatformTaxDefaultView(**_FULL_DOC)
    dumped = view.model_dump(mode="json")
    assert dumped["acc_levy_rate"] == 0.016
    assert isinstance(dumped["acc_levy_rate"], float)
    assert isinstance(dumped["paye_brackets"][0]["rate"], float)
    rendered = json.dumps(dumped)
    # The value is a bare JSON number, never a quoted string.
    assert '"0.016"' not in rendered
    assert "0.016" in rendered


def test_open_ended_top_band_is_null():
    view = PlatformTaxDefaultView(**_FULL_DOC)
    assert view.paye_brackets[-1].upper_limit is None
    dumped = view.model_dump(mode="json")
    assert dumped["paye_brackets"][-1]["upper_limit"] is None


def test_json_round_trip_preserves_decimal_values():
    view = PlatformTaxDefaultView(**_FULL_DOC)
    rendered = json.dumps(view.model_dump(mode="json"))
    reparsed = PlatformTaxDefaultView(**json.loads(rendered))
    assert reparsed.acc_levy_rate == Decimal("0.016")
    assert reparsed.secondary_rates.SA == Decimal("0.39")
    assert reparsed.paye_brackets[-1].upper_limit is None


def test_platform_update_accepts_full_document():
    upd = PlatformTaxDefaultUpdate(**_FULL_DOC)
    assert upd.tax_year_label == "2024/25"
    assert upd.default_kiwisaver_employer_rate == Decimal("3.00")


def test_org_overrides_are_sparse():
    ovr = OrgOverridesUpdate(acc_levy_rate=0.02)
    assert ovr.model_fields_set == {"acc_levy_rate"}
    assert ovr.model_dump(exclude_unset=True) == {"acc_levy_rate": Decimal("0.02")}
    assert ovr.model_dump(mode="json", exclude_unset=True) == {"acc_levy_rate": 0.02}


def test_org_overrides_reject_unknown_field():
    # tax_year_label is platform-only and must not be an org override.
    with pytest.raises(Exception):
        OrgOverridesUpdate(tax_year_label="2025/26")


def test_org_overrides_can_set_nested_structures():
    ovr = OrgOverridesUpdate(
        secondary_rates={"SB": 0.10, "S": 0.17, "SH": 0.30, "ST": 0.33, "SA": 0.39},
        paye_brackets=[{"upper_limit": 10000, "rate": 0.10}, {"upper_limit": None, "rate": 0.30}],
    )
    assert ovr.secondary_rates.SB == Decimal("0.10")
    assert ovr.paye_brackets[-1].upper_limit is None
    assert ovr.model_fields_set == {"secondary_rates", "paye_brackets"}


def test_org_tax_settings_view_carries_field_status():
    view = OrgTaxSettingsView(
        **_FULL_DOC,
        field_status={
            "acc_levy_rate": FieldInheritance(
                inherited=False, override=True, source="override"
            ),
            "tax_year_label": FieldInheritance(
                inherited=True, override=False, source="platform"
            ),
        },
    )
    assert view.field_status["acc_levy_rate"].override is True
    assert view.field_status["tax_year_label"].inherited is True
    assert view.field_status["acc_levy_rate"].source == "override"


def test_field_error_shape():
    err = FieldError(field="acc_max_liable_earnings", message="must be greater than zero")
    assert err.field == "acc_max_liable_earnings"
    assert "greater than zero" in err.message


def test_secondary_rates_requires_all_codes():
    with pytest.raises(Exception):
        SecondaryRatesSchema(SB=0.1, S=0.17, SH=0.3, ST=0.33)  # missing SA


def test_ietc_and_bracket_shapes_independently_usable():
    ietc = IETCParamsSchema(amount=520, lower=24000, abatement_start=44000, abatement_rate=0.13, upper=48000)
    assert ietc.amount == Decimal("520")
    bracket = PAYEBracketSchema(rate=0.39)
    assert bracket.upper_limit is None
    assert bracket.rate == Decimal("0.39")

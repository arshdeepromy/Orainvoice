"""Pydantic request/response schemas for the Payroll_Tax_Settings module.

These schemas describe the JSON shapes exchanged over the platform-tier
(`/api/v2/admin/platform-tax-default`) and org-tier
(`/api/v2/payroll-tax-settings`) APIs. They mirror the calculation-ready
value objects in ``app/modules/timesheets/paye.py`` (``ResolvedTaxConfig``,
``PAYEBracket``, ``IETCParams``).

Decimal handling
----------------
Tax rates, caps, and thresholds are cents-precise ``Decimal`` values. To avoid
binary-float drift while still exchanging plain JSON numbers (per the design's
"Tax_Field keys (JSONB schema)" table), every monetary/rate field uses the
``TaxDecimal`` annotated type, which:

* **rehydrates** any incoming JSON number/string into ``Decimal(str(value))``
  (a before-validator), so the in-memory value is always an exact ``Decimal``;
* **serializes** to a JSON number (``float``) when dumping to JSON, so the wire
  format is a number rather than a quoted string.

The ``Decimal(str(...))`` round-trip is what guarantees, for example, that the
JSON number ``0.105`` becomes ``Decimal("0.105")`` and not
``Decimal("0.105000000000000001...")``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

# --- Constants ------------------------------------------------------------

#: The supported secondary tax codes (Req 8.5).
SECONDARY_CODES: tuple[str, ...] = ("SB", "S", "SH", "ST", "SA")


# --- Decimal handling -----------------------------------------------------


def _rehydrate_decimal(value: Any) -> Any:
    """Coerce an incoming JSON number/string into an exact ``Decimal``.

    Uses ``Decimal(str(value))`` so a JSON number such as ``0.105`` is parsed
    as ``Decimal("0.105")`` rather than the nearest binary float. ``None`` and
    values that are already ``Decimal`` pass through unchanged; unparseable
    values are returned untouched so Pydantic raises its standard error.
    """
    if value is None or isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return value


def _decimal_to_number(value: Decimal) -> float:
    """Serialize a ``Decimal`` as a JSON number."""
    return float(value)


#: A ``Decimal`` that rehydrates from JSON numbers via ``Decimal(str(...))``
#: and serializes back to a JSON number.
TaxDecimal = Annotated[
    Decimal,
    BeforeValidator(_rehydrate_decimal),
    PlainSerializer(_decimal_to_number, return_type=float, when_used="json"),
]


# --- Tax-field shapes -----------------------------------------------------


class PAYEBracketSchema(BaseModel):
    """One progressive income-tax band.

    ``upper_limit`` is the annual income ceiling; ``None`` marks the
    open-ended top band.
    """

    upper_limit: TaxDecimal | None = Field(
        default=None,
        description="Annual income ceiling for the band; null = open-ended top band.",
    )
    rate: TaxDecimal = Field(description="Marginal tax rate in [0, 1].")


class IETCParamsSchema(BaseModel):
    """Independent Earner Tax Credit parameters for the ME tax code."""

    amount: TaxDecimal
    lower: TaxDecimal
    abatement_start: TaxDecimal
    abatement_rate: TaxDecimal
    upper: TaxDecimal


class SecondaryRatesSchema(BaseModel):
    """Flat annual rates for the secondary tax codes (SB, S, SH, ST, SA)."""

    SB: TaxDecimal
    S: TaxDecimal
    SH: TaxDecimal
    ST: TaxDecimal
    SA: TaxDecimal


# --- Platform tier --------------------------------------------------------


class PlatformTaxDefaultView(BaseModel):
    """Editable view of every Platform_Tax_Default field (Req 2.1)."""

    paye_brackets: list[PAYEBracketSchema]
    secondary_rates: SecondaryRatesSchema
    acc_levy_rate: TaxDecimal
    acc_max_liable_earnings: TaxDecimal
    student_loan_rate: TaxDecimal
    student_loan_threshold: TaxDecimal
    ietc: IETCParamsSchema
    default_kiwisaver_employee_rate: TaxDecimal
    default_kiwisaver_employer_rate: TaxDecimal
    tax_year_label: str
    updated_at: datetime | None = None
    updated_by: UUID | None = None


class PlatformTaxDefaultUpdate(BaseModel):
    """Full Platform_Tax_Default document submitted by a Global_Admin (Req 2.2).

    The platform editor submits the complete configuration, so every field is
    required. Validation of the values themselves is performed by
    ``validate_config_fragment`` in the service layer.
    """

    paye_brackets: list[PAYEBracketSchema]
    secondary_rates: SecondaryRatesSchema
    acc_levy_rate: TaxDecimal
    acc_max_liable_earnings: TaxDecimal
    student_loan_rate: TaxDecimal
    student_loan_threshold: TaxDecimal
    ietc: IETCParamsSchema
    default_kiwisaver_employee_rate: TaxDecimal
    default_kiwisaver_employer_rate: TaxDecimal
    tax_year_label: str


# --- Org tier -------------------------------------------------------------


class OrgOverridesUpdate(BaseModel):
    """Sparse set of Org_Tax_Settings overrides (Req 3.2).

    Every field is optional. Only the fields explicitly present (see
    ``model_fields_set`` / ``model_dump(exclude_unset=True)``) are treated as
    overrides; absent fields continue to inherit the Platform_Tax_Default.

    ``tax_year_label`` is platform-only and intentionally **not** present here:
    it is never an org override (per the design data model).
    """

    model_config = ConfigDict(extra="forbid")

    paye_brackets: list[PAYEBracketSchema] | None = None
    secondary_rates: SecondaryRatesSchema | None = None
    acc_levy_rate: TaxDecimal | None = None
    acc_max_liable_earnings: TaxDecimal | None = None
    student_loan_rate: TaxDecimal | None = None
    student_loan_threshold: TaxDecimal | None = None
    ietc: IETCParamsSchema | None = None
    default_kiwisaver_employee_rate: TaxDecimal | None = None
    default_kiwisaver_employer_rate: TaxDecimal | None = None


class FieldInheritance(BaseModel):
    """Resolution status for a single Tax_Field in the org settings view.

    ``inherited`` is ``True`` when the effective value comes from the
    Platform_Tax_Default (or the Safety_Net), and ``False`` when the
    organisation has set an explicit override. ``source`` records the precise
    tier the value was resolved from.
    """

    inherited: bool
    override: bool
    source: Literal["override", "platform", "safety_net"]


class OrgTaxSettingsView(BaseModel):
    """Org_Tax_Settings view: effective value + inherited/override per field.

    The top-level fields carry the fully-resolved (effective) value for the
    organisation; ``field_status`` carries, for each Tax_Field, whether that
    value is inherited from the platform default (or safety net) or set as an
    organisation override (Req 4.3, 9.4).

    ``tax_year_label`` is platform-only and always reports as inherited.
    """

    paye_brackets: list[PAYEBracketSchema]
    secondary_rates: SecondaryRatesSchema
    acc_levy_rate: TaxDecimal
    acc_max_liable_earnings: TaxDecimal
    student_loan_rate: TaxDecimal
    student_loan_threshold: TaxDecimal
    ietc: IETCParamsSchema
    default_kiwisaver_employee_rate: TaxDecimal
    default_kiwisaver_employer_rate: TaxDecimal
    tax_year_label: str
    field_status: dict[str, FieldInheritance] = Field(default_factory=dict)


# --- Validation errors ----------------------------------------------------


class FieldError(BaseModel):
    """A single validation failure naming the offending Tax_Field (Req 8.6)."""

    field: str
    message: str

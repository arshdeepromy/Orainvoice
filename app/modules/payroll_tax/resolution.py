"""Resolution service for the Payroll_Tax_Settings module.

Produces a fully-populated :class:`~app.modules.timesheets.paye.ResolvedTaxConfig`
for an organisation by applying the **Resolution_Precedence** field by field:

    Org_Tax_Settings override → Platform_Tax_Default value → Safety_Net

This is the only component that knows about all three tiers. It reads the two
stored rows (the single ``platform_tax_default`` row and the org's
``org_tax_settings`` row, which may be absent), then builds the config one
Tax_Field at a time. The result is:

* **deterministic and date-independent** — pay-period dates are ignored
  entirely (Req 12.2);
* **total** — every Tax_Field is always populated with a non-null, non-blank
  value, even when both higher tiers are missing or unparseable, so the PAYE
  engine never computes against a blank, null, or zero value (Req 5.4, 11.1).

Robustness: each tier's stored value is coerced via typed parsing
(``Decimal(str(...))`` for scalars; structured construction for brackets and
IETC). A value that is **missing** or **fails to parse** falls through to the
next tier (logged at ``warning``); a missing platform row falls every
non-overridden field through to the :data:`SAFETY_NET`.

**Validates: Requirements 1.4, 3.1, 3.3, 5.1, 5.2, 5.3, 5.4, 11.1, 11.2,
11.3, 11.4, 12.2 — Payroll Tax Settings.**
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payroll_tax.models import OrgTaxSettings, PlatformTaxDefault
from app.modules.payroll_tax.schemas import SECONDARY_CODES
from app.modules.timesheets.paye import (
    SAFETY_NET,
    IETCParams,
    PAYEBracket,
    ResolvedTaxConfig,
)

logger = logging.getLogger(__name__)

__all__ = ["resolve_tax_config"]


# ---------------------------------------------------------------------------
# Typed coercion of stored JSON values into calculation-ready value objects.
# ---------------------------------------------------------------------------
#
# Each coercer turns a raw JSON value (as stored in a ``config``/``overrides``
# JSONB document) into the exact in-memory type the engine expects. Coercers
# raise on any missing key, wrong shape, or unparseable number; the resolver
# catches that and falls through to the next tier. ``Decimal(str(value))``
# avoids binary-float drift, matching the cents-precise handling in ``paye.py``
# and the schema rehydration in ``schemas.TaxDecimal``.


def _coerce_decimal(raw: Any) -> Decimal:
    """Coerce a JSON number/string into an exact ``Decimal``.

    Raises on ``None`` or any value Decimal cannot parse (NaN/Inf included),
    so the field falls through to the next tier.
    """
    if raw is None or isinstance(raw, bool):
        raise ValueError("missing or non-numeric value")
    value = Decimal(str(raw))
    if not value.is_finite():
        raise ValueError("non-finite value")
    return value


def _coerce_brackets(raw: Any) -> tuple[PAYEBracket, ...]:
    """Coerce the ``paye_brackets`` list into a tuple of :class:`PAYEBracket`.

    Each element must carry a ``rate`` and an ``upper_limit`` (``None`` marks
    the open-ended top band). A non-list, an empty list, or any malformed
    element raises so the field falls through to the next tier.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) == 0:
        raise ValueError("paye_brackets must be a non-empty list")
    brackets: list[PAYEBracket] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each bracket must be an object")
        upper_raw = item.get("upper_limit", None)
        upper = None if upper_raw is None else _coerce_decimal(upper_raw)
        rate = _coerce_decimal(item["rate"])
        brackets.append(PAYEBracket(upper_limit=upper, rate=rate))
    return tuple(brackets)


def _coerce_secondary(raw: Any) -> dict[str, Decimal]:
    """Coerce the ``secondary_rates`` map; every supported code must be present."""
    if not isinstance(raw, dict):
        raise ValueError("secondary_rates must be an object")
    return {code: _coerce_decimal(raw[code]) for code in SECONDARY_CODES}


def _coerce_ietc(raw: Any) -> IETCParams:
    """Coerce the ``ietc`` object into :class:`IETCParams`; all fields required."""
    if not isinstance(raw, dict):
        raise ValueError("ietc must be an object")
    return IETCParams(
        amount=_coerce_decimal(raw["amount"]),
        lower=_coerce_decimal(raw["lower"]),
        abatement_start=_coerce_decimal(raw["abatement_start"]),
        abatement_rate=_coerce_decimal(raw["abatement_rate"]),
        upper=_coerce_decimal(raw["upper"]),
    )


def _coerce_label(raw: Any) -> str:
    """Coerce the ``tax_year_label`` into a non-blank string."""
    if raw is None:
        raise ValueError("tax_year_label is missing")
    label = str(raw).strip()
    if not label:
        raise ValueError("tax_year_label is blank")
    return label


#: Maps each Tax_Field key to the coercer that rehydrates its stored JSON form.
_COERCERS: dict[str, Callable[[Any], Any]] = {
    "paye_brackets": _coerce_brackets,
    "secondary_rates": _coerce_secondary,
    "acc_levy_rate": _coerce_decimal,
    "acc_max_liable_earnings": _coerce_decimal,
    "student_loan_rate": _coerce_decimal,
    "student_loan_threshold": _coerce_decimal,
    "ietc": _coerce_ietc,
    "default_kiwisaver_employee_rate": _coerce_decimal,
    "default_kiwisaver_employer_rate": _coerce_decimal,
    "tax_year_label": _coerce_label,
}


# ---------------------------------------------------------------------------
# Field-by-field precedence
# ---------------------------------------------------------------------------


def _resolve_field(
    field_key: str,
    org_overrides: dict[str, Any],
    platform_config: dict[str, Any],
    safety_net_value: Any,
) -> Any:
    """Resolve one Tax_Field by precedence: override → platform → Safety_Net.

    Pure function. For each higher tier in turn, if the field is present its
    raw value is coerced into the calculation-ready type; a present-but-
    unparseable value is logged at ``warning`` and the resolver falls through
    to the next tier. ``safety_net_value`` is always a valid value, so this
    function is total — it never returns ``None`` for a populated Tax_Field.
    """
    coerce = _COERCERS[field_key]

    # Tier 1: organisation override.
    if field_key in org_overrides:
        try:
            return coerce(org_overrides[field_key])
        except Exception:  # noqa: BLE001 — any parse failure falls through
            logger.warning(
                "payroll_tax: org override for %r failed to parse; "
                "falling through to platform/safety-net",
                field_key,
            )

    # Tier 2: platform default.
    if field_key in platform_config:
        try:
            return coerce(platform_config[field_key])
        except Exception:  # noqa: BLE001 — any parse failure falls through
            logger.warning(
                "payroll_tax: platform value for %r failed to parse; "
                "falling through to safety-net",
                field_key,
            )

    # Tier 3: hard-coded Safety_Net (always valid).
    return safety_net_value


# ---------------------------------------------------------------------------
# Public resolution entry point
# ---------------------------------------------------------------------------


async def resolve_tax_config(
    db: AsyncSession, org_id: uuid.UUID
) -> ResolvedTaxConfig:
    """Produce the Resolved_Tax_Config for an org via Resolution_Precedence.

    Loads the single ``platform_tax_default`` row and the org's
    ``org_tax_settings`` row (which may be absent), then resolves each
    Tax_Field independently: org override if present and parseable, else the
    platform default value if present and parseable, else the Safety_Net.

    The result is always a fully-populated :class:`ResolvedTaxConfig` (every
    field non-null/non-blank). Pay-period dates are intentionally ignored
    (effective-dating is out of scope).
    """
    # --- Load the single platform default row (may be absent). ---
    platform_row = (
        await db.execute(select(PlatformTaxDefault).limit(1))
    ).scalar_one_or_none()

    platform_config: dict[str, Any] = {}
    if platform_row is not None and isinstance(platform_row.config, dict):
        platform_config = dict(platform_row.config)
    # ``tax_year_label`` lives in its own column, not the JSONB config; fold it
    # into the platform tier so the generic resolver treats it uniformly.
    if platform_row is not None and platform_row.tax_year_label is not None:
        platform_config["tax_year_label"] = platform_row.tax_year_label

    # --- Load the org's overrides row (may be absent → inherit everything). ---
    org_row = (
        await db.execute(
            select(OrgTaxSettings).where(OrgTaxSettings.org_id == org_id)
        )
    ).scalar_one_or_none()

    org_overrides: dict[str, Any] = {}
    if org_row is not None and isinstance(org_row.overrides, dict):
        org_overrides = org_row.overrides

    # --- Resolve every field by precedence. Pass fresh copies for mutable
    #     Safety_Net values so a returned config can never alias the constant.
    return ResolvedTaxConfig(
        paye_brackets=_resolve_field(
            "paye_brackets", org_overrides, platform_config,
            SAFETY_NET.paye_brackets,
        ),
        secondary_rates=_resolve_field(
            "secondary_rates", org_overrides, platform_config,
            dict(SAFETY_NET.secondary_rates),
        ),
        acc_levy_rate=_resolve_field(
            "acc_levy_rate", org_overrides, platform_config,
            SAFETY_NET.acc_levy_rate,
        ),
        acc_max_liable_earnings=_resolve_field(
            "acc_max_liable_earnings", org_overrides, platform_config,
            SAFETY_NET.acc_max_liable_earnings,
        ),
        student_loan_rate=_resolve_field(
            "student_loan_rate", org_overrides, platform_config,
            SAFETY_NET.student_loan_rate,
        ),
        student_loan_threshold=_resolve_field(
            "student_loan_threshold", org_overrides, platform_config,
            SAFETY_NET.student_loan_threshold,
        ),
        ietc=_resolve_field(
            "ietc", org_overrides, platform_config, SAFETY_NET.ietc,
        ),
        default_kiwisaver_employee_rate=_resolve_field(
            "default_kiwisaver_employee_rate", org_overrides, platform_config,
            SAFETY_NET.default_kiwisaver_employee_rate,
        ),
        default_kiwisaver_employer_rate=_resolve_field(
            "default_kiwisaver_employer_rate", org_overrides, platform_config,
            SAFETY_NET.default_kiwisaver_employer_rate,
        ),
        tax_year_label=_resolve_field(
            "tax_year_label", org_overrides, platform_config,
            SAFETY_NET.tax_year_label,
        ),
    )

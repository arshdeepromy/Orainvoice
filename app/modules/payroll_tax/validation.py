"""Pure validation of submitted tax-configuration fragments.

``validate_config_fragment`` is a **pure** function over any sparse ``fragment``
dict: it validates only the Tax_Fields that are present and returns a list of
:class:`~app.modules.payroll_tax.schemas.FieldError`. An empty list means the
fragment is valid. The same rules apply to both tiers (a full platform document
and a sparse org override set), per the design — the platform editor submits the
complete configuration while an org submits only the fields it overrides, and
both are checked here.

The rules implemented (mapped to the requirements):

PAYE brackets (Req 7)
  * at least one band (7.4)
  * every finite ``upper_limit`` strictly greater than zero (7.5)
  * finite ``upper_limit`` values strictly ascending (7.1)
  * exactly one open-ended top band, and it must be last (7.2)
  * every ``rate`` in ``[0, 1]`` inclusive (7.3)

Rates / cap / threshold / IETC / secondary (Req 8)
  * ``acc_levy_rate``, ``student_loan_rate``, each secondary rate, and
    ``ietc.abatement_rate`` in ``[0, 1]``; the two KiwiSaver default percent
    fields in ``[0, 100]`` (8.1)
  * ``acc_max_liable_earnings`` strictly greater than zero (8.2)
  * ``student_loan_threshold`` greater than or equal to zero (8.3)
  * IETC ``lower <= abatement_start <= upper`` (non-decreasing) (8.4)
  * when ``secondary_rates`` is present it must contain all of
    ``SB, S, SH, ST, SA`` (8.5)

Every returned ``FieldError`` names the offending Tax_Field with a
human-readable message (8.6). Message generation is wrapped so that, if building
a message ever raises, a generic message is substituted but the submission is
still rejected (8.7) — validation never silently passes a bad value because the
explanation could not be produced.

Decimals are parsed via ``Decimal(str(value))`` to avoid binary-float drift,
consistent with the rest of the module. A value that cannot be parsed as a
number is itself a validation error for that field.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7**
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.modules.payroll_tax.schemas import SECONDARY_CODES, FieldError

__all__ = ["validate_config_fragment"]

#: Substituted when a human-readable message cannot be generated (Req 8.7).
_GENERIC_MESSAGE = "Invalid value."

#: Sentinel returned by :func:`_as_decimal` when a value cannot be parsed.
_UNPARSEABLE = object()


def _field_error(field: str, message_builder: Callable[[], str]) -> FieldError:
    """Build a :class:`FieldError`, never failing on message generation.

    ``message_builder`` is invoked to produce the human-readable message
    (Req 8.6). If it raises for any reason, a generic message is substituted so
    the submission is still rejected (Req 8.7) — the error is always produced.
    """
    try:
        message = message_builder()
    except Exception:  # noqa: BLE001 - any message failure must still reject
        message = _GENERIC_MESSAGE
    return FieldError(field=field, message=message)


def _as_decimal(value: Any) -> Decimal | object:
    """Parse ``value`` into an exact ``Decimal`` via ``Decimal(str(value))``.

    Returns the :data:`_UNPARSEABLE` sentinel when the value is ``None`` or
    cannot be parsed as a finite number, so callers can flag it as an error.
    """
    if value is None:
        return _UNPARSEABLE
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return _UNPARSEABLE
    if not parsed.is_finite():
        return _UNPARSEABLE
    return parsed


def _validate_bounded_rate(
    field: str,
    value: Any,
    low: Decimal,
    high: Decimal,
    *,
    label: str,
) -> list[FieldError]:
    """Validate that ``value`` parses and falls within ``[low, high]``."""
    parsed = _as_decimal(value)
    if parsed is _UNPARSEABLE:
        return [
            _field_error(
                field,
                lambda: f"{label} must be a number between {low} and {high}.",
            )
        ]
    if parsed < low or parsed > high:  # type: ignore[operator]
        return [
            _field_error(
                field,
                lambda: f"{label} must be between {low} and {high} (got {parsed}).",
            )
        ]
    return []


def _validate_brackets(value: Any) -> list[FieldError]:
    """Validate the PAYE_Bracket_Set (Req 7.1–7.5)."""
    field = "paye_brackets"
    errors: list[FieldError] = []

    if not isinstance(value, (list, tuple)):
        return [
            _field_error(field, lambda: "PAYE brackets must be a list of bands.")
        ]

    # Req 7.4: at least one band.
    if len(value) == 0:
        return [
            _field_error(
                field, lambda: "PAYE brackets must contain at least one band."
            )
        ]

    finite_limits: list[Decimal] = []
    open_ended_count = 0
    open_ended_indexes: list[int] = []

    for index, band in enumerate(value):
        if not isinstance(band, dict):
            errors.append(
                _field_error(
                    field,
                    lambda i=index: f"PAYE bracket #{i + 1} must be an object "
                    "with 'upper_limit' and 'rate'.",
                )
            )
            continue

        upper_limit = band.get("upper_limit")
        rate = band.get("rate")

        # Req 7.3: every rate in [0, 1].
        parsed_rate = _as_decimal(rate)
        if parsed_rate is _UNPARSEABLE:
            errors.append(
                _field_error(
                    field,
                    lambda i=index: f"PAYE bracket #{i + 1} rate must be a "
                    "number between 0 and 1.",
                )
            )
        elif parsed_rate < Decimal("0") or parsed_rate > Decimal("1"):  # type: ignore[operator]
            errors.append(
                _field_error(
                    field,
                    lambda i=index, r=parsed_rate: f"PAYE bracket #{i + 1} rate "
                    f"must be between 0 and 1 (got {r}).",
                )
            )

        # An absent/null upper_limit marks the open-ended top band.
        if upper_limit is None:
            open_ended_count += 1
            open_ended_indexes.append(index)
            continue

        parsed_limit = _as_decimal(upper_limit)
        if parsed_limit is _UNPARSEABLE:
            errors.append(
                _field_error(
                    field,
                    lambda i=index: f"PAYE bracket #{i + 1} upper limit must be "
                    "a number or null (open-ended).",
                )
            )
            continue

        # Req 7.5: every finite upper_limit > 0.
        if parsed_limit <= Decimal("0"):  # type: ignore[operator]
            errors.append(
                _field_error(
                    field,
                    lambda i=index, v=parsed_limit: f"PAYE bracket #{i + 1} "
                    f"upper limit must be greater than zero (got {v}).",
                )
            )
        finite_limits.append(parsed_limit)  # type: ignore[arg-type]

    # Req 7.2: exactly one open-ended top band, and it must be last.
    if open_ended_count != 1:
        errors.append(
            _field_error(
                field,
                lambda c=open_ended_count: "PAYE brackets must have exactly one "
                f"open-ended top band (found {c}).",
            )
        )
    elif open_ended_indexes[0] != len(value) - 1:
        errors.append(
            _field_error(
                field,
                lambda: "The open-ended top band must be the last PAYE bracket.",
            )
        )

    # Req 7.1: finite upper_limits strictly ascending.
    for prev, curr in zip(finite_limits, finite_limits[1:]):
        if curr <= prev:
            errors.append(
                _field_error(
                    field,
                    lambda p=prev, c=curr: "PAYE bracket upper limits must be "
                    f"strictly ascending (got {c} after {p}).",
                )
            )
            break

    return errors


def _validate_secondary(value: Any) -> list[FieldError]:
    """Validate the secondary tax-rate set (Req 8.1, 8.5)."""
    field = "secondary_rates"

    if not isinstance(value, dict):
        return [
            _field_error(
                field, lambda: "Secondary rates must be an object keyed by tax code."
            )
        ]

    errors: list[FieldError] = []

    # Req 8.5: must contain all of SB, S, SH, ST, SA.
    missing = [code for code in SECONDARY_CODES if code not in value]
    if missing:
        errors.append(
            _field_error(
                field,
                lambda m=missing: "Secondary rates must include all codes "
                f"{', '.join(SECONDARY_CODES)} (missing {', '.join(m)}).",
            )
        )

    # Req 8.1: each present secondary rate in [0, 1].
    for code in SECONDARY_CODES:
        if code in value:
            errors.extend(
                _validate_bounded_rate(
                    field,
                    value[code],
                    Decimal("0"),
                    Decimal("1"),
                    label=f"Secondary rate {code}",
                )
            )
    return errors


def _validate_ietc(value: Any) -> list[FieldError]:
    """Validate IETC parameters: abatement-rate bounds and ordering (Req 8.1, 8.4)."""
    field = "ietc"

    if not isinstance(value, dict):
        return [
            _field_error(field, lambda: "IETC parameters must be an object.")
        ]

    errors: list[FieldError] = []

    # Req 8.1: abatement rate in [0, 1].
    if "abatement_rate" in value:
        errors.extend(
            _validate_bounded_rate(
                field,
                value["abatement_rate"],
                Decimal("0"),
                Decimal("1"),
                label="IETC abatement rate",
            )
        )

    # Req 8.4: lower <= abatement_start <= upper (non-decreasing).
    lower = _as_decimal(value.get("lower"))
    abatement_start = _as_decimal(value.get("abatement_start"))
    upper = _as_decimal(value.get("upper"))

    ordering = [
        ("lower", lower),
        ("abatement_start", abatement_start),
        ("upper", upper),
    ]
    if any(parsed is _UNPARSEABLE for _, parsed in ordering):
        errors.append(
            _field_error(
                field,
                lambda: "IETC lower, abatement_start, and upper must all be "
                "numbers.",
            )
        )
    else:
        if not (lower <= abatement_start <= upper):  # type: ignore[operator]
            errors.append(
                _field_error(
                    field,
                    lambda lo=lower, ab=abatement_start, up=upper: "IETC bounds "
                    "must be non-decreasing: lower <= abatement_start <= upper "
                    f"(got {lo}, {ab}, {up}).",
                )
            )
    return errors


def validate_config_fragment(fragment: dict) -> list[FieldError]:
    """Validate any subset of tax fields present in ``fragment``.

    Pure function: only the Tax_Fields present in ``fragment`` are validated
    (a sparse org override validates only what it sets). Returns ``[]`` when the
    present fields are all valid, or a list of :class:`FieldError` naming each
    offending field with a human-readable message.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5,
    8.6, 8.7**
    """
    if not isinstance(fragment, dict):
        return [
            _field_error(
                "config", lambda: "Tax configuration must be an object."
            )
        ]

    errors: list[FieldError] = []

    if "paye_brackets" in fragment:
        errors.extend(_validate_brackets(fragment["paye_brackets"]))

    if "secondary_rates" in fragment:
        errors.extend(_validate_secondary(fragment["secondary_rates"]))

    # Fractional rates in [0, 1] (Req 8.1).
    for key, label in (
        ("acc_levy_rate", "ACC levy rate"),
        ("student_loan_rate", "Student loan rate"),
    ):
        if key in fragment:
            errors.extend(
                _validate_bounded_rate(
                    key, fragment[key], Decimal("0"), Decimal("1"), label=label
                )
            )

    # KiwiSaver default percent fields in [0, 100] (Req 8.1).
    for key, label in (
        ("default_kiwisaver_employee_rate", "Default KiwiSaver employee rate"),
        ("default_kiwisaver_employer_rate", "Default KiwiSaver employer rate"),
    ):
        if key in fragment:
            errors.extend(
                _validate_bounded_rate(
                    key, fragment[key], Decimal("0"), Decimal("100"), label=label
                )
            )

    # Req 8.2: ACC cap strictly greater than zero.
    if "acc_max_liable_earnings" in fragment:
        parsed = _as_decimal(fragment["acc_max_liable_earnings"])
        if parsed is _UNPARSEABLE:
            errors.append(
                _field_error(
                    "acc_max_liable_earnings",
                    lambda: "ACC maximum liable earnings must be a number "
                    "greater than zero.",
                )
            )
        elif parsed <= Decimal("0"):  # type: ignore[operator]
            errors.append(
                _field_error(
                    "acc_max_liable_earnings",
                    lambda v=parsed: "ACC maximum liable earnings must be "
                    f"greater than zero (got {v}).",
                )
            )

    # Req 8.3: student loan threshold >= 0.
    if "student_loan_threshold" in fragment:
        parsed = _as_decimal(fragment["student_loan_threshold"])
        if parsed is _UNPARSEABLE:
            errors.append(
                _field_error(
                    "student_loan_threshold",
                    lambda: "Student loan threshold must be a number greater "
                    "than or equal to zero.",
                )
            )
        elif parsed < Decimal("0"):  # type: ignore[operator]
            errors.append(
                _field_error(
                    "student_loan_threshold",
                    lambda v=parsed: "Student loan threshold must be greater "
                    f"than or equal to zero (got {v}).",
                )
            )

    if "ietc" in fragment:
        errors.extend(_validate_ietc(fragment["ietc"]))

    return errors

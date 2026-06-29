"""Property-based test for deterministic, date-independent resolution (task 4.4).

# Feature: payroll-tax-settings, Property 3: Resolution is deterministic and date-independent

Exercises ``resolve_tax_config(db, org_id)`` in
``app/modules/payroll_tax/resolution.py`` against the real dev Postgres
database, mirroring the DB-backed Hypothesis pattern used by the sibling
resolution property tests
(``tests/test_payroll_tax_resolution_precedence_property.py`` — Property 1, and
``tests/property/test_resolution_totality.py`` — Property 2): a fresh async
engine per example (asyncpg connections are bound to the loop ``asyncio.run``
creates), the singleton ``platform_tax_default`` row deleted then re-inserted
with a generated document, the org's ``org_tax_settings`` row inserted with a
generated sparse ``overrides`` document, ``app.current_org_id`` set for the
RLS-scoped org tier, and the whole transaction rolled back at the end so the
migration-seeded platform row is restored and nothing leaks between examples.

The property under test
------------------------
*For any* fixed stored configuration, resolving it repeatedly — and for *any*
pay-period dates — yields identical ``Resolved_Tax_Config`` results, and that
result is identical to an **independent reference** application of the
Resolution_Precedence to the same stored configuration.

Two distinct guarantees are asserted for each example:

* **Determinism (Req 11.4).** ``resolve_tax_config`` is called several times
  against the same fixed stored state and every result must be equal to the
  first (and equal to the independent reference computation). The reference is
  computed here, in the test, without calling the resolver — so agreement is
  meaningful rather than tautological.

* **Date-independence (Req 12.2).** ``resolve_tax_config`` takes **no**
  pay-period date parameter — its signature is ``(db, org_id)`` — so it
  *cannot* vary with the pay-period dates. We make that concrete by generating
  an arbitrary set of pay-period dates and resolving once "under" each one
  (the date is unused context): every result must still be identical, which
  demonstrates the configuration the engine receives is the current stored
  configuration regardless of the pay-period dates.

**Validates: Requirements 11.4, 12.2**
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings
from app.modules.payroll_tax.models import OrgTaxSettings, PlatformTaxDefault
from app.modules.payroll_tax.resolution import resolve_tax_config
from app.modules.payroll_tax.schemas import SECONDARY_CODES
from app.modules.timesheets.paye import (
    SAFETY_NET,
    IETCParams,
    PAYEBracket,
    ResolvedTaxConfig,
)


# ---------------------------------------------------------------------------
# Tax_Field keys storable in both tiers (``tax_year_label`` is platform-only —
# it lives in its own column, never the org overrides document — handled
# separately).
# ---------------------------------------------------------------------------

FIELDS: tuple[str, ...] = (
    "paye_brackets",
    "secondary_rates",
    "acc_levy_rate",
    "acc_max_liable_earnings",
    "student_loan_rate",
    "student_loan_threshold",
    "ietc",
    "default_kiwisaver_employee_rate",
    "default_kiwisaver_employer_rate",
)


# ---------------------------------------------------------------------------
# Value strategies — every numeric value is a STRING so it stores losslessly in
# JSONB and round-trips exactly (no binary-float drift), matching the sibling
# precedence test.
# ---------------------------------------------------------------------------


def _dec_str(lo: str, hi: str, places: int):
    return st.decimals(
        min_value=Decimal(lo),
        max_value=Decimal(hi),
        places=places,
        allow_nan=False,
        allow_infinity=False,
    ).map(str)


_rate_str = _dec_str("0", "1", 4)
_acc_cap_str = _dec_str("1", "500000", 2)
_sl_threshold_str = _dec_str("0", "100000", 2)
_ks_rate_str = _dec_str("0", "100", 2)
_amount_str = _dec_str("0", "2000", 2)
_bound_str = _dec_str("0", "100000", 2)

_secondary_strategy = st.fixed_dictionaries(
    {code: _rate_str for code in SECONDARY_CODES}
)

_ietc_strategy = st.fixed_dictionaries(
    {
        "amount": _amount_str,
        "lower": _bound_str,
        "abatement_start": _bound_str,
        "abatement_rate": _rate_str,
        "upper": _bound_str,
    }
)


@st.composite
def _brackets_strategy(draw):
    """Generate a non-empty bracket list ending in an open-ended top band.

    Resolution only coerces shape (validation is a separate layer), so values
    need only be parseable.
    """
    n_finite = draw(st.integers(min_value=0, max_value=4))
    finite = [
        {
            "upper_limit": draw(_dec_str("1", "300000", 2)),
            "rate": draw(_rate_str),
        }
        for _ in range(n_finite)
    ]
    top = {"upper_limit": None, "rate": draw(_rate_str)}
    return finite + [top]


_VALUE_STRATS: dict[str, st.SearchStrategy] = {
    "paye_brackets": _brackets_strategy(),
    "secondary_rates": _secondary_strategy,
    "acc_levy_rate": _rate_str,
    "acc_max_liable_earnings": _acc_cap_str,
    "student_loan_rate": _rate_str,
    "student_loan_threshold": _sl_threshold_str,
    "ietc": _ietc_strategy,
    "default_kiwisaver_employee_rate": _ks_rate_str,
    "default_kiwisaver_employer_rate": _ks_rate_str,
}

# A non-blank label so the resolver's _coerce_label accepts it.
_label_strategy = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())


@st.composite
def _scenario(draw):
    """Generate a fixed stored-state scenario.

    Independently decides whether each tier's row exists and, when it does,
    which Tax_Fields it carries.
    """
    platform_has_row = draw(st.booleans())
    org_has_row = draw(st.booleans())

    platform_fields: dict = {}
    platform_label: str | None = None
    if platform_has_row:
        for field in FIELDS:
            value = draw(st.one_of(st.none(), _VALUE_STRATS[field]))
            if value is not None:
                platform_fields[field] = value
        platform_label = draw(_label_strategy)

    org_fields: dict = {}
    if org_has_row:
        for field in FIELDS:
            value = draw(st.one_of(st.none(), _VALUE_STRATS[field]))
            if value is not None:
                org_fields[field] = value

    return {
        "platform_has_row": platform_has_row,
        "platform_fields": platform_fields,
        "platform_label": platform_label,
        "org_has_row": org_has_row,
        "org_fields": org_fields,
    }


# A set of arbitrary pay-period dates to resolve "under". The resolver ignores
# dates entirely, so these are unused context that must not change the result.
_pay_period_dates = st.lists(
    st.dates(
        min_value=_dt.date(2000, 1, 1),
        max_value=_dt.date(2100, 12, 31),
    ),
    min_size=1,
    max_size=4,
)


# ---------------------------------------------------------------------------
# Independent reference application of Resolution_Precedence.
#
# Computed here in the test (NOT by calling the resolver) so that agreement
# with resolve_tax_config is a meaningful check rather than a tautology.
# ---------------------------------------------------------------------------


def _ref_brackets(raw) -> tuple[PAYEBracket, ...]:
    return tuple(
        PAYEBracket(
            upper_limit=(
                None if b["upper_limit"] is None else Decimal(str(b["upper_limit"]))
            ),
            rate=Decimal(str(b["rate"])),
        )
        for b in raw
    )


def _ref_secondary(raw) -> dict[str, Decimal]:
    return {code: Decimal(str(raw[code])) for code in SECONDARY_CODES}


def _ref_ietc(raw) -> IETCParams:
    return IETCParams(
        amount=Decimal(str(raw["amount"])),
        lower=Decimal(str(raw["lower"])),
        abatement_start=Decimal(str(raw["abatement_start"])),
        abatement_rate=Decimal(str(raw["abatement_rate"])),
        upper=Decimal(str(raw["upper"])),
    )


_REF_COERCERS = {
    "paye_brackets": _ref_brackets,
    "secondary_rates": _ref_secondary,
    "acc_levy_rate": lambda raw: Decimal(str(raw)),
    "acc_max_liable_earnings": lambda raw: Decimal(str(raw)),
    "student_loan_rate": lambda raw: Decimal(str(raw)),
    "student_loan_threshold": lambda raw: Decimal(str(raw)),
    "ietc": _ref_ietc,
    "default_kiwisaver_employee_rate": lambda raw: Decimal(str(raw)),
    "default_kiwisaver_employer_rate": lambda raw: Decimal(str(raw)),
}


def _reference_config(scenario: dict) -> ResolvedTaxConfig:
    """Independently apply override → platform → Safety_Net for every field."""
    org_fields = scenario["org_fields"]
    platform_fields = scenario["platform_fields"]

    def field(key: str) -> Any:
        coerce = _REF_COERCERS[key]
        if key in org_fields:
            return coerce(org_fields[key])
        if key in platform_fields:
            return coerce(platform_fields[key])
        return getattr(SAFETY_NET, key)

    if scenario["platform_has_row"]:
        label = scenario["platform_label"].strip()
    else:
        label = SAFETY_NET.tax_year_label

    return ResolvedTaxConfig(
        paye_brackets=field("paye_brackets"),
        secondary_rates=field("secondary_rates"),
        acc_levy_rate=field("acc_levy_rate"),
        acc_max_liable_earnings=field("acc_max_liable_earnings"),
        student_loan_rate=field("student_loan_rate"),
        student_loan_threshold=field("student_loan_threshold"),
        ietc=field("ietc"),
        default_kiwisaver_employee_rate=field("default_kiwisaver_employee_rate"),
        default_kiwisaver_employer_rate=field("default_kiwisaver_employer_rate"),
        tax_year_label=label,
    )


# ---------------------------------------------------------------------------
# Engine / session helpers (mirror the sibling DB-backed property tests).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _run_example(scenario: dict, dates: list[_dt.date]) -> None:
    org_id = uuid.uuid4()
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # RLS scope for the org_tax_settings tier.
                await session.execute(
                    sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
                    {"oid": str(org_id)},
                )

                # --- Seed the singleton platform row (delete then re-insert);
                #     rolled back at the end, restoring the migration-seeded row.
                await session.execute(sa.delete(PlatformTaxDefault))
                if scenario["platform_has_row"]:
                    session.add(
                        PlatformTaxDefault(
                            config=scenario["platform_fields"],
                            tax_year_label=scenario["platform_label"],
                        )
                    )

                # --- Seed the org overrides row (sparse), if present.
                if scenario["org_has_row"]:
                    session.add(
                        OrgTaxSettings(
                            org_id=org_id,
                            overrides=scenario["org_fields"],
                        )
                    )

                await session.flush()

                # Independent reference application of the precedence.
                reference = _reference_config(scenario)

                # --- Determinism: resolve repeatedly against the fixed stored
                #     state; every result must equal the first and the
                #     independent reference. ---
                first = await resolve_tax_config(session, org_id)
                assert isinstance(first, ResolvedTaxConfig)
                assert first == reference, (
                    "resolved config differs from the independent reference "
                    "application of the Resolution_Precedence"
                )

                for _ in range(3):
                    again = await resolve_tax_config(session, org_id)
                    assert again == first, (
                        "repeated resolution of a fixed stored config produced "
                        "a different result (non-deterministic)"
                    )

                # --- Date-independence: resolve once "under" each generated
                #     pay-period date; the resolver takes no date parameter, so
                #     every result must remain identical regardless of date. ---
                for _ in dates:
                    under_date = await resolve_tax_config(session, org_id)
                    assert under_date == first, (
                        "resolution varied with pay-period date context; it "
                        "must be date-independent (effective-dating is out of "
                        "scope)"
                    )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3: Resolution is deterministic and date-independent.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(scenario=_scenario(), dates=_pay_period_dates)
def test_resolution_is_deterministic_and_date_independent(
    scenario: dict, dates: list[_dt.date]
):
    """Property 3: Resolution is deterministic and date-independent.

    # Feature: payroll-tax-settings, Property 3: Resolution is deterministic and date-independent

    For any fixed stored configuration, resolving it repeatedly — and for any
    pay-period dates — yields identical ``Resolved_Tax_Config`` results equal to
    an independent reference application of the Resolution_Precedence to the same
    stored configuration.

    **Validates: Requirements 11.4, 12.2**
    """
    asyncio.run(_run_example(scenario, dates))

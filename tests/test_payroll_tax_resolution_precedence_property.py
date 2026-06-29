"""Property-based test for Property 1: Field-wise resolution precedence.

# Feature: payroll-tax-settings, Property 1: Field-wise resolution precedence

Exercises ``app.modules.payroll_tax.resolution.resolve_tax_config`` (task 4.1)
against the real dev Postgres database, mirroring the DB-backed Hypothesis
pattern used by the pay-cycle resolution property tests
(``tests/test_pay_cycle_default_fallback_property.py`` and friends).

The property under test
------------------------
For any platform configuration, any sparse set of org overrides, and any
per-field choice of which tiers are present, the ``Resolved_Tax_Config`` value
for each Tax_Field equals:

    org override (when that field is overridden)
    else the platform default value (when the platform has it)
    else the Safety_Net value

— and is never zero or blank when a higher tier is absent. In particular, when
both an override and a platform value are absent for *every* field (and there is
no platform row at all), the resolved config equals :data:`SAFETY_NET`.

How each example is exercised
-----------------------------
Each Hypothesis example seeds, inside a single transaction that is rolled back at
the end:

* the singleton ``platform_tax_default`` row — deleted then re-inserted with a
  generated, possibly-partial ``config`` document (or omitted entirely to model
  "no platform row"); and
* the org's ``org_tax_settings`` row — inserted with a generated sparse
  ``overrides`` document (or omitted to model "org inherits everything").

The org tier is RLS-scoped, so ``app.current_org_id`` is set on the session
before seeding/reading the org row. ``resolve_tax_config`` is then driven against
that same session and the resolved value of every field is compared to an
independently-computed expectation. The transaction is always rolled back, so the
migration-seeded platform row is restored and no rows leak between examples.

A fresh async engine is created per example because asyncpg connections are bound
to the event loop ``asyncio.run`` creates — exactly like the reference DB-backed
property tests in this repo.

**Validates: Requirements 1.4, 2.5, 3.1, 3.3, 5.1, 5.2, 5.3, 11.2, 11.3**
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_pay_cycle_default_fallback_property.py).
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401
from app.modules.payroll_tax import models as _payroll_tax_models  # noqa: F401

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
# Tax_Field keys that are storable in both tiers (tax_year_label is platform-
# only — it lives in a column, never in the org overrides document — and is
# handled separately).
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
# Value strategies — every numeric value is generated as a STRING so it stores
# losslessly in JSONB and round-trips exactly through the resolver's
# ``Decimal(str(raw))`` coercion (no binary-float drift).
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

    Resolution does not validate the schedule (that is the validation layer's
    job, Property 10); it only coerces shape, so values need only be parseable.
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

# A non-blank label so the resolver's _coerce_label accepts it (a blank label
# would itself fall through to the safety-net, which is a different scenario).
_label_strategy = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())


@st.composite
def _scenario(draw):
    """Generate a full stored-state scenario.

    Independently decides whether each tier's row exists and, when it does,
    which Tax_Fields it carries (so every field's tier-presence is chosen
    independently).
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


# ---------------------------------------------------------------------------
# Independent expectation: coerce a stored raw JSON value into the engine value
# object, mirroring (independently of the resolver) what the resolved field
# should be when that tier wins.
# ---------------------------------------------------------------------------


def _expect_brackets(raw) -> tuple[PAYEBracket, ...]:
    return tuple(
        PAYEBracket(
            upper_limit=(
                None if b["upper_limit"] is None else Decimal(str(b["upper_limit"]))
            ),
            rate=Decimal(str(b["rate"])),
        )
        for b in raw
    )


def _expect_secondary(raw) -> dict[str, Decimal]:
    return {code: Decimal(str(raw[code])) for code in SECONDARY_CODES}


def _expect_ietc(raw) -> IETCParams:
    return IETCParams(
        amount=Decimal(str(raw["amount"])),
        lower=Decimal(str(raw["lower"])),
        abatement_start=Decimal(str(raw["abatement_start"])),
        abatement_rate=Decimal(str(raw["abatement_rate"])),
        upper=Decimal(str(raw["upper"])),
    )


_EXPECT_COERCERS = {
    "paye_brackets": _expect_brackets,
    "secondary_rates": _expect_secondary,
    "acc_levy_rate": lambda raw: Decimal(str(raw)),
    "acc_max_liable_earnings": lambda raw: Decimal(str(raw)),
    "student_loan_rate": lambda raw: Decimal(str(raw)),
    "student_loan_threshold": lambda raw: Decimal(str(raw)),
    "ietc": _expect_ietc,
    "default_kiwisaver_employee_rate": lambda raw: Decimal(str(raw)),
    "default_kiwisaver_employer_rate": lambda raw: Decimal(str(raw)),
}


def _expected_field(field: str, org_fields: dict, platform_fields: dict):
    """Return (expected_value, source) for one field by Resolution_Precedence."""
    coerce = _EXPECT_COERCERS[field]
    if field in org_fields:
        return coerce(org_fields[field]), "override"
    if field in platform_fields:
        return coerce(platform_fields[field]), "platform"
    return getattr(SAFETY_NET, field), "safety_net"


# ---------------------------------------------------------------------------
# Engine / session helpers (mirror the reference DB-backed property tests).
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


async def _run_example(scenario: dict) -> None:
    org_id = uuid.uuid4()
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # RLS scope for the org_tax_settings tier.
                await session.execute(
                    sa.text(
                        "SELECT set_config('app.current_org_id', :oid, true)"
                    ),
                    {"oid": str(org_id)},
                )

                # --- Seed the singleton platform row (delete then re-insert).
                #     Rolled back at the end, restoring the migration-seeded row.
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

                # --- Resolve and check field by field. ---
                resolved = await resolve_tax_config(session, org_id)
                assert isinstance(resolved, ResolvedTaxConfig)

                org_fields = scenario["org_fields"]
                platform_fields = scenario["platform_fields"]

                for field in FIELDS:
                    expected, source = _expected_field(
                        field, org_fields, platform_fields
                    )
                    actual = getattr(resolved, field)
                    assert actual == expected, (
                        f"field {field!r} resolved to {actual!r} but expected "
                        f"{expected!r} (source={source})"
                    )
                    # Never zero/blank when a higher tier is absent: the value
                    # is the populated Safety_Net constant in that case.
                    assert actual is not None, f"field {field!r} resolved to None"

                # --- tax_year_label: platform-only (never an org override). ---
                if scenario["platform_has_row"]:
                    expected_label = scenario["platform_label"].strip()
                else:
                    expected_label = SAFETY_NET.tax_year_label
                assert resolved.tax_year_label == expected_label
                assert resolved.tax_year_label, "tax_year_label resolved to blank"

                # --- When every tier is absent the whole config equals the
                #     Safety_Net (Req 11.2). ---
                no_overrides = (not scenario["org_has_row"]) or (not org_fields)
                if not scenario["platform_has_row"] and no_overrides:
                    assert resolved == SAFETY_NET, (
                        "with no platform row and no overrides the resolved "
                        "config must equal SAFETY_NET"
                    )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 1: Field-wise resolution precedence.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(scenario=_scenario())
def test_field_wise_resolution_precedence(scenario: dict):
    """Property 1: Field-wise resolution precedence.

    # Feature: payroll-tax-settings, Property 1: Field-wise resolution precedence

    For any platform configuration, any sparse override set, and any per-field
    choice of which tiers are present, each resolved Tax_Field equals the org
    override when present, else the platform default when present, else the
    Safety_Net — never zero or blank when a higher tier is absent. When no
    platform row and no overrides exist, the resolved config equals SAFETY_NET.

    **Validates: Requirements 1.4, 2.5, 3.1, 3.3, 5.1, 5.2, 5.3, 11.2, 11.3**
    """
    asyncio.run(_run_example(scenario))

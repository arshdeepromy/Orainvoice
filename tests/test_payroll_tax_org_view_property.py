"""Property-based test for Property 9: Org settings view reflects resolution
and inheritance status.

# Feature: payroll-tax-settings, Property 9: Org settings view reflects resolution and inheritance status

Exercises ``app.modules.payroll_tax.service.get_org_resolved_view`` (task 7.2)
against the real dev Postgres database, mirroring the DB-backed Hypothesis
pattern used by the resolution-precedence property test
(``tests/test_payroll_tax_resolution_precedence_property.py``): a fresh async
engine per example (asyncpg connections are bound to the event loop
``asyncio.run`` creates), ``app.current_org_id`` set for the RLS-scoped org
tier, the singleton ``platform_tax_default`` row deleted then re-inserted with a
generated document, the org's ``org_tax_settings`` row inserted with a generated
sparse ``overrides`` document, and the whole transaction rolled back at the end
so the migration-seeded platform row is restored and nothing leaks between
examples.

The property under test
------------------------
For any (valid) platform configuration and any valid sparse set of org
overrides, ``get_org_resolved_view`` must return an ``OrgTaxSettingsView`` such
that, for every Tax_Field:

1. the view's **effective value** equals the independently-resolved value
   (org override → platform default → Safety_Net), compared as
   ``Decimal(str(...))`` to avoid binary-float drift; and
2. the view's per-field ``field_status`` marks ``override=True`` (and
   ``inherited=False``) **exactly** for the fields present in the org
   ``overrides`` JSONB, and ``inherited=True`` (``override=False``) otherwise; and
3. ``tax_year_label`` is platform-only and is therefore **always** reported as
   inherited (never an override).

**Validates: Requirements 4.3, 9.4**
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
# property tests, e.g. tests/test_payroll_tax_resolution_precedence_property.py).
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
from app.modules.payroll_tax.schemas import SECONDARY_CODES
from app.modules.payroll_tax.service import (
    ORG_FIELD_KEYS,
    PLATFORM_FIELD_KEYS,
    get_org_resolved_view,
)
from app.modules.timesheets.paye import SAFETY_NET, IETCParams, PAYEBracket


# ---------------------------------------------------------------------------
# Tax_Field keys storable in both tiers (tax_year_label is platform-only — it
# lives in its own column, never in the org overrides document — and is handled
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
# Value strategies — every numeric value is generated as a STRING so it stores
# losslessly in JSONB and round-trips exactly through ``Decimal(str(raw))``
# coercion (no binary-float drift).
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
    """A non-empty bracket list ending in an open-ended top band.

    The view path coerces shape only (validation is a separate layer), so the
    values need only be parseable.
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

_label_strategy = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())


@st.composite
def _scenario(draw):
    """Generate a valid full platform config plus a valid sparse override set.

    The platform tier carries every Tax_Field (a complete, valid config). The
    org tier carries a sparse subset of overrides — each field is independently
    present or absent — and the org row itself may also be absent entirely (the
    org inherits everything).
    """
    platform_fields = {field: draw(_VALUE_STRATS[field]) for field in FIELDS}
    platform_label = draw(_label_strategy)

    org_has_row = draw(st.booleans())
    org_fields: dict = {}
    if org_has_row:
        for field in FIELDS:
            value = draw(st.one_of(st.none(), _VALUE_STRATS[field]))
            if value is not None:
                org_fields[field] = value

    return {
        "platform_fields": platform_fields,
        "platform_label": platform_label,
        "org_has_row": org_has_row,
        "org_fields": org_fields,
    }


# ---------------------------------------------------------------------------
# Independent expectation: coerce a stored raw JSON value into the engine value
# object, mirroring (independently of the service) what each resolved field's
# effective value should be when that tier wins.
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


def _expected_value(field: str, org_fields: dict, platform_fields: dict):
    """Independently resolve a field by precedence: override → platform → safety."""
    coerce = _EXPECT_COERCERS[field]
    if field in org_fields:
        return coerce(org_fields[field])
    if field in platform_fields:
        return coerce(platform_fields[field])
    return getattr(SAFETY_NET, field)


# ---------------------------------------------------------------------------
# View → comparable value projection (the view nests brackets/IETC/secondary in
# their schema shapes; project them back to the same Decimal forms the
# independent expectation produces).
# ---------------------------------------------------------------------------


def _view_brackets(view) -> tuple[PAYEBracket, ...]:
    return tuple(
        PAYEBracket(upper_limit=b.upper_limit, rate=b.rate)
        for b in view.paye_brackets
    )


def _view_secondary(view) -> dict[str, Decimal]:
    return {code: getattr(view.secondary_rates, code) for code in SECONDARY_CODES}


def _view_ietc(view) -> IETCParams:
    return IETCParams(
        amount=view.ietc.amount,
        lower=view.ietc.lower,
        abatement_start=view.ietc.abatement_start,
        abatement_rate=view.ietc.abatement_rate,
        upper=view.ietc.upper,
    )


def _view_value(field: str, view):
    if field == "paye_brackets":
        return _view_brackets(view)
    if field == "secondary_rates":
        return _view_secondary(view)
    if field == "ietc":
        return _view_ietc(view)
    return getattr(view, field)


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
                    sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
                    {"oid": str(org_id)},
                )

                # --- Seed the singleton platform row (delete then re-insert).
                #     Rolled back at the end, restoring the migration-seeded row.
                await session.execute(sa.delete(PlatformTaxDefault))
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

                # --- Build the org settings view and check it field by field.
                view = await get_org_resolved_view(session, org_id=org_id)

                org_fields = scenario["org_fields"]
                platform_fields = scenario["platform_fields"]

                for field in FIELDS:
                    # (1) Effective value equals the independently-resolved value.
                    expected = _expected_value(field, org_fields, platform_fields)
                    actual = _view_value(field, view)
                    assert actual == expected, (
                        f"field {field!r} view value {actual!r} != resolved "
                        f"{expected!r}"
                    )

                    # (2) inherited/override status reflects override presence.
                    status = view.field_status[field]
                    is_overridden = field in org_fields
                    assert status.override is is_overridden, (
                        f"field {field!r} override flag {status.override} but "
                        f"override-present={is_overridden}"
                    )
                    assert status.inherited is (not is_overridden), (
                        f"field {field!r} inherited flag {status.inherited} but "
                        f"override-present={is_overridden}"
                    )
                    assert status.source == (
                        "override" if is_overridden else "platform"
                    ), (
                        f"field {field!r} source {status.source!r} unexpected "
                        f"(override-present={is_overridden}, platform present)"
                    )

                # (3) tax_year_label is platform-only: always inherited, never an
                #     override; its effective value is the platform label.
                label_status = view.field_status["tax_year_label"]
                assert label_status.override is False
                assert label_status.inherited is True
                assert "tax_year_label" not in ORG_FIELD_KEYS
                assert view.tax_year_label == scenario["platform_label"].strip()

                # Sanity: field_status covers exactly the platform field set.
                assert set(view.field_status) == set(PLATFORM_FIELD_KEYS)
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 9: Org settings view reflects resolution and inheritance status.
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
def test_org_view_reflects_resolution_and_inheritance(scenario: dict):
    """Property 9: Org settings view reflects resolution and inheritance status.

    # Feature: payroll-tax-settings, Property 9: Org settings view reflects resolution and inheritance status

    For any valid platform configuration and any valid sparse override set, the
    ``OrgTaxSettingsView`` returned by ``get_org_resolved_view`` carries, for
    each Tax_Field, an effective value equal to the independently-resolved value
    (override → platform → Safety_Net) and a ``field_status`` that marks
    ``override`` exactly for the fields present in the org overrides JSONB and
    ``inherited`` otherwise. ``tax_year_label`` is platform-only and always
    reports as inherited.

    **Validates: Requirements 4.3, 9.4**
    """
    asyncio.run(_run_example(scenario))

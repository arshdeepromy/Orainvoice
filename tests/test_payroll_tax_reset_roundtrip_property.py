"""Property-based test for Property 8: Reset round-trip restores inheritance.

# Feature: payroll-tax-settings, Property 8: Reset round-trip restores inheritance

Exercises the org-tier persistence service in
``app/modules/payroll_tax/service.py`` (task 7.2) against the real dev Postgres
database, mirroring the DB-backed Hypothesis pattern used by the sibling
resolution property tests (``tests/test_payroll_tax_resolution_precedence_property.py``
and ``tests/property/test_resolution_totality.py``): a fresh async engine per
example (asyncpg connections are bound to the event loop ``asyncio.run`` creates),
``app.current_org_id`` set for the RLS-scoped org tier, and the whole transaction
rolled back at the end so the migration-seeded platform row is restored and
nothing leaks between examples.

The property under test
-----------------------
Starting from an organisation that has a generated, non-empty set of **valid**
overrides (persisted via ``set_org_overrides``):

* **Reset one field** (``reset_org_field``) removes that field's override so it
  resolves to the **platform default** and reports as **inherited**
  (``field_status[field].override is False`` / ``inherited is True``); every
  *other* overridden field is untouched (still an override, still its override
  value).
* **Reset all fields** (``reset_org_all``) removes every override so **every**
  Tax_Field resolves to the platform default and reports as inherited.

Values are compared as ``Decimal(str(...))`` so the JSON round-trip through JSONB
never introduces binary-float drift.

The platform tier is taken under full control per example: every
``platform_tax_default`` row (including the one seeded by migration 0231) is
deleted inside the rolled-back transaction and re-inserted with a generated full
configuration, so each reset field has a known platform default to resolve to.
The test DB connection (``postgres``) is a superuser and bypasses
``org_tax_settings`` RLS, so the org row written by the service is readable here;
``app.current_org_id`` is still set so the service's own scoped reads behave.

**Validates: Requirements 9.1, 9.2, 9.4**
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

from app.modules.payroll_tax.models import PlatformTaxDefault
from app.modules.payroll_tax.service import (
    get_org_resolved_view,
    reset_org_all,
    reset_org_field,
    set_org_overrides,
)
from app.modules.payroll_tax.schemas import SECONDARY_CODES


# ---------------------------------------------------------------------------
# Org-overridable Tax_Field keys (tax_year_label is platform-only — never an
# org override — so it is excluded here).
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

_IETC_KEYS: tuple[str, ...] = (
    "amount",
    "lower",
    "abatement_start",
    "abatement_rate",
    "upper",
)


# ---------------------------------------------------------------------------
# Value strategies — every numeric value is generated as a STRING so it stores
# losslessly in JSONB and round-trips exactly through ``Decimal(str(raw))``. All
# generated fragments are deliberately VALID so ``set_org_overrides`` (which
# validates before persisting) accepts them.
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
_acc_cap_str = _dec_str("1", "500000", 2)  # > 0 (Req 8.2)
_sl_threshold_str = _dec_str("0", "100000", 2)  # >= 0 (Req 8.3)
_ks_rate_str = _dec_str("0", "100", 2)
_amount_str = _dec_str("0", "2000", 2)

_secondary_strategy = st.fixed_dictionaries(
    {code: _rate_str for code in SECONDARY_CODES}
)


@st.composite
def _valid_ietc(draw):
    """IETC params with lower <= abatement_start <= upper (Req 8.4)."""
    bounds = sorted(draw(st.lists(st.integers(0, 100000), min_size=3, max_size=3)))
    lower, abatement_start, upper = bounds
    return {
        "amount": draw(_amount_str),
        "lower": str(lower),
        "abatement_start": str(abatement_start),
        "abatement_rate": draw(_rate_str),
        "upper": str(upper),
    }


@st.composite
def _valid_brackets(draw):
    """A valid PAYE bracket set: strictly ascending finite limits (> 0) plus a
    single open-ended top band, every rate in [0, 1] (Req 7.1-7.5)."""
    n_finite = draw(st.integers(min_value=0, max_value=3))
    limits = sorted(
        draw(
            st.lists(
                st.integers(min_value=1, max_value=300000),
                min_size=n_finite,
                max_size=n_finite,
                unique=True,
            )
        )
    )
    finite = [{"upper_limit": str(limit), "rate": draw(_rate_str)} for limit in limits]
    top = {"upper_limit": None, "rate": draw(_rate_str)}
    return finite + [top]


_VALID_STRATS: dict[str, st.SearchStrategy] = {
    "paye_brackets": _valid_brackets(),
    "secondary_rates": _secondary_strategy,
    "acc_levy_rate": _rate_str,
    "acc_max_liable_earnings": _acc_cap_str,
    "student_loan_rate": _rate_str,
    "student_loan_threshold": _sl_threshold_str,
    "ietc": _valid_ietc(),
    "default_kiwisaver_employee_rate": _ks_rate_str,
    "default_kiwisaver_employer_rate": _ks_rate_str,
}

# A non-blank label so the resolver accepts the platform tier's label.
_label_strategy = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())


@st.composite
def _scenario(draw):
    """Generate a full platform config + a non-empty sparse, valid override set.

    Also chooses which single field the per-field reset will target (one of the
    overridden fields).
    """
    platform_fields = {field: draw(_VALID_STRATS[field]) for field in FIELDS}
    platform_label = draw(_label_strategy)

    override_keys = draw(
        st.lists(st.sampled_from(FIELDS), min_size=1, unique=True)
    )
    override_fields = {key: draw(_VALID_STRATS[key]) for key in override_keys}

    reset_field = draw(st.sampled_from(sorted(override_keys)))

    return {
        "platform_fields": platform_fields,
        "platform_label": platform_label,
        "override_fields": override_fields,
        "reset_field": reset_field,
    }


# ---------------------------------------------------------------------------
# Normalisers — collapse both stored-raw values (strings/None/dicts) and the
# view's Pydantic attributes into a canonical Decimal structure for comparison.
# ---------------------------------------------------------------------------


def _norm_raw(field: str, raw):
    if field == "paye_brackets":
        return tuple(
            (
                None if b["upper_limit"] is None else Decimal(str(b["upper_limit"])),
                Decimal(str(b["rate"])),
            )
            for b in raw
        )
    if field == "secondary_rates":
        return {code: Decimal(str(raw[code])) for code in SECONDARY_CODES}
    if field == "ietc":
        return {key: Decimal(str(raw[key])) for key in _IETC_KEYS}
    return Decimal(str(raw))


def _norm_view(field: str, view):
    if field == "paye_brackets":
        return tuple(
            (
                None if b.upper_limit is None else Decimal(str(b.upper_limit)),
                Decimal(str(b.rate)),
            )
            for b in view.paye_brackets
        )
    if field == "secondary_rates":
        secondary = view.secondary_rates
        return {
            code: Decimal(str(getattr(secondary, code))) for code in SECONDARY_CODES
        }
    if field == "ietc":
        ietc = view.ietc
        return {key: Decimal(str(getattr(ietc, key))) for key in _IETC_KEYS}
    return Decimal(str(getattr(view, field)))


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
    user_id = uuid.uuid4()
    platform_fields = scenario["platform_fields"]
    override_fields = scenario["override_fields"]
    reset_field = scenario["reset_field"]

    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # RLS scope for the org_tax_settings tier.
                await session.execute(
                    sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
                    {"oid": str(org_id)},
                )

                # --- Take control of the singleton platform row: delete the
                #     migration-seeded row and insert a known full config so each
                #     reset field has a definite platform default to resolve to.
                await session.execute(sa.delete(PlatformTaxDefault))
                session.add(
                    PlatformTaxDefault(
                        config=platform_fields,
                        tax_year_label=scenario["platform_label"],
                        is_singleton=True,
                    )
                )
                await session.flush()

                # --- Apply the org's (valid) overrides via the service. ---
                await set_org_overrides(
                    session,
                    org_id=org_id,
                    fields=override_fields,
                    user_id=user_id,
                    request=None,
                )

                # Sanity: every overridden field reports as an override and holds
                # the submitted override value before any reset.
                view = await get_org_resolved_view(session, org_id=org_id)
                for field in override_fields:
                    assert view.field_status[field].override is True
                    assert view.field_status[field].inherited is False
                    assert _norm_view(field, view) == _norm_raw(
                        field, override_fields[field]
                    ), f"override {field!r} did not round-trip before reset"

                # ----- Reset ONE field -> inherits platform default. -----
                await reset_org_field(
                    session,
                    org_id=org_id,
                    field=reset_field,
                    user_id=user_id,
                    request=None,
                )
                view = await get_org_resolved_view(session, org_id=org_id)

                # The reset field now inherits and resolves to the platform default.
                assert view.field_status[reset_field].override is False, (
                    f"reset field {reset_field!r} still reports as an override"
                )
                assert view.field_status[reset_field].inherited is True, (
                    f"reset field {reset_field!r} does not report as inherited"
                )
                assert _norm_view(reset_field, view) == _norm_raw(
                    reset_field, platform_fields[reset_field]
                ), (
                    f"reset field {reset_field!r} did not resolve to the platform "
                    "default"
                )

                # Every OTHER overridden field is untouched (still an override,
                # still holding its override value).
                for field in override_fields:
                    if field == reset_field:
                        continue
                    assert view.field_status[field].override is True, (
                        f"unrelated override {field!r} was cleared by resetting "
                        f"{reset_field!r}"
                    )
                    assert _norm_view(field, view) == _norm_raw(
                        field, override_fields[field]
                    ), (
                        f"unrelated override {field!r} changed value when "
                        f"resetting {reset_field!r}"
                    )

                # ----- Reset ALL fields -> every field inherits the platform
                #       default. -----
                await reset_org_all(
                    session, org_id=org_id, user_id=user_id, request=None
                )
                view = await get_org_resolved_view(session, org_id=org_id)

                for field in FIELDS:
                    assert view.field_status[field].override is False, (
                        f"field {field!r} still reports as an override after "
                        "reset-all"
                    )
                    assert view.field_status[field].inherited is True, (
                        f"field {field!r} does not report as inherited after "
                        "reset-all"
                    )
                    assert _norm_view(field, view) == _norm_raw(
                        field, platform_fields[field]
                    ), (
                        f"field {field!r} did not resolve to the platform default "
                        "after reset-all"
                    )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 8: Reset round-trip restores inheritance.
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
def test_reset_round_trip_restores_inheritance(scenario: dict):
    """Property 8: Reset round-trip restores inheritance.

    # Feature: payroll-tax-settings, Property 8: Reset round-trip restores inheritance

    For an org with a non-empty set of valid overrides, resetting one field
    removes that override so the field resolves to the platform default and
    reports as inherited (other overrides untouched); resetting all removes every
    override so every Tax_Field resolves to the platform default and reports as
    inherited.

    **Validates: Requirements 9.1, 9.2, 9.4**
    """
    asyncio.run(_run_example(scenario))

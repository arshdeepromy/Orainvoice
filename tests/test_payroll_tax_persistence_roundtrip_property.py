"""Property-based test for Property 4: Persistence round-trip (spec task 7.3).

# Feature: payroll-tax-settings, Property 4: Persistence round-trip

Exercises the persistence/audit **service** layer
(``app.modules.payroll_tax.service``) against the real dev Postgres database,
mirroring the DB-backed Hypothesis pattern used by the resolution property tests
(``tests/property/test_resolution_totality.py`` and
``tests/test_payroll_tax_resolution_precedence_property.py``): a fresh async
engine per example (asyncpg connections are bound to the event loop
``asyncio.run`` creates), everything done inside a single transaction that is
**rolled back** at the end so nothing persists. The services use ``flush`` (never
``commit``), so the trailing ``rollback`` discards every write — including the
seeded platform row, which is restored.

The property under test
-----------------------
For any **valid** full platform configuration submitted via
``update_platform_default``, and any **valid** sparse override set submitted via
``set_org_overrides``, reading the configuration back returns values equal to
what was submitted:

* **Platform round-trip (Req 2.2).** After saving the platform document, an org
  with no overrides resolves (via ``resolve_tax_config``) every Tax_Field to the
  submitted platform value (and the platform-only ``tax_year_label``).
* **Org round-trip (Req 3.2).** After saving a sparse override set, the org
  settings view (``get_org_resolved_view``) reports each overridden field's
  effective value equal to the submitted override (marked as an override) and
  every non-overridden field equal to the platform value (marked inherited).

How each example is exercised
-----------------------------
Inside one rolled-back transaction:

1. Set ``app.current_org_id`` so the RLS-scoped ``org_tax_settings`` writes/reads
   are permitted for the generated org.
2. Delete the migration-seeded ``platform_tax_default`` row so the example fully
   controls the platform tier, then submit a generated valid full platform
   document via ``update_platform_default``.
3. Resolve for an org with no overrides and assert the platform round-trip.
4. Submit a generated valid sparse override set via ``set_org_overrides`` and
   assert the org-view round-trip.

Every generated numeric value is produced as a **string** so it stores
losslessly in JSONB and round-trips exactly through the service/resolution
``Decimal(str(...))`` coercion (no binary-float drift). All generated fragments
satisfy ``validate_config_fragment`` (ascending finite bracket limits + a single
open-ended top band last, rates in ``[0, 1]``, KiwiSaver percents in
``[0, 100]``, ACC cap > 0, SL threshold >= 0, non-decreasing IETC bounds, and a
complete secondary-code map), so no submission is rejected.

**Validates: Requirements 2.2, 3.2**
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
from app.modules.payroll_tax.resolution import resolve_tax_config
from app.modules.payroll_tax.schemas import SECONDARY_CODES, OrgTaxSettingsView
from app.modules.payroll_tax.service import (
    get_org_resolved_view,
    set_org_overrides,
    update_platform_default,
)
from app.modules.timesheets.paye import ResolvedTaxConfig


# ---------------------------------------------------------------------------
# Tax_Field keys an organisation may override (tax_year_label is platform-only).
# ---------------------------------------------------------------------------

ORG_FIELDS: tuple[str, ...] = (
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
# losslessly in JSONB and round-trips exactly through ``Decimal(str(raw))``.
# Every generated fragment is VALID per ``validate_config_fragment``.
# ---------------------------------------------------------------------------


def _dec_str(lo: str, hi: str, places: int):
    return st.decimals(
        min_value=Decimal(lo),
        max_value=Decimal(hi),
        places=places,
        allow_nan=False,
        allow_infinity=False,
    ).map(str)


_rate_str = _dec_str("0", "1", 4)  # fractional rate in [0, 1]
_acc_cap_str = _dec_str("1", "500000", 2)  # ACC cap > 0
_sl_threshold_str = _dec_str("0", "100000", 2)  # SL threshold >= 0
_ks_rate_str = _dec_str("0", "100", 2)  # KiwiSaver percent in [0, 100]
_amount_str = _dec_str("0", "2000", 2)  # IETC credit amount

# A non-blank label with no surrounding whitespace, so resolution (which strips)
# round-trips it identically.
_label_strategy = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip() == s and s != "")


@st.composite
def _brackets_strategy(draw):
    """A valid PAYE bracket set: strictly-ascending finite limits + open top band.

    Finite ``upper_limit`` values are distinct positive integers sorted
    ascending (Req 7.1, 7.5); the schedule always ends with a single open-ended
    top band (``upper_limit = None``) last (Req 7.2); every ``rate`` is in
    ``[0, 1]`` (Req 7.3).
    """
    n_finite = draw(st.integers(min_value=0, max_value=4))
    finite_limits = sorted(
        draw(
            st.lists(
                st.integers(min_value=1, max_value=300000),
                min_size=n_finite,
                max_size=n_finite,
                unique=True,
            )
        )
    )
    brackets = [
        {"upper_limit": str(limit), "rate": draw(_rate_str)}
        for limit in finite_limits
    ]
    brackets.append({"upper_limit": None, "rate": draw(_rate_str)})
    return brackets


_secondary_strategy = st.fixed_dictionaries(
    {code: _rate_str for code in SECONDARY_CODES}
)


@st.composite
def _ietc_strategy(draw):
    """Valid IETC params: lower <= abatement_start <= upper (Req 8.4)."""
    bounds = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=100000),
                min_size=3,
                max_size=3,
            )
        )
    )
    return {
        "amount": draw(_amount_str),
        "lower": str(bounds[0]),
        "abatement_start": str(bounds[1]),
        "abatement_rate": draw(_rate_str),
        "upper": str(bounds[2]),
    }


#: Strategy for each overridable Tax_Field's value.
_FIELD_STRATS: dict[str, st.SearchStrategy] = {
    "paye_brackets": _brackets_strategy(),
    "secondary_rates": _secondary_strategy,
    "acc_levy_rate": _rate_str,
    "acc_max_liable_earnings": _acc_cap_str,
    "student_loan_rate": _rate_str,
    "student_loan_threshold": _sl_threshold_str,
    "ietc": _ietc_strategy(),
    "default_kiwisaver_employee_rate": _ks_rate_str,
    "default_kiwisaver_employer_rate": _ks_rate_str,
}


@st.composite
def _platform_config(draw):
    """A full, valid platform document (every field present, plus the label)."""
    config = {field: draw(_FIELD_STRATS[field]) for field in ORG_FIELDS}
    config["tax_year_label"] = draw(_label_strategy)
    return config


@st.composite
def _org_overrides(draw):
    """A valid sparse override set: each field independently present/absent."""
    overrides: dict = {}
    for field in ORG_FIELDS:
        if draw(st.booleans()):
            overrides[field] = draw(_FIELD_STRATS[field])
    return overrides


# ---------------------------------------------------------------------------
# Independent coercion of a stored raw value into the comparable form
# (Decimal(str(...)) everywhere) so round-trip equality is exact.
# ---------------------------------------------------------------------------


def _coerce_expected(field: str, raw):
    if field == "paye_brackets":
        return [
            (
                None if b["upper_limit"] is None else Decimal(str(b["upper_limit"])),
                Decimal(str(b["rate"])),
            )
            for b in raw
        ]
    if field == "secondary_rates":
        return {code: Decimal(str(raw[code])) for code in SECONDARY_CODES}
    if field == "ietc":
        return {key: Decimal(str(raw[key])) for key in _IETC_KEYS}
    return Decimal(str(raw))


def _resolved_value(resolved: ResolvedTaxConfig, field: str):
    if field == "paye_brackets":
        return [(b.upper_limit, b.rate) for b in resolved.paye_brackets]
    if field == "secondary_rates":
        return {code: resolved.secondary_rates[code] for code in SECONDARY_CODES}
    if field == "ietc":
        return {key: getattr(resolved.ietc, key) for key in _IETC_KEYS}
    return getattr(resolved, field)


def _view_value(view: OrgTaxSettingsView, field: str):
    if field == "paye_brackets":
        return [(b.upper_limit, b.rate) for b in view.paye_brackets]
    if field == "secondary_rates":
        return {code: getattr(view.secondary_rates, code) for code in SECONDARY_CODES}
    if field == "ietc":
        return {key: getattr(view.ietc, key) for key in _IETC_KEYS}
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


async def _run_example(platform_config: dict, org_overrides: dict) -> None:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # RLS scope for org_tax_settings writes/reads.
                await session.execute(
                    sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
                    {"oid": str(org_id)},
                )

                # Take full control of the platform tier: drop the seeded row so
                # update_platform_default creates the singleton from scratch.
                await session.execute(sa.delete(PlatformTaxDefault))
                await session.flush()

                # --- Submit the full platform document. ---
                await update_platform_default(
                    session, fields=platform_config, user_id=user_id, request=None
                )

                # --- Platform round-trip (Req 2.2): an org with NO overrides
                #     resolves every field to the submitted platform value. ---
                resolved = await resolve_tax_config(session, org_id)
                assert isinstance(resolved, ResolvedTaxConfig)
                for field in ORG_FIELDS:
                    expected = _coerce_expected(field, platform_config[field])
                    actual = _resolved_value(resolved, field)
                    assert actual == expected, (
                        f"platform round-trip: field {field!r} resolved to "
                        f"{actual!r}, expected {expected!r}"
                    )
                assert resolved.tax_year_label == platform_config["tax_year_label"]

                # --- Submit the sparse override set. ---
                await set_org_overrides(
                    session,
                    org_id=org_id,
                    fields=org_overrides,
                    user_id=user_id,
                    request=None,
                )

                # --- Org round-trip (Req 3.2): the view's effective value equals
                #     the submitted override where overridden, else the platform
                #     value; the inherited/override flag matches. ---
                view = await get_org_resolved_view(session, org_id=org_id)
                assert isinstance(view, OrgTaxSettingsView)
                for field in ORG_FIELDS:
                    if field in org_overrides:
                        expected = _coerce_expected(field, org_overrides[field])
                        status = view.field_status[field]
                        assert status.override is True and status.inherited is False, (
                            f"field {field!r} should report as an override"
                        )
                    else:
                        expected = _coerce_expected(field, platform_config[field])
                        status = view.field_status[field]
                        assert status.override is False and status.inherited is True, (
                            f"field {field!r} should report as inherited"
                        )
                    actual = _view_value(view, field)
                    assert actual == expected, (
                        f"org round-trip: field {field!r} read back as {actual!r}, "
                        f"expected {expected!r}"
                    )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 4: Persistence round-trip.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(platform_config=_platform_config(), org_overrides=_org_overrides())
def test_persistence_round_trip(platform_config: dict, org_overrides: dict):
    """Property 4: Persistence round-trip.

    # Feature: payroll-tax-settings, Property 4: Persistence round-trip

    For any valid full platform configuration submitted via
    ``update_platform_default`` and any valid sparse override set submitted via
    ``set_org_overrides``, reading the configuration back (via
    ``resolve_tax_config`` for the platform tier and ``get_org_resolved_view``
    for the org tier) returns values equal to what was submitted.

    **Validates: Requirements 2.2, 3.2**
    """
    asyncio.run(_run_example(platform_config, org_overrides))

"""Property-based test for Property 7: every successful change is audited.

# Feature: payroll-tax-settings, Property 7: Every successful change is audited with prior and new values

Exercises the persistence + audit service in
``app/modules/payroll_tax/service.py`` (tasks 7.1, 7.2) against the real dev
Postgres database, mirroring the DB-backed Hypothesis pattern used by the
resolution property tests (``tests/test_payroll_tax_resolution_precedence_property.py``
and ``tests/property/test_resolution_totality.py``): a fresh async engine per
example via ``asyncio.run``, ``app.current_org_id`` set for RLS, everything done
inside a single transaction that is rolled back at the end. The services
``flush`` (never ``commit``), and ``write_audit_log`` INSERTs the audit row into
the same transaction, so the ``audit_log`` row is queried back within that
transaction before the rollback discards the whole example.

The property under test
------------------------
For any successful

* **platform save** (``update_platform_default``),
* **org override save** (``set_org_overrides``),
* **org field reset** (``reset_org_field``), or
* **org reset-all** (``reset_org_all``)

an ``audit_log`` row is recorded that identifies the acting user, the
organisation (``org_id`` for org actions; ``NULL`` for the platform action), the
changed Tax_Field(s), the prior value(s), and the new value(s). A reset records
the prior override value(s) and that the field(s) now inherit (the
``inherited_fields`` marker with an empty/cleared ``fields`` after-state).

**Validates: Requirements 2.4, 9.3, 10.1, 10.2**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``.
- Generated values are valid (they must pass ``validate_config_fragment`` so the
  service persists and audits rather than raising ``HTTPException(422)``), and
  numeric values are generated as strings so they round-trip losslessly through
  JSONB and the service's ``Decimal(str(...))`` handling.
"""

from __future__ import annotations

import asyncio
import json
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
# property tests in this repo).
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
    reset_org_all,
    reset_org_field,
    set_org_overrides,
    update_platform_default,
)


# ---------------------------------------------------------------------------
# Shared JSON normalisation — must match service._jsonify so the comparison is
# made on identical representations (numeric/string forms, nested structures).
# ---------------------------------------------------------------------------


def _jsonify(value):
    return json.loads(json.dumps(value, default=str))


def _as_obj(value):
    """Coerce a JSONB column value (returned as a str by asyncpg) to Python."""
    if isinstance(value, str):
        return json.loads(value)
    return value


# ---------------------------------------------------------------------------
# Valid value strategies (every numeric value is generated as a STRING so it
# round-trips losslessly through JSONB / Decimal(str(...))). All fragments must
# pass ``validate_config_fragment`` so the service persists and audits.
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
_ks_rate_str = _dec_str("0", "100", 2)
_acc_cap_str = _dec_str("1", "500000", 2)
_sl_threshold_str = _dec_str("0", "100000", 2)


@st.composite
def _valid_brackets(draw):
    """A valid bracket set: strictly-ascending finite limits + open-ended top."""
    n_finite = draw(st.integers(min_value=0, max_value=4))
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
    finite.append({"upper_limit": None, "rate": draw(_rate_str)})
    return finite


@st.composite
def _valid_ietc(draw):
    """Valid IETC params: lower <= abatement_start <= upper, rate in [0, 1]."""
    lower = draw(st.integers(min_value=0, max_value=100000))
    abatement_start = draw(st.integers(min_value=lower, max_value=100000))
    upper = draw(st.integers(min_value=abatement_start, max_value=100000))
    return {
        "amount": draw(_dec_str("0", "2000", 2)),
        "lower": str(lower),
        "abatement_start": str(abatement_start),
        "abatement_rate": draw(_rate_str),
        "upper": str(upper),
    }


_valid_secondary = st.fixed_dictionaries({code: _rate_str for code in SECONDARY_CODES})

_label_strategy = st.text(
    min_size=1,
    max_size=12,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())


#: Valid-value strategy for every overridable Tax_Field.
_VALUE_STRATS: dict[str, st.SearchStrategy] = {
    "paye_brackets": _valid_brackets(),
    "secondary_rates": _valid_secondary,
    "acc_levy_rate": _rate_str,
    "acc_max_liable_earnings": _acc_cap_str,
    "student_loan_rate": _rate_str,
    "student_loan_threshold": _sl_threshold_str,
    "ietc": _valid_ietc(),
    "default_kiwisaver_employee_rate": _ks_rate_str,
    "default_kiwisaver_employer_rate": _ks_rate_str,
}

#: Every field a platform document may carry (org fields + the platform-only
#: display label).
PLATFORM_FIELD_KEYS_ALL: tuple[str, ...] = ORG_FIELD_KEYS + ("tax_year_label",)

#: A fixed, valid baseline platform document used as the "prior" state for the
#: platform-update scenario so the per-field diff is exactly the mutated keys.
BASE_CONFIG_FULL: dict[str, object] = {
    "paye_brackets": [
        {"upper_limit": "15600", "rate": "0.105"},
        {"upper_limit": "53500", "rate": "0.175"},
        {"upper_limit": "78100", "rate": "0.30"},
        {"upper_limit": "180000", "rate": "0.33"},
        {"upper_limit": None, "rate": "0.39"},
    ],
    "secondary_rates": {"SB": "0.105", "S": "0.175", "SH": "0.30", "ST": "0.33", "SA": "0.39"},
    "acc_levy_rate": "0.016",
    "acc_max_liable_earnings": "142283",
    "student_loan_rate": "0.12",
    "student_loan_threshold": "24128",
    "ietc": {
        "amount": "520",
        "lower": "24000",
        "abatement_start": "44000",
        "abatement_rate": "0.13",
        "upper": "48000",
    },
    "default_kiwisaver_employee_rate": "3.00",
    "default_kiwisaver_employer_rate": "3.00",
    "tax_year_label": "2024/25",
}


def _diff_value_strategy(field: str) -> st.SearchStrategy:
    """A valid value for ``field`` guaranteed to differ from the baseline."""
    if field == "tax_year_label":
        base = _jsonify(BASE_CONFIG_FULL[field])
        return _label_strategy.filter(lambda v: _jsonify(v) != base)
    base = _jsonify(BASE_CONFIG_FULL[field])
    return _VALUE_STRATS[field].filter(lambda v: _jsonify(v) != base)


# ---------------------------------------------------------------------------
# Scenario strategies — one per audited action.
# ---------------------------------------------------------------------------


@st.composite
def _platform_update_scenario(draw):
    keys = draw(
        st.lists(
            st.sampled_from(PLATFORM_FIELD_KEYS_ALL),
            min_size=1,
            max_size=len(PLATFORM_FIELD_KEYS_ALL),
            unique=True,
        )
    )
    mutations = {key: draw(_diff_value_strategy(key)) for key in keys}
    submitted = {**BASE_CONFIG_FULL, **mutations}
    return {
        "kind": "platform_update",
        "submitted": submitted,
        "changed": set(keys),
    }


@st.composite
def _org_update_scenario(draw):
    keys = draw(
        st.lists(
            st.sampled_from(ORG_FIELD_KEYS),
            min_size=1,
            max_size=len(ORG_FIELD_KEYS),
            unique=True,
        )
    )
    overrides = {key: draw(_VALUE_STRATS[key]) for key in keys}
    return {
        "kind": "org_update",
        "overrides": overrides,
        "changed": set(keys),
    }


@st.composite
def _reset_field_scenario(draw):
    field = draw(st.sampled_from(ORG_FIELD_KEYS))
    extra_keys = draw(
        st.lists(
            st.sampled_from([k for k in ORG_FIELD_KEYS if k != field]),
            unique=True,
        )
    )
    seeded = {key: draw(_VALUE_STRATS[key]) for key in [field, *extra_keys]}
    return {"kind": "reset_field", "field": field, "seeded": seeded}


@st.composite
def _reset_all_scenario(draw):
    keys = draw(
        st.lists(
            st.sampled_from(ORG_FIELD_KEYS),
            min_size=1,
            max_size=len(ORG_FIELD_KEYS),
            unique=True,
        )
    )
    seeded = {key: draw(_VALUE_STRATS[key]) for key in keys}
    return {"kind": "reset_all", "seeded": seeded}


def _any_scenario():
    return st.one_of(
        _platform_update_scenario(),
        _org_update_scenario(),
        _reset_field_scenario(),
        _reset_all_scenario(),
    )


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
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


async def _fetch_audit_row(session: AsyncSession, action: str) -> dict:
    """Return the single audit_log row for ``action`` within this transaction."""
    row = (
        await session.execute(
            sa.text(
                """
                SELECT user_id, org_id, entity_type, before_value, after_value
                FROM audit_log
                WHERE action = :action
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"action": action},
        )
    ).mappings().first()
    assert row is not None, f"no audit_log row recorded for action {action!r}"
    return {
        "user_id": row["user_id"],
        "org_id": row["org_id"],
        "entity_type": row["entity_type"],
        "before_value": _as_obj(row["before_value"]),
        "after_value": _as_obj(row["after_value"]),
    }


# ---------------------------------------------------------------------------
# Per-scenario drivers.
# ---------------------------------------------------------------------------


async def _check_platform_update(session, scenario, user_id):
    # Take control of the singleton platform tier: replace the migration-seeded
    # row with our known baseline so the diff is exactly the mutated keys.
    await session.execute(sa.delete(PlatformTaxDefault))
    session.add(
        PlatformTaxDefault(
            is_singleton=True,
            config={k: BASE_CONFIG_FULL[k] for k in ORG_FIELD_KEYS},
            tax_year_label=BASE_CONFIG_FULL["tax_year_label"],
        )
    )
    await session.flush()

    await update_platform_default(
        session, fields=scenario["submitted"], user_id=user_id, request=None
    )

    audit = await _fetch_audit_row(session, "payroll_tax.platform.update")
    changed = scenario["changed"]

    # Acting user recorded; platform action is non-org-scoped (org_id NULL).
    assert str(audit["user_id"]) == str(user_id)
    assert audit["org_id"] is None

    before_fields = audit["before_value"]["fields"]
    after_fields = audit["after_value"]["fields"]
    assert set(before_fields) == changed
    assert set(after_fields) == changed
    for key in changed:
        assert before_fields[key] == _jsonify(BASE_CONFIG_FULL[key]), (
            f"platform audit prior value for {key!r} mismatch"
        )
        assert after_fields[key] == _jsonify(scenario["submitted"][key]), (
            f"platform audit new value for {key!r} mismatch"
        )


async def _check_org_update(session, scenario, org_id, user_id):
    await set_org_overrides(
        session,
        org_id=org_id,
        fields=scenario["overrides"],
        user_id=user_id,
        request=None,
    )

    audit = await _fetch_audit_row(session, "payroll_tax.org.update")
    changed = scenario["changed"]

    assert str(audit["user_id"]) == str(user_id)
    assert str(audit["org_id"]) == str(org_id)

    before_fields = audit["before_value"]["fields"]
    after_fields = audit["after_value"]["fields"]
    assert set(before_fields) == changed
    assert set(after_fields) == changed
    for key in changed:
        # The org had no prior row, so every override is newly added: prior None.
        assert before_fields[key] is None, (
            f"org audit prior value for {key!r} should be None (newly added)"
        )
        assert after_fields[key] == _jsonify(scenario["overrides"][key]), (
            f"org audit new value for {key!r} mismatch"
        )


async def _check_reset_field(session, scenario, org_id, user_id):
    field = scenario["field"]
    seeded = scenario["seeded"]
    session.add(OrgTaxSettings(org_id=org_id, overrides=seeded))
    await session.flush()

    await reset_org_field(
        session, org_id=org_id, field=field, user_id=user_id, request=None
    )

    audit = await _fetch_audit_row(session, "payroll_tax.org.reset_field")

    assert str(audit["user_id"]) == str(user_id)
    assert str(audit["org_id"]) == str(org_id)

    # Prior override value recorded, and the field now inherits.
    assert audit["before_value"]["fields"] == {field: _jsonify(seeded[field])}
    assert audit["after_value"]["fields"] == {field: None}
    assert audit["after_value"]["inherited_fields"] == [field]


async def _check_reset_all(session, scenario, org_id, user_id):
    seeded = scenario["seeded"]
    session.add(OrgTaxSettings(org_id=org_id, overrides=seeded))
    await session.flush()

    await reset_org_all(session, org_id=org_id, user_id=user_id, request=None)

    audit = await _fetch_audit_row(session, "payroll_tax.org.reset_all")

    assert str(audit["user_id"]) == str(user_id)
    assert str(audit["org_id"]) == str(org_id)

    # All prior override values recorded, and all fields now inherit.
    expected_prior = {k: _jsonify(v) for k, v in seeded.items()}
    assert audit["before_value"]["fields"] == expected_prior
    assert audit["after_value"]["fields"] == {}
    assert set(audit["after_value"]["inherited_fields"]) == set(seeded.keys())


async def _run_example(scenario: dict) -> None:
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # RLS scope for the org_tax_settings tier.
                await session.execute(
                    sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
                    {"oid": str(org_id)},
                )

                kind = scenario["kind"]
                if kind == "platform_update":
                    await _check_platform_update(session, scenario, user_id)
                elif kind == "org_update":
                    await _check_org_update(session, scenario, org_id, user_id)
                elif kind == "reset_field":
                    await _check_reset_field(session, scenario, org_id, user_id)
                elif kind == "reset_all":
                    await _check_reset_all(session, scenario, org_id, user_id)
                else:  # pragma: no cover - defensive
                    raise AssertionError(f"unknown scenario kind {kind!r}")
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 7: Every successful change is audited with prior and new values.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(scenario=_any_scenario())
def test_every_successful_change_is_audited(scenario: dict):
    """Property 7: Every successful change is audited with prior and new values.

    # Feature: payroll-tax-settings, Property 7: Every successful change is audited with prior and new values

    For any successful platform save, org override save, field reset, or
    reset-all, an ``audit_log`` row records the acting user, the organisation
    (``org_id`` for org actions; ``NULL`` for the platform action), the changed
    Tax_Field(s), and the prior + new value(s). A reset records the prior
    override value(s) and that the field(s) now inherit.

    **Validates: Requirements 2.4, 9.3, 10.1, 10.2**
    """
    asyncio.run(_run_example(scenario))

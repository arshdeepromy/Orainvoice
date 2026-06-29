"""Property-based test for resolution totality (spec task 4.3).

# Feature: payroll-tax-settings, Property 2: Resolution is total (never blank)

Exercises ``resolve_tax_config(db, org_id)`` in
``app/modules/payroll_tax/resolution.py`` against the real dev Postgres
database, mirroring the DB-backed Hypothesis pattern in
``tests/test_pay_cycle_resolution_priority_property.py`` (fresh async engine per
example, everything rolled back at the end so no rows are left behind).

For any stored platform/org state — a missing org row, a missing platform row, a
platform ``config`` (or org ``overrides``) document missing arbitrary subsets of
Tax_Fields, and/or fields whose stored JSON is unparseable (null, a string, the
wrong shape, NaN/Infinity, an empty/partial nested object) — ``resolve_tax_config``
must still return a fully-populated :class:`ResolvedTaxConfig`: every Tax_Field
populated with a non-null, non-blank value before any calculation. A field that
is absent or unparseable at every tier falls through to the hard-coded
``SAFETY_NET``.

This is the totality guarantee that lets the PAYE engine assume completeness and
never compute against a blank, null, or zero statutory figure.

Because the seed migration (0231) inserts a platform row, each example first
deletes every ``platform_tax_default`` row inside its (rolled-back) transaction
so the test has full control over the platform tier. The test DB connection
(``postgres``) is a superuser and bypasses ``org_tax_settings`` RLS, so org rows
can be inserted/read directly with an arbitrary ``org_id`` (no FK on ``org_id``).

**Validates: Requirements 5.4, 11.1**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings
from app.modules.payroll_tax.models import OrgTaxSettings, PlatformTaxDefault
from app.modules.payroll_tax.resolution import resolve_tax_config
from app.modules.payroll_tax.schemas import SECONDARY_CODES
from app.modules.timesheets.paye import IETCParams, PAYEBracket, ResolvedTaxConfig


# ---------------------------------------------------------------------------
# The JSONB Tax_Field keys eligible in a platform ``config`` and an org
# ``overrides`` document. ``tax_year_label`` is platform-only and lives in its
# own column (handled separately below), so it is not in this list.
# ---------------------------------------------------------------------------

_FIELD_KEYS: tuple[str, ...] = (
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

#: A representative valid, JSON-serialisable value for each Tax_Field.
_VALID_VALUE: dict[str, object] = {
    "paye_brackets": [
        {"upper_limit": 15600, "rate": 0.105},
        {"upper_limit": 53500, "rate": 0.175},
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
}

#: Unparseable / malformed stored values for each Tax_Field. Each must cause the
#: resolver's typed coercion to raise so the field falls through to the next
#: tier (a present-but-null key, a string, the wrong container type, a
#: non-finite number, or a nested object missing required keys).
_CORRUPT_SCALAR: list[object] = [None, "garbage", "NaN", "Infinity", [], {}, True]

_CORRUPT_VALUE: dict[str, list[object]] = {
    "paye_brackets": [
        None,
        "garbage",
        [],  # empty list — not a valid bracket set
        [{"upper_limit": 100}],  # element missing required ``rate``
        [{"rate": "garbage", "upper_limit": 100}],  # unparseable rate
        123,
        {},
    ],
    "secondary_rates": [
        None,
        "garbage",
        {},  # missing every code
        {"SB": 0.1},  # missing S/SH/ST/SA
        {"SB": 0.1, "S": 0.1, "SH": 0.1, "ST": 0.1, "SA": "garbage"},  # unparseable SA
        [],
    ],
    "acc_levy_rate": _CORRUPT_SCALAR,
    "acc_max_liable_earnings": _CORRUPT_SCALAR,
    "student_loan_rate": _CORRUPT_SCALAR,
    "student_loan_threshold": _CORRUPT_SCALAR,
    "ietc": [
        None,
        "garbage",
        {},  # missing every key
        {"amount": 520},  # missing lower/abatement_start/abatement_rate/upper
        {  # missing ``upper``
            "amount": 520,
            "lower": 24000,
            "abatement_start": 44000,
            "abatement_rate": 0.13,
        },
        [],
    ],
    "default_kiwisaver_employee_rate": _CORRUPT_SCALAR,
    "default_kiwisaver_employer_rate": _CORRUPT_SCALAR,
}


@st.composite
def _jsonb_document(draw) -> dict[str, object]:
    """Generate a sparse JSONB document of Tax_Fields.

    Each field is independently absent, present-and-valid, or
    present-and-unparseable, so the union across platform + org tiers covers
    "missing arbitrary fields" and "unparseable arbitrary fields".
    """
    document: dict[str, object] = {}
    for key in _FIELD_KEYS:
        kind = draw(st.sampled_from(["absent", "valid", "corrupt"]))
        if kind == "valid":
            document[key] = _VALID_VALUE[key]
        elif kind == "corrupt":
            document[key] = draw(st.sampled_from(_CORRUPT_VALUE[key]))
        # "absent" → leave the key out entirely.
    return document


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


# ---------------------------------------------------------------------------
# Totality assertion.
# ---------------------------------------------------------------------------


def _assert_total(config: ResolvedTaxConfig) -> None:
    """Assert every Tax_Field in ``config`` is populated and non-blank."""
    # PAYE bracket set: a non-empty tuple of fully-populated bands.
    assert isinstance(config.paye_brackets, tuple)
    assert len(config.paye_brackets) >= 1, "paye_brackets must be non-empty"
    for bracket in config.paye_brackets:
        assert isinstance(bracket, PAYEBracket)
        assert isinstance(bracket.rate, Decimal), "bracket rate must be a Decimal"
        # ``None`` only ever marks the open-ended top band; otherwise a Decimal.
        assert bracket.upper_limit is None or isinstance(bracket.upper_limit, Decimal)

    # Secondary rates: every one of the five supported codes present + Decimal.
    assert isinstance(config.secondary_rates, dict)
    for code in SECONDARY_CODES:
        assert code in config.secondary_rates, f"secondary code {code} missing"
        assert isinstance(config.secondary_rates[code], Decimal)

    # Scalar Decimal fields: non-null Decimals.
    for attr in (
        "acc_levy_rate",
        "acc_max_liable_earnings",
        "student_loan_rate",
        "student_loan_threshold",
        "default_kiwisaver_employee_rate",
        "default_kiwisaver_employer_rate",
    ):
        value = getattr(config, attr)
        assert isinstance(value, Decimal), f"{attr} must be a non-null Decimal"

    # IETC: fully populated.
    assert isinstance(config.ietc, IETCParams)
    for attr in ("amount", "lower", "abatement_start", "abatement_rate", "upper"):
        value = getattr(config.ietc, attr)
        assert isinstance(value, Decimal), f"ietc.{attr} must be a non-null Decimal"

    # Tax year label: a non-blank string.
    assert isinstance(config.tax_year_label, str)
    assert config.tax_year_label.strip() != "", "tax_year_label must be non-blank"


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    *,
    platform_present: bool,
    platform_config: dict[str, object],
    platform_label: str,
    org_present: bool,
    org_overrides: dict[str, object],
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # Take full control of the platform tier: remove the row seeded
                # by migration 0231 so this example's platform state is exactly
                # what we generate (including "no platform row at all").
                await session.execute(delete(PlatformTaxDefault))
                await session.flush()

                if platform_present:
                    session.add(
                        PlatformTaxDefault(
                            config=platform_config,
                            tax_year_label=platform_label,
                            is_singleton=True,
                        )
                    )
                    await session.flush()

                org_id = uuid.uuid4()
                if org_present:
                    session.add(
                        OrgTaxSettings(org_id=org_id, overrides=org_overrides)
                    )
                    await session.flush()

                config = await resolve_tax_config(session, org_id)
                _assert_total(config)
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2: Resolution is total (never blank).
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    platform_present=st.booleans(),
    platform_config=_jsonb_document(),
    platform_label=st.sampled_from(["2024/25", "2025/26", "", "   "]),
    org_present=st.booleans(),
    org_overrides=_jsonb_document(),
)
def test_resolution_is_total_never_blank(
    platform_present: bool,
    platform_config: dict[str, object],
    platform_label: str,
    org_present: bool,
    org_overrides: dict[str, object],
):
    """Property 2: Resolution is total (never blank).

    # Feature: payroll-tax-settings, Property 2: Resolution is total (never blank)

    For any stored platform and org state — including a missing org row, a
    missing platform row, and platform/org documents missing arbitrary fields or
    holding unparseable values — ``resolve_tax_config`` returns a
    ``ResolvedTaxConfig`` in which every Tax_Field is populated with a non-null,
    non-blank value (PAYE brackets non-empty, all five secondary codes present,
    every scalar/IETC Decimal non-null, the tax-year label non-blank). Anything
    absent or unparseable at every tier falls through to the ``SAFETY_NET``.

    **Validates: Requirements 5.4, 11.1**
    """
    asyncio.run(
        _run_example(
            platform_present=platform_present,
            platform_config=platform_config,
            platform_label=platform_label,
            org_present=org_present,
            org_overrides=org_overrides,
        )
    )

"""Seed-migration tests for the Payroll_Tax_Settings tables (spec task 5.2).

Exercises the seed performed by Alembic migration ``0231_payroll_tax_settings``
(``alembic/versions/2026_06_28_0001-0231_payroll_tax_settings.py``) against the
real dev Postgres database, mirroring the DB-backed pattern used by the
payroll-tax resolution property tests (a fresh async engine per example, with
every write performed inside a transaction that is rolled back so the
migration-seeded row and live schema are never disturbed).

Three behaviours are asserted:

* **Req 1.2 — exact 2024/25 seed values.** The single ``platform_tax_default``
  row created by the migration holds exactly the current 2024/25 constants:
  the five PAYE brackets (open-ended top band as ``upper_limit: null``), the
  five secondary rates, the ACC levy rate + cap, the student-loan rate +
  threshold, the IETC parameters, the two 3.00 KiwiSaver defaults, and the
  ``"2024/25"`` tax-year label.

* **Req 1.3 — re-running the seed leaves an existing row unchanged.** Replaying
  the migration's ``INSERT ... WHERE NOT EXISTS`` guard while a row already
  exists is a no-op: still exactly one row, with the same id and config.

* **Req 1.1 — singleton enforced.** A second ``platform_tax_default`` insert
  (``is_singleton = true``) conflicts on the ``uq_platform_tax_default_singleton``
  UNIQUE constraint, raising an ``IntegrityError`` — so exactly one row can ever
  exist.

The test DB connection (``postgres``) is a superuser; ``platform_tax_default``
is not org-scoped and has no RLS, so the row is read/written directly.

**Validates: Requirements 1.1, 1.2, 1.3**

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings``.
- Backend tests run via ``docker compose exec app python -m pytest``.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings
from app.modules.payroll_tax.models import PlatformTaxDefault


# ---------------------------------------------------------------------------
# The exact 2024/25 seed the migration inserts (Req 1.2). Numbers are compared
# as ``Decimal(str(...))`` so JSON-number drift cannot mask a mismatch.
# ---------------------------------------------------------------------------

_EXPECTED_LABEL = "2024/25"

_EXPECTED_BRACKETS: list[tuple[object, str]] = [
    (15600, "0.105"),
    (53500, "0.175"),
    (78100, "0.30"),
    (180000, "0.33"),
    (None, "0.39"),  # open-ended top band
]

_EXPECTED_SECONDARY: dict[str, str] = {
    "SB": "0.105",
    "S": "0.175",
    "SH": "0.30",
    "ST": "0.33",
    "SA": "0.39",
}

_EXPECTED_IETC: dict[str, str] = {
    "amount": "520",
    "lower": "24000",
    "abatement_start": "44000",
    "abatement_rate": "0.13",
    "upper": "48000",
}

#: The migration's seed statement, replayed verbatim to prove idempotence
#: (Req 1.3). ``WHERE NOT EXISTS`` makes it a no-op when a row already exists.
_SEED_SQL = sa.text(
    """
    INSERT INTO platform_tax_default (config, tax_year_label)
    SELECT
        '{
            "paye_brackets": [
                {"upper_limit": 15600, "rate": 0.105},
                {"upper_limit": 53500, "rate": 0.175},
                {"upper_limit": 78100, "rate": 0.30},
                {"upper_limit": 180000, "rate": 0.33},
                {"upper_limit": null, "rate": 0.39}
            ],
            "secondary_rates": {
                "SB": 0.105, "S": 0.175, "SH": 0.30, "ST": 0.33, "SA": 0.39
            },
            "acc_levy_rate": 0.016,
            "acc_max_liable_earnings": 142283,
            "student_loan_rate": 0.12,
            "student_loan_threshold": 24128,
            "ietc": {
                "amount": 520, "lower": 24000, "abatement_start": 44000,
                "abatement_rate": 0.13, "upper": 48000
            },
            "default_kiwisaver_employee_rate": 3.00,
            "default_kiwisaver_employer_rate": 3.00
        }'::jsonb,
        '2024/25'
    WHERE NOT EXISTS (SELECT 1 FROM platform_tax_default)
    """
)


# ---------------------------------------------------------------------------
# Engine / session helper — fresh engine per test (asyncpg connections are
# bound to the event loop ``asyncio.run`` creates), matching the reference
# DB-backed tests in this repo.
# ---------------------------------------------------------------------------


async def _make_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _dec(value: object) -> Decimal:
    """Coerce a JSON-rehydrated value to an exact ``Decimal`` for comparison."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Req 1.2 — the seeded row holds the exact 2024/25 values.
# ---------------------------------------------------------------------------


async def _check_seeded_values() -> None:
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            try:
                rows = (
                    await session.execute(sa.select(PlatformTaxDefault))
                ).scalars().all()

                # Exactly one platform row exists (seeded by migration 0231).
                assert len(rows) == 1, (
                    f"expected exactly one platform_tax_default row, got {len(rows)}"
                )
                row = rows[0]

                assert row.is_singleton is True
                assert row.tax_year_label == _EXPECTED_LABEL

                config = row.config
                assert isinstance(config, dict)

                # PAYE brackets — order, limits, and rates.
                brackets = config["paye_brackets"]
                assert len(brackets) == len(_EXPECTED_BRACKETS)
                for actual, (exp_limit, exp_rate) in zip(brackets, _EXPECTED_BRACKETS):
                    if exp_limit is None:
                        assert actual["upper_limit"] is None, "top band must be open-ended"
                    else:
                        assert _dec(actual["upper_limit"]) == _dec(exp_limit)
                    assert _dec(actual["rate"]) == Decimal(exp_rate)

                # Secondary rates — all five codes, exact values.
                secondary = config["secondary_rates"]
                assert set(secondary) == set(_EXPECTED_SECONDARY)
                for code, exp_rate in _EXPECTED_SECONDARY.items():
                    assert _dec(secondary[code]) == Decimal(exp_rate)

                # ACC, student loan scalars.
                assert _dec(config["acc_levy_rate"]) == Decimal("0.016")
                assert _dec(config["acc_max_liable_earnings"]) == Decimal("142283")
                assert _dec(config["student_loan_rate"]) == Decimal("0.12")
                assert _dec(config["student_loan_threshold"]) == Decimal("24128")

                # IETC parameters.
                ietc = config["ietc"]
                assert set(ietc) == set(_EXPECTED_IETC)
                for key, exp in _EXPECTED_IETC.items():
                    assert _dec(ietc[key]) == Decimal(exp)

                # KiwiSaver defaults (3.00 / 3.00).
                assert _dec(config["default_kiwisaver_employee_rate"]) == Decimal("3.00")
                assert _dec(config["default_kiwisaver_employer_rate"]) == Decimal("3.00")
            finally:
                # Read-only, but roll back to leave nothing behind.
                await session.rollback()
    finally:
        await engine.dispose()


def test_seed_row_has_exact_2024_25_values() -> None:
    """Req 1.2: the seeded platform_tax_default row holds the 2024/25 constants."""
    asyncio.run(_check_seeded_values())


# ---------------------------------------------------------------------------
# Req 1.3 — replaying the seed with a row present leaves it unchanged.
# ---------------------------------------------------------------------------


async def _check_reseed_is_noop() -> None:
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            try:
                before = (
                    await session.execute(sa.select(PlatformTaxDefault))
                ).scalars().all()
                assert len(before) == 1, "fixture expects the migration-seeded row"
                before_id = before[0].id
                before_config = before[0].config
                before_label = before[0].tax_year_label

                # Replay the migration's INSERT ... WHERE NOT EXISTS guard.
                result = await session.execute(_SEED_SQL)
                # The guard short-circuits: no row inserted.
                assert result.rowcount == 0, "re-seed must not insert a second row"
                await session.flush()

                after = (
                    await session.execute(sa.select(PlatformTaxDefault))
                ).scalars().all()
                assert len(after) == 1, "re-seed must leave exactly one row"
                assert after[0].id == before_id, "existing row id must be unchanged"
                assert after[0].config == before_config, "config must be unchanged"
                assert after[0].tax_year_label == before_label, "label must be unchanged"
            finally:
                # Never persist — the seed replay is exercised then discarded.
                await session.rollback()
    finally:
        await engine.dispose()


def test_reseed_with_existing_row_leaves_it_unchanged() -> None:
    """Req 1.3: re-running the seed while a row exists is a no-op."""
    asyncio.run(_check_reseed_is_noop())


# ---------------------------------------------------------------------------
# Req 1.1 — a second platform insert conflicts on is_singleton.
# ---------------------------------------------------------------------------


async def _check_second_insert_conflicts() -> None:
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            raised = False
            try:
                # A row already exists (seeded). Force a second insert with the
                # same is_singleton sentinel — it must violate the UNIQUE
                # constraint uq_platform_tax_default_singleton.
                session.add(
                    PlatformTaxDefault(
                        is_singleton=True,
                        config={"paye_brackets": []},
                        tax_year_label="conflict",
                    )
                )
                await session.flush()
            except IntegrityError:
                raised = True
            finally:
                # Roll back: either the failed flush poisoned the tx, or (if it
                # had somehow succeeded) we must not keep the bogus row.
                await session.rollback()

            assert raised, (
                "a second platform_tax_default insert must conflict on "
                "is_singleton (UNIQUE), raising IntegrityError"
            )
    finally:
        await engine.dispose()


def test_second_platform_insert_conflicts_on_singleton() -> None:
    """Req 1.1: exactly one platform row — a second insert raises IntegrityError."""
    asyncio.run(_check_second_insert_conflicts())

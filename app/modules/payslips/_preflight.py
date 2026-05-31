"""Startup-time preflight checks for the payslips module.

Task B0 from ``.kiro/specs/staff-management-p4/tasks.md`` — the
:func:`assert_phase1_columns_present` helper runs at app startup
(called from ``app/main.py``'s ``@app.on_event("startup")`` block) and
hard-fails when the database is missing any column that Phase 4 reads
off ``staff_members``. It also confirms the ``payroll`` row exists in
``module_registry`` because every P4 endpoint is invisible to every
org via the module-disabled middleware (``app/middleware/modules.py``)
without it.

Two cross-phase prerequisites are validated here:

  - **P1 migration 0203** ships the 12 ``staff_members`` columns
    listed in :data:`_REQUIRED_STAFF_COLUMNS`. P4's payslip math reads
    every one of them.
  - **P1 migration 0203** also seeds the ``payroll`` row in
    ``module_registry``. Without it, no org sees the payroll surface
    even when otherwise configured correctly.

The check is **skipped under pytest** (``PYTEST_RUNNING=1`` env var)
so the test suite can exercise individual P4 modules without a fully
applied P1 schema. Production / staging / dev startup paths all run
the check.

Failure mode:

  - On missing column(s): logs the names at ``CRITICAL`` and raises
    :class:`PayslipsPreflightError`. The startup hook in ``app/main.py``
    re-raises so the FastAPI process exits rather than booting in a
    half-broken state.
  - On missing ``payroll`` module_registry row: same shape, same
    abort.

The function is designed to be safe to call multiple times — it makes
two read-only SELECTs and never writes.

**Validates: Requirement N7 — Staff Management Phase 4 task B0**
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


__all__ = [
    "PayslipsPreflightError",
    "assert_phase1_columns_present",
]


# ---------------------------------------------------------------------------
# The set of P1-owned ``staff_members`` columns that P4 reads (per
# requirements.md "Hard prerequisites" section). Kept as a frozenset so
# we don't accidentally add duplicates on edit, and order doesn't
# matter for the equality check.
# ---------------------------------------------------------------------------
_REQUIRED_STAFF_COLUMNS: frozenset[str] = frozenset({
    "employment_type",
    "tax_code",
    "kiwisaver_enrolled",
    "kiwisaver_employee_rate",
    "kiwisaver_employer_rate",
    "student_loan",
    "employment_start_date",
    "employment_end_date",
    "standard_hours_per_week",
    "bank_account_number_encrypted",
    "ird_number_encrypted",
    "average_daily_pay_snapshot",
})


# ---------------------------------------------------------------------------
# Module-registry row that MUST exist for P4 endpoints to be reachable
# via the module-enabled middleware.
# ---------------------------------------------------------------------------
_REQUIRED_MODULE_SLUG: str = "payroll"


# ---------------------------------------------------------------------------
# Env-var gate — set to "1" by ``conftest.py`` so the test suite can run
# without the full P1 schema applied.
# ---------------------------------------------------------------------------
_PYTEST_ENV_VAR: str = "PYTEST_RUNNING"


class PayslipsPreflightError(RuntimeError):
    """Raised when the database is missing a P4 hard prerequisite.

    Carries a human-readable message naming what's wrong; the caller in
    ``app/main.py`` logs it at ``CRITICAL`` and re-raises so the FastAPI
    process exits rather than booting in a half-configured state.
    """


def _is_skipped_for_tests() -> bool:
    """Return ``True`` when ``PYTEST_RUNNING=1`` is set in the environment.

    Split out so tests can monkeypatch the env var without having to
    reach into the function-local logic.
    """
    return os.environ.get(_PYTEST_ENV_VAR, "").strip() == "1"


async def _load_present_staff_columns(db: AsyncSession) -> set[str]:
    """Return the set of column names currently on ``staff_members``.

    Reads ``information_schema.columns`` directly so the check is
    independent of the ORM model definition — if the migration hasn't
    been applied, the ORM will happily import but the SQL columns
    won't exist, which is exactly the failure mode this preflight is
    designed to catch.
    """
    result = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'staff_members' "
            "  AND table_schema = current_schema()"
        ),
    )
    return {row[0] for row in result.fetchall()}


async def _payroll_module_row_exists(db: AsyncSession) -> bool:
    """Return ``True`` when ``module_registry`` has a row for ``payroll``.

    Uses a parameterised SELECT 1 — the row count is implicit in
    whether ``scalar_one_or_none()`` returns ``None`` or ``1``.
    """
    result = await db.execute(
        text("SELECT 1 FROM module_registry WHERE slug = :slug LIMIT 1"),
        {"slug": _REQUIRED_MODULE_SLUG},
    )
    return result.scalar_one_or_none() is not None


async def assert_phase1_columns_present(db: AsyncSession) -> None:
    """Hard-fail at startup when P1 migration 0203 is not applied.

    Two checks:

      1. Every column in :data:`_REQUIRED_STAFF_COLUMNS` is present on
         the ``staff_members`` table. Missing columns are listed in
         the raised error and the ``CRITICAL`` log line.
      2. A row with ``slug='payroll'`` exists in ``module_registry``.

    Skipped when ``PYTEST_RUNNING=1`` is set in the environment — the
    test suite intentionally exercises P4 modules without the full P1
    schema.

    Raises:
      :class:`PayslipsPreflightError` on any failure. The caller
      (``app/main.py``'s ``@app.on_event("startup")`` hook) is expected
      to log + re-raise so the process exits.
    """
    if _is_skipped_for_tests():
        logger.debug(
            "payslips preflight: skipped (PYTEST_RUNNING=1)",
        )
        return

    # 1. staff_members columns.
    present = await _load_present_staff_columns(db)
    missing = sorted(_REQUIRED_STAFF_COLUMNS - present)
    if missing:
        msg = (
            "Payslips preflight failed: the following P1-owned "
            "staff_members columns are missing — apply migration 0203 "
            f"before P4 can boot. Missing: {', '.join(missing)}"
        )
        logger.critical(msg)
        raise PayslipsPreflightError(msg)

    # 2. module_registry payroll row.
    if not await _payroll_module_row_exists(db):
        msg = (
            "Payslips preflight failed: module_registry has no row "
            f"for slug='{_REQUIRED_MODULE_SLUG}'. Apply P1 migration "
            "0203's module-registry seed before P4 can boot — "
            "without this row, the module-enabled middleware blocks "
            "every payroll endpoint with HTTP 403 for every org."
        )
        logger.critical(msg)
        raise PayslipsPreflightError(msg)

    logger.info(
        "payslips preflight: P1 prerequisites OK "
        "(%d staff_members columns + payroll module_registry row present)",
        len(_REQUIRED_STAFF_COLUMNS),
    )

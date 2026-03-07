"""Post-migration integrity checks for V1 organisations.

Verifies that all migrated V1 orgs have valid references and required
modules enabled.

**Validates: Requirement 7.5 — Integrity check after migration**
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.migration.v1_migration_service import V1_CORE_MODULES

logger = logging.getLogger(__name__)


@dataclass
class IntegrityResult:
    """Result of a single integrity check."""

    check_name: str
    passed: bool
    details: str = ""
    failing_org_ids: list[str] = field(default_factory=list)


@dataclass
class MigrationIntegrityReport:
    """Aggregate report of all integrity checks."""

    total_orgs: int = 0
    checks: list[IntegrityResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_orgs": self.total_orgs,
            "all_passed": self.all_passed,
            "checks": [
                {
                    "check_name": c.check_name,
                    "passed": c.passed,
                    "details": c.details,
                    "failing_org_ids": c.failing_org_ids,
                }
                for c in self.checks
            ],
        }


async def run_integrity_checks(
    db: AsyncSession,
    org_ids: list[uuid.UUID] | None = None,
) -> MigrationIntegrityReport:
    """Run all post-migration integrity checks.

    If org_ids is provided, checks only those orgs. Otherwise checks
    all orgs that have the migrated_from_v1 marker.
    """
    report = MigrationIntegrityReport()

    # Determine which orgs to check
    if org_ids:
        id_list = [str(oid) for oid in org_ids]
        org_filter = "id = ANY(:org_ids)"
        params: dict = {"org_ids": id_list}
    else:
        org_filter = "(setup_wizard_state->>'migrated_from_v1')::boolean IS TRUE"
        params = {}

    # Count total orgs
    count_q = f"SELECT COUNT(*) FROM organisations WHERE {org_filter}"
    count_result = await db.execute(text(count_q), params)
    report.total_orgs = count_result.scalar() or 0

    if report.total_orgs == 0:
        logger.info("No migrated orgs found for integrity checks.")
        return report

    # Check 1: Valid trade_category_id
    report.checks.append(
        await _check_trade_category(db, org_filter, params)
    )

    # Check 2: Valid compliance_profile_id
    report.checks.append(
        await _check_compliance_profile(db, org_filter, params)
    )

    # Check 3: Core modules enabled
    report.checks.append(
        await _check_core_modules(db, org_filter, params)
    )

    # Check 4: Required fields populated
    report.checks.append(
        await _check_required_fields(db, org_filter, params)
    )

    status = "PASSED" if report.all_passed else "FAILED"
    logger.info(
        "Integrity checks %s for %d orgs (%d/%d checks passed)",
        status,
        report.total_orgs,
        sum(1 for c in report.checks if c.passed),
        len(report.checks),
    )
    return report


async def _check_trade_category(
    db: AsyncSession, org_filter: str, params: dict,
) -> IntegrityResult:
    """Verify all migrated orgs have a valid trade_category_id."""
    query = f"""
        SELECT o.id::text
        FROM organisations o
        WHERE {org_filter}
          AND (
            o.trade_category_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM trade_categories tc WHERE tc.id = o.trade_category_id
            )
          )
    """
    result = await db.execute(text(query), params)
    failing = [row[0] for row in result.fetchall()]

    return IntegrityResult(
        check_name="valid_trade_category_id",
        passed=len(failing) == 0,
        details=f"{len(failing)} orgs missing valid trade_category_id",
        failing_org_ids=failing,
    )


async def _check_compliance_profile(
    db: AsyncSession, org_filter: str, params: dict,
) -> IntegrityResult:
    """Verify all migrated orgs have a valid compliance_profile_id."""
    query = f"""
        SELECT o.id::text
        FROM organisations o
        WHERE {org_filter}
          AND (
            o.compliance_profile_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM compliance_profiles cp
                WHERE cp.id = o.compliance_profile_id
            )
          )
    """
    result = await db.execute(text(query), params)
    failing = [row[0] for row in result.fetchall()]

    return IntegrityResult(
        check_name="valid_compliance_profile_id",
        passed=len(failing) == 0,
        details=f"{len(failing)} orgs missing valid compliance_profile_id",
        failing_org_ids=failing,
    )


async def _check_core_modules(
    db: AsyncSession, org_filter: str, params: dict,
) -> IntegrityResult:
    """Verify all migrated orgs have at least the V1 core modules enabled."""
    # Find orgs missing any core module
    module_conditions = " AND ".join(
        f"""
        EXISTS (
            SELECT 1 FROM org_modules om
            WHERE om.org_id = o.id
              AND om.module_slug = '{slug}'
              AND om.is_enabled = true
        )
        """
        for slug in V1_CORE_MODULES
    )

    query = f"""
        SELECT o.id::text
        FROM organisations o
        WHERE {org_filter}
          AND NOT ({module_conditions})
    """
    result = await db.execute(text(query), params)
    failing = [row[0] for row in result.fetchall()]

    return IntegrityResult(
        check_name="core_modules_enabled",
        passed=len(failing) == 0,
        details=f"{len(failing)} orgs missing one or more core modules ({V1_CORE_MODULES})",
        failing_org_ids=failing,
    )


async def _check_required_fields(
    db: AsyncSession, org_filter: str, params: dict,
) -> IntegrityResult:
    """Verify all migrated orgs have required V2 fields populated."""
    query = f"""
        SELECT o.id::text
        FROM organisations o
        WHERE {org_filter}
          AND (
            o.country_code IS NULL
            OR o.base_currency IS NULL
            OR o.locale IS NULL
            OR o.tax_label IS NULL
            OR o.default_tax_rate IS NULL
            OR o.timezone IS NULL
            OR o.date_format IS NULL
          )
    """
    result = await db.execute(text(query), params)
    failing = [row[0] for row in result.fetchall()]

    return IntegrityResult(
        check_name="required_fields_populated",
        passed=len(failing) == 0,
        details=f"{len(failing)} orgs with NULL required V2 fields",
        failing_org_ids=failing,
    )

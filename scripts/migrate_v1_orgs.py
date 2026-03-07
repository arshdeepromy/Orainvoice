#!/usr/bin/env python3
"""Migrate all existing V1 organisations to the universal platform schema.

Queries all organisations that haven't been migrated yet, applies NZ defaults,
enables V1 core modules, and sets setup_wizard_state to 'completed'.

Usage:
    python scripts/migrate_v1_orgs.py [--dry-run]

Requirements: 7.1 — V1 Organisation Data Migration (Task 53.3)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.migration.v1_migration_service import (
    V1MigrationService,
    NZ_DEFAULTS,
    V1_CORE_MODULES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def run_migration(dry_run: bool = False) -> dict:
    """Execute the V1 → V2 migration for all unmigrated organisations."""
    results = {
        "total_orgs": 0,
        "migrated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    async with async_session_factory() as session:
        async with session.begin():
            service = V1MigrationService(db=session)

            # Query all unmigrated orgs
            orgs = await service.get_all_v1_orgs()
            results["total_orgs"] = len(orgs)

            if not orgs:
                logger.info("No unmigrated V1 organisations found.")
                return results

            logger.info("Found %d unmigrated V1 organisations.", len(orgs))

            if dry_run:
                logger.info("[DRY RUN] Would migrate the following orgs:")
                for org in orgs:
                    logger.info("  - %s (%s)", org["name"], org["id"])
                results["skipped"] = len(orgs)
                return results

            for org in orgs:
                org_id = org["id"]
                org_name = org.get("name", "unknown")
                try:
                    result = await service.migrate_org(org_id)
                    results["migrated"] += 1
                    logger.info(
                        "Migrated org '%s' (%s): modules=%s",
                        org_name,
                        org_id,
                        result["modules_enabled"],
                    )
                except Exception as exc:
                    results["failed"] += 1
                    error_msg = f"Failed to migrate org '{org_name}' ({org_id}): {exc}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate V1 organisations to universal platform schema."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List orgs that would be migrated without making changes.",
    )
    args = parser.parse_args()

    results = asyncio.run(run_migration(dry_run=args.dry_run))

    logger.info("=" * 60)
    logger.info("Migration Results:")
    logger.info("  Total orgs found:  %d", results["total_orgs"])
    logger.info("  Migrated:          %d", results["migrated"])
    logger.info("  Skipped:           %d", results["skipped"])
    logger.info("  Failed:            %d", results["failed"])
    if results["errors"]:
        logger.warning("  Errors:")
        for err in results["errors"]:
            logger.warning("    - %s", err)
    logger.info("=" * 60)

    # Exit with non-zero if any failures
    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Rollback V1 migration for specified organisations.

Reverts V2 column values to NULL and removes V1 core module enablement
records for organisations whose migration failed or needs to be undone.

Usage:
    python scripts/rollback_v1_migration.py --org-ids <id1> <id2> ...
    python scripts/rollback_v1_migration.py --all-migrated [--dry-run]

Requirements: 7.6 — Rollback migration (Task 53.6)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.migration.v1_migration_service import V1_CORE_MODULES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def rollback_org(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Rollback V1 migration for a single organisation.

    Reverts trade_category_id, compliance_profile_id, and country_code
    to NULL. Resets setup_wizard_state. Removes V1 core module records.
    """
    # Revert V2 columns to NULL / defaults
    await db.execute(
        text(
            """
            UPDATE organisations
            SET trade_category_id = NULL,
                compliance_profile_id = NULL,
                country_code = NULL,
                setup_wizard_state = '{}'::jsonb
            WHERE id = :org_id
            """
        ),
        {"org_id": str(org_id)},
    )

    # Remove V1 core module enablement records
    await db.execute(
        text(
            """
            DELETE FROM org_modules
            WHERE org_id = :org_id
              AND module_slug = ANY(:slugs)
            """
        ),
        {"org_id": str(org_id), "slugs": V1_CORE_MODULES},
    )

    return {"org_id": str(org_id), "status": "rolled_back"}


async def run_rollback(
    org_ids: list[str] | None = None,
    all_migrated: bool = False,
    dry_run: bool = False,
) -> dict:
    """Execute rollback for specified orgs or all migrated orgs."""
    results = {
        "total": 0,
        "rolled_back": 0,
        "failed": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    async with async_session_factory() as session:
        async with session.begin():
            # Determine target orgs
            if all_migrated:
                rows = await session.execute(
                    text(
                        """
                        SELECT id FROM organisations
                        WHERE (setup_wizard_state->>'migrated_from_v1')::boolean IS TRUE
                        """
                    )
                )
                target_ids = [row[0] for row in rows.fetchall()]
            elif org_ids:
                target_ids = [uuid.UUID(oid) for oid in org_ids]
            else:
                logger.error("No org IDs specified and --all-migrated not set.")
                return results

            results["total"] = len(target_ids)

            if dry_run:
                logger.info("[DRY RUN] Would rollback %d orgs.", len(target_ids))
                for oid in target_ids:
                    logger.info("  - %s", oid)
                return results

            for oid in target_ids:
                try:
                    await rollback_org(session, oid)
                    results["rolled_back"] += 1
                    logger.info("Rolled back org %s", oid)
                except Exception as exc:
                    results["failed"] += 1
                    error_msg = f"Failed to rollback org {oid}: {exc}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rollback V1 migration for specified organisations."
    )
    parser.add_argument(
        "--org-ids",
        nargs="+",
        help="Specific organisation IDs to rollback.",
    )
    parser.add_argument(
        "--all-migrated",
        action="store_true",
        help="Rollback all orgs with migrated_from_v1 marker.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List orgs that would be rolled back without making changes.",
    )
    args = parser.parse_args()

    if not args.org_ids and not args.all_migrated:
        parser.error("Specify --org-ids or --all-migrated")

    results = asyncio.run(
        run_rollback(
            org_ids=args.org_ids,
            all_migrated=args.all_migrated,
            dry_run=args.dry_run,
        )
    )

    logger.info("=" * 60)
    logger.info("Rollback Results:")
    logger.info("  Total orgs:    %d", results["total"])
    logger.info("  Rolled back:   %d", results["rolled_back"])
    logger.info("  Failed:        %d", results["failed"])
    if results["errors"]:
        logger.warning("  Errors:")
        for err in results["errors"]:
            logger.warning("    - %s", err)
    logger.info("=" * 60)

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

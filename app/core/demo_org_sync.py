"""Auto-sync all modules and feature flags for the demo org on app startup.

In development, ensures the demo org_admin (demo@orainvoice.com) always
has every module from module_registry enabled and every feature flag
targeted with an org_override rule. This means any newly added module or
flag is automatically available to the demo org without manual steps.

Only runs when ENVIRONMENT=development (no-op in production).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text

from app.config import settings
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)

DEMO_EMAIL = "demo@orainvoice.com"


async def sync_demo_org_modules() -> None:
    """Enable all modules and flag overrides for the demo org. Idempotent, dev-only."""
    if settings.environment != "development":
        return

    try:
        async with async_session_factory() as session:
            async with session.begin():
                # Find the demo user
                result = await session.execute(
                    text("SELECT id, org_id FROM users WHERE email = :email"),
                    {"email": DEMO_EMAIL},
                )
                row = result.first()
                if not row:
                    logger.debug("Demo org user not found — skipping module sync.")
                    return

                user_id = str(row[0])
                org_id = str(row[1])

                # --- Sync modules ---
                modules = await session.execute(
                    text("SELECT slug FROM module_registry")
                )
                all_slugs = [r[0] for r in modules.fetchall()]

                for slug in all_slugs:
                    await session.execute(
                        text("""
                            INSERT INTO org_modules
                                (id, org_id, module_slug, is_enabled, enabled_by)
                            VALUES (gen_random_uuid(), :org_id, :slug, true, CAST(:uid AS uuid))
                            ON CONFLICT (org_id, module_slug)
                            DO NOTHING
                        """),
                        {"org_id": org_id, "slug": slug, "uid": user_id},
                    )

                # --- Sync feature flag org_overrides ---
                flags = await session.execute(
                    text("SELECT id, key, targeting_rules FROM feature_flags WHERE is_active = true")
                )
                flags_updated = 0
                for flag_id, flag_key, targeting_rules in flags.fetchall():
                    rules = targeting_rules if isinstance(targeting_rules, list) else []
                    has_override = any(
                        r.get("type") == "org_override" and str(r.get("value")) == org_id
                        for r in rules
                    )
                    if not has_override:
                        rules.append({
                            "type": "org_override",
                            "value": org_id,
                            "enabled": True,
                        })
                        await session.execute(
                            text("""
                                UPDATE feature_flags
                                SET targeting_rules = CAST(:rules AS jsonb)
                                WHERE id = CAST(:fid AS uuid)
                            """),
                            {"rules": json.dumps(rules), "fid": str(flag_id)},
                        )
                        flags_updated += 1

                logger.info(
                    "Demo org sync: %d modules enabled, %d flag overrides added for %s",
                    len(all_slugs),
                    flags_updated,
                    DEMO_EMAIL,
                )
    except Exception as exc:
        # Non-fatal — don't block app startup
        logger.warning("Demo org module sync failed (non-fatal): %s", exc)

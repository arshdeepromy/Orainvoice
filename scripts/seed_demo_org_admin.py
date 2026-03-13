"""Seed a demo org_admin user with all modules and feature flags enabled.

Run: python scripts/seed_demo_org_admin.py

Creates:
  - A private subscription plan (Demo Plan) — not available during registration
  - An organisation (Demo Workshop) on the Demo Plan
  - An org_admin user: demo@orainvoice.com / demo123
  - Enables ALL modules from module_registry for the org
  - Enables ALL feature flags (default_value=true) for the org

Idempotent — skips creation if the user already exists, but always
syncs modules and feature flags so new ones are picked up automatically.
"""

from __future__ import annotations

import asyncio
import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.modules.auth.password import hash_password


DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"
DEMO_ROLE = "org_admin"
ORG_NAME = "Demo Workshop"
PLAN_NAME = "Demo Plan"


async def seed() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # ---------------------------------------------------------
            # 1. Check if demo user already exists
            # ---------------------------------------------------------
            result = await session.execute(
                text("SELECT id, org_id FROM users WHERE email = :email"),
                {"email": DEMO_EMAIL},
            )
            row = result.first()

            if row:
                user_id = str(row[0])
                org_id = str(row[1])
                print(f"User {DEMO_EMAIL} already exists ({user_id}) — skipping user creation.")
            else:
                # ---------------------------------------------------------
                # 2. Create the Demo Plan (private, is_public=false)
                # ---------------------------------------------------------
                plan_id = str(uuid.uuid4())
                await session.execute(
                    text("""
                        INSERT INTO subscription_plans
                            (id, name, monthly_price_nzd, user_seats, storage_quota_gb,
                             carjam_lookups_included, enabled_modules, is_public)
                        VALUES (:id, :name, 0, 999, 100, 9999, '["all"]'::jsonb, false)
                        ON CONFLICT DO NOTHING
                    """),
                    {"id": plan_id, "name": PLAN_NAME},
                )
                # If plan already exists by name, fetch its id
                plan_row = await session.execute(
                    text("SELECT id FROM subscription_plans WHERE name = :name"),
                    {"name": PLAN_NAME},
                )
                plan_id = str(plan_row.scalar_one())
                print(f"Subscription plan: {PLAN_NAME} ({plan_id}) [private]")

                # ---------------------------------------------------------
                # 3. Create the Demo Organisation
                # ---------------------------------------------------------
                org_id = str(uuid.uuid4())
                await session.execute(
                    text("""
                        INSERT INTO organisations
                            (id, name, plan_id, status, storage_quota_gb, settings)
                        VALUES (:id, :name, :plan_id, 'active', 100, '{}'::jsonb)
                    """),
                    {"id": org_id, "name": ORG_NAME, "plan_id": plan_id},
                )
                print(f"Organisation: {ORG_NAME} ({org_id})")

                # ---------------------------------------------------------
                # 4. Create the org_admin user
                # ---------------------------------------------------------
                user_id = str(uuid.uuid4())
                pw_hash = hash_password(DEMO_PASSWORD)
                await session.execute(
                    text("""
                        INSERT INTO users
                            (id, org_id, email, password_hash, role, is_active, is_email_verified)
                        VALUES (:id, :org_id, :email, :pw_hash, :role, true, true)
                    """),
                    {
                        "id": user_id,
                        "org_id": org_id,
                        "email": DEMO_EMAIL,
                        "pw_hash": pw_hash,
                        "role": DEMO_ROLE,
                    },
                )
                print(f"User: {DEMO_EMAIL} ({user_id})")

            # ---------------------------------------------------------
            # 5. Sync ALL modules — enable every module_registry entry
            #    for the demo org. Uses ON CONFLICT to be idempotent.
            # ---------------------------------------------------------
            module_result = await session.execute(
                text("SELECT slug FROM module_registry")
            )
            all_modules = [r[0] for r in module_result.fetchall()]

            enabled_count = 0
            for slug in all_modules:
                await session.execute(
                    text("""
                        INSERT INTO org_modules (id, org_id, module_slug, is_enabled, enabled_by)
                        VALUES (gen_random_uuid(), :org_id, :slug, true, CAST(:user_id AS uuid))
                        ON CONFLICT (org_id, module_slug)
                        DO NOTHING
                    """),
                    {"org_id": org_id, "slug": slug, "user_id": user_id},
                )
                enabled_count += 1
            print(f"Modules enabled: {enabled_count}/{len(all_modules)}")

            # ---------------------------------------------------------
            # 6. Add org_override targeting rules to ALL feature flags
            #    so they evaluate to true for the demo org.
            # ---------------------------------------------------------
            flag_result = await session.execute(
                text("SELECT id, key, targeting_rules FROM feature_flags WHERE is_active = true")
            )
            all_flags = flag_result.fetchall()
            flags_updated = 0
            for flag_id, flag_key, targeting_rules in all_flags:
                rules = targeting_rules if isinstance(targeting_rules, list) else []
                # Check if org_override for this org already exists
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
                    import json
                    await session.execute(
                        text("""
                            UPDATE feature_flags
                            SET targeting_rules = CAST(:rules AS jsonb)
                            WHERE id = CAST(:fid AS uuid)
                        """),
                        {"rules": json.dumps(rules), "fid": str(flag_id)},
                    )
                    flags_updated += 1
            print(f"Feature flags with org_override: {flags_updated} added, {len(all_flags)} total")

        # ---------------------------------------------------------
        # Print credentials
        # ---------------------------------------------------------
        print()
        print("=" * 50)
        print("  DEMO ORG ADMIN CREDENTIALS")
        print("=" * 50)
        print(f"  Email:    {DEMO_EMAIL}")
        print(f"  Password: {DEMO_PASSWORD}")
        print(f"  Role:     {DEMO_ROLE}")
        print(f"  Org:      {ORG_NAME}")
        print(f"  Plan:     {PLAN_NAME} (private)")
        print("=" * 50)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

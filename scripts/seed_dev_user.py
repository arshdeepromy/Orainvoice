"""Seed a default dev admin user and organisation.

Run: python scripts/seed_dev_user.py

Creates:
  - A subscription plan (Dev Plan)
  - An organisation (OraInvoice Dev Org)
  - A global_admin user: admin@orainvoice.com / admin123

Idempotent — skips creation if the user already exists.
"""

from __future__ import annotations

import asyncio
import uuid
import sys
import os

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.modules.auth.password import hash_password


ADMIN_EMAIL = "admin@orainvoice.com"
ADMIN_PASSWORD = "admin123"
ADMIN_ROLE = "global_admin"
ORG_NAME = "OraInvoice Dev Org"
PLAN_NAME = "Dev Plan"


async def seed() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # Check if admin user already exists
            result = await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": ADMIN_EMAIL},
            )
            if result.scalar_one_or_none():
                print(f"User {ADMIN_EMAIL} already exists — skipping seed.")
                await engine.dispose()
                return

            # 1. Create a subscription plan
            plan_id = str(uuid.uuid4())
            await session.execute(
                text("""
                    INSERT INTO subscription_plans (id, name, monthly_price_nzd, user_seats, storage_quota_gb, carjam_lookups_included, enabled_modules, is_public)
                    VALUES (:id, :name, 0, 999, 100, 9999, '["all"]'::jsonb, true)
                """),
                {"id": plan_id, "name": PLAN_NAME},
            )
            print(f"Created subscription plan: {PLAN_NAME} ({plan_id})")

            # 2. Create an organisation
            org_id = str(uuid.uuid4())
            await session.execute(
                text("""
                    INSERT INTO organisations (id, name, plan_id, status, storage_quota_gb, settings)
                    VALUES (:id, :name, :plan_id, 'active', 100, '{}'::jsonb)
                """),
                {"id": org_id, "name": ORG_NAME, "plan_id": plan_id},
            )
            print(f"Created organisation: {ORG_NAME} ({org_id})")

            # 3. Create the admin user
            user_id = str(uuid.uuid4())
            pw_hash = hash_password(ADMIN_PASSWORD)
            await session.execute(
                text("""
                    INSERT INTO users (id, org_id, email, password_hash, role, is_active, is_email_verified)
                    VALUES (:id, :org_id, :email, :pw_hash, :role, true, true)
                """),
                {
                    "id": user_id,
                    "org_id": org_id,
                    "email": ADMIN_EMAIL,
                    "pw_hash": pw_hash,
                    "role": ADMIN_ROLE,
                },
            )
            print(f"Created admin user: {ADMIN_EMAIL} ({user_id})")
            print()
            print("=" * 50)
            print("  DEV LOGIN CREDENTIALS")
            print("=" * 50)
            print(f"  Email:    {ADMIN_EMAIL}")
            print(f"  Password: {ADMIN_PASSWORD}")
            print(f"  Role:     {ADMIN_ROLE}")
            print("=" * 50)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

"""Enable the accounting module for all organisations."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_session_factory
from sqlalchemy import text


async def enable_accounting():
    async with async_session_factory() as session:
        # Get all orgs
        result = await session.execute(text("SELECT id, name FROM organisations"))
        orgs = result.fetchall()
        print(f"Found {len(orgs)} organisations")

        # Check accounting module exists
        result = await session.execute(
            text("SELECT id, slug FROM module_registry WHERE slug = 'accounting'")
        )
        module = result.fetchone()
        if not module:
            print("ERROR: accounting module not found in module_registry")
            return

        print(f"Accounting module found: {module.id}")

        # Enable for all orgs
        for org in orgs:
            await session.execute(
                text(
                    "INSERT INTO org_modules (id, org_id, module_slug, is_enabled) "
                    "VALUES (gen_random_uuid(), :org_id, 'accounting', true) "
                    "ON CONFLICT (org_id, module_slug) DO UPDATE SET is_enabled = true"
                ),
                {"org_id": str(org.id)},
            )
            print(f"  Enabled accounting for: {org.name}")

        await session.commit()
        print("Done! Accounting module enabled for all orgs.")


if __name__ == "__main__":
    asyncio.run(enable_accounting())

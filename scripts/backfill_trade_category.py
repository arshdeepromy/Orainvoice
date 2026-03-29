"""Backfill trade_category_id on orgs that don't have one set.

Sets all NULL orgs to 'general-automotive' as the default.
"""
import asyncio
from sqlalchemy import text
from app.core.database import async_session_factory


async def main():
    async with async_session_factory() as session:
        # Get the general-automotive trade category ID
        r = await session.execute(
            text("SELECT id FROM trade_categories WHERE slug = 'general-automotive'")
        )
        row = r.fetchone()
        if not row:
            print("ERROR: general-automotive category not found in trade_categories")
            return
        cat_id = row[0]
        print(f"Found general-automotive category: {cat_id}")

        # Set it on all orgs that don't have one
        r2 = await session.execute(
            text("UPDATE organisations SET trade_category_id = :cat_id WHERE trade_category_id IS NULL RETURNING name"),
            {"cat_id": cat_id},
        )
        updated = r2.fetchall()
        await session.commit()
        for u in updated:
            print(f"  Updated: {u[0]}")
        print(f"Total updated: {len(updated)}")


if __name__ == "__main__":
    asyncio.run(main())

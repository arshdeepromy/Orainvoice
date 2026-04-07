"""Check demo user and org state."""
import asyncio
from app.core.database import async_session_factory
from sqlalchemy import text

async def main():
    async with async_session_factory() as db:
        r = await db.execute(text(
            "SELECT u.id, u.email, u.org_id, u.role, o.name, o.status "
            "FROM users u LEFT JOIN organisations o ON u.org_id = o.id "
            "WHERE u.email = 'demo@orainvoice.com'"
        ))
        row = r.first()
        if row:
            print(f"User: {row[1]}")
            print(f"  org_id: {row[2]}")
            print(f"  role: {row[3]}")
            print(f"  org_name: {row[4]}")
            print(f"  org_status: {row[5]}")
        else:
            print("NOT FOUND")

        # Check if org_modules exist
        if row and row[2]:
            r2 = await db.execute(text(
                "SELECT COUNT(*) FROM org_modules WHERE org_id = CAST(:oid AS uuid)"
            ), {"oid": str(row[2])})
            count = r2.scalar()
            print(f"  org_modules count: {count}")

        # Check branches
        if row and row[2]:
            r3 = await db.execute(text(
                "SELECT id, name, is_active FROM branches WHERE org_id = CAST(:oid AS uuid)"
            ), {"oid": str(row[2])})
            branches = r3.fetchall()
            print(f"  branches: {len(branches)}")
            for b in branches:
                print(f"    - {b[1]} (active={b[2]})")

asyncio.run(main())

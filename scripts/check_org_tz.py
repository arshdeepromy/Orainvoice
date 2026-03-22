"""Check org timezone and test invoice date conversion."""
import asyncio
from app.core.database import async_session_factory
from sqlalchemy import text

async def check():
    async with async_session_factory() as db:
        # Check columns
        r = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'organisations' ORDER BY ordinal_position"
        ))
        cols = [row[0] for row in r.all()]
        print("Columns:", cols)

        # Check org data
        r = await db.execute(text(
            "SELECT name, settings, locale FROM organisations LIMIT 1"
        ))
        row = r.first()
        if row:
            print(f"Org: {row[0]}, locale: {row[2]}")
            s = row[1] or {}
            print(f"settings timezone: {s.get('timezone', 'NOT SET')}")
            print(f"settings keys: {sorted(s.keys())}")

            # Check if timezone column exists
            if 'timezone' in cols:
                r2 = await db.execute(text(
                    "SELECT timezone FROM organisations LIMIT 1"
                ))
                tz_row = r2.first()
                print(f"timezone column value: {tz_row[0] if tz_row else 'NULL'}")

        # Check a payment's created_at
        r = await db.execute(text(
            "SELECT p.created_at, o.timezone "
            "FROM payments p "
            "JOIN invoices i ON p.invoice_id = i.id "
            "JOIN organisations o ON i.org_id = o.id "
            "LIMIT 1"
        ))
        prow = r.first()
        if prow:
            from app.core.timezone_utils import to_org_timezone
            utc_dt = prow[0]
            tz_name = prow[1] or "UTC"
            local_dt = to_org_timezone(utc_dt, tz_name)
            print(f"\nPayment UTC: {utc_dt}")
            print(f"Payment Local ({tz_name}): {local_dt}")
            print(f"Payment Local ISO: {local_dt.isoformat()}")
        else:
            print("\nNo payments found")

asyncio.run(check())

"""One-off script to update the invoice status check constraint."""
import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def fix():
    url = os.environ.get("DATABASE_URL", "")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE invoices DROP CONSTRAINT IF EXISTS ck_invoices_status")
        )
        await conn.execute(
            text(
                "ALTER TABLE invoices ADD CONSTRAINT ck_invoices_status "
                "CHECK (status IN ("
                "'draft','issued','partially_paid','paid','overdue',"
                "'voided','refunded','partially_refunded'"
                "))"
            )
        )
        print("Constraint updated successfully")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(fix())

"""Quick check: what template is configured for the demo org?"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_session_factory
from sqlalchemy import text

async def main():
    async with async_session_factory() as db:
        result = await db.execute(text("SELECT settings FROM organisations LIMIT 1"))
        row = result.fetchone()
        if row and row[0]:
            settings = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            print("invoice_template_id:", settings.get("invoice_template_id", "(not set)"))
            print("invoice_template_colours:", settings.get("invoice_template_colours", "(not set)"))
        else:
            print("No settings found")

asyncio.run(main())

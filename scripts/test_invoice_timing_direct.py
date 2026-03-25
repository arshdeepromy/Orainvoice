"""Direct timing of create_invoice — bypasses all middleware."""
import asyncio
import time
from sqlalchemy import text
from sqlalchemy.orm import configure_mappers

# Load ALL models
from app.modules.auth import models as _1
from app.modules.admin import models as _2
from app.modules.organisations import models as _3
from app.modules.customers import models as _4
from app.modules.suppliers import models as _5
from app.modules.catalogue import models as _6
from app.modules.inventory import models as _7
from app.modules.invoices import models as _8
from app.modules.vehicles import models as _9
from app.modules.billing import models as _10
from app.modules.stock import models as _11
from app.modules.quotes import models as _12
from app.modules.payments import models as _13
from app.modules.job_cards import models as _14
from app.modules.staff import models as _15
from app.modules.ha import models as _16
from app.modules.sms_chat import models as _17
configure_mappers()

from app.core.database import async_session_factory
from app.modules.invoices.service import create_invoice


async def test():
    async with async_session_factory() as db:
        row = await db.execute(text(
            "SELECT u.id, u.org_id FROM users u WHERE u.email = 'demo@orainvoice.com' LIMIT 1"
        ))
        user_id, org_id = row.fetchone()
        cust_row = await db.execute(text(
            "SELECT id FROM customers WHERE org_id = :oid LIMIT 1"
        ), {"oid": str(org_id)})
        customer_id = cust_row.fetchone()[0]
        print(f"User: {user_id}, Org: {org_id}, Customer: {customer_id}")

    async with async_session_factory() as db:
        async with db.begin():
            t0 = time.time()
            result = await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                status="sent",
                currency="NZD",
                line_items_data=[{
                    "item_type": "service",
                    "description": "Timing Test",
                    "quantity": 1,
                    "unit_price": 50,
                    "is_gst_exempt": False,
                }],
            )
            elapsed = time.time() - t0
            print(f"create_invoice: {elapsed:.3f}s")
            print(f"  Invoice: {result.get('id', '?')}")

asyncio.run(test())

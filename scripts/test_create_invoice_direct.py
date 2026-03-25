"""Direct test of create_invoice — bypasses all middleware."""
import asyncio
import time
import uuid
from sqlalchemy import select, text

async def test():
    # Force all models to load
    from app.modules.auth import models as _a1  # noqa
    from app.modules.admin import models as _a2  # noqa
    from app.modules.customers import models as _a3  # noqa
    from app.modules.suppliers import models as _a4  # noqa
    from app.modules.catalogue import models as _a5  # noqa
    from app.modules.inventory import models as _a5b  # noqa
    from app.modules.invoices import models as _a6  # noqa
    from app.modules.vehicles import models as _a7  # noqa
    from app.modules.billing import models as _a8  # noqa
    from app.modules.stock import models as _a9  # noqa

    from app.core.database import async_session_factory
    from app.modules.invoices.service import create_invoice

    # Get demo org + user
    async with async_session_factory() as db:
        row = await db.execute(text(
            "SELECT u.id, u.org_id FROM users u WHERE u.email = 'demo@orainvoice.com' LIMIT 1"
        ))
        user = row.fetchone()
        if not user:
            print("Demo user not found")
            return
        user_id, org_id = user[0], user[1]
        print(f"User: {user_id}, Org: {org_id}")

        # Get a customer
        cust_row = await db.execute(text(
            f"SELECT id FROM customers WHERE org_id = '{org_id}' LIMIT 1"
        ))
        cust = cust_row.fetchone()
        if not cust:
            print("No customer found")
            return
        customer_id = cust[0]
        print(f"Customer: {customer_id}")

    # Now create invoice
    async with async_session_factory() as db:
        async with db.begin():
            t0 = time.time()
            try:
                result = await create_invoice(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    status="sent",
                    currency="NZD",
                    line_items_data=[{
                        "item_type": "service",
                        "description": "Test Part",
                        "catalogue_item_id": "f1832470-b04b-4ef9-be07-a5aba99a8bf4",
                        "quantity": 1,
                        "unit_price": 89.95,
                        "is_gst_exempt": False,
                    }],
                )
                elapsed = time.time() - t0
                print(f"SUCCESS in {elapsed:.2f}s")
                print(f"  Invoice: {result.get('id', '?')}")
            except Exception as e:
                elapsed = time.time() - t0
                print(f"ERROR in {elapsed:.2f}s: {type(e).__name__}: {e}")

asyncio.run(test())

"""Direct test of adjust_stock — bypasses all middleware."""
import asyncio
import uuid
from app.core.database import async_session_factory
from app.modules.catalogue.models import PartsCatalogue, PartCategory
from app.modules.inventory.models import PartSupplier
from app.modules.suppliers.models import Supplier
from app.modules.admin.models import Organisation
from app.modules.auth.models import User
from app.modules.inventory.service import adjust_stock
from sqlalchemy import select

async def test():
    async with async_session_factory() as db:
        async with db.begin():
            # Find the demo org's first part
            result = await db.execute(
                select(PartsCatalogue).limit(1)
            )
            part = result.scalar_one_or_none()
            if not part:
                print("No parts found")
                return
            print(f"Part: {part.id} {part.name} stock={part.current_stock}")

            # Find a user in the same org
            user_result = await db.execute(
                select(User).where(User.org_id == part.org_id).limit(1)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                print("No user found")
                return
            print(f"User: {user.id} {user.email}")

            try:
                result = await adjust_stock(
                    db,
                    org_id=part.org_id,
                    user_id=user.id,
                    part_id=part.id,
                    quantity_change=5,
                    reason="received_from_supplier",
                )
                print(f"SUCCESS: {result}")
            except Exception as e:
                print(f"ERROR: {type(e).__name__}: {e}")

asyncio.run(test())

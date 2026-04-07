"""One-off script to list Xero bank accounts for the connected org."""
import asyncio

async def main():
    from app.core.database import async_session_factory
    from app.modules.accounting.models import AccountingIntegration
    from app.modules.accounting.service import _ensure_valid_token
    from app.integrations.xero import _xero_api_call, XERO_API_BASE
    from sqlalchemy import select

    async with async_session_factory() as db:
        async with db.begin():
            stmt = select(AccountingIntegration).where(
                AccountingIntegration.provider == "xero",
                AccountingIntegration.is_connected == True,
            )
            result = await db.execute(stmt)
            conn = result.scalar_one_or_none()
            if not conn:
                print("No Xero connection found")
                return

            token = await _ensure_valid_token(db, conn)
            if not token:
                print("Could not get valid token")
                return

            # Get ALL accounts from Xero (filter for BANK type)
            resp = await _xero_api_call(
                "GET", f"{XERO_API_BASE}/Accounts",
                access_token=token,
                tenant_id=conn.xero_tenant_id,
            )
            data = resp.json()
            print("=== BANK accounts ===")
            for acc in data.get("Accounts", []):
                if acc.get("Type") == "BANK":
                    print(f"  Code: {acc.get('Code')}  Name: {acc.get('Name')}  Status: {acc.get('Status')}")
            print("\n=== All account types ===")
            types = set()
            for acc in data.get("Accounts", []):
                types.add(acc.get("Type"))
            print(f"  Types found: {sorted(types)}")

asyncio.run(main())

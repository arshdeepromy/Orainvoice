"""Simulate Save and Send button — create invoice with catalogue part, time everything."""
import asyncio
import time
import httpx

BASE = "http://127.0.0.1:8000"

async def test():
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        # Login
        t0 = time.time()
        r = await c.post("/api/v1/auth/login", json={"email": "demo@orainvoice.com", "password": "demo123"})
        print(f"Login: {r.status_code} ({time.time()-t0:.2f}s)")
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # Get a customer
        t1 = time.time()
        r = await c.get("/api/v1/customers", headers=h, params={"limit": 1})
        customers = r.json().get("customers", [])
        cust_id = customers[0]["id"] if customers else None
        print(f"Get customer: {r.status_code} ({time.time()-t1:.2f}s) id={cust_id}")

        if not cust_id:
            print("No customers found")
            return

        # Build invoice payload — same as frontend "Save and Send"
        payload = {
            "customer_id": cust_id,
            "status": "sent",
            "currency": "NZD",
            "line_items": [
                {
                    "item_type": "service",
                    "description": "Brake Pad Set - Front",
                    "catalogue_item_id": "f1832470-b04b-4ef9-be07-a5aba99a8bf4",
                    "quantity": 2,
                    "unit_price": 89.95,
                    "is_gst_exempt": False,
                },
            ],
        }

        # Create invoice with timing
        print("\nCreating invoice (Save and Send)...")
        t2 = time.time()
        r = await c.post("/api/v1/invoices", json=payload, headers=h)
        elapsed = time.time() - t2
        print(f"POST /invoices: {r.status_code} ({elapsed:.2f}s)")
        if r.status_code >= 400:
            print(f"  Error: {r.text[:500]}")
        else:
            inv = r.json()
            print(f"  Invoice ID: {inv.get('id', inv.get('invoice', {}).get('id', '?'))}")

asyncio.run(test())

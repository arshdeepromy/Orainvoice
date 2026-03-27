"""Quick test: update a fluid/oil product."""
import httpx, asyncio

async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=15) as c:
        r = await c.post("/api/v1/auth/login", json={"email": "demo@orainvoice.com", "password": "demo123"})
        token = r.json().get("access_token")
        h = {"Authorization": f"Bearer {token}"}

        r2 = await c.get("/api/v1/catalogue/fluids", headers=h)
        products = r2.json().get("products", [])
        if not products:
            print("No products"); return

        pid = products[0]["id"]
        print(f"Updating {pid}...")

        r3 = await c.put(f"/api/v1/catalogue/fluids/{pid}", headers=h, json={
            "brand_name": "Updated Brand Test",
            "purchase_price": "2000.00",
            "sell_price_per_unit": "6.00",
            "gst_mode": "exclusive",
            "min_stock_volume": "50",
            "reorder_volume": "200",
        })
        print(f"Status: {r3.status_code}")
        print(f"Response: {r3.text[:300]}")

        if r3.status_code == 200:
            # Verify
            r4 = await c.get("/api/v1/catalogue/fluids", headers=h)
            updated = [p for p in r4.json().get("products", []) if p["id"] == pid]
            if updated:
                p = updated[0]
                print(f"✅ brand_name: {p['brand_name']}")
                print(f"✅ purchase_price: {p['purchase_price']}")
                print(f"✅ min_stock_volume: {p.get('min_stock_volume')}")
                print(f"✅ reorder_volume: {p.get('reorder_volume')}")
                print(f"✅ cost_per_unit: {p.get('cost_per_unit')}")
                print(f"✅ margin: {p.get('margin')}")
            else:
                print("❌ Product not found after update")
        else:
            print("❌ Update failed")

asyncio.run(main())


async def test_toggle():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=15) as c:
        r = await c.post("/api/v1/auth/login", json={"email": "demo@orainvoice.com", "password": "demo123"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r2 = await c.get("/api/v1/catalogue/fluids", headers=h)
        pid = r2.json()["products"][0]["id"]
        r3 = await c.put(f"/api/v1/catalogue/fluids/{pid}/toggle-active", headers=h)
        print(f"\nToggle: {r3.status_code} {r3.text[:100]}")

asyncio.run(test_toggle())

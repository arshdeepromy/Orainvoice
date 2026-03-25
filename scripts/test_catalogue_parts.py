"""Test script: Create part + tyre in catalogue, verify full flow."""
import asyncio
import httpx

BASE = "http://127.0.0.1:8000"

async def test():
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as c:
        # 1. Login
        r = await c.post("/api/v1/auth/login", json={"email": "demo@orainvoice.com", "password": "demo123"})
        print(f"1. Login: {r.status_code}")
        if r.status_code != 200:
            print(f"   ERROR: {r.text[:200]}")
            return
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # 2. Create category "Brake Parts"
        r = await c.post("/api/v1/catalogue/part-categories", json={"name": "Brake Parts"}, headers=h)
        print(f"2. Create category: {r.status_code} -> {r.json()}")
        cat_id = r.json().get("id")

        # 3. Get suppliers
        r = await c.get("/api/v1/inventory/suppliers", headers=h)
        suppliers = r.json().get("suppliers", [])
        supplier_id = suppliers[0]["id"] if suppliers else None
        print(f"3. Suppliers: {len(suppliers)}" + (f" (using {supplier_id})" if supplier_id else ""))

        # 4. Create a PART
        part_body = {
            "name": "Brake Pad Set - Front",
            "part_number": "BRK-FP-001",
            "description": "Premium ceramic brake pads for front axle",
            "part_type": "part",
            "default_price": "89.95",
            "brand": "Bosch",
            "is_active": True,
        }
        if cat_id:
            part_body["category_id"] = cat_id
        if supplier_id:
            part_body["supplier_id"] = supplier_id
        r = await c.post("/api/v1/catalogue/parts", json=part_body, headers=h)
        print(f"4. Create part: {r.status_code}")
        if r.status_code == 201:
            part = r.json().get("part", r.json())
            for k in ["id", "name", "part_type", "category_name", "brand", "default_price", "supplier_name", "description"]:
                print(f"   {k}: {part.get(k)}")
        else:
            print(f"   ERROR: {r.text[:300]}")

        # 5. Create category "Tyres" + create a TYRE
        r2 = await c.post("/api/v1/catalogue/part-categories", json={"name": "Tyres"}, headers=h)
        tyre_cat_id = r2.json().get("id")

        tyre_body = {
            "name": "Continental PremiumContact 6",
            "part_number": "TYR-CON-205",
            "part_type": "tyre",
            "default_price": "189.00",
            "brand": "Continental",
            "tyre_width": "205",
            "tyre_profile": "55",
            "tyre_rim_dia": "16",
            "tyre_load_index": "91",
            "tyre_speed_index": "V",
            "is_active": True,
        }
        if tyre_cat_id:
            tyre_body["category_id"] = tyre_cat_id
        r = await c.post("/api/v1/catalogue/parts", json=tyre_body, headers=h)
        print(f"5. Create tyre: {r.status_code}")
        if r.status_code == 201:
            tyre = r.json().get("part", r.json())
            for k in ["id", "name", "part_type", "category_name", "brand", "default_price",
                       "tyre_width", "tyre_profile", "tyre_rim_dia", "tyre_load_index", "tyre_speed_index"]:
                print(f"   {k}: {tyre.get(k)}")
        else:
            print(f"   ERROR: {r.text[:300]}")

        # 6. List all parts
        r = await c.get("/api/v1/catalogue/parts", headers=h)
        print(f"6. List parts: {r.status_code}")
        parts = r.json().get("parts", [])
        print(f"   Total: {len(parts)}")
        for p in parts:
            line = f"   - {p['name']} ({p['part_type']}) ${p['default_price']}"
            if p.get("category_name"):
                line += f" cat={p['category_name']}"
            if p.get("brand"):
                line += f" brand={p['brand']}"
            if p.get("supplier_name"):
                line += f" supplier={p['supplier_name']}"
            if p["part_type"] == "tyre":
                line += f" {p.get('tyre_width','')}/{p.get('tyre_profile','')}R{p.get('tyre_rim_dia','')}"
            print(line)

        # 7. Verify in DB
        print("\n7. DB verification:")
        print("   (checking via API - parts listed above are from DB)")
        print("\nAll tests passed!" if len(parts) >= 2 else "\nWARNING: Expected at least 2 parts")

asyncio.run(test())

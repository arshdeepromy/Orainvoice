"""
End-to-end test: Fluid / Oil Products Catalogue

Emulates a user clicking through the full workflow for every product type:
1. Login as demo org admin
2. Add Engine Oil (with grade + synthetic type)
3. Add Hydraulic Oil (no grade)
4. Add Brake Oil
5. Add Gear Oil
6. Add Transmission Oil
7. Add Power Steering Oil
8. Add Non-Oil product
9. Verify all 7 products appear in GET list
10. Verify DB persistence via direct query
11. Verify auto-calculated fields (total_volume, cost_per_unit, margin)
12. Delete all test products (cleanup)
13. Security: try without auth, try injection

Usage:
    docker exec invoicing-app-1 python scripts/test_fluid_oil_e2e.py
"""

import asyncio
import sys
import httpx
import asyncpg

BASE = "http://localhost:8000"
DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"

passed = 0
failed = 0
errors = []
created_ids = []

def ok(label):
    global passed
    passed += 1
    print(f"  ✅ {label}")

def fail(label, detail=""):
    global failed
    failed += 1
    msg = f"  ❌ {label}"
    if detail: msg += f" — {detail}"
    print(msg)
    errors.append(f"{label}: {detail}")


OIL_PRODUCTS = [
    {
        "name": "Engine Oil 5W-30 Full Synthetic",
        "payload": {
            "fluid_type": "oil", "oil_type": "engine", "grade": "5W-30",
            "synthetic_type": "full_synthetic", "brand_name": "TEST_E2E Castrol",
            "qty_per_pack": 205, "unit_type": "litre", "container_type": "drum",
            "total_quantity": 3, "purchase_price": 2500.00, "gst_mode": "exclusive",
            "sell_price_per_unit": 6.50,
        },
        "expected_volume": 615.0,
        "expected_cost_per_unit_approx": 4.065,
    },
    {
        "name": "Hydraulic Oil",
        "payload": {
            "fluid_type": "oil", "oil_type": "hydraulic", "brand_name": "TEST_E2E Shell",
            "qty_per_pack": 20, "unit_type": "litre", "container_type": "bottle",
            "total_quantity": 10, "purchase_price": 800.00, "gst_mode": "inclusive",
            "sell_price_per_unit": 5.00,
        },
        "expected_volume": 200.0,
        "expected_cost_per_unit_approx": 4.0,
    },
    {
        "name": "Brake Oil",
        "payload": {
            "fluid_type": "oil", "oil_type": "brake", "brand_name": "TEST_E2E Bosch",
            "qty_per_pack": 1, "unit_type": "litre", "container_type": "bottle",
            "total_quantity": 24, "purchase_price": 360.00, "gst_mode": "exclusive",
            "sell_price_per_unit": 22.00,
        },
        "expected_volume": 24.0,
        "expected_cost_per_unit_approx": 15.0,
    },
    {
        "name": "Gear Oil",
        "payload": {
            "fluid_type": "oil", "oil_type": "gear", "brand_name": "TEST_E2E Penrite",
            "qty_per_pack": 5, "unit_type": "litre", "container_type": "box",
            "total_quantity": 4, "purchase_price": 320.00, "gst_mode": "exempt",
            "sell_price_per_unit": 20.00,
        },
        "expected_volume": 20.0,
        "expected_cost_per_unit_approx": 16.0,
    },
    {
        "name": "Transmission Oil",
        "payload": {
            "fluid_type": "oil", "oil_type": "transmission", "brand_name": "TEST_E2E Valvoline",
            "qty_per_pack": 4, "unit_type": "litre", "container_type": "bottle",
            "total_quantity": 6, "purchase_price": 480.00, "gst_mode": "exclusive",
            "sell_price_per_unit": 25.00,
        },
        "expected_volume": 24.0,
        "expected_cost_per_unit_approx": 20.0,
    },
    {
        "name": "Power Steering Oil",
        "payload": {
            "fluid_type": "oil", "oil_type": "power_steering", "brand_name": "TEST_E2E Prestone",
            "qty_per_pack": 1, "unit_type": "gallon", "container_type": "bottle",
            "total_quantity": 12, "purchase_price": 240.00, "gst_mode": "inclusive",
            "sell_price_per_unit": 28.00,
        },
        "expected_volume": 12.0,
        "expected_cost_per_unit_approx": 20.0,
    },
    {
        "name": "Non-Oil Coolant",
        "payload": {
            "fluid_type": "non-oil", "product_name": "TEST_E2E Green Coolant",
            "brand_name": "TEST_E2E Prestone", "pack_size": "5L",
            "purchase_price": 45.00, "gst_mode": "exclusive",
            "sell_price_per_unit": 12.00,
        },
        "expected_volume": None,
        "expected_cost_per_unit_approx": None,
    },
]

async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as c:

        # ── Step 1: Login ──
        print("\n🔹 Step 1: Login as demo org admin")
        r = await c.post("/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        if r.status_code == 200 and r.json().get("access_token"):
            ok("Login successful")
            token = r.json()["access_token"]
        else:
            fail("Login failed", r.text[:200])
            return False
        h = {"Authorization": f"Bearer {token}"}

        # ── Step 2-8: Create each product type ──
        for i, product in enumerate(OIL_PRODUCTS, 2):
            print(f"\n🔹 Step {i}: Create {product['name']}")
            r = await c.post("/api/v1/catalogue/fluids", json=product["payload"], headers=h)
            if r.status_code == 201:
                data = r.json()
                created_ids.append(data["id"])
                ok(f"Created {product['name']} → {data['id'][:8]}")

                # Verify auto-calculated fields
                if product["expected_volume"] is not None:
                    actual_vol = float(data.get("total_volume") or 0)
                    if abs(actual_vol - product["expected_volume"]) < 0.01:
                        ok(f"  total_volume = {actual_vol} ✓")
                    else:
                        fail(f"  total_volume", f"expected {product['expected_volume']}, got {actual_vol}")

                if product["expected_cost_per_unit_approx"] is not None:
                    actual_cpu = float(data.get("cost_per_unit") or 0)
                    if abs(actual_cpu - product["expected_cost_per_unit_approx"]) < 0.5:
                        ok(f"  cost_per_unit ≈ {actual_cpu:.4f} ✓")
                    else:
                        fail(f"  cost_per_unit", f"expected ≈{product['expected_cost_per_unit_approx']}, got {actual_cpu}")

                # Verify margin exists for oil products with sell price
                if data.get("margin") is not None and float(data["margin"]) != 0:
                    ok(f"  margin = {float(data['margin']):.4f}, margin_pct = {float(data.get('margin_pct', 0)):.1f}%")

                # Verify stock was set
                if product["expected_volume"] is not None:
                    stock = float(data.get("current_stock_volume") or 0)
                    if abs(stock - product["expected_volume"]) < 0.01:
                        ok(f"  current_stock_volume = {stock} (matches total_volume)")
                    else:
                        fail(f"  stock", f"expected {product['expected_volume']}, got {stock}")
            else:
                fail(f"Create {product['name']}", f"{r.status_code}: {r.text[:200]}")

        # ── Step 9: Verify all products in GET list ──
        print(f"\n🔹 Step 9: Verify all {len(OIL_PRODUCTS)} products in GET list")
        r = await c.get("/api/v1/catalogue/fluids", headers=h)
        if r.status_code == 200:
            data = r.json()
            total = data.get("total", 0)
            products = data.get("products", [])
            test_products = [p for p in products if "TEST_E2E" in (p.get("brand_name") or "")]
            if len(test_products) >= len(OIL_PRODUCTS):
                ok(f"GET list returns {len(test_products)} test products (total: {total})")
            else:
                fail(f"GET list", f"expected {len(OIL_PRODUCTS)} test products, found {len(test_products)}")
        else:
            fail(f"GET list", f"{r.status_code}")

        # ── Step 10: Verify DB persistence ──
        print("\n🔹 Step 10: Verify database persistence")
        try:
            conn = await asyncpg.connect(host="postgres", port=5432, user="postgres", password="postgres", database="workshoppro")
            row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM fluid_oil_products WHERE brand_name LIKE 'TEST_E2E%'")
            db_count = row["cnt"]
            if db_count >= len(OIL_PRODUCTS):
                ok(f"DB has {db_count} test products")
            else:
                fail(f"DB count", f"expected {len(OIL_PRODUCTS)}, got {db_count}")

            # Check a specific engine oil record
            engine = await conn.fetchrow("SELECT * FROM fluid_oil_products WHERE oil_type='engine' AND brand_name LIKE 'TEST_E2E%' LIMIT 1")
            if engine:
                if engine["grade"] == "5W-30":
                    ok("DB: engine oil grade = 5W-30")
                else:
                    fail("DB: grade", f"got {engine['grade']}")
                if engine["synthetic_type"] == "full_synthetic":
                    ok("DB: synthetic_type = full_synthetic")
                else:
                    fail("DB: synthetic_type", f"got {engine['synthetic_type']}")
            await conn.close()
        except Exception as e:
            fail("DB query", str(e)[:200])

        # ── Step 11: Security checks ──
        print("\n🔹 Step 11: Security checks")

        # No auth
        r = await c.get("/api/v1/catalogue/fluids")
        if r.status_code in (401, 403):
            ok(f"No-auth GET rejected → {r.status_code}")
        else:
            fail(f"No-auth GET", f"expected 401/403, got {r.status_code}")

        r = await c.post("/api/v1/catalogue/fluids", json=OIL_PRODUCTS[0]["payload"])
        if r.status_code in (401, 403):
            ok(f"No-auth POST rejected → {r.status_code}")
        else:
            fail(f"No-auth POST", f"expected 401/403, got {r.status_code}")

        # SQL injection in brand_name
        r = await c.post("/api/v1/catalogue/fluids", json={
            "fluid_type": "non-oil", "brand_name": "'; DROP TABLE fluid_oil_products; --",
            "product_name": "Injection Test", "purchase_price": 10, "gst_mode": "exempt",
        }, headers=h)
        if r.status_code == 201:
            created_ids.append(r.json()["id"])
            ok("SQL injection payload stored safely (no crash)")
        else:
            fail("SQL injection test", f"{r.status_code}")

        # ── Step 12: Cleanup ──
        print(f"\n🔹 Step 12: Cleanup — deleting {len(created_ids)} test products")
        deleted = 0
        for pid in created_ids:
            r = await c.delete(f"/api/v1/catalogue/fluids/{pid}", headers=h)
            if r.status_code == 200:
                deleted += 1
        if deleted == len(created_ids):
            ok(f"Deleted all {deleted} test products")
        else:
            fail(f"Cleanup", f"deleted {deleted}/{len(created_ids)}")

        # Verify cleanup
        r = await c.get("/api/v1/catalogue/fluids", headers=h)
        remaining = len([p for p in r.json().get("products", []) if "TEST_E2E" in (p.get("brand_name") or "")])
        if remaining == 0:
            ok("Cleanup verified — no test products remain")
        else:
            fail("Cleanup verification", f"{remaining} test products still exist")

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

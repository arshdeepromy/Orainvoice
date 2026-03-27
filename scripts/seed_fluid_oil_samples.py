"""
Seed sample fluid/oil products for the demo org.
Creates one of each type so the Fluids/Oils tab has data to display.

Usage:
    docker exec invoicing-app-1 python scripts/seed_fluid_oil_samples.py
"""

import asyncio
import httpx

BASE = "http://localhost:8000"
EMAIL = "demo@orainvoice.com"
PASSWORD = "demo123"

SAMPLES = [
    {
        "fluid_type": "oil", "oil_type": "engine", "grade": "5W-30",
        "synthetic_type": "full_synthetic", "brand_name": "Castrol EDGE",
        "description": "Advanced full synthetic engine oil for modern engines",
        "qty_per_pack": 205, "unit_type": "litre", "container_type": "drum",
        "total_quantity": 2, "purchase_price": 1850.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 5.80,
    },
    {
        "fluid_type": "oil", "oil_type": "engine", "grade": "10W-40",
        "synthetic_type": "semi_synthetic", "brand_name": "Penrite HPR 10",
        "description": "Semi-synthetic multi-grade engine oil",
        "qty_per_pack": 20, "unit_type": "litre", "container_type": "bottle",
        "total_quantity": 6, "purchase_price": 540.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 6.00,
    },
    {
        "fluid_type": "oil", "oil_type": "engine", "grade": "15W-40",
        "synthetic_type": "mineral", "brand_name": "Shell Helix HX3",
        "description": "Mineral engine oil for older vehicles",
        "qty_per_pack": 5, "unit_type": "litre", "container_type": "bottle",
        "total_quantity": 12, "purchase_price": 360.00, "gst_mode": "inclusive",
        "sell_price_per_unit": 8.50,
    },
    {
        "fluid_type": "oil", "oil_type": "hydraulic", "brand_name": "Shell Tellus S2 V46",
        "description": "High performance hydraulic fluid",
        "qty_per_pack": 20, "unit_type": "litre", "container_type": "drum",
        "total_quantity": 4, "purchase_price": 640.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 9.50,
    },
    {
        "fluid_type": "oil", "oil_type": "brake", "brand_name": "Bosch ENV6",
        "description": "DOT 4 brake fluid for ABS systems",
        "qty_per_pack": 1, "unit_type": "litre", "container_type": "bottle",
        "total_quantity": 24, "purchase_price": 288.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 18.00,
    },
    {
        "fluid_type": "oil", "oil_type": "gear", "brand_name": "Penrite Pro Gear 75W-85",
        "description": "Full synthetic gear oil for manual transmissions",
        "qty_per_pack": 1, "unit_type": "litre", "container_type": "bottle",
        "total_quantity": 12, "purchase_price": 240.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 28.00,
    },
    {
        "fluid_type": "oil", "oil_type": "transmission", "brand_name": "Valvoline MaxLife ATF",
        "description": "Multi-vehicle automatic transmission fluid",
        "qty_per_pack": 4, "unit_type": "litre", "container_type": "bottle",
        "total_quantity": 6, "purchase_price": 420.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 22.00,
    },
    {
        "fluid_type": "oil", "oil_type": "power_steering", "brand_name": "Prestone Power Steering",
        "description": "Universal power steering fluid",
        "qty_per_pack": 1, "unit_type": "litre", "container_type": "bottle",
        "total_quantity": 12, "purchase_price": 144.00, "gst_mode": "inclusive",
        "sell_price_per_unit": 16.00,
    },
    {
        "fluid_type": "non-oil", "product_name": "Prestone Green Coolant",
        "brand_name": "Prestone", "pack_size": "5L",
        "description": "Long-life antifreeze/coolant concentrate",
        "purchase_price": 42.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 12.00,
    },
    {
        "fluid_type": "non-oil", "product_name": "Windscreen Washer Fluid",
        "brand_name": "Rain-X", "pack_size": "2L",
        "description": "All-season washer fluid with rain repellent",
        "purchase_price": 8.50, "gst_mode": "inclusive",
        "sell_price_per_unit": 5.00,
    },
    {
        "fluid_type": "non-oil", "product_name": "AdBlue DEF",
        "brand_name": "Yara", "pack_size": "10L",
        "description": "Diesel exhaust fluid for SCR systems",
        "purchase_price": 18.00, "gst_mode": "exclusive",
        "sell_price_per_unit": 3.50,
    },
]


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as c:
        r = await c.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
        token = r.json().get("access_token")
        if not token:
            print("❌ Login failed")
            return
        h = {"Authorization": f"Bearer {token}"}

        # Check existing
        r = await c.get("/api/v1/catalogue/fluids", headers=h)
        existing = len(r.json().get("products", []))
        if existing > 0:
            print(f"ℹ️  {existing} products already exist. Adding samples anyway.")

        created = 0
        for sample in SAMPLES:
            r = await c.post("/api/v1/catalogue/fluids", json=sample, headers=h)
            if r.status_code == 201:
                d = r.json()
                label = sample.get("brand_name", "") + " " + (sample.get("product_name") or sample.get("oil_type") or "")
                vol = d.get("total_volume")
                cpu = d.get("cost_per_unit")
                print(f"  ✅ {label.strip()} — vol:{vol} cpu:{cpu}")
                created += 1
            else:
                print(f"  ❌ Failed: {r.status_code} {r.text[:100]}")

        print(f"\n✅ Created {created}/{len(SAMPLES)} sample fluid/oil products")


if __name__ == "__main__":
    asyncio.run(main())

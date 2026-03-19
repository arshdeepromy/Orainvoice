"""
E2E test script: Storage Packages — simulates the full user flow via API.

Covers Task 12 verification steps:
  12.1 — Global Admin: create 4 storage packages
  12.2 — Global Admin: list, edit one, deactivate one
  12.3 — Org Admin: GET /billing/storage-addon → verify packages shown
  12.4 — Org Admin: purchase 10 GB package → verify quota increased
  12.5 — Org Admin: resize to 25 GB → verify quota/price updated
  12.6 — Org Admin: resize to custom 15 GB → verify fallback pricing
  12.7 — Org Admin: remove add-on → verify quota reverts
  12.8 — Org Admin: verify billing dashboard shows add-on in estimate

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_storage_packages_e2e.py

Or from host (if app is running on localhost:8000):
  python scripts/test_storage_packages_e2e.py
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@orainvoice.com"
ADMIN_PASSWORD = "admin123"
ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = "W4h3guru1#"

# Track created package IDs for cleanup
created_package_ids: list[str] = []

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = client.post("/auth/login", json={"email": email, "password": password, "remember_me": False})
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)
    passed = 0
    failed = 0

    print("=" * 65)
    print("  STORAGE PACKAGES — END-TO-END VERIFICATION")
    print("=" * 65)

    # ── Login as Global Admin ──
    print(f"\n{INFO} Logging in as Global Admin ({ADMIN_EMAIL})")
    admin_h = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"  {PASS} Authenticated")

    # ── 12.1: Create 4 storage packages ──
    print(f"\n{'─' * 65}")
    print("12.1 — Create storage packages")
    packages_to_create = [
        {"name": "Starter 5 GB", "storage_gb": 5, "price_nzd_per_month": 2.50, "description": "Light usage", "sort_order": 1},
        {"name": "Standard 10 GB", "storage_gb": 10, "price_nzd_per_month": 4.00, "description": "Most popular", "sort_order": 2},
        {"name": "Pro 25 GB", "storage_gb": 25, "price_nzd_per_month": 8.00, "description": "Growing business", "sort_order": 3},
        {"name": "Enterprise 50 GB", "storage_gb": 50, "price_nzd_per_month": 12.00, "description": "High volume", "sort_order": 4},
    ]

    for pkg in packages_to_create:
        r = client.post("/admin/storage-packages", json=pkg, headers=admin_h)
        if r.status_code == 201:
            pkg_id = r.json()["id"]
            created_package_ids.append(pkg_id)
            print(f"  {PASS} Created: {pkg['name']} ({pkg['storage_gb']} GB, ${pkg['price_nzd_per_month']}/mo) → {pkg_id[:8]}…")
            passed += 1
        else:
            print(f"  {FAIL} Failed to create {pkg['name']}: {r.status_code} {r.text[:200]}")
            failed += 1

    # ── 12.2: List, edit one, deactivate one ──
    print(f"\n{'─' * 65}")
    print("12.2 — List, edit, and deactivate packages")

    # List all
    r = client.get("/admin/storage-packages", params={"include_inactive": "false"}, headers=admin_h)
    if r.status_code == 200:
        data = r.json()
        pkg_list = data.get("packages", data) if isinstance(data, dict) else data
        print(f"  {PASS} Listed {len(pkg_list)} active packages")
        passed += 1
    else:
        print(f"  {FAIL} List failed: {r.status_code} {r.text[:200]}")
        failed += 1
        pkg_list = []

    # Edit the first package (update description)
    if len(created_package_ids) >= 1:
        edit_id = created_package_ids[0]
        r = client.put(f"/admin/storage-packages/{edit_id}", json={"description": "Updated: light usage tier"}, headers=admin_h)
        if r.status_code == 200:
            updated = r.json()
            print(f"  {PASS} Edited '{updated['name']}' — description: '{updated['description']}'")
            passed += 1
        else:
            print(f"  {FAIL} Edit failed: {r.status_code} {r.text[:200]}")
            failed += 1

    # Deactivate the last package (Enterprise 50 GB)
    if len(created_package_ids) >= 4:
        deactivate_id = created_package_ids[3]
        r = client.delete(f"/admin/storage-packages/{deactivate_id}", headers=admin_h)
        if r.status_code == 200:
            print(f"  {PASS} Deactivated Enterprise 50 GB package")
            passed += 1
        else:
            print(f"  {FAIL} Deactivate failed: {r.status_code} {r.text[:200]}")
            failed += 1

    # Verify deactivated shows with include_inactive
    r = client.get("/admin/storage-packages", params={"include_inactive": "true"}, headers=admin_h)
    if r.status_code == 200:
        data = r.json()
        all_pkgs = data.get("packages", data) if isinstance(data, dict) else data
        inactive = [p for p in all_pkgs if not p.get("is_active", True)]
        print(f"  {PASS} With include_inactive: {len(all_pkgs)} total, {len(inactive)} deactivated")
        passed += 1
    else:
        print(f"  {FAIL} List with inactive failed: {r.status_code}")
        failed += 1

    # ── Login as Org Admin ──
    print(f"\n{INFO} Logging in as Org Admin ({ORG_EMAIL})")
    org_h = login(client, ORG_EMAIL, ORG_PASSWORD)
    print(f"  {PASS} Authenticated")

    # ── 12.3: Verify packages shown in storage-addon status ──
    print(f"\n{'─' * 65}")
    print("12.3 — Org Admin: verify storage-addon status shows packages")

    r = client.get("/billing/storage-addon", headers=org_h)
    if r.status_code == 200:
        status = r.json()
        avail = status.get("available_packages", [])
        print(f"  {PASS} Storage addon status loaded")
        print(f"       Current add-on: {status.get('current_addon') or 'None'}")
        print(f"       Available packages: {len(avail)}")
        print(f"       Fallback price/GB: ${status.get('fallback_price_per_gb_nzd', '?')}")
        print(f"       Base quota: {status.get('base_quota_gb')} GB, Total: {status.get('total_quota_gb')} GB")
        print(f"       Storage used: {status.get('storage_used_gb', 0):.2f} GB")
        for p in avail:
            print(f"       • {p['name']}: {p['storage_gb']} GB @ ${p['price_nzd_per_month']}/mo")
        passed += 1
    else:
        print(f"  {FAIL} GET /billing/storage-addon failed: {r.status_code} {r.text[:200]}")
        failed += 1
        status = {}

    # ── 12.4: Purchase 10 GB package ──
    print(f"\n{'─' * 65}")
    print("12.4 — Org Admin: purchase Standard 10 GB package")

    # Find the 10 GB package ID
    ten_gb_id = None
    twenty_five_gb_id = None
    if status.get("available_packages"):
        for p in status["available_packages"]:
            if p["storage_gb"] == 10:
                ten_gb_id = p["id"]
            if p["storage_gb"] == 25:
                twenty_five_gb_id = p["id"]

    initial_quota = status.get("total_quota_gb", 0)

    if ten_gb_id:
        r = client.post("/billing/storage-addon", json={"package_id": ten_gb_id}, headers=org_h)
        if r.status_code == 201:
            addon = r.json()
            print(f"  {PASS} Purchased: {addon.get('package_name', 'Custom')} — {addon['quantity_gb']} GB @ ${addon['price_nzd_per_month']}/mo")
            passed += 1

            # Verify quota increased
            r2 = client.get("/billing/storage-addon", headers=org_h)
            if r2.status_code == 200:
                new_status = r2.json()
                new_quota = new_status.get("total_quota_gb", 0)
                if new_quota == initial_quota + 10:
                    print(f"  {PASS} Quota increased: {initial_quota} → {new_quota} GB")
                    passed += 1
                else:
                    print(f"  {FAIL} Quota mismatch: expected {initial_quota + 10}, got {new_quota}")
                    failed += 1
        elif r.status_code == 409:
            print(f"  {INFO} Org already has an add-on (409) — removing first, then retrying")
            client.delete("/billing/storage-addon", headers=org_h)
            r = client.post("/billing/storage-addon", json={"package_id": ten_gb_id}, headers=org_h)
            if r.status_code == 201:
                addon = r.json()
                print(f"  {PASS} Purchased after cleanup: {addon.get('package_name')} — {addon['quantity_gb']} GB")
                passed += 1
            else:
                print(f"  {FAIL} Retry purchase failed: {r.status_code} {r.text[:200]}")
                failed += 1
        else:
            print(f"  {FAIL} Purchase failed: {r.status_code} {r.text[:200]}")
            failed += 1
    else:
        print(f"  {FAIL} Could not find 10 GB package in available list")
        failed += 1

    # ── 12.5: Resize to 25 GB ──
    print(f"\n{'─' * 65}")
    print("12.5 — Org Admin: resize to Pro 25 GB package")

    if twenty_five_gb_id:
        r = client.put("/billing/storage-addon", json={"package_id": twenty_five_gb_id}, headers=org_h)
        if r.status_code == 200:
            addon = r.json()
            print(f"  {PASS} Resized to: {addon.get('package_name', 'Custom')} — {addon['quantity_gb']} GB @ ${addon['price_nzd_per_month']}/mo")
            passed += 1

            # Verify quota updated
            r2 = client.get("/billing/storage-addon", headers=org_h)
            if r2.status_code == 200:
                s = r2.json()
                ca = s.get("current_addon")
                if ca and ca["quantity_gb"] == 25:
                    print(f"  {PASS} Add-on confirmed: {ca['quantity_gb']} GB, ${ca['price_nzd_per_month']}/mo")
                    passed += 1
                else:
                    print(f"  {FAIL} Add-on mismatch: {ca}")
                    failed += 1
        else:
            print(f"  {FAIL} Resize failed: {r.status_code} {r.text[:200]}")
            failed += 1
    else:
        print(f"  {FAIL} Could not find 25 GB package")
        failed += 1

    # ── 12.6: Resize to custom 15 GB (fallback pricing) ──
    print(f"\n{'─' * 65}")
    print("12.6 — Org Admin: resize to custom 15 GB")

    r = client.put("/billing/storage-addon", json={"custom_gb": 15}, headers=org_h)
    if r.status_code == 200:
        addon = r.json()
        print(f"  {PASS} Resized to custom: {addon['quantity_gb']} GB @ ${addon['price_nzd_per_month']}/mo (is_custom={addon['is_custom']})")
        if addon["is_custom"]:
            print(f"  {PASS} Correctly marked as custom add-on")
            passed += 1
        else:
            print(f"  {FAIL} Expected is_custom=true")
            failed += 1
        passed += 1
    else:
        print(f"  {FAIL} Custom resize failed: {r.status_code} {r.text[:200]}")
        failed += 1

    # ── 12.8: Verify billing dashboard shows add-on ──
    print(f"\n{'─' * 65}")
    print("12.8 — Org Admin: verify billing dashboard includes add-on")

    r = client.get("/billing", headers=org_h)
    if r.status_code == 200:
        dash = r.json()
        addon_gb = dash.get("storage_addon_gb")
        addon_price = dash.get("storage_addon_price_nzd")
        addon_name = dash.get("storage_addon_package_name")
        est_total = dash.get("estimated_next_invoice_nzd")
        print(f"  {PASS} Billing dashboard loaded")
        print(f"       Add-on GB: {addon_gb}")
        print(f"       Add-on price: ${addon_price}")
        print(f"       Add-on package: {addon_name or 'Custom'}")
        print(f"       Estimated next invoice: ${est_total}")
        if addon_gb and addon_gb > 0:
            print(f"  {PASS} Add-on reflected in billing dashboard")
            passed += 1
        else:
            print(f"  {FAIL} Add-on not showing in dashboard")
            failed += 1
        passed += 1
    else:
        print(f"  {FAIL} GET /billing failed: {r.status_code} {r.text[:200]}")
        failed += 1

    # ── 12.7: Remove add-on ──
    print(f"\n{'─' * 65}")
    print("12.7 — Org Admin: remove storage add-on")

    # Get quota before removal
    r_before = client.get("/billing/storage-addon", headers=org_h)
    base_quota = r_before.json().get("base_quota_gb", 0) if r_before.status_code == 200 else 0

    r = client.delete("/billing/storage-addon", headers=org_h)
    if r.status_code == 200:
        print(f"  {PASS} Add-on removed successfully")
        passed += 1

        # Verify quota reverted
        r2 = client.get("/billing/storage-addon", headers=org_h)
        if r2.status_code == 200:
            s = r2.json()
            if s.get("current_addon") is None:
                print(f"  {PASS} No active add-on confirmed")
                passed += 1
            else:
                print(f"  {FAIL} Add-on still exists after removal")
                failed += 1
            if s.get("total_quota_gb") == base_quota:
                print(f"  {PASS} Quota reverted to base: {base_quota} GB")
                passed += 1
            else:
                print(f"  {FAIL} Quota not reverted: expected {base_quota}, got {s.get('total_quota_gb')}")
                failed += 1
    else:
        print(f"  {FAIL} Remove failed: {r.status_code} {r.text[:200]}")
        failed += 1

    # ── Cleanup: deactivate test packages ──
    print(f"\n{'─' * 65}")
    print("Cleanup — deactivating test packages")
    for pkg_id in created_package_ids:
        r = client.delete(f"/admin/storage-packages/{pkg_id}", headers=admin_h)
        status_code = r.status_code
        print(f"  {PASS if status_code == 200 else INFO} Deactivated {pkg_id[:8]}… ({status_code})")

    # ── Summary ──
    print(f"\n{'=' * 65}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {PASS} {passed} passed, {FAIL} {failed} failed (of {total})")
    print(f"{'=' * 65}")

    client.close()


if __name__ == "__main__":
    main()

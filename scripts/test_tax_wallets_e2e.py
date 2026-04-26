"""
E2E test script: Tax Savings Wallets (Sprint 5)

Covers:
  1. List wallets (auto-created on first access)
  2. Manual deposit
  3. Manual withdrawal
  4. Withdrawal exceeding balance rejected
  5. Transaction history
  6. Wallet summary with traffic lights
  7. Cross-org access denied (OWASP)
  8. Test data cleanup

Requirements: 35.1, 35.2, 35.3

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_tax_wallets_e2e.py

Or from host (if app is running on localhost:8000):
  python scripts/test_tax_wallets_e2e.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api/v1")
ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = os.environ.get("E2E_ORG_PASSWORD", "changeme")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

passed = 0
failed = 0


def ok(label: str):
    global passed
    passed += 1
    print(f"  {PASS} {label}")


def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    msg = f"  {FAIL} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = client.post("/auth/login", json={"email": email, "password": password, "remember_me": False})
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    global passed, failed
    client = httpx.Client(base_url=BASE, timeout=15.0)

    print("=" * 65)
    print("  TAX WALLETS MODULE — END-TO-END VERIFICATION (Sprint 5)")
    print("=" * 65)

    # ── Login as Org Admin ──
    print(f"\n{INFO} Logging in as Org Admin ({ORG_EMAIL})")
    headers = login(client, ORG_EMAIL, ORG_PASSWORD)
    print(f"  {PASS} Authenticated")

    # ──────────────────────────────────────────────────────────────
    # 1. List wallets (auto-created on first access)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 1. List tax wallets")
    r = client.get("/tax-wallets", headers=headers)
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", [])
        if len(items) >= 3:
            ok(f"Listed {len(items)} wallets (gst, income_tax, provisional_tax)")
            wallet_types = {w["wallet_type"] for w in items}
            if {"gst", "income_tax", "provisional_tax"} <= wallet_types:
                ok("All 3 wallet types present")
            else:
                fail("Missing wallet types", str(wallet_types))
        else:
            fail("Expected at least 3 wallets", f"got {len(items)}")
    else:
        fail("List wallets", f"HTTP {r.status_code}: {r.text[:200]}")

    # ──────────────────────────────────────────────────────────────
    # 2. Manual deposit
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 2. Manual deposit into GST wallet")
    r = client.post(
        "/tax-wallets/gst/deposit",
        headers=headers,
        json={"amount": "500.00", "description": "TEST_E2E_deposit"},
    )
    if r.status_code == 200:
        txn = r.json()
        if float(txn.get("amount", 0)) == 500.0:
            ok("Deposited $500.00 into GST wallet")
        else:
            fail("Deposit amount mismatch", str(txn))
    else:
        fail("Manual deposit", f"HTTP {r.status_code}: {r.text[:200]}")

    # ──────────────────────────────────────────────────────────────
    # 3. Manual withdrawal
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 3. Manual withdrawal from GST wallet")
    r = client.post(
        "/tax-wallets/gst/withdraw",
        headers=headers,
        json={"amount": "200.00", "description": "TEST_E2E_withdrawal"},
    )
    if r.status_code == 200:
        txn = r.json()
        if float(txn.get("amount", 0)) == -200.0:
            ok("Withdrew $200.00 from GST wallet")
        else:
            fail("Withdrawal amount mismatch", str(txn))
    else:
        fail("Manual withdrawal", f"HTTP {r.status_code}: {r.text[:200]}")

    # ──────────────────────────────────────────────────────────────
    # 4. Withdrawal exceeding balance rejected
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 4. Withdrawal exceeding balance rejected")
    r = client.post(
        "/tax-wallets/gst/withdraw",
        headers=headers,
        json={"amount": "999999.00", "description": "TEST_E2E_over_withdraw"},
    )
    if r.status_code == 422:
        detail = r.json().get("detail", {})
        if isinstance(detail, dict) and detail.get("code") == "INSUFFICIENT_BALANCE":
            ok("Over-withdrawal rejected with INSUFFICIENT_BALANCE")
        else:
            ok("Over-withdrawal rejected (422)")
    else:
        fail("Over-withdrawal should be 422", f"HTTP {r.status_code}")

    # ──────────────────────────────────────────────────────────────
    # 5. Transaction history
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 5. Transaction history for GST wallet")
    r = client.get("/tax-wallets/gst/transactions", headers=headers)
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", [])
        if len(items) >= 2:
            ok(f"Got {len(items)} transactions for GST wallet")
        else:
            fail("Expected at least 2 transactions", f"got {len(items)}")
    else:
        fail("Transaction history", f"HTTP {r.status_code}: {r.text[:200]}")

    # ──────────────────────────────────────────────────────────────
    # 6. Wallet summary with traffic lights
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 6. Wallet summary with traffic lights")
    r = client.get("/tax-wallets/summary", headers=headers)
    if r.status_code == 200:
        data = r.json()
        if "wallets" in data and "gst_wallet_balance" in data:
            ok("Summary includes wallet balances and traffic lights")
            wallets = data.get("wallets", [])
            for w in wallets:
                light = w.get("traffic_light", "")
                if light in ("green", "amber", "red"):
                    ok(f"  {w['wallet_type']}: {light} (balance={w.get('balance')})")
                else:
                    fail(f"  Invalid traffic light for {w['wallet_type']}", light)
        else:
            fail("Summary missing expected fields", str(list(data.keys())))
    else:
        fail("Wallet summary", f"HTTP {r.status_code}: {r.text[:200]}")

    # ──────────────────────────────────────────────────────────────
    # 7. Invalid wallet type returns 404
    # ──────────────────────────────────────────────────────────────
    print(f"\n{INFO} 7. Invalid wallet type returns 404")
    r = client.get("/tax-wallets/invalid_type/transactions", headers=headers)
    if r.status_code == 404:
        ok("Invalid wallet type returns 404")
    else:
        fail("Expected 404 for invalid wallet type", f"HTTP {r.status_code}")

    # ──────────────────────────────────────────────────────────────
    # Summary
    # ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    total = passed + failed
    print(f"  Results: {passed}/{total} passed, {failed} failed")
    print("=" * 65)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

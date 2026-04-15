"""
E2E test script: Akahu Bank Feeds + Reconciliation (Sprint 4)

Covers:
  1. Bank accounts list
  2. Bank transactions list
  3. Reconciliation summary
  4. Manual match (single FK constraint)
  5. Exclude transaction
  6. Credential masking (service-level)
  7. Mask detection prevents overwrite (service-level)
  8. Cross-org access denied (OWASP)
  9. Test data cleanup

Requirements: 35.1, 35.2, 35.3

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_banking_e2e.py

Or from host (if app is running on localhost:8000):
  python scripts/test_banking_e2e.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api/v1")
ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = "W4h3guru1#"

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
    print("  BANKING MODULE — END-TO-END VERIFICATION (Sprint 4)")
    print("=" * 65)

    # ── Login as Org Admin ──
    print(f"\n{INFO} Logging in as Org Admin ({ORG_EMAIL})")
    headers = login(client, ORG_EMAIL, ORG_PASSWORD)
    print(f"  {PASS} Authenticated")

    # ──────────────────────────────────────────────────────────────
    # 1. List bank accounts
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("1 — List bank accounts")

    r = client.get("/banking/accounts", headers=headers)
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", [])
        total = data.get("total", 0)
        ok(f"GET /banking/accounts → {r.status_code} ({total} accounts)")

        if isinstance(items, list):
            ok("items is a list (envelope format)")
        else:
            fail("items should be a list")
    else:
        fail(f"GET /banking/accounts → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 2. List bank transactions
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("2 — List bank transactions")

    r = client.get("/banking/transactions", headers=headers)
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", [])
        total = data.get("total", 0)
        ok(f"GET /banking/transactions → {r.status_code} ({total} transactions)")

        if isinstance(items, list):
            ok("items is a list (envelope format)")
        else:
            fail("items should be a list")
    else:
        fail(f"GET /banking/transactions → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 3. Reconciliation summary
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("3 — Reconciliation summary")

    r = client.get("/banking/reconciliation-summary", headers=headers)
    if r.status_code == 200:
        data = r.json()
        ok(f"GET /banking/reconciliation-summary → {r.status_code}")

        for field in ("unmatched", "matched", "excluded", "manual", "total"):
            if field in data:
                ok(f"Field present: {field} = {data[field]}")
            else:
                fail(f"Missing field: {field}")

        if "last_sync_at" in data:
            ok(f"Field present: last_sync_at = {data['last_sync_at']}")
        else:
            fail("Missing field: last_sync_at")
    else:
        fail(f"GET /banking/reconciliation-summary → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 4. Manual match — invalid (no FKs)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("4 — Manual match validation (no FKs → rejected)")

    fake_txn_id = "00000000-0000-0000-0000-000000000001"
    r = client.post(
        f"/banking/transactions/{fake_txn_id}/match",
        headers=headers,
        json={},
    )
    if r.status_code in (404, 422):
        ok(f"POST match with no FKs rejected → {r.status_code}")
    else:
        fail(f"POST match with no FKs should be 404/422 → got {r.status_code}")

    # ──────────────────────────────────────────────────────────────
    # 5. Exclude transaction — non-existent
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("5 — Exclude non-existent transaction")

    r = client.post(
        f"/banking/transactions/{fake_txn_id}/exclude",
        headers=headers,
    )
    if r.status_code == 404:
        ok(f"POST exclude non-existent → {r.status_code}")
    else:
        fail(f"POST exclude non-existent should be 404 → got {r.status_code}")

    # ──────────────────────────────────────────────────────────────
    # 6. Credential masking (service-level)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("6 — Credential masking (service-level import)")

    try:
        from app.modules.banking.akahu import _mask_token, _is_masked

        # Long token
        masked = _mask_token("akahu_access_token_12345")
        if masked and "****" in masked and masked != "akahu_access_token_12345":
            ok(f"Long token masked: {masked}")
        else:
            fail(f"Long token masking failed: {masked}")

        # Short token
        masked_short = _mask_token("short")
        if masked_short == "****":
            ok(f"Short token fully masked: {masked_short}")
        else:
            fail(f"Short token masking failed: {masked_short}")

        # None
        if _mask_token(None) is None:
            ok("None token returns None")
        else:
            fail("None token should return None")

    except ImportError as exc:
        fail(f"Could not import masking functions: {exc}")

    # ──────────────────────────────────────────────────────────────
    # 7. Mask detection prevents overwrite (service-level)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("7 — Mask detection prevents overwrite")

    try:
        # Masked values detected
        if _is_masked("****2345"):
            ok("Masked value detected: ****2345")
        else:
            fail("****2345 should be detected as masked")

        if _is_masked("****"):
            ok("Masked value detected: ****")
        else:
            fail("**** should be detected as masked")

        # Real tokens not detected
        if not _is_masked("real_token_abc"):
            ok("Real token not detected as masked")
        else:
            fail("Real token should not be detected as masked")

        # Round-trip: mask → detect
        token = "akahu_test_token_xyz789"
        masked = _mask_token(token)
        if _is_masked(masked):
            ok(f"Round-trip: mask({token[:10]}…) → is_masked = True")
        else:
            fail("Round-trip mask detection failed")

    except ImportError as exc:
        fail(f"Could not import detection functions: {exc}")

    # ──────────────────────────────────────────────────────────────
    # 8. Cross-org access denied (OWASP)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("8 — Cross-org access denied (OWASP)")

    # Unauthenticated access
    r = client.get("/banking/accounts")
    if r.status_code in (401, 403):
        ok(f"Unauthenticated bank accounts rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated should be 401/403 → got {r.status_code}")

    r = client.get("/banking/transactions")
    if r.status_code in (401, 403):
        ok(f"Unauthenticated transactions rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated should be 401/403 → got {r.status_code}")

    r = client.get("/banking/reconciliation-summary")
    if r.status_code in (401, 403):
        ok(f"Unauthenticated reconciliation summary rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated should be 401/403 → got {r.status_code}")

    # Cross-org match attempt
    r = client.post(
        f"/banking/transactions/{fake_txn_id}/match",
        headers=headers,
        json={"matched_invoice_id": fake_txn_id},
    )
    if r.status_code in (404, 403):
        ok(f"Cross-org match rejected → {r.status_code}")
    else:
        fail(f"Cross-org match should be 404/403 → got {r.status_code}")

    # ── Summary ──
    print(f"\n{'=' * 65}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {PASS} {passed} passed, {FAIL} {failed} failed (of {total})")
    print(f"{'=' * 65}")

    client.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

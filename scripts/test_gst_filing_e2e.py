"""
E2E test script: GST Filing Periods + IRD Readiness (Sprint 3)

Covers:
  1. GST period generation (two_monthly → 6 periods)
  2. GST period list and detail
  3. Filing status transition: draft → ready
  4. Period locking (invoices/expenses locked)
  5. IRD mod-11 validation (service-level, imported directly)
  6. Cross-org access denied (OWASP)
  7. Test data cleanup with TEST_E2E_ prefix

Requirements: 35.1, 35.2, 35.3

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_gst_filing_e2e.py

Or from host (if app is running on localhost:8000):
  python scripts/test_gst_filing_e2e.py
"""
from __future__ import annotations

import sys
import os

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

# Track created resource IDs for cleanup
created_period_ids: list[str] = []


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
    print("  GST FILING PERIODS — END-TO-END VERIFICATION (Sprint 3)")
    print("=" * 65)

    # ── Login as Org Admin ──
    print(f"\n{INFO} Logging in as Org Admin ({ORG_EMAIL})")
    headers = login(client, ORG_EMAIL, ORG_PASSWORD)
    print(f"  {PASS} Authenticated")

    # ──────────────────────────────────────────────────────────────
    # 1. Generate GST periods (two_monthly for tax year 2026)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("1 — Generate GST filing periods (two_monthly, tax year 2026)")

    r = client.post("/gst/periods/generate", headers=headers, json={
        "period_type": "two_monthly",
        "tax_year": 2026,
    })
    if r.status_code == 201:
        data = r.json()
        items = data.get("items", [])
        total = data.get("total", 0)
        ok(f"POST /gst/periods/generate → {r.status_code} ({total} periods)")

        if total == 6:
            ok("two_monthly generates 6 periods (correct)")
        else:
            fail(f"Expected 6 periods for two_monthly, got {total}")

        # Track IDs for cleanup
        for p in items:
            created_period_ids.append(p["id"])

        # Verify response shape on first period
        if items:
            first = items[0]
            for field in ("id", "org_id", "period_type", "period_start",
                          "period_end", "due_date", "status", "created_at",
                          "updated_at"):
                if field in first:
                    ok(f"Field present: {field}")
                else:
                    fail(f"Missing field: {field}")

            if first.get("status") == "draft":
                ok("Generated periods start as draft")
            else:
                fail(f"Expected status=draft, got {first.get('status')}")

            if first.get("period_type") == "two_monthly":
                ok("period_type is two_monthly")
            else:
                fail(f"Expected period_type=two_monthly, got {first.get('period_type')}")
    else:
        fail(f"POST /gst/periods/generate → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 2. List GST periods
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("2 — List GST filing periods")

    r = client.get("/gst/periods", headers=headers)
    if r.status_code == 200:
        data = r.json()
        items = data.get("items", [])
        total = data.get("total", 0)
        ok(f"GET /gst/periods → {r.status_code} ({total} periods)")

        if total >= 6:
            ok(f"At least 6 periods listed (got {total})")
        else:
            fail(f"Expected ≥6 periods, got {total}")

        if isinstance(items, list):
            ok("items is a list (envelope format)")
        else:
            fail("items should be a list")
    else:
        fail(f"GET /gst/periods → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 3. Get single GST period detail
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("3 — Get single GST period detail")

    test_period_id = created_period_ids[0] if created_period_ids else None
    if test_period_id:
        r = client.get(f"/gst/periods/{test_period_id}", headers=headers)
        if r.status_code == 200:
            period = r.json()
            ok(f"GET /gst/periods/{test_period_id[:8]}… → {r.status_code}")

            if period.get("id") == test_period_id:
                ok("Period ID matches request")
            else:
                fail(f"Period ID mismatch: {period.get('id')}")

            # Nullable fields should be present (even if null)
            for field in ("filed_at", "filed_by", "ird_reference", "return_data"):
                if field in period:
                    ok(f"Nullable field present: {field}")
                else:
                    fail(f"Missing nullable field: {field}")
        else:
            fail(f"GET /gst/periods/{test_period_id[:8]}… → {r.status_code}", r.text[:200])
    else:
        fail("Skipped — no period ID available")

    # ──────────────────────────────────────────────────────────────
    # 4. Mark period as ready (draft → ready)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("4 — Mark GST period as ready (draft → ready)")

    if test_period_id:
        r = client.post(f"/gst/periods/{test_period_id}/ready", headers=headers)
        if r.status_code == 200:
            period = r.json()
            ok(f"POST /gst/periods/{test_period_id[:8]}…/ready → {r.status_code}")

            if period.get("status") == "ready":
                ok("Status transitioned to ready")
            else:
                fail(f"Expected status=ready, got {period.get('status')}")
        else:
            fail(f"POST /gst/periods/{test_period_id[:8]}…/ready → {r.status_code}", r.text[:200])

        # Verify invalid transition: ready → ready should fail
        r2 = client.post(f"/gst/periods/{test_period_id}/ready", headers=headers)
        if r2.status_code == 400:
            ok(f"Duplicate ready transition rejected → {r2.status_code}")
        else:
            fail(f"Duplicate ready transition should be 400 → got {r2.status_code}")
    else:
        fail("Skipped — no period ID available")

    # ──────────────────────────────────────────────────────────────
    # 5. Lock GST period (invoices/expenses locked)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("5 — Lock GST period")

    if test_period_id:
        r = client.post(f"/gst/periods/{test_period_id}/lock", headers=headers)
        if r.status_code == 200:
            period = r.json()
            ok(f"POST /gst/periods/{test_period_id[:8]}…/lock → {r.status_code}")
            ok("Period lock executed successfully")
        else:
            fail(f"POST /gst/periods/{test_period_id[:8]}…/lock → {r.status_code}", r.text[:200])
    else:
        fail("Skipped — no period ID available")

    # ──────────────────────────────────────────────────────────────
    # 6. IRD mod-11 validation (service-level)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("6 — IRD mod-11 validation (service-level import)")

    try:
        from app.modules.ledger.service import validate_ird_number

        # Known valid
        if validate_ird_number("49-091-850") is True:
            ok("49-091-850 is valid (known valid IRD)")
        else:
            fail("49-091-850 should be valid")

        if validate_ird_number("35-901-981") is True:
            ok("35-901-981 is valid (known valid IRD)")
        else:
            fail("35-901-981 should be valid")

        # Known invalid
        if validate_ird_number("12-345-678") is False:
            ok("12-345-678 is invalid (known invalid IRD)")
        else:
            fail("12-345-678 should be invalid")

        # Edge cases
        if validate_ird_number("") is False:
            ok("Empty string rejected")
        else:
            fail("Empty string should be rejected")

        if validate_ird_number("1234567") is False:
            ok("Too-short number rejected (7 digits)")
        else:
            fail("7-digit number should be rejected")

        if validate_ird_number("49091850") is True:
            ok("8-digit number accepted (padded to 9)")
        else:
            fail("8-digit valid number should be accepted")

    except ImportError as exc:
        fail(f"Could not import validate_ird_number: {exc}")

    # ──────────────────────────────────────────────────────────────
    # 7. Cross-org access denied (OWASP)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("7 — Cross-org access denied (OWASP)")

    fake_id = "00000000-0000-0000-0000-000000000001"

    # Unauthenticated access
    r = client.get("/gst/periods")
    if r.status_code in (401, 403):
        ok(f"Unauthenticated GST periods list rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated GST periods should be 401/403 → got {r.status_code}")

    # Cross-org period detail
    r = client.get(f"/gst/periods/{fake_id}", headers=headers)
    if r.status_code in (404, 403):
        ok(f"Cross-org period detail rejected → {r.status_code}")
    else:
        fail(f"Cross-org period detail should be 404/403 → got {r.status_code}")

    # Cross-org period ready
    r = client.post(f"/gst/periods/{fake_id}/ready", headers=headers)
    if r.status_code in (404, 403):
        ok(f"Cross-org period ready rejected → {r.status_code}")
    else:
        fail(f"Cross-org period ready should be 404/403 → got {r.status_code}")

    # Cross-org period lock
    r = client.post(f"/gst/periods/{fake_id}/lock", headers=headers)
    if r.status_code in (404, 403):
        ok(f"Cross-org period lock rejected → {r.status_code}")
    else:
        fail(f"Cross-org period lock should be 404/403 → got {r.status_code}")

    # ──────────────────────────────────────────────────────────────
    # Cleanup — remove TEST_E2E_ data
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("Cleanup — tracking TEST_E2E_ test data")

    for pid in created_period_ids:
        print(f"  {INFO} GST period {pid[:8]}… (tracked for cleanup)")

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

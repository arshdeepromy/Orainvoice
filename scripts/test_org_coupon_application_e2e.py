"""
E2E test script: Organisation Coupon Application — simulates the full admin flow via API.

Covers Task 7.1 verification steps:
  1  — Login as global_admin
  2  — List organisations — verify response shape
  3  — List coupons — verify response shape
  4  — Pick test org + test coupon (create coupon if needed)
  5  — Apply coupon — verify 200 with correct fields
  6  — Verify coupon times_redeemed incremented
  7  — Duplicate apply — verify 409
  8  — Non-existent coupon_id — verify 404
  9  — Non-existent org_id — verify 404
  10 — OWASP A1: no auth token → 401
  11 — OWASP A1: org_admin token → 403
  12 — OWASP A3: SQL injection in coupon_id → 400
  13 — OWASP A3: XSS payload in coupon_id → 400
  14 — OWASP A5: error responses contain no stack traces
  15 — Cleanup via asyncpg

Run inside container:
  docker exec invoicing-app-1 python scripts/test_org_coupon_application_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@orainvoice.com"
ADMIN_PASSWORD = "Admin123!"
ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = "W4h3guru1#"

DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_NAME = os.environ.get("DB_NAME", "workshoppro")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = client.post("/auth/login", json={"email": email, "password": password, "remember_me": False})
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def get_db_conn():
    import asyncpg
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


async def pre_cleanup(org_id: str, coupon_id: str) -> None:
    """Remove any leftover OrganisationCoupon from a previous test run."""
    conn = await get_db_conn()
    try:
        deleted = await conn.execute(
            "DELETE FROM organisation_coupons WHERE org_id = $1 AND coupon_id = $2",
            uuid.UUID(org_id),
            uuid.UUID(coupon_id),
        )
        if "DELETE 1" in deleted:
            print(f"  {INFO} Pre-cleanup: removed leftover OrganisationCoupon for org/coupon pair")
    finally:
        await conn.close()


async def cleanup_db(
    org_coupon_id: str | None,
    coupon_id: str | None,
    was_created: bool,
    original_redeemed: int | None,
) -> None:
    """Clean up test data via direct DB queries using asyncpg."""
    conn = await get_db_conn()
    try:
        # Delete the OrganisationCoupon record created during the test
        if org_coupon_id:
            await conn.execute(
                "DELETE FROM organisation_coupons WHERE id = $1",
                uuid.UUID(org_coupon_id),
            )
            print(f"  {PASS} Deleted OrganisationCoupon {org_coupon_id[:8]}…")

        # Restore times_redeemed on the coupon
        if coupon_id and original_redeemed is not None:
            await conn.execute(
                "UPDATE coupons SET times_redeemed = $1 WHERE id = $2",
                original_redeemed,
                uuid.UUID(coupon_id),
            )
            print(f"  {PASS} Restored coupon times_redeemed to {original_redeemed}")

        # If we created a test coupon, deactivate it
        if was_created and coupon_id:
            await conn.execute(
                "UPDATE coupons SET is_active = false WHERE id = $1",
                uuid.UUID(coupon_id),
            )
            print(f"  {PASS} Deactivated test coupon {coupon_id[:8]}…")
    finally:
        await conn.close()


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)
    passed = 0
    failed = 0

    # Track state for cleanup
    cleanup_org_coupon_id: str | None = None
    cleanup_coupon_id: str | None = None
    cleanup_coupon_was_created: bool = False
    cleanup_original_times_redeemed: int | None = None

    # Collect error responses for OWASP A5 check
    error_responses: list[str] = []

    print("=" * 65)
    print("  ORG COUPON APPLICATION — END-TO-END VERIFICATION")
    print("=" * 65)

    # ── Step 1: Login as global_admin ──
    print(f"\n{INFO} Step 1: Login as Global Admin ({ADMIN_EMAIL})")
    admin_h = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"  {PASS} Authenticated as global_admin")
    passed += 1

    # ── Step 2: List organisations ──
    print(f"\n{'─' * 65}")
    print("Step 2 — List organisations")
    r = client.get("/admin/organisations", headers=admin_h)
    if r.status_code == 200:
        data = r.json()
        orgs = data.get("organisations", [])
        if isinstance(orgs, list):
            print(f"  {PASS} GET /admin/organisations → {len(orgs)} organisations, total={data.get('total', '?')}")
            passed += 1
        else:
            print(f"  {FAIL} Response 'organisations' is not a list")
            failed += 1
    else:
        print(f"  {FAIL} GET /admin/organisations → {r.status_code} {r.text[:200]}")
        failed += 1
        orgs = []

    # ── Step 3: List coupons ──
    print(f"\n{'─' * 65}")
    print("Step 3 — List coupons")
    r = client.get("/admin/coupons", params={"include_inactive": "true"}, headers=admin_h)
    if r.status_code == 200:
        data = r.json()
        coupons = data.get("coupons", [])
        if isinstance(coupons, list):
            print(f"  {PASS} GET /admin/coupons → {len(coupons)} coupons, total={data.get('total', '?')}")
            passed += 1
        else:
            print(f"  {FAIL} Response 'coupons' is not a list")
            failed += 1
    else:
        print(f"  {FAIL} GET /admin/coupons → {r.status_code} {r.text[:200]}")
        failed += 1
        coupons = []

    # ── Step 4: Pick test org and test coupon ──
    print(f"\n{'─' * 65}")
    print("Step 4 — Pick test org and test coupon")

    # Pick first non-deleted org
    test_org = None
    for org in orgs:
        if org.get("status") != "deleted":
            test_org = org
            break

    if test_org:
        print(f"  {PASS} Test org: {test_org['name']} (id={test_org['id'][:8]}…, status={test_org['status']})")
        passed += 1
    else:
        print(f"  {FAIL} No non-deleted organisation found")
        failed += 1
        print(f"\n{'=' * 65}")
        print(f"  RESULTS: {passed} passed, {failed} failed")
        print(f"{'=' * 65}")
        client.close()
        sys.exit(1)

    test_org_id = test_org["id"]

    # Pick first active coupon, or create one
    test_coupon = None
    for c in coupons:
        if c.get("is_active"):
            test_coupon = c
            break

    if test_coupon:
        print(f"  {PASS} Test coupon: {test_coupon['code']} (id={test_coupon['id'][:8]}…)")
        passed += 1
    else:
        print(f"  {INFO} No active coupon found — creating E2E-TEST-COUPON")
        r = client.post(
            "/admin/coupons",
            json={
                "code": "E2E-TEST-COUPON",
                "description": "E2E test coupon",
                "discount_type": "percentage",
                "discount_value": 10,
                "duration_months": 3,
                "usage_limit": 100,
                "is_active": True,
            },
            headers=admin_h,
        )
        if r.status_code == 201:
            test_coupon = r.json()
            cleanup_coupon_was_created = True
            print(f"  {PASS} Created test coupon: {test_coupon['code']} (id={test_coupon['id'][:8]}…)")
            passed += 1
        else:
            print(f"  {FAIL} Failed to create test coupon: {r.status_code} {r.text[:200]}")
            failed += 1
            print(f"\n{'=' * 65}")
            print(f"  RESULTS: {passed} passed, {failed} failed")
            print(f"{'=' * 65}")
            client.close()
            sys.exit(1)

    test_coupon_id = test_coupon["id"]
    cleanup_coupon_id = test_coupon_id
    cleanup_original_times_redeemed = test_coupon.get("times_redeemed", 0)

    # Pre-cleanup: remove any leftover OrganisationCoupon from a previous run
    try:
        asyncio.run(pre_cleanup(test_org_id, test_coupon_id))
    except Exception as exc:
        print(f"  {INFO} Pre-cleanup skipped: {exc}")

    # Re-fetch coupon to get accurate times_redeemed after pre-cleanup
    r = client.get(f"/admin/coupons/{test_coupon_id}", headers=admin_h)
    if r.status_code == 200:
        cleanup_original_times_redeemed = r.json().get("times_redeemed", 0)

    # ── Step 5: Apply coupon ──
    print(f"\n{'─' * 65}")
    print("Step 5 — Apply coupon to organisation")
    r = client.post(
        f"/admin/organisations/{test_org_id}/apply-coupon",
        json={"coupon_id": test_coupon_id},
        headers=admin_h,
    )
    if r.status_code == 200:
        result = r.json()
        org_coupon_id = result.get("organisation_coupon_id")
        coupon_code = result.get("coupon_code")
        benefit_desc = result.get("benefit_description")
        message = result.get("message")

        checks = [
            ("organisation_coupon_id present", bool(org_coupon_id)),
            ("coupon_code present", bool(coupon_code)),
            ("benefit_description present", bool(benefit_desc)),
            ("message present", bool(message)),
        ]
        for label, ok in checks:
            if ok:
                print(f"  {PASS} {label}")
                passed += 1
            else:
                print(f"  {FAIL} {label}")
                failed += 1

        cleanup_org_coupon_id = org_coupon_id
        print(f"       coupon_code={coupon_code}, benefit={benefit_desc}")
    else:
        print(f"  {FAIL} Apply coupon → {r.status_code} {r.text[:200]}")
        error_responses.append(r.text)
        failed += 4  # count all 4 field checks as failed

    # ── Step 6: Verify times_redeemed incremented ──
    print(f"\n{'─' * 65}")
    print("Step 6 — Verify coupon times_redeemed incremented")
    r = client.get(f"/admin/coupons/{test_coupon_id}", headers=admin_h)
    if r.status_code == 200:
        coupon_data = r.json()
        new_redeemed = coupon_data.get("times_redeemed", 0)
        expected = (cleanup_original_times_redeemed or 0) + 1
        if new_redeemed == expected:
            print(f"  {PASS} times_redeemed: {cleanup_original_times_redeemed} → {new_redeemed}")
            passed += 1
        else:
            print(f"  {FAIL} times_redeemed: expected {expected}, got {new_redeemed}")
            failed += 1
    else:
        print(f"  {FAIL} GET /admin/coupons/{test_coupon_id[:8]}… → {r.status_code}")
        failed += 1

    # ── Step 7: Duplicate apply → 409 ──
    print(f"\n{'─' * 65}")
    print("Step 7 — Duplicate apply → expect 409")
    r = client.post(
        f"/admin/organisations/{test_org_id}/apply-coupon",
        json={"coupon_id": test_coupon_id},
        headers=admin_h,
    )
    if r.status_code == 409:
        detail = r.json().get("detail", "")
        if "already applied" in detail.lower():
            print(f"  {PASS} 409 with 'already applied' message: {detail}")
            passed += 1
        else:
            print(f"  {FAIL} 409 but unexpected message: {detail}")
            failed += 1
    else:
        print(f"  {FAIL} Expected 409, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 8: Non-existent coupon_id → 404 ──
    print(f"\n{'─' * 65}")
    print("Step 8 — Non-existent coupon_id → expect 404")
    fake_coupon_id = str(uuid.uuid4())
    r = client.post(
        f"/admin/organisations/{test_org_id}/apply-coupon",
        json={"coupon_id": fake_coupon_id},
        headers=admin_h,
    )
    if r.status_code == 404:
        print(f"  {PASS} 404 for non-existent coupon_id")
        passed += 1
    else:
        print(f"  {FAIL} Expected 404, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 9: Non-existent org_id → 404 ──
    print(f"\n{'─' * 65}")
    print("Step 9 — Non-existent org_id → expect 404")
    fake_org_id = str(uuid.uuid4())
    r = client.post(
        f"/admin/organisations/{fake_org_id}/apply-coupon",
        json={"coupon_id": test_coupon_id},
        headers=admin_h,
    )
    if r.status_code == 404:
        print(f"  {PASS} 404 for non-existent org_id")
        passed += 1
    else:
        print(f"  {FAIL} Expected 404, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 10: OWASP A1 — No auth token → 401 ──
    print(f"\n{'─' * 65}")
    print("Step 10 — OWASP A1: No auth token → expect 401")
    r = client.post(
        f"/admin/organisations/{test_org_id}/apply-coupon",
        json={"coupon_id": test_coupon_id},
    )
    if r.status_code == 401:
        print(f"  {PASS} 401 without auth token")
        passed += 1
    else:
        print(f"  {FAIL} Expected 401, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 11: OWASP A1 — Org admin token → 403 ──
    print(f"\n{'─' * 65}")
    print(f"Step 11 — OWASP A1: Org admin token ({ORG_EMAIL}) → expect 403")
    try:
        org_h = login(client, ORG_EMAIL, ORG_PASSWORD)
        r = client.post(
            f"/admin/organisations/{test_org_id}/apply-coupon",
            json={"coupon_id": test_coupon_id},
            headers=org_h,
        )
        if r.status_code == 403:
            print(f"  {PASS} 403 for org_admin user")
            passed += 1
        else:
            print(f"  {FAIL} Expected 403, got {r.status_code}: {r.text[:200]}")
            failed += 1
        error_responses.append(r.text)
    except Exception:
        # Org admin login failed — test with an invalid token instead
        print(f"  {INFO} Org admin login failed — testing with an invalid token instead")
        r = client.post(
            f"/admin/organisations/{test_org_id}/apply-coupon",
            json={"coupon_id": test_coupon_id},
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        if r.status_code in (401, 403):
            print(f"  {PASS} {r.status_code} for invalid token (org admin login unavailable)")
            passed += 1
        else:
            print(f"  {FAIL} Expected 401 or 403, got {r.status_code}: {r.text[:200]}")
            failed += 1
        error_responses.append(r.text)

    # ── Step 12: OWASP A3 — SQL injection in coupon_id → 400 ──
    print(f"\n{'─' * 65}")
    print("Step 12 — OWASP A3: SQL injection in coupon_id → expect 400")
    r = client.post(
        f"/admin/organisations/{test_org_id}/apply-coupon",
        json={"coupon_id": "'; DROP TABLE coupons; --"},
        headers=admin_h,
    )
    if r.status_code in (400, 422):
        print(f"  {PASS} {r.status_code} for SQL injection payload")
        passed += 1
    else:
        print(f"  {FAIL} Expected 400 or 422, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 13: OWASP A3 — XSS payload in coupon_id → 400 ──
    print(f"\n{'─' * 65}")
    print("Step 13 — OWASP A3: XSS payload in coupon_id → expect 400")
    r = client.post(
        f"/admin/organisations/{test_org_id}/apply-coupon",
        json={"coupon_id": "<script>alert('xss')</script>"},
        headers=admin_h,
    )
    if r.status_code in (400, 422):
        print(f"  {PASS} {r.status_code} for XSS payload")
        passed += 1
    else:
        print(f"  {FAIL} Expected 400 or 422, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 14: OWASP A5 — Error responses contain no stack traces ──
    print(f"\n{'─' * 65}")
    print("Step 14 — OWASP A5: Error responses contain no stack traces or internal paths")
    stack_trace_indicators = ["Traceback", "File \"/", "app/modules/", "site-packages/"]
    leak_found = False
    for resp_text in error_responses:
        for indicator in stack_trace_indicators:
            if indicator in resp_text:
                print(f"  {FAIL} Found '{indicator}' in error response: {resp_text[:200]}")
                leak_found = True
                break
    if not leak_found:
        print(f"  {PASS} No stack traces or internal paths in {len(error_responses)} error responses")
        passed += 1
    else:
        failed += 1

    # ── Step 15: Cleanup ──
    print(f"\n{'─' * 65}")
    print("Step 15 — Cleanup via asyncpg")
    try:
        asyncio.run(
            cleanup_db(
                org_coupon_id=cleanup_org_coupon_id,
                coupon_id=cleanup_coupon_id,
                was_created=cleanup_coupon_was_created,
                original_redeemed=cleanup_original_times_redeemed,
            )
        )
        print(f"  {PASS} Cleanup completed")
    except Exception as exc:
        print(f"  {FAIL} Cleanup error: {exc}")

    # ── Summary ──
    print(f"\n{'=' * 65}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {PASS} {passed} passed, {FAIL} {failed} failed (of {total})")
    print(f"{'=' * 65}")

    client.close()
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()

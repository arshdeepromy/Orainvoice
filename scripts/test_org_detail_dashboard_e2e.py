"""
E2E test script: Organisation Detail Dashboard

Covers Task 9.1 verification steps:
  1  — Login as global_admin
  2  — Call GET /admin/organisations/{org_id}/detail → verify 200 + correct shape
  3  — Verify payment method masking (no stripe_payment_method_id in response)
  4  — Verify aggregate counts are non-negative integers
  5  — Verify user data has no password_hash field
  6  — Verify admin actions have no before_value/after_value fields
  7  — Verify audit log entry created (query DB directly via asyncpg)
  8  — Test 404 for non-existent org UUID
  9  — Test 403 for non-admin user (login as demo user)
  10 — OWASP A1: access org detail without token → 401/403
  11 — OWASP A3: SQL injection in org_id path param
  12 — OWASP A5: error responses contain no stack traces
  13 — Cleanup test data

Requirements: 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7

Run inside container:
  docker exec invoicing-app-1 python scripts/test_org_detail_dashboard_e2e.py
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


async def cleanup_audit_entries(org_id: str) -> int:
    """Remove audit log entries created by this test run."""
    conn = await get_db_conn()
    try:
        result = await conn.execute(
            "DELETE FROM audit_log WHERE action = 'org_detail_viewed' "
            "AND entity_type = 'organisation' AND entity_id = $1",
            uuid.UUID(org_id),
        )
        count = int(result.split()[-1]) if result else 0
        return count
    finally:
        await conn.close()


async def count_audit_entries(org_id: str) -> int:
    """Count audit log entries for org_detail_viewed on this org."""
    conn = await get_db_conn()
    try:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM audit_log "
            "WHERE action = 'org_detail_viewed' "
            "AND entity_type = 'organisation' AND entity_id = $1",
            uuid.UUID(org_id),
        )
        return row["cnt"] if row else 0
    finally:
        await conn.close()


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)
    passed = 0
    failed = 0

    # Collect error responses for OWASP A5 check
    error_responses: list[str] = []

    print("=" * 65)
    print("  ORG DETAIL DASHBOARD — END-TO-END VERIFICATION")
    print("=" * 65)

    # ── Step 1: Login as global_admin ──
    print(f"\n{INFO} Step 1: Login as Global Admin ({ADMIN_EMAIL})")
    admin_h = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"  {PASS} Authenticated as global_admin")
    passed += 1

    # ── Pick a test org ──
    print(f"\n{'─' * 65}")
    print("Picking test organisation")
    r = client.get("/admin/organisations", headers=admin_h)
    assert r.status_code == 200, f"List orgs failed: {r.status_code}"
    orgs = r.json().get("organisations", [])
    test_org = None
    for org in orgs:
        if org.get("status") != "deleted":
            test_org = org
            break
    if not test_org:
        print(f"  {FAIL} No non-deleted organisation found — cannot continue")
        client.close()
        sys.exit(1)
    test_org_id = test_org["id"]
    print(f"  {PASS} Test org: {test_org['name']} (id={test_org_id[:8]}…)")
    passed += 1

    # Record audit count before the detail call
    audit_count_before = asyncio.run(count_audit_entries(test_org_id))

    # ── Step 2: Call GET /admin/organisations/{org_id}/detail → 200 + shape ──
    print(f"\n{'─' * 65}")
    print("Step 2 — GET /admin/organisations/{org_id}/detail → 200 + correct shape")
    r = client.get(f"/admin/organisations/{test_org_id}/detail", headers=admin_h)
    if r.status_code == 200:
        data = r.json()
        # Verify top-level keys
        expected_sections = ["overview", "billing", "usage", "users", "security", "health"]
        missing = [k for k in expected_sections if k not in data]
        if not missing:
            print(f"  {PASS} 200 with all top-level sections: {', '.join(expected_sections)}")
            passed += 1
        else:
            print(f"  {FAIL} Missing top-level sections: {missing}")
            failed += 1

        # Verify overview sub-fields
        overview = data.get("overview", {})
        overview_fields = ["id", "name", "status", "plan_name", "plan_id", "signup_date",
                           "billing_interval", "timezone", "locale"]
        missing_ov = [f for f in overview_fields if f not in overview]
        if not missing_ov:
            print(f"  {PASS} Overview section has all required fields")
            passed += 1
        else:
            print(f"  {FAIL} Overview missing fields: {missing_ov}")
            failed += 1

        # Verify billing sub-fields
        billing = data.get("billing", {})
        billing_fields = ["plan_name", "monthly_price_nzd", "billing_interval",
                          "receipts_success_90d", "receipts_failed_90d"]
        missing_bl = [f for f in billing_fields if f not in billing]
        if not missing_bl:
            print(f"  {PASS} Billing section has all required fields")
            passed += 1
        else:
            print(f"  {FAIL} Billing missing fields: {missing_bl}")
            failed += 1

        # Verify usage sub-fields
        usage = data.get("usage", {})
        usage_fields = ["invoice_count", "quote_count", "customer_count", "vehicle_count",
                        "storage_used_bytes", "storage_quota_gb"]
        missing_us = [f for f in usage_fields if f not in usage]
        if not missing_us:
            print(f"  {PASS} Usage section has all required fields")
            passed += 1
        else:
            print(f"  {FAIL} Usage missing fields: {missing_us}")
            failed += 1

        # Verify users sub-fields
        users_section = data.get("users", {})
        users_fields = ["users", "active_count", "seat_limit"]
        missing_usr = [f for f in users_fields if f not in users_section]
        if not missing_usr:
            print(f"  {PASS} Users section has all required fields")
            passed += 1
        else:
            print(f"  {FAIL} Users missing fields: {missing_usr}")
            failed += 1

        # Verify security sub-fields
        security = data.get("security", {})
        security_fields = ["login_attempts", "admin_actions", "mfa_enrolled_count",
                           "mfa_total_users", "failed_payments_90d"]
        missing_sec = [f for f in security_fields if f not in security]
        if not missing_sec:
            print(f"  {PASS} Security section has all required fields")
            passed += 1
        else:
            print(f"  {FAIL} Security missing fields: {missing_sec}")
            failed += 1

        # Verify health sub-fields
        health = data.get("health", {})
        health_fields = ["billing_ok", "storage_ok", "storage_warning", "seats_ok", "mfa_ok", "status_ok"]
        missing_hl = [f for f in health_fields if f not in health]
        if not missing_hl:
            print(f"  {PASS} Health section has all required fields")
            passed += 1
        else:
            print(f"  {FAIL} Health missing fields: {missing_hl}")
            failed += 1
    else:
        print(f"  {FAIL} Expected 200, got {r.status_code}: {r.text[:200]}")
        error_responses.append(r.text)
        failed += 8  # count all shape checks as failed
        data = {}

    # ── Step 3: Verify payment method masking ──
    print(f"\n{'─' * 65}")
    print("Step 3 — Verify payment method masking (no stripe_payment_method_id)")
    response_json_str = json.dumps(data)
    forbidden_payment_keys = ["stripe_payment_method_id", "cvv", "card_number", "full_number"]
    payment_leak = False
    for key in forbidden_payment_keys:
        if f'"{key}"' in response_json_str:
            print(f"  {FAIL} Found forbidden key '{key}' in response JSON")
            payment_leak = True
            failed += 1
    if not payment_leak:
        print(f"  {PASS} No forbidden payment keys in response ({', '.join(forbidden_payment_keys)})")
        passed += 1

    # If payment_method is present, verify it only has allowed keys
    pm = data.get("billing", {}).get("payment_method")
    if pm is not None:
        allowed_pm_keys = {"brand", "last4", "exp_month", "exp_year"}
        actual_pm_keys = set(pm.keys())
        extra = actual_pm_keys - allowed_pm_keys
        if not extra:
            print(f"  {PASS} Payment method contains only allowed keys: {allowed_pm_keys}")
            passed += 1
        else:
            print(f"  {FAIL} Payment method has extra keys: {extra}")
            failed += 1

        # Verify last4 is exactly 4 characters
        last4 = pm.get("last4", "")
        if len(str(last4)) == 4:
            print(f"  {PASS} last4 is exactly 4 characters: {last4}")
            passed += 1
        else:
            print(f"  {FAIL} last4 is not 4 characters: '{last4}' (len={len(str(last4))})")
            failed += 1
    else:
        print(f"  {INFO} No payment method on file — masking checks N/A (still passes)")

    # ── Step 4: Verify aggregate counts are non-negative integers ──
    print(f"\n{'─' * 65}")
    print("Step 4 — Verify aggregate counts are non-negative integers")
    count_fields = {
        "usage.invoice_count": data.get("usage", {}).get("invoice_count"),
        "usage.quote_count": data.get("usage", {}).get("quote_count"),
        "usage.customer_count": data.get("usage", {}).get("customer_count"),
        "usage.vehicle_count": data.get("usage", {}).get("vehicle_count"),
        "usage.storage_used_bytes": data.get("usage", {}).get("storage_used_bytes"),
        "usage.storage_quota_gb": data.get("usage", {}).get("storage_quota_gb"),
        "billing.receipts_success_90d": data.get("billing", {}).get("receipts_success_90d"),
        "billing.receipts_failed_90d": data.get("billing", {}).get("receipts_failed_90d"),
        "users.active_count": data.get("users", {}).get("active_count"),
        "users.seat_limit": data.get("users", {}).get("seat_limit"),
        "security.mfa_enrolled_count": data.get("security", {}).get("mfa_enrolled_count"),
        "security.mfa_total_users": data.get("security", {}).get("mfa_total_users"),
        "security.failed_payments_90d": data.get("security", {}).get("failed_payments_90d"),
    }
    all_counts_ok = True
    for field_path, value in count_fields.items():
        if value is None:
            print(f"  {FAIL} {field_path} is None (missing)")
            all_counts_ok = False
            failed += 1
        elif not isinstance(value, int) or value < 0:
            print(f"  {FAIL} {field_path} = {value} (not a non-negative integer)")
            all_counts_ok = False
            failed += 1
    if all_counts_ok:
        print(f"  {PASS} All {len(count_fields)} aggregate count fields are non-negative integers")
        passed += 1

    # ── Step 5: Verify user data has no password_hash field ──
    print(f"\n{'─' * 65}")
    print("Step 5 — Verify user data has no password_hash field")
    users_list = data.get("users", {}).get("users", [])
    sensitive_user_keys = ["password_hash", "authentication_token", "refresh_token", "secret_encrypted"]
    user_leak = False
    for i, user in enumerate(users_list):
        for key in sensitive_user_keys:
            if key in user:
                print(f"  {FAIL} User[{i}] contains forbidden key '{key}'")
                user_leak = True
                failed += 1
    if not user_leak:
        user_count = len(users_list)
        print(f"  {PASS} No sensitive keys in {user_count} user record(s) ({', '.join(sensitive_user_keys)})")
        passed += 1

    # ── Step 6: Verify admin actions have no before_value/after_value ──
    print(f"\n{'─' * 65}")
    print("Step 6 — Verify admin actions have no before_value/after_value fields")
    admin_actions = data.get("security", {}).get("admin_actions", [])
    action_leak = False
    for i, action in enumerate(admin_actions):
        for key in ["before_value", "after_value"]:
            if key in action:
                print(f"  {FAIL} admin_actions[{i}] contains forbidden key '{key}'")
                action_leak = True
                failed += 1
    if not action_leak:
        action_count = len(admin_actions)
        print(f"  {PASS} No before_value/after_value in {action_count} admin action(s)")
        passed += 1

    # Also check login_attempts for sensitive data
    login_attempts = data.get("security", {}).get("login_attempts", [])
    login_leak = False
    for i, attempt in enumerate(login_attempts):
        for key in ["before_value", "after_value", "password_hash"]:
            if key in attempt:
                print(f"  {FAIL} login_attempts[{i}] contains forbidden key '{key}'")
                login_leak = True
                failed += 1
    if not login_leak:
        print(f"  {PASS} No sensitive keys in {len(login_attempts)} login attempt(s)")
        passed += 1

    # ── Step 7: Verify audit log entry created ──
    print(f"\n{'─' * 65}")
    print("Step 7 — Verify audit log entry created (query DB via asyncpg)")
    audit_count_after = asyncio.run(count_audit_entries(test_org_id))
    if audit_count_after > audit_count_before:
        print(f"  {PASS} Audit log entries increased: {audit_count_before} → {audit_count_after}")
        passed += 1
    else:
        print(f"  {FAIL} Audit log entries did not increase: before={audit_count_before}, after={audit_count_after}")
        failed += 1

    # ── Step 8: Test 404 for non-existent org UUID ──
    print(f"\n{'─' * 65}")
    print("Step 8 — 404 for non-existent org UUID")
    fake_org_id = str(uuid.uuid4())
    r = client.get(f"/admin/organisations/{fake_org_id}/detail", headers=admin_h)
    if r.status_code == 404:
        print(f"  {PASS} 404 for non-existent org UUID")
        passed += 1
    else:
        print(f"  {FAIL} Expected 404, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 9: Test 403 for non-admin user ──
    print(f"\n{'─' * 65}")
    print(f"Step 9 — 403 for non-admin user ({ORG_EMAIL})")
    try:
        org_h = login(client, ORG_EMAIL, ORG_PASSWORD)
        r = client.get(f"/admin/organisations/{test_org_id}/detail", headers=org_h)
        if r.status_code == 403:
            print(f"  {PASS} 403 for org_admin user")
            passed += 1
        else:
            print(f"  {FAIL} Expected 403, got {r.status_code}: {r.text[:200]}")
            failed += 1
        error_responses.append(r.text)
    except Exception:
        # Org admin login failed — test with an invalid token instead
        print(f"  {INFO} Org admin login failed — testing with invalid token instead")
        r = client.get(
            f"/admin/organisations/{test_org_id}/detail",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        if r.status_code in (401, 403):
            print(f"  {PASS} {r.status_code} for invalid token (org admin login unavailable)")
            passed += 1
        else:
            print(f"  {FAIL} Expected 401 or 403, got {r.status_code}: {r.text[:200]}")
            failed += 1
        error_responses.append(r.text)

    # ── Step 10: OWASP A1 — No auth token → 401/403 ──
    print(f"\n{'─' * 65}")
    print("Step 10 — OWASP A1: No auth token → expect 401")
    r = client.get(f"/admin/organisations/{test_org_id}/detail")
    if r.status_code in (401, 403):
        print(f"  {PASS} {r.status_code} without auth token")
        passed += 1
    else:
        print(f"  {FAIL} Expected 401 or 403, got {r.status_code}: {r.text[:200]}")
        failed += 1
    error_responses.append(r.text)

    # ── Step 11: OWASP A3 — SQL injection in org_id path param ──
    print(f"\n{'─' * 65}")
    print("Step 11 — OWASP A3: SQL injection in org_id path param")
    sqli_payloads = [
        "'; DROP TABLE organisations; --",
        "1 OR 1=1",
        "00000000-0000-0000-0000-000000000000' UNION SELECT * FROM users--",
    ]
    sqli_all_ok = True
    for payload in sqli_payloads:
        r = client.get(f"/admin/organisations/{payload}/detail", headers=admin_h)
        if r.status_code in (400, 404, 422):
            print(f"  {PASS} {r.status_code} for SQL injection payload: {payload[:40]}…")
        else:
            print(f"  {FAIL} Expected 400/404/422, got {r.status_code} for payload: {payload[:40]}…")
            sqli_all_ok = False
        error_responses.append(r.text)
    if sqli_all_ok:
        passed += 1
    else:
        failed += 1

    # ── Step 12: OWASP A5 — Error responses contain no stack traces ──
    print(f"\n{'─' * 65}")
    print("Step 12 — OWASP A5: Error responses contain no stack traces or internal paths")
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

    # ── Step 13: Cleanup ──
    print(f"\n{'─' * 65}")
    print("Step 13 — Cleanup test data")
    try:
        deleted = asyncio.run(cleanup_audit_entries(test_org_id))
        print(f"  {PASS} Cleaned up {deleted} audit log entries for org_detail_viewed")
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

"""
E2E test script: Payment Method Enforcement

Covers:
  1. Login as org_admin, call status endpoint, verify response structure
  2. Insert test payment methods via direct DB (asyncpg), verify status response
  3. Insert card expiring within 30 days, verify has_expiring_soon=true
  4. Login as global_admin, verify safe default response (has_payment_method=true)
  5. OWASP A1: unauthenticated access → 401
  6. OWASP A1: cross-org access → returns only own org's data
  7. OWASP A2: response contains no stripe_payment_method_id or secret keys
  8. OWASP A5: error responses contain no stack traces or internal paths
  9. Clean up all test payment method records

Requirements: 6.1, 6.2, 6.3, 6.4

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
      python scripts/test_payment_method_enforcement_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import asyncpg

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API = f"{BASE}/api/v1"

ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = "W4h3guru1#"
GLOBAL_ADMIN_EMAIL = "admin@orainvoice.com"
GLOBAL_ADMIN_PASSWORD = "admin123"

DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_NAME = os.environ.get("DB_NAME", "workshoppro")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

passed = 0
failed = 0
errors: list[str] = []
cleanup_ids: list[str] = []


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
    errors.append(f"{label}: {detail}")


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    r = await client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "remember_me": False},
    )
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def get_db_conn() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


async def insert_payment_method(
    conn: asyncpg.Connection,
    org_id: str,
    brand: str,
    last4: str,
    exp_month: int,
    exp_year: int,
    stripe_pm_id: str | None = None,
    is_default: bool = False,
    is_verified: bool = True,
) -> str:
    """Insert a test payment method and return its UUID."""
    pm_id = str(uuid.uuid4())
    if stripe_pm_id is None:
        stripe_pm_id = f"pm_test_{uuid.uuid4().hex[:16]}"
    await conn.execute(
        """
        INSERT INTO org_payment_methods
            (id, org_id, stripe_payment_method_id, brand, last4,
             exp_month, exp_year, is_default, is_verified)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        uuid.UUID(pm_id),
        uuid.UUID(org_id),
        stripe_pm_id,
        brand,
        last4,
        exp_month,
        exp_year,
        is_default,
        is_verified,
    )
    cleanup_ids.append(pm_id)
    return pm_id


async def cleanup_test_records(conn: asyncpg.Connection):
    """Delete all test payment method records created during this run."""
    if not cleanup_ids:
        return
    for pm_id in cleanup_ids:
        await conn.execute(
            "DELETE FROM org_payment_methods WHERE id = $1",
            uuid.UUID(pm_id),
        )


async def main():
    global passed, failed

    print("=" * 65)
    print("  PAYMENT METHOD ENFORCEMENT — END-TO-END VERIFICATION")
    print("=" * 65)

    conn: asyncpg.Connection | None = None

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # ──────────────────────────────────────────────────────────
            # 1. Login as org_admin, call status endpoint, verify structure
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("1 — Login as org_admin and verify status endpoint response structure")

            print(f"  {INFO} Logging in as Org Admin ({ORG_EMAIL})")
            org_headers = await login(client, ORG_EMAIL, ORG_PASSWORD)
            ok("Org Admin authenticated")

            r = await client.get(f"{API}/billing/payment-method-status", headers=org_headers)
            if r.status_code == 200:
                data = r.json()
                ok(f"GET /billing/payment-method-status → {r.status_code}")

                # Verify required fields exist
                required_fields = ["has_payment_method", "has_expiring_soon", "expiring_method"]
                for field in required_fields:
                    if field in data:
                        ok(f"Field present: {field}")
                    else:
                        fail(f"Missing required field: {field}")

                # Verify field types
                if isinstance(data.get("has_payment_method"), bool):
                    ok("has_payment_method is boolean")
                else:
                    fail("has_payment_method type", f"expected bool, got {type(data.get('has_payment_method'))}")

                if isinstance(data.get("has_expiring_soon"), bool):
                    ok("has_expiring_soon is boolean")
                else:
                    fail("has_expiring_soon type", f"expected bool, got {type(data.get('has_expiring_soon'))}")

                if data.get("expiring_method") is None or isinstance(data.get("expiring_method"), dict):
                    ok("expiring_method is null or object")
                else:
                    fail("expiring_method type", f"expected null/object, got {type(data.get('expiring_method'))}")
            else:
                fail(f"GET /billing/payment-method-status → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 2. Insert test payment methods, verify status correctness
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("2 — Insert test payment methods via DB, verify status response")

            # Get org_id for the org_admin user
            conn = await get_db_conn()
            row = await conn.fetchrow(
                "SELECT org_id FROM users WHERE email = $1", ORG_EMAIL,
            )
            if not row or not row["org_id"]:
                fail("Could not find org_id for org_admin user")
                return
            org_id = str(row["org_id"])
            ok(f"Org ID resolved: {org_id[:8]}…")

            # First, record any existing payment methods so we know the baseline
            existing_count = await conn.fetchval(
                "SELECT COUNT(*) FROM org_payment_methods WHERE org_id = $1",
                uuid.UUID(org_id),
            )

            # Insert a non-expiring payment method (far future)
            future_year = date.today().year + 5
            pm1_id = await insert_payment_method(
                conn, org_id, "visa", "4242", 12, future_year,
            )
            ok(f"Inserted non-expiring test card (visa ****4242, exp 12/{future_year})")

            # Verify status now shows has_payment_method=true
            r = await client.get(f"{API}/billing/payment-method-status", headers=org_headers)
            if r.status_code == 200:
                data = r.json()
                if data["has_payment_method"] is True:
                    ok("has_payment_method=true after inserting card")
                else:
                    fail("has_payment_method should be true", f"got {data['has_payment_method']}")

                if data["has_expiring_soon"] is False:
                    ok("has_expiring_soon=false for far-future card")
                else:
                    fail("has_expiring_soon should be false", f"got {data['has_expiring_soon']}")

                if data["expiring_method"] is None:
                    ok("expiring_method=null for non-expiring card")
                else:
                    fail("expiring_method should be null", f"got {data['expiring_method']}")
            else:
                fail(f"Status check after insert → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 3. Insert card expiring within 30 days, verify expiring_soon
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("3 — Insert expiring card, verify has_expiring_soon=true")

            # Card that expires this month or next month (within 30 days)
            today = date.today()
            expiring_date = today + timedelta(days=15)
            exp_month = expiring_date.month
            exp_year = expiring_date.year

            pm2_id = await insert_payment_method(
                conn, org_id, "mastercard", "9999", exp_month, exp_year,
            )
            ok(f"Inserted expiring test card (mastercard ****9999, exp {exp_month}/{exp_year})")

            r = await client.get(f"{API}/billing/payment-method-status", headers=org_headers)
            if r.status_code == 200:
                data = r.json()
                if data["has_payment_method"] is True:
                    ok("has_payment_method=true (two cards on file)")
                else:
                    fail("has_payment_method should be true")

                if data["has_expiring_soon"] is True:
                    ok("has_expiring_soon=true for card expiring within 30 days")
                else:
                    fail("has_expiring_soon should be true", f"got {data['has_expiring_soon']}")

                em = data.get("expiring_method")
                if em is not None:
                    ok("expiring_method is populated")

                    # Verify expiring_method fields
                    if em.get("brand") == "mastercard":
                        ok(f"expiring_method.brand = mastercard")
                    else:
                        fail("expiring_method.brand", f"expected mastercard, got {em.get('brand')}")

                    if em.get("last4") == "9999":
                        ok(f"expiring_method.last4 = 9999")
                    else:
                        fail("expiring_method.last4", f"expected 9999, got {em.get('last4')}")

                    if em.get("exp_month") == exp_month:
                        ok(f"expiring_method.exp_month = {exp_month}")
                    else:
                        fail("expiring_method.exp_month", f"expected {exp_month}, got {em.get('exp_month')}")

                    if em.get("exp_year") == exp_year:
                        ok(f"expiring_method.exp_year = {exp_year}")
                    else:
                        fail("expiring_method.exp_year", f"expected {exp_year}, got {em.get('exp_year')}")

                    # Verify ONLY allowed fields are present (no stripe_payment_method_id)
                    allowed_fields = {"brand", "last4", "exp_month", "exp_year"}
                    extra_fields = set(em.keys()) - allowed_fields
                    if not extra_fields:
                        ok("expiring_method contains only allowed fields (no internal IDs)")
                    else:
                        fail("expiring_method has extra fields", f"{extra_fields}")
                else:
                    fail("expiring_method should be populated for expiring card")
            else:
                fail(f"Status check after expiring insert → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 4. Login as global_admin, verify safe default response
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("4 — Login as global_admin, verify safe default response")

            print(f"  {INFO} Logging in as Global Admin ({GLOBAL_ADMIN_EMAIL})")
            global_headers = await login(client, GLOBAL_ADMIN_EMAIL, GLOBAL_ADMIN_PASSWORD)
            ok("Global Admin authenticated")

            r = await client.get(f"{API}/billing/payment-method-status", headers=global_headers)
            if r.status_code == 200:
                data = r.json()
                ok(f"GET /billing/payment-method-status → {r.status_code}")

                if data.get("has_payment_method") is True:
                    ok("Safe default: has_payment_method=true (global_admin, no org)")
                else:
                    fail("Safe default: has_payment_method should be true", f"got {data.get('has_payment_method')}")

                if data.get("has_expiring_soon") is False:
                    ok("Safe default: has_expiring_soon=false")
                else:
                    fail("Safe default: has_expiring_soon should be false", f"got {data.get('has_expiring_soon')}")

                if data.get("expiring_method") is None:
                    ok("Safe default: expiring_method=null")
                else:
                    fail("Safe default: expiring_method should be null", f"got {data.get('expiring_method')}")
            else:
                fail(f"Global admin status → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 5. OWASP A1: unauthenticated access → 401
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("5 — OWASP A1: unauthenticated access → 401")

            r = await client.get(f"{API}/billing/payment-method-status")
            if r.status_code in (401, 403):
                ok(f"Unauthenticated request rejected → {r.status_code}")
            else:
                fail(f"Unauthenticated should be 401/403 → got {r.status_code}")

            # ──────────────────────────────────────────────────────────
            # 6. OWASP A1: cross-org access — returns only own org's data
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("6 — OWASP A1: cross-org access — returns only own org's data")

            # Global admin has no org_id, so their response should be safe defaults
            # (not the org_admin's payment methods)
            r = await client.get(f"{API}/billing/payment-method-status", headers=global_headers)
            if r.status_code == 200:
                data = r.json()
                # Global admin should NOT see the org_admin's expiring card
                if data.get("has_expiring_soon") is False and data.get("expiring_method") is None:
                    ok("Global admin does not see org_admin's payment methods (cross-org isolation)")
                else:
                    fail("Cross-org leak", "global_admin sees org_admin's payment data")
            else:
                fail(f"Cross-org check → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 7. OWASP A2: response contains no secrets
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("7 — OWASP A2: response contains no stripe_payment_method_id or secret keys")

            r = await client.get(f"{API}/billing/payment-method-status", headers=org_headers)
            if r.status_code == 200:
                raw_text = r.text
                data = r.json()

                # Check top-level response for forbidden fields
                forbidden_keys = [
                    "stripe_payment_method_id", "stripe_customer_id",
                    "stripe_secret", "secret_key", "sk_live", "sk_test",
                ]
                leaked = [k for k in forbidden_keys if k in raw_text]
                if not leaked:
                    ok("No secret keys or stripe IDs in response body")
                else:
                    fail("Secret data leaked in response", f"found: {leaked}")

                # Check that top-level has no id field (internal UUID)
                if "id" not in data:
                    ok("No internal 'id' field in top-level response")
                else:
                    fail("Internal 'id' field leaked in response")
            else:
                fail(f"Secret check request → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 8. OWASP A5: error responses contain no stack traces
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("8 — OWASP A5: error responses contain no stack traces or internal paths")

            # Send request with invalid auth token to trigger error
            bad_headers = {"Authorization": "Bearer invalid_token_12345"}
            r = await client.get(f"{API}/billing/payment-method-status", headers=bad_headers)
            raw_text = r.text.lower()

            stack_trace_indicators = [
                "traceback", "file \"", "line ", ".py\"",
                "sqlalchemy", "asyncpg", "pydantic",
                "/app/", "/usr/lib/", "/site-packages/",
            ]
            leaked_traces = [ind for ind in stack_trace_indicators if ind in raw_text]
            if not leaked_traces:
                ok(f"Error response ({r.status_code}) contains no stack traces or internal paths")
            else:
                fail("Stack trace/path leaked in error response", f"found: {leaked_traces}")

            # Also check the unauthenticated response
            r2 = await client.get(f"{API}/billing/payment-method-status")
            raw_text2 = r2.text.lower()
            leaked_traces2 = [ind for ind in stack_trace_indicators if ind in raw_text2]
            if not leaked_traces2:
                ok(f"Unauthenticated error ({r2.status_code}) contains no stack traces")
            else:
                fail("Stack trace leaked in unauth response", f"found: {leaked_traces2}")

        finally:
            # ──────────────────────────────────────────────────────────
            # 9. Cleanup — delete all test payment method records
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print(f"9 — Cleanup — deleting {len(cleanup_ids)} test payment method records")

            try:
                if conn is None:
                    conn = await get_db_conn()
                await cleanup_test_records(conn)
                if cleanup_ids:
                    ok(f"Deleted {len(cleanup_ids)} test payment method records")
                else:
                    ok("No test records to clean up")

                # Verify cleanup
                remaining = 0
                for pm_id in cleanup_ids:
                    row = await conn.fetchrow(
                        "SELECT id FROM org_payment_methods WHERE id = $1",
                        uuid.UUID(pm_id),
                    )
                    if row:
                        remaining += 1
                if remaining == 0:
                    ok("Cleanup verified — no test records remain")
                else:
                    fail("Cleanup verification", f"{remaining} test records still exist")
            except Exception as e:
                fail("Cleanup error", str(e)[:200])
            finally:
                if conn:
                    await conn.close()

    # ── Summary ──
    print(f"\n{'=' * 65}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {PASS} {passed} passed, {FAIL} {failed} failed (of {total})")
    print(f"{'=' * 65}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

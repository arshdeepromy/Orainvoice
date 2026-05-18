"""
End-to-end test: Kiosk User Password Reset by Org Admin

Covers:
  1. Login as org_admin, reset kiosk user password → 200 with sessions_invalidated
  2. Verify kiosk user can login with new password
  3. Verify kiosk user CANNOT login with old password
  4. OWASP A1 (Broken Access Control): Unauthenticated request → 401
  5. OWASP A1: Salesperson token → 403
  6. OWASP A1: Target non-kiosk user → 400
  7. OWASP A1: Target user in different org → 404
  8. OWASP A3 (Injection): SQL injection payload in password → 200 (stored as hash)
  9. Cleanup: Reset kiosk user password back to original

Requirements: 4.1, 4.2, 5.1–5.6, 6.1, 7.1

Run inside container:
    docker exec invoicing-app-1 python scripts/test_kiosk_password_reset_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import asyncpg
import bcrypt

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API = f"{BASE}/api/v1"

# Known org_admin credentials from the dev environment
ORG_ADMIN_EMAIL = "demo@orainvoice.com"
ORG_ADMIN_PASSWORD = os.environ.get("E2E_ORG_PASSWORD", "demo123")

# Test kiosk user credentials (created during setup)
KIOSK_EMAIL_PREFIX = "TEST_E2E_kiosk_reset"
KIOSK_ORIGINAL_PASSWORD = "OriginalKiosk123"
KIOSK_NEW_PASSWORD = "NewKioskPass456"

# DB connection settings
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



async def login(client: httpx.AsyncClient, email: str, password: str) -> str | None:
    """Login and return access_token, or None on failure."""
    r = await client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "remember_me": False},
    )
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


async def get_db_conn() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
    )


async def main():
    # Track created resources for cleanup
    created_user_ids: list[uuid.UUID] = []
    created_org_ids: list[uuid.UUID] = []
    kiosk_user_id: uuid.UUID | None = None
    conn: asyncpg.Connection | None = None

    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        try:
            # ─── Setup: DB connection ───
            conn = await get_db_conn()

            # ─── Setup: Clean up any leftover test data from previous runs ───
            leftover = await conn.fetch(
                "SELECT id FROM users WHERE email LIKE $1",
                f"{KIOSK_EMAIL_PREFIX}%",
            )
            if leftover:
                for r in leftover:
                    await conn.execute("DELETE FROM sessions WHERE user_id = $1", r["id"])
                    await conn.execute("DELETE FROM audit_log WHERE user_id = $1", r["id"])
                    await conn.execute("DELETE FROM users WHERE id = $1", r["id"])
                await conn.execute(
                    "DELETE FROM organisations WHERE name LIKE 'TEST_E2E_KioskReset%'"
                )

            # ─── Setup: Get org_id for the admin user ───
            print("\n🔹 Setup: Resolve org_admin org_id")
            admin_row = await conn.fetchrow(
                "SELECT id, org_id FROM users WHERE email = $1",
                ORG_ADMIN_EMAIL,
            )
            if not admin_row:
                fail("Setup", f"org_admin user '{ORG_ADMIN_EMAIL}' not found in DB")
                return False
            org_id = admin_row["org_id"]
            ok(f"Org admin org_id: {org_id}")

            # ─── Setup: Create a kiosk user ───
            print("\n🔹 Setup: Create test kiosk user")
            kiosk_user_id = uuid.uuid4()
            kiosk_email = f"{KIOSK_EMAIL_PREFIX}_{uuid.uuid4().hex[:8]}@example.com"
            kiosk_hash = bcrypt.hashpw(
                KIOSK_ORIGINAL_PASSWORD.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name,
                   password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E', 'Kiosk', $4, 'kiosk', true, true)""",
                kiosk_user_id, org_id, kiosk_email, kiosk_hash,
            )
            created_user_ids.append(kiosk_user_id)
            ok(f"Created kiosk user: {kiosk_email} (id={kiosk_user_id})")

            # ─── Setup: Create a salesperson user (for OWASP A1 test) ───
            print("\n🔹 Setup: Create test salesperson user")
            sales_user_id = uuid.uuid4()
            sales_email = f"{KIOSK_EMAIL_PREFIX}_sales_{uuid.uuid4().hex[:8]}@example.com"
            sales_password = "SalesPass123"
            sales_hash = bcrypt.hashpw(
                sales_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name,
                   password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E', 'Sales', $4, 'salesperson', true, true)""",
                sales_user_id, org_id, sales_email, sales_hash,
            )
            created_user_ids.append(sales_user_id)
            ok(f"Created salesperson user: {sales_email}")

            # ─── Setup: Create a second org + user (for cross-org test) ───
            print("\n🔹 Setup: Create second org for cross-org test")
            other_org_id = uuid.uuid4()
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            plan_id = plan_row["id"]

            await conn.execute(
                """INSERT INTO organisations (id, name, status, plan_id, storage_quota_gb, created_at, updated_at)
                   VALUES ($1, 'TEST_E2E_KioskReset_OtherOrg', 'active', $2, 5, NOW(), NOW())""",
                other_org_id, plan_id,
            )
            created_org_ids.append(other_org_id)

            other_kiosk_id = uuid.uuid4()
            other_kiosk_email = f"{KIOSK_EMAIL_PREFIX}_other_{uuid.uuid4().hex[:8]}@example.com"
            other_kiosk_hash = bcrypt.hashpw(
                "OtherKiosk123".encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name,
                   password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E', 'OtherKiosk', $4, 'kiosk', true, true)""",
                other_kiosk_id, other_org_id, other_kiosk_email, other_kiosk_hash,
            )
            created_user_ids.append(other_kiosk_id)
            ok(f"Created other-org kiosk user: {other_kiosk_email}")

            # ─── Setup: Login as org_admin ───
            print("\n🔹 Setup: Login as org_admin")
            admin_token = await login(client, ORG_ADMIN_EMAIL, ORG_ADMIN_PASSWORD)
            if not admin_token:
                fail("Setup: login as org_admin", "Could not authenticate")
                return False
            ok("Org admin login successful")
            admin_headers = {"Authorization": f"Bearer {admin_token}"}

            # ─── Setup: Login as salesperson ───
            print("\n🔹 Setup: Login as salesperson")
            sales_token = await login(client, sales_email, sales_password)
            if not sales_token:
                fail("Setup: login as salesperson", "Could not authenticate")
                return False
            ok("Salesperson login successful")
            sales_headers = {"Authorization": f"Bearer {sales_token}"}

            # ─── Setup: Verify kiosk user can login with original password ───
            print("\n🔹 Setup: Verify kiosk user can login with original password")
            kiosk_token = await login(client, kiosk_email, KIOSK_ORIGINAL_PASSWORD)
            if not kiosk_token:
                fail("Setup: kiosk login with original password", "Could not authenticate")
                return False
            ok("Kiosk user login with original password successful")

            # ═══════════════════════════════════════════════════════════
            # Test 1: Reset kiosk user password as org_admin → 200
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 1: Reset kiosk user password (Req 4.1, 4.2, 5.1, 6.1, 7.1)")
            reset_url = f"{API}/org/users/{kiosk_user_id}/reset-password"
            r = await client.post(
                reset_url,
                headers=admin_headers,
                json={"new_password": KIOSK_NEW_PASSWORD},
            )
            if r.status_code == 200:
                ok(f"Password reset returned 200")
                data = r.json()
                # Verify response structure
                if "message" in data:
                    ok(f"Response has 'message': {data['message']}")
                else:
                    fail("Response missing 'message' field")
                if "user_id" in data:
                    ok(f"Response has 'user_id': {data['user_id']}")
                else:
                    fail("Response missing 'user_id' field")
                if "sessions_invalidated" in data:
                    ok(f"Response has 'sessions_invalidated': {data['sessions_invalidated']}")
                else:
                    fail("Response missing 'sessions_invalidated' field")
            else:
                fail("Password reset", f"Expected 200, got {r.status_code}: {r.text[:200]}")
                return False

            # ═══════════════════════════════════════════════════════════
            # Test 2: Kiosk user can login with NEW password
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 2: Kiosk user can login with new password (Req 6.1)")
            new_token = await login(client, kiosk_email, KIOSK_NEW_PASSWORD)
            if new_token:
                ok("Kiosk user login with new password successful")
            else:
                fail("Kiosk user login with new password", "Authentication failed")

            # ═══════════════════════════════════════════════════════════
            # Test 3: Kiosk user CANNOT login with OLD password
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 3: Kiosk user cannot login with old password (Req 6.1)")
            old_token = await login(client, kiosk_email, KIOSK_ORIGINAL_PASSWORD)
            if old_token is None:
                ok("Kiosk user login with old password correctly rejected")
            else:
                fail("Kiosk user login with old password", "Should have been rejected but succeeded")

            # ═══════════════════════════════════════════════════════════
            # Test 4: OWASP A1 — Unauthenticated request → 401
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 4: OWASP A1 — No token → 401 (Req 4.2)")
            r = await client.post(
                reset_url,
                json={"new_password": "SomePassword123"},
            )
            if r.status_code == 401:
                ok("Unauthenticated request returned 401")
            else:
                fail("Unauthenticated request", f"Expected 401, got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # Test 5: OWASP A1 — Salesperson token → 403
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 5: OWASP A1 — Salesperson token → 403 (Req 4.2)")
            r = await client.post(
                reset_url,
                headers=sales_headers,
                json={"new_password": "SomePassword123"},
            )
            if r.status_code == 403:
                ok("Salesperson request returned 403")
            else:
                fail("Salesperson request", f"Expected 403, got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # Test 6: OWASP A1 — Target non-kiosk user → 400
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 6: OWASP A1 — Target non-kiosk user → 400 (Req 5.3, 5.4)")
            # Target the salesperson (role=salesperson, not kiosk)
            non_kiosk_url = f"{API}/org/users/{sales_user_id}/reset-password"
            r = await client.post(
                non_kiosk_url,
                headers=admin_headers,
                json={"new_password": "SomePassword123"},
            )
            if r.status_code == 400:
                ok("Target non-kiosk user returned 400")
            else:
                fail("Target non-kiosk user", f"Expected 400, got {r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # Test 7: OWASP A1 — Target user in different org → 404
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7: OWASP A1 — Target user in different org → 404 (Req 5.1, 5.2)")
            cross_org_url = f"{API}/org/users/{other_kiosk_id}/reset-password"
            r = await client.post(
                cross_org_url,
                headers=admin_headers,
                json={"new_password": "SomePassword123"},
            )
            if r.status_code == 404:
                ok("Cross-org target returned 404")
            else:
                fail("Cross-org target", f"Expected 404, got {r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # Test 8: OWASP A3 — SQL injection in password → 200
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 8: OWASP A3 — SQL injection payload in password (Req 6.1)")
            sql_injection_password = "'; DROP TABLE users; --"
            r = await client.post(
                reset_url,
                headers=admin_headers,
                json={"new_password": sql_injection_password},
            )
            if r.status_code == 200:
                ok("SQL injection payload accepted as normal password (stored as hash)")
                # Verify the user can login with the injection string as password
                injection_token = await login(client, kiosk_email, sql_injection_password)
                if injection_token:
                    ok("Kiosk user can login with SQL injection string (safely hashed)")
                else:
                    fail("Kiosk user login with SQL injection password", "Should work since it's hashed")
            elif r.status_code == 422:
                # Password might be too short (min 8 chars) — the injection string is 27 chars so should pass
                fail("SQL injection payload", f"Got 422 (validation error): {r.text[:200]}")
            else:
                fail("SQL injection payload", f"Expected 200, got {r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # Cleanup: Reset kiosk user password back to original
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Cleanup: Reset kiosk user password back to original")
            r = await client.post(
                reset_url,
                headers=admin_headers,
                json={"new_password": KIOSK_ORIGINAL_PASSWORD},
            )
            if r.status_code == 200:
                ok("Password reset back to original")
            else:
                fail("Cleanup: reset password back", f"status={r.status_code}: {r.text[:200]}")

        finally:
            # ═══════════════════════════════════════════════════════════
            # Cleanup: Delete all TEST_E2E_ data from DB
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Cleanup: Delete test data from database")

            if conn is None:
                conn = await get_db_conn()

            try:
                # Delete sessions for test users
                for uid in created_user_ids:
                    await conn.execute(
                        "DELETE FROM sessions WHERE user_id = $1",
                        uid,
                    )

                # Delete audit logs for test users
                for uid in created_user_ids:
                    await conn.execute(
                        "DELETE FROM audit_log WHERE user_id = $1",
                        uid,
                    )

                # Delete test users
                for uid in created_user_ids:
                    await conn.execute(
                        "DELETE FROM users WHERE id = $1",
                        uid,
                    )

                # Delete test orgs
                for oid in created_org_ids:
                    await conn.execute(
                        "DELETE FROM organisations WHERE id = $1",
                        oid,
                    )

                ok("Cleanup: deleted all test resources")

                # Verify cleanup
                remaining = await conn.fetch(
                    "SELECT email FROM users WHERE email LIKE $1",
                    f"{KIOSK_EMAIL_PREFIX}%",
                )
                if len(remaining) == 0:
                    ok("Cleanup verification: zero TEST_E2E_ kiosk rows remain")
                else:
                    fail("Cleanup verification", f"{len(remaining)} TEST_E2E_ rows remain")

            except Exception as e:
                fail("Cleanup error", str(e)[:300])
            finally:
                if conn:
                    await conn.close()

    # ─── Summary ───
    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

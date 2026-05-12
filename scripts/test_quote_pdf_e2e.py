"""
End-to-end test: Quote PDF Endpoint (GET /api/v1/quotes/{id}/pdf)

Emulates real user interactions with the quote PDF download endpoint:
1.  org_admin → draft quote → 200 + %PDF- body
2.  org_admin → sent quote → 200
3.  org_admin → accepted quote → 200
4.  No Authorization header → 401
5.  Wrong org's quote_id → 404 (org isolation)
6.  Non-existent UUID → 404
7.  salesperson role → 200
8.  Non-permitted role (staff_member) → 403
9.  Content-Disposition contains quote_number for numbered quotes
10. Content-Disposition contains DRAFT for unnumbered quotes
11. Cleanup verification — no TEST_E2E_ rows remain

Usage:
    docker exec invoicing-app-1 python scripts/test_quote_pdf_e2e.py
"""

import asyncio
import sys
import uuid

import httpx

BASE = "http://localhost:8000"

# Existing test accounts
DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"
ADMIN_EMAIL = "admin@orainvoice.com"
ADMIN_PASSWORD = "admin123"

passed = 0
failed = 0
errors = []


def ok(label: str):
    global passed
    passed += 1
    print(f"  ✅ {label}")


def fail(label: str, detail: str = ""):
    global failed
    failed += 1
    msg = f"  ❌ {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    errors.append(f"{label}: {detail}")


async def login(client: httpx.AsyncClient, email: str, password: str) -> str | None:
    """Login and return access_token, or None on failure."""
    r = await client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password,
        "remember_me": True,
    })
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


async def main():
    import asyncpg

    # Track created resources for cleanup
    created = {
        "quote_ids": [],
        "customer_ids": [],
        "user_ids": [],
        "org_ids": [],
    }

    conn: asyncpg.Connection | None = None

    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        try:
            # ─── Setup: DB connection for direct SQL operations ───
            conn = await asyncpg.connect(
                host="postgres", port=5432,
                user="postgres", password="postgres",
                database="workshoppro",
            )

            # ─── Setup: Login as org_admin (demo user) ───
            print("\n🔹 Setup: Login as org_admin")
            token = await login(client, DEMO_EMAIL, DEMO_PASSWORD)
            if not token:
                fail("Setup: login as org_admin", "Could not authenticate")
                return False
            ok("Login as org_admin")
            headers = {"Authorization": f"Bearer {token}"}

            # Get org_id for the demo user
            org_row = await conn.fetchrow(
                "SELECT org_id FROM users WHERE email = $1", DEMO_EMAIL
            )
            org_id = str(org_row["org_id"])

            # ─── Setup: Create a TEST_E2E_ customer ───
            print("\n🔹 Setup: Create test customer")
            r = await client.post("/api/v1/customers", headers=headers, json={
                "first_name": "TEST_E2E_QuotePDF",
                "last_name": "Customer",
                "email": f"TEST_E2E_quotepdf_{uuid.uuid4().hex[:8]}@example.com",
            })
            if r.status_code not in (200, 201):
                fail("Setup: create customer", f"status={r.status_code} body={r.text[:200]}")
                return False
            customer_data = r.json()
            # Handle both response shapes: direct object or nested
            customer_id = customer_data.get("id") or customer_data.get("customer", {}).get("id")
            if not customer_id:
                fail("Setup: create customer", f"No id in response: {r.text[:200]}")
                return False
            created["customer_ids"].append(customer_id)
            ok(f"Created test customer: {customer_id}")

            # ─── Setup: Create a draft quote ───
            print("\n🔹 Setup: Create draft quote")
            r = await client.post("/api/v1/quotes", headers=headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_QuotePDF Draft",
                "validity_days": 30,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_QuotePDF line item",
                    "quantity": 1,
                    "unit_price": 100.00,
                    "sort_order": 0,
                }],
            })
            if r.status_code not in (200, 201):
                fail("Setup: create quote", f"status={r.status_code} body={r.text[:200]}")
                return False
            quote_data = r.json()
            quote_obj = quote_data.get("quote", quote_data)
            quote_id = quote_obj.get("id")
            quote_number = quote_obj.get("quote_number")
            if not quote_id:
                fail("Setup: create quote", f"No id in response: {r.text[:200]}")
                return False
            created["quote_ids"].append(quote_id)
            ok(f"Created draft quote: {quote_id} (number={quote_number})")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 1: org_admin → draft quote → 200 + %PDF- body
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 1: org_admin → draft quote → GET /quotes/{id}/pdf → 200")
            r = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=headers)
            if r.status_code == 200:
                ok("Status 200")
                ct = r.headers.get("content-type", "")
                if "application/pdf" in ct:
                    ok("Content-Type: application/pdf")
                else:
                    fail("Content-Type check", f"got: {ct}")
                if r.content[:5] == b"%PDF-":
                    ok("Body starts with %PDF-")
                else:
                    fail("Body prefix check", f"got: {r.content[:20]!r}")
                cd = r.headers.get("content-disposition", "")
                if cd.startswith('inline; filename="'):
                    ok("Content-Disposition starts with 'inline; filename=\"'")
                else:
                    fail("Content-Disposition check", f"got: {cd}")
            else:
                fail("Test 1: expected 200", f"got {r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 2: org_admin → sent quote → 200
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 2: org_admin → sent quote → 200")
            # Try to send via API first
            r_send = await client.post(f"/api/v1/quotes/{quote_id}/send", headers=headers)
            if r_send.status_code == 200:
                ok("Quote sent via API")
            else:
                # Fallback: set status directly via SQL
                print(f"     Send API returned {r_send.status_code}, using direct SQL fallback")
                acceptance_token = str(uuid.uuid4())
                await conn.execute(
                    """UPDATE quotes SET status = 'sent',
                       acceptance_token = $1,
                       sent_at = NOW()
                       WHERE id = $2::uuid""",
                    acceptance_token, uuid.UUID(quote_id),
                )
                ok("Quote status set to 'sent' via SQL")

            r = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=headers)
            if r.status_code == 200 and r.content[:5] == b"%PDF-":
                ok("Sent quote → 200 + %PDF- body")
            else:
                fail("Test 2: sent quote PDF", f"status={r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 3: org_admin → accepted quote → 200
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 3: org_admin → accepted quote → 200")
            # Mark as accepted via direct SQL
            await conn.execute(
                "UPDATE quotes SET status = 'accepted' WHERE id = $1::uuid",
                uuid.UUID(quote_id),
            )
            r = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=headers)
            if r.status_code == 200 and r.content[:5] == b"%PDF-":
                ok("Accepted quote → 200 + %PDF- body")
            else:
                fail("Test 3: accepted quote PDF", f"status={r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 4: No Authorization header → 401
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 4: No Authorization header → 401")
            r = await client.get(f"/api/v1/quotes/{quote_id}/pdf")
            if r.status_code == 401:
                ok("No auth → 401")
            else:
                fail("Test 4: expected 401", f"got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 5: Wrong org's quote_id → 404 (org isolation)
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 5: Wrong org's quote_id → 404")
            # Create a second org + user via direct SQL
            second_org_id = uuid.uuid4()
            second_user_id = uuid.uuid4()
            second_email = f"TEST_E2E_org2_{uuid.uuid4().hex[:8]}@example.com"
            second_password = "testpass123"

            # Hash the password using bcrypt
            import bcrypt
            pw_hash = bcrypt.hashpw(second_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            # Get a valid plan_id for the org
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            plan_id = plan_row["id"]

            # Create org
            await conn.execute(
                """INSERT INTO organisations (id, name, status, plan_id, storage_quota_gb, created_at, updated_at)
                   VALUES ($1, 'TEST_E2E_Org2_QuotePDF', 'active', $2, 5, NOW(), NOW())""",
                second_org_id, plan_id,
            )
            created["org_ids"].append(str(second_org_id))

            # Create user in second org
            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name, password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E', 'Org2Admin', $4, 'org_admin', true, true)""",
                second_user_id, second_org_id, second_email, pw_hash,
            )
            created["user_ids"].append(str(second_user_id))

            # Create a customer in second org
            second_customer_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO customers (id, org_id, first_name, last_name, created_at, updated_at)
                   VALUES ($1, $2, 'TEST_E2E_Org2', 'Customer', NOW(), NOW())""",
                second_customer_id, second_org_id,
            )
            created["customer_ids"].append(str(second_customer_id))

            # Create a quote in second org
            second_quote_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO quotes (id, org_id, customer_id, quote_number, status, subject,
                   subtotal, tax_amount, total, line_items, version_number, quote_data_json,
                   created_at, updated_at)
                   VALUES ($1, $2, $3, 'TEST_E2E_Q001', 'draft', 'TEST_E2E_Org2 Quote',
                   100, 15, 115, '[]'::jsonb, 1, '{}'::jsonb, NOW(), NOW())""",
                second_quote_id, second_org_id, second_customer_id,
            )
            created["quote_ids"].append(str(second_quote_id))

            # Authenticate as first org's user and request second org's quote
            r = await client.get(f"/api/v1/quotes/{second_quote_id}/pdf", headers=headers)
            if r.status_code == 404:
                ok("Wrong org's quote → 404 (org isolation confirmed)")
            else:
                fail("Test 5: expected 404", f"got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 6: Non-existent UUID → 404
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 6: Non-existent UUID → 404")
            fake_id = str(uuid.uuid4())
            r = await client.get(f"/api/v1/quotes/{fake_id}/pdf", headers=headers)
            if r.status_code == 404:
                ok("Non-existent UUID → 404")
            else:
                fail("Test 6: expected 404", f"got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 7: salesperson role → 200
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7: salesperson role → 200")
            # Create a salesperson user in the first org
            sp_user_id = uuid.uuid4()
            sp_email = f"TEST_E2E_salesperson_{uuid.uuid4().hex[:8]}@example.com"
            sp_password = "testpass123"
            sp_hash = bcrypt.hashpw(sp_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name, password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2::uuid, $3, 'TEST_E2E', 'Salesperson', $4, 'salesperson', true, true)""",
                sp_user_id, uuid.UUID(org_id), sp_email, sp_hash,
            )
            created["user_ids"].append(str(sp_user_id))

            sp_token = await login(client, sp_email, sp_password)
            if sp_token:
                sp_headers = {"Authorization": f"Bearer {sp_token}"}
                r = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=sp_headers)
                if r.status_code == 200 and r.content[:5] == b"%PDF-":
                    ok("Salesperson → 200 + %PDF- body")
                else:
                    fail("Test 7: salesperson PDF", f"status={r.status_code}")
            else:
                fail("Test 7: salesperson login failed")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 8: Non-permitted role (staff_member) → 403
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 8: Non-permitted role (staff_member) → 403")
            sm_user_id = uuid.uuid4()
            sm_email = f"TEST_E2E_staffmember_{uuid.uuid4().hex[:8]}@example.com"
            sm_password = "testpass123"
            sm_hash = bcrypt.hashpw(sm_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name, password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2::uuid, $3, 'TEST_E2E', 'StaffMember', $4, 'staff_member', true, true)""",
                sm_user_id, uuid.UUID(org_id), sm_email, sm_hash,
            )
            created["user_ids"].append(str(sm_user_id))

            sm_token = await login(client, sm_email, sm_password)
            if sm_token:
                sm_headers = {"Authorization": f"Bearer {sm_token}"}
                r = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=sm_headers)
                if r.status_code == 403:
                    ok("staff_member → 403")
                else:
                    fail("Test 8: expected 403", f"got {r.status_code}")
            else:
                fail("Test 8: staff_member login failed")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 9: Content-Disposition contains quote_number
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 9: Content-Disposition contains quote_number")
            # Re-fetch the quote to get the current quote_number
            r_quote = await client.get(f"/api/v1/quotes/{quote_id}", headers=headers)
            if r_quote.status_code == 200:
                current_quote = r_quote.json()
                current_number = current_quote.get("quote_number")
                if current_number:
                    r = await client.get(f"/api/v1/quotes/{quote_id}/pdf", headers=headers)
                    cd = r.headers.get("content-disposition", "")
                    if current_number in cd and cd.endswith('.pdf"'):
                        ok(f"Content-Disposition contains '{current_number}' and ends with .pdf\"")
                    else:
                        fail("Test 9: quote_number in Content-Disposition", f"number={current_number}, cd={cd}")
                else:
                    fail("Test 9: quote has no quote_number", "Cannot verify numbered filename")
            else:
                fail("Test 9: could not fetch quote", f"status={r_quote.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TEST CASE 10: Content-Disposition contains DRAFT for unnumbered
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 10: Content-Disposition contains DRAFT for unnumbered quotes")
            # Create a quote with empty quote_number via direct SQL to trigger the
            # 'DRAFT' fallback in the endpoint (quote_number or 'DRAFT')
            draft_no_number_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO quotes (id, org_id, customer_id, quote_number, status, subject,
                   subtotal, tax_amount, total, line_items, version_number, quote_data_json,
                   created_at, updated_at)
                   VALUES ($1, $2::uuid, $3::uuid, '', 'draft', 'TEST_E2E_NullNumber',
                   50, 7.5, 57.5, '[]'::jsonb, 1, '{}'::jsonb, NOW(), NOW())""",
                draft_no_number_id, uuid.UUID(org_id), uuid.UUID(customer_id),
            )
            created["quote_ids"].append(str(draft_no_number_id))

            r = await client.get(f"/api/v1/quotes/{draft_no_number_id}/pdf", headers=headers)
            if r.status_code == 200:
                cd = r.headers.get("content-disposition", "")
                if 'filename="DRAFT.pdf"' in cd:
                    ok("Unnumbered quote → Content-Disposition: inline; filename=\"DRAFT.pdf\"")
                else:
                    fail("Test 10: expected DRAFT.pdf in Content-Disposition", f"got: {cd}")
            else:
                fail("Test 10: expected 200", f"got {r.status_code}: {r.text[:200]}")

        finally:
            # ═══════════════════════════════════════════════════════════
            # TEST CASE 11: Cleanup verification
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 11: Cleanup — delete all TEST_E2E_ rows")

            if conn is None:
                conn = await asyncpg.connect(
                    host="postgres", port=5432,
                    user="postgres", password="postgres",
                    database="workshoppro",
                )

            try:
                # Delete quotes first (child of customers and orgs)
                for qid in created["quote_ids"]:
                    # Delete quote line items first
                    await conn.execute(
                        "DELETE FROM quote_line_items WHERE quote_id = $1::uuid",
                        uuid.UUID(qid),
                    )
                    await conn.execute(
                        "DELETE FROM quotes WHERE id = $1::uuid",
                        uuid.UUID(qid),
                    )

                # Delete customers
                for cid in created["customer_ids"]:
                    await conn.execute(
                        "DELETE FROM customers WHERE id = $1::uuid",
                        uuid.UUID(cid),
                    )

                # Delete sessions for test users before deleting users
                for uid in created["user_ids"]:
                    await conn.execute(
                        "DELETE FROM sessions WHERE user_id = $1::uuid",
                        uuid.UUID(uid),
                    )
                    await conn.execute(
                        "DELETE FROM users WHERE id = $1::uuid",
                        uuid.UUID(uid),
                    )

                # Delete orgs (after users and customers are gone)
                for oid in created["org_ids"]:
                    await conn.execute(
                        "DELETE FROM organisations WHERE id = $1::uuid",
                        uuid.UUID(oid),
                    )

                ok("Cleanup: deleted all created resources")

                # Verify no TEST_E2E_ rows remain
                remaining_users = await conn.fetch(
                    "SELECT email FROM users WHERE email LIKE 'TEST_E2E_%'"
                )
                remaining_customers = await conn.fetch(
                    "SELECT first_name FROM customers WHERE first_name LIKE 'TEST_E2E_%'"
                )
                remaining_orgs = await conn.fetch(
                    "SELECT name FROM organisations WHERE name LIKE 'TEST_E2E_%'"
                )
                remaining_quotes = await conn.fetch(
                    "SELECT subject FROM quotes WHERE subject LIKE 'TEST_E2E_%'"
                )

                total_remaining = (
                    len(remaining_users) + len(remaining_customers)
                    + len(remaining_orgs) + len(remaining_quotes)
                )
                if total_remaining == 0:
                    ok("Cleanup verification: zero TEST_E2E_ rows remain")
                else:
                    detail_parts = []
                    if remaining_users:
                        detail_parts.append(f"{len(remaining_users)} users")
                    if remaining_customers:
                        detail_parts.append(f"{len(remaining_customers)} customers")
                    if remaining_orgs:
                        detail_parts.append(f"{len(remaining_orgs)} orgs")
                    if remaining_quotes:
                        detail_parts.append(f"{len(remaining_quotes)} quotes")
                    fail("Cleanup verification", f"{total_remaining} TEST_E2E_ rows remain: {', '.join(detail_parts)}")

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

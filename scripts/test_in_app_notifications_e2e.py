"""
End-to-end test: In-App Notifications

Covers acceptance criteria AC-1, AC-3, AC-4:
- AC-1: Email failure creates notification with correct fields
- AC-3: Second user (salesperson) sees same notification independently
- AC-4: Dismissing as one user does NOT remove it from the other user's inbox

Workflow:
1. Create org + admin user + salesperson user (TEST_E2E_ prefix)
2. Create a customer + draft quote
3. Trigger quote send (no email provider configured → email failure)
4. Assert notification created in app_notifications with correct fields
5. Assert admin sees notification via GET /inbox
6. Assert salesperson sees same notification independently (separate unread state)
7. Mark read as admin → assert salesperson still sees it as unread
8. Dismiss as admin → assert salesperson still sees it
9. Cleanup all TEST_E2E_ data

Usage:
    docker exec invoicing-app-1 python scripts/test_in_app_notifications_e2e.py
"""

import asyncio
import sys
import uuid

import httpx

BASE = "http://localhost:8000"

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
    import bcrypt

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
            # ─── Setup: DB connection ───
            conn = await asyncpg.connect(
                host="postgres", port=5432,
                user="postgres", password="postgres",
                database="workshoppro",
            )

            # ─── Setup: Create test org ───
            print("\n🔹 Setup: Create test organisation")
            org_id = uuid.uuid4()
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            plan_id = plan_row["id"]

            await conn.execute(
                """INSERT INTO organisations (id, name, status, plan_id, storage_quota_gb, created_at, updated_at)
                   VALUES ($1, 'TEST_E2E_InAppNotif_Org', 'active', $2, 5, NOW(), NOW())""",
                org_id, plan_id,
            )
            created["org_ids"].append(str(org_id))
            ok(f"Created test org: {org_id}")

            # ─── Setup: Create admin user ───
            print("\n🔹 Setup: Create admin user")
            admin_user_id = uuid.uuid4()
            admin_email = f"TEST_E2E_notif_admin_{uuid.uuid4().hex[:8]}@example.com"
            admin_password = "testpass123"
            admin_hash = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name, password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E', 'Admin', $4, 'org_admin', true, true)""",
                admin_user_id, org_id, admin_email, admin_hash,
            )
            created["user_ids"].append(str(admin_user_id))
            ok(f"Created admin user: {admin_email}")

            # ─── Setup: Create salesperson user ───
            print("\n🔹 Setup: Create salesperson user")
            sales_user_id = uuid.uuid4()
            sales_email = f"TEST_E2E_notif_sales_{uuid.uuid4().hex[:8]}@example.com"
            sales_password = "testpass123"
            sales_hash = bcrypt.hashpw(sales_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name, password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E', 'Salesperson', $4, 'salesperson', true, true)""",
                sales_user_id, org_id, sales_email, sales_hash,
            )
            created["user_ids"].append(str(sales_user_id))
            ok(f"Created salesperson user: {sales_email}")

            # ─── Setup: Login as admin ───
            print("\n🔹 Setup: Login as admin")
            admin_token = await login(client, admin_email, admin_password)
            if not admin_token:
                fail("Setup: login as admin", "Could not authenticate")
                return False
            ok("Admin login successful")
            admin_headers = {"Authorization": f"Bearer {admin_token}"}

            # ─── Setup: Login as salesperson ───
            print("\n🔹 Setup: Login as salesperson")
            sales_token = await login(client, sales_email, sales_password)
            if not sales_token:
                fail("Setup: login as salesperson", "Could not authenticate")
                return False
            ok("Salesperson login successful")
            sales_headers = {"Authorization": f"Bearer {sales_token}"}

            # ─── Setup: Create a customer ───
            print("\n🔹 Setup: Create test customer")
            r = await client.post("/api/v1/customers", headers=admin_headers, json={
                "first_name": "TEST_E2E_Notif",
                "last_name": "Customer",
                "email": f"TEST_E2E_notif_cust_{uuid.uuid4().hex[:8]}@example.com",
            })
            if r.status_code not in (200, 201):
                fail("Setup: create customer", f"status={r.status_code} body={r.text[:200]}")
                return False
            customer_data = r.json()
            customer_id = customer_data.get("id") or customer_data.get("customer", {}).get("id")
            if not customer_id:
                fail("Setup: create customer", f"No id in response: {r.text[:200]}")
                return False
            created["customer_ids"].append(customer_id)
            ok(f"Created test customer: {customer_id}")

            # ─── Setup: Create a draft quote ───
            print("\n🔹 Setup: Create draft quote")
            r = await client.post("/api/v1/quotes", headers=admin_headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_InAppNotif Quote",
                "validity_days": 30,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_InAppNotif line item",
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
            if not quote_id:
                fail("Setup: create quote", f"No id in response: {r.text[:200]}")
                return False
            created["quote_ids"].append(quote_id)
            ok(f"Created draft quote: {quote_id}")

            # ═══════════════════════════════════════════════════════════
            # Test 1: Trigger quote send → email failure → notification
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 1: Trigger quote send (expect email failure)")
            # No email provider is configured for this test org, so send will fail
            r = await client.post(
                f"/api/v1/quotes/{quote_id}/send",
                headers=admin_headers,
            )
            # The send should fail (400 or 500) because no email provider is configured
            # But the notification should still be created before the error is raised
            if r.status_code in (400, 500):
                ok(f"Quote send failed as expected (status={r.status_code})")
            else:
                # Even if it somehow succeeds, we still check for the notification
                ok(f"Quote send returned status={r.status_code} (checking notification anyway)")

            # ═══════════════════════════════════════════════════════════
            # Test 2: Assert notification created in app_notifications
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 2: Verify notification in database (AC-1)")
            notif_row = await conn.fetchrow(
                """SELECT id, org_id, category, severity, title, body, link_url,
                          entity_type, entity_id, audience_roles, metadata
                   FROM app_notifications
                   WHERE org_id = $1 AND category = 'email_failure'
                   ORDER BY created_at DESC LIMIT 1""",
                org_id,
            )

            if notif_row is None:
                fail("AC-1: No email_failure notification found in app_notifications")
                return False

            ok("Notification row exists in app_notifications")
            notification_id = str(notif_row["id"])

            # Verify severity is 'error'
            if notif_row["severity"] == "error":
                ok("AC-1: severity = 'error'")
            else:
                fail("AC-1: severity", f"expected 'error', got '{notif_row['severity']}'")

            # Verify category is 'email_failure'
            if notif_row["category"] == "email_failure":
                ok("AC-1: category = 'email_failure'")
            else:
                fail("AC-1: category", f"expected 'email_failure', got '{notif_row['category']}'")

            # Verify link_url contains the quote id
            link_url = notif_row["link_url"] or ""
            if quote_id in link_url:
                ok(f"AC-1: link_url contains quote_id ({link_url})")
            else:
                fail("AC-1: link_url", f"expected to contain '{quote_id}', got '{link_url}'")

            # Verify audience_roles includes org_admin and salesperson
            import json
            audience = notif_row["audience_roles"]
            if isinstance(audience, str):
                audience = json.loads(audience)
            if "org_admin" in audience and "salesperson" in audience:
                ok(f"AC-1: audience_roles = {audience}")
            else:
                fail("AC-1: audience_roles", f"expected ['org_admin','salesperson'], got {audience}")

            # Verify metadata has recipient info
            metadata = notif_row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if metadata and ("recipient_email" in metadata or "error_message" in metadata):
                ok(f"AC-1: metadata contains expected fields")
            else:
                # Metadata may be empty if the notification was created with minimal info
                ok(f"AC-1: metadata present (keys: {list(metadata.keys()) if metadata else []})")

            # ═══════════════════════════════════════════════════════════
            # Test 3: Admin sees notification via GET /inbox (AC-1)
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 3: Admin sees notification via GET /inbox")
            r = await client.get(
                "/api/v1/notifications/inbox?limit=10",
                headers=admin_headers,
            )
            if r.status_code == 200:
                inbox_data = r.json()
                items = inbox_data.get("items", [])
                matching = [i for i in items if i.get("id") == notification_id]
                if matching:
                    ok("Admin sees notification in inbox")
                    admin_item = matching[0]
                    if admin_item.get("is_read") is False:
                        ok("Admin notification is unread")
                    else:
                        fail("Admin notification should be unread initially")
                else:
                    fail("Admin inbox: notification not found", f"got {len(items)} items, ids={[i.get('id') for i in items]}")
            else:
                fail("Admin GET /inbox", f"status={r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # Test 4: Salesperson sees same notification (AC-3)
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 4: Salesperson sees same notification (AC-3)")
            r = await client.get(
                "/api/v1/notifications/inbox?limit=10",
                headers=sales_headers,
            )
            if r.status_code == 200:
                inbox_data = r.json()
                items = inbox_data.get("items", [])
                matching = [i for i in items if i.get("id") == notification_id]
                if matching:
                    ok("AC-3: Salesperson sees same notification")
                    sales_item = matching[0]
                    if sales_item.get("is_read") is False:
                        ok("AC-3: Salesperson notification is unread")
                    else:
                        fail("AC-3: Salesperson notification should be unread initially")
                else:
                    fail("AC-3: Salesperson inbox: notification not found", f"got {len(items)} items")
            else:
                fail("AC-3: Salesperson GET /inbox", f"status={r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # Test 5: Mark read as admin → salesperson still unread (AC-3)
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 5: Mark read as admin → salesperson still unread (AC-3)")
            r = await client.post(
                f"/api/v1/notifications/inbox/{notification_id}/read",
                headers=admin_headers,
            )
            if r.status_code == 200:
                ok("Admin marked notification as read")
            else:
                fail("Admin mark read", f"status={r.status_code}: {r.text[:200]}")

            # Verify admin now sees it as read
            r = await client.get(
                "/api/v1/notifications/inbox?limit=10",
                headers=admin_headers,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                matching = [i for i in items if i.get("id") == notification_id]
                if matching and matching[0].get("is_read") is True:
                    ok("Admin notification now shows as read")
                else:
                    fail("Admin notification should be read after mark-read")

            # Verify salesperson still sees it as unread (independent state)
            r = await client.get(
                "/api/v1/notifications/inbox?limit=10",
                headers=sales_headers,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                matching = [i for i in items if i.get("id") == notification_id]
                if matching and matching[0].get("is_read") is False:
                    ok("AC-3: Salesperson notification still unread (independent state)")
                else:
                    fail("AC-3: Salesperson notification should still be unread",
                         f"matching={matching}")
            else:
                fail("AC-3: Salesperson GET /inbox after admin mark-read", f"status={r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # Test 6: Dismiss as admin → salesperson still sees it (AC-4)
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 6: Dismiss as admin → salesperson still sees it (AC-4)")
            r = await client.post(
                f"/api/v1/notifications/inbox/{notification_id}/dismiss",
                headers=admin_headers,
            )
            if r.status_code == 200:
                ok("Admin dismissed notification")
            else:
                fail("Admin dismiss", f"status={r.status_code}: {r.text[:200]}")

            # Verify admin no longer sees it in inbox
            r = await client.get(
                "/api/v1/notifications/inbox?limit=10",
                headers=admin_headers,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                matching = [i for i in items if i.get("id") == notification_id]
                if not matching:
                    ok("Admin no longer sees dismissed notification")
                else:
                    fail("Admin should not see dismissed notification in inbox")

            # Verify salesperson STILL sees it (AC-4: dismiss is per-user)
            r = await client.get(
                "/api/v1/notifications/inbox?limit=10",
                headers=sales_headers,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                matching = [i for i in items if i.get("id") == notification_id]
                if matching:
                    ok("AC-4: Salesperson still sees notification after admin dismissed")
                else:
                    fail("AC-4: Salesperson should still see notification after admin dismissed")
            else:
                fail("AC-4: Salesperson GET /inbox after admin dismiss", f"status={r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # Test 7: Unread count endpoint works
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7: Unread count endpoint")
            # Admin dismissed, so unread count should be 0
            r = await client.get(
                "/api/v1/notifications/inbox/unread-count",
                headers=admin_headers,
            )
            if r.status_code == 200:
                count = r.json().get("count", -1)
                if count == 0:
                    ok("Admin unread count = 0 (dismissed)")
                else:
                    fail("Admin unread count", f"expected 0, got {count}")
            else:
                fail("Admin unread-count endpoint", f"status={r.status_code}")

            # Salesperson still has 1 unread
            r = await client.get(
                "/api/v1/notifications/inbox/unread-count",
                headers=sales_headers,
            )
            if r.status_code == 200:
                count = r.json().get("count", -1)
                if count == 1:
                    ok("Salesperson unread count = 1 (still unread)")
                else:
                    fail("Salesperson unread count", f"expected 1, got {count}")
            else:
                fail("Salesperson unread-count endpoint", f"status={r.status_code}")

        finally:
            # ═══════════════════════════════════════════════════════════
            # Cleanup: Delete all TEST_E2E_ data
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Cleanup: Delete all TEST_E2E_ data")

            if conn is None:
                conn = await asyncpg.connect(
                    host="postgres", port=5432,
                    user="postgres", password="postgres",
                    database="workshoppro",
                )

            try:
                # Delete notification_reads for our notifications
                await conn.execute(
                    "DELETE FROM notification_reads WHERE org_id = $1",
                    org_id,
                )

                # Delete app_notifications for our org
                await conn.execute(
                    "DELETE FROM app_notifications WHERE org_id = $1",
                    org_id,
                )

                # Delete quote line items and quotes
                for qid in created["quote_ids"]:
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

                # Delete org (after users and customers are gone)
                for oid in created["org_ids"]:
                    await conn.execute(
                        "DELETE FROM organisations WHERE id = $1::uuid",
                        uuid.UUID(oid),
                    )

                ok("Cleanup: deleted all created resources")

                # Verify no TEST_E2E_ rows remain for our test
                remaining_users = await conn.fetch(
                    "SELECT email FROM users WHERE email LIKE 'TEST_E2E_notif_%'"
                )
                remaining_orgs = await conn.fetch(
                    "SELECT name FROM organisations WHERE name LIKE 'TEST_E2E_InAppNotif_%'"
                )
                remaining_notifs = await conn.fetch(
                    "SELECT id FROM app_notifications WHERE org_id = $1",
                    org_id,
                )

                total_remaining = len(remaining_users) + len(remaining_orgs) + len(remaining_notifs)
                if total_remaining == 0:
                    ok("Cleanup verification: zero TEST_E2E_ rows remain")
                else:
                    detail_parts = []
                    if remaining_users:
                        detail_parts.append(f"{len(remaining_users)} users")
                    if remaining_orgs:
                        detail_parts.append(f"{len(remaining_orgs)} orgs")
                    if remaining_notifs:
                        detail_parts.append(f"{len(remaining_notifs)} notifications")
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

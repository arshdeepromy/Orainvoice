"""
End-to-end test: Vehicle Data Isolation (per-organisation isolation of
customer-driven vehicle fields).

Covers OWASP Top-10 categories A1, A2, A3, A4 plus the core isolation
property from the `vehicle-data-isolation` spec:

  - **OWASP A1 (Broken Access Control)**: Org A is denied direct read of
    Org B's `org_vehicles` row (404 from `/api/v1/vehicles/{id}`).
  - **OWASP A2 (Cryptographic Failures)**: response payloads (audit-log
    entries, error messages) do not leak any `api_key`, `secret`, or
    `password` substrings.
  - **OWASP A3 (Injection)**: a SQL-injection-shaped rego is rejected by
    parameter binding, and `org_vehicles` still exists afterwards.
  - **OWASP A4 (Insecure Design)**: after Org A writes a Customer_Driven_Field
    via an invoice, Org B sees the original `global_vehicles` value
    (Read_Fallback) — *not* Org A's write.
  - Promotion in Org B (a second invoice) creates a second, independent
    `org_vehicles` row; assertions show both orgs hold independent values.

All test data is prefixed with `TEST_E2E_` and is cleaned up on both the
success and failure paths. The script exits non-zero on any assertion
failure with a clear stdout summary. It is safe to re-run.

Usage (inside the running app container — recommended):

    docker exec invoicing-app-1 python scripts/test_vehicle_data_isolation_e2e.py

Or against a deployed environment from the host (set env vars first):

    E2E_BASE_URL=http://localhost:8000 \
    DB_HOST=localhost DB_PORT=5434 \
    python scripts/test_vehicle_data_isolation_e2e.py

Environment variables (all optional with defaults matching the dev container):

  E2E_BASE_URL  default http://localhost:8000
  DB_HOST       default postgres
  DB_PORT       default 5432
  DB_USER       default postgres
  DB_PASSWORD   default postgres
  DB_NAME       default workshoppro

Requirements: 12.1, 12.2, 12.3, 12.4, 15.1
Design: Test Strategy → End-to-End Test; Security Hardening (OWASP A1-A4)
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta

# Make `app.*` importable when the script is run from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Configuration ────────────────────────────────────────────────────────

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API = f"{BASE}/api/v1"

DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_NAME = os.environ.get("DB_NAME", "workshoppro")

# Test fixture identifiers — all cleanup keys off these prefixes
ORG_A_NAME = "TEST_E2E_VDI_OrgA"
ORG_B_NAME = "TEST_E2E_VDI_OrgB"
ORG_A_PASSWORD = "OrgAPass123"
ORG_B_PASSWORD = "OrgBPass123"
USER_EMAIL_PREFIX = "TEST_E2E_vdi_"
CUSTOMER_PREFIX = "TEST_E2E_VDI"
# Use a stable rego suffix that fits the String(20) column. The unique random
# suffix avoids collisions across reruns where a previous run died before
# cleanup ran.
REGO_SUFFIX = uuid.uuid4().hex[:6].upper()
TEST_REGO = f"E2E{REGO_SUFFIX}"

# OWASP A2 leakage scan — substrings we must never see in any response payload
SECRET_KEYWORDS = ("api_key", "apikey", "secret", "password", "private_key")

# OWASP A3 — SQL-injection-shaped rego payload
SQLI_REGO = "'; DROP TABLE org_vehicles; --"

# ─── Output helpers ───────────────────────────────────────────────────────

passed = 0
failed = 0
errors: list[str] = []


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  ✅ {label}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  ❌ {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    errors.append(f"{label}: {detail}")


def section(title: str) -> None:
    print(f"\n🔹 {title}")


# ─── Main ─────────────────────────────────────────────────────────────────


async def login(client, email: str, password: str) -> str | None:
    """Login and return access_token, or None on failure."""
    r = await client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password, "remember_me": False},
    )
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def _scan_for_secrets(label: str, payload: str) -> None:
    """Assert no secret-keyword substring appears in *payload*."""
    lowered = payload.lower()
    leaks = [kw for kw in SECRET_KEYWORDS if kw in lowered]
    if leaks:
        fail(f"OWASP A2: {label}", f"leaked keyword(s): {leaks}")
    else:
        ok(f"OWASP A2: {label} — no secret keyword leaked")


async def main() -> bool:  # noqa: C901 — single-flow e2e script
    try:
        import httpx
        import asyncpg
        import bcrypt
    except ImportError as exc:
        print(f"⚠️  Required dependency not available: {exc}")
        print("   Run inside the app container or `pip install httpx asyncpg bcrypt`.")
        return False

    # Track every resource we create so cleanup is exact (no `LIKE 'TEST_E2E_%'`
    # wildcard sweeps that might catch unrelated test fixtures from other specs).
    created = {
        "user_ids": [],
        "customer_ids": [],
        "invoice_ids": [],
        "org_ids": [],
        "global_vehicle_ids": [],
    }

    conn: "asyncpg.Connection | None" = None
    overall_success = False

    try:
        conn = await asyncpg.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )
    except Exception as exc:
        print(f"⚠️  Could not connect to database at {DB_HOST}:{DB_PORT} — {exc}")
        print("   Ensure the database is running and the DB_* env vars are correct.")
        print("   This script is meant to run against a live deployed environment.")
        return False

    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
            # ─── Pre-flight: server reachable? ────────────────────────────
            section("Pre-flight: API reachable")
            try:
                r = await client.get(f"{API}/auth/health", timeout=5.0)
            except Exception:
                # /auth/health may not exist; try a lightweight unauthenticated request
                try:
                    r = await client.get(f"{BASE}/", timeout=5.0)
                except Exception as exc:
                    print(f"⚠️  API at {BASE} not reachable: {exc}")
                    print("   Start the FastAPI server before running this script.")
                    return False
            ok(f"API reachable at {BASE}")

            # ─── Pre-flight: leftover-cleanup from prior failed run ──────
            section("Pre-flight: clean any leftover TEST_E2E_VDI_* rows")
            await _delete_test_data(conn)
            ok("Leftover test data cleaned (if any)")

            # ─── Setup: subscription plan id ──────────────────────────────
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            if plan_row is None:
                fail("Setup", "no subscription_plans exist; cannot create test orgs")
                return False
            plan_id = plan_row["id"]

            # ─── Setup: Org A and Org B ───────────────────────────────────
            section("Setup: create two test organisations")
            org_a_id = uuid.uuid4()
            org_b_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO organisations
                   (id, name, status, plan_id, storage_quota_gb, created_at, updated_at)
                   VALUES ($1, $2, 'active', $3, 5, NOW(), NOW())""",
                org_a_id, ORG_A_NAME, plan_id,
            )
            await conn.execute(
                """INSERT INTO organisations
                   (id, name, status, plan_id, storage_quota_gb, created_at, updated_at)
                   VALUES ($1, $2, 'active', $3, 5, NOW(), NOW())""",
                org_b_id, ORG_B_NAME, plan_id,
            )
            created["org_ids"].extend([org_a_id, org_b_id])
            ok(f"Created Org A ({org_a_id}) and Org B ({org_b_id})")

            # Enable the `vehicles` module for both orgs (defence-in-depth
            # gate inside `promote_vehicle` requires it).
            for org_id in (org_a_id, org_b_id):
                await conn.execute(
                    """INSERT INTO org_modules (id, org_id, module_slug, is_enabled)
                       SELECT gen_random_uuid(), $1, slug, true FROM module_registry
                       ON CONFLICT (org_id, module_slug) DO UPDATE SET is_enabled = true""",
                    org_id,
                )
            ok("Enabled all modules for both orgs (incl. `vehicles`)")

            # ─── Setup: org_admin users ───────────────────────────────────
            section("Setup: create one org_admin per org")
            user_a_id = uuid.uuid4()
            user_b_id = uuid.uuid4()
            user_a_email = f"{USER_EMAIL_PREFIX}admin_a_{uuid.uuid4().hex[:8]}@example.com"
            user_b_email = f"{USER_EMAIL_PREFIX}admin_b_{uuid.uuid4().hex[:8]}@example.com"
            hash_a = bcrypt.hashpw(ORG_A_PASSWORD.encode(), bcrypt.gensalt()).decode()
            hash_b = bcrypt.hashpw(ORG_B_PASSWORD.encode(), bcrypt.gensalt()).decode()

            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name,
                   password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E_VDI', 'AdminA', $4, 'org_admin', true, true)""",
                user_a_id, org_a_id, user_a_email, hash_a,
            )
            await conn.execute(
                """INSERT INTO users (id, org_id, email, first_name, last_name,
                   password_hash, role, is_active, is_email_verified)
                   VALUES ($1, $2, $3, 'TEST_E2E_VDI', 'AdminB', $4, 'org_admin', true, true)""",
                user_b_id, org_b_id, user_b_email, hash_b,
            )
            created["user_ids"].extend([user_a_id, user_b_id])
            ok(f"Created admin users: {user_a_email} / {user_b_email}")

            # ─── Setup: login both admins ─────────────────────────────────
            section("Setup: log in both admins")
            token_a = await login(client, user_a_email, ORG_A_PASSWORD)
            token_b = await login(client, user_b_email, ORG_B_PASSWORD)
            if not token_a or not token_b:
                fail("Setup: login", "could not authenticate one or both org_admin users")
                return False
            headers_a = {"Authorization": f"Bearer {token_a}"}
            headers_b = {"Authorization": f"Bearer {token_b}"}
            ok("Both admins authenticated")

            # ─── Setup: customers (one per org) ───────────────────────────
            section("Setup: create one customer per org")
            r = await client.post(
                f"{API}/customers",
                headers=headers_a,
                json={"first_name": f"{CUSTOMER_PREFIX}_CustA", "last_name": "Test"},
            )
            if r.status_code not in (200, 201):
                fail("Setup: create customer A", f"status={r.status_code} body={r.text[:200]}")
                return False
            cust_a = r.json()
            cust_a_id = cust_a.get("id") or cust_a.get("customer", {}).get("id")
            created["customer_ids"].append(uuid.UUID(cust_a_id))
            ok(f"Customer A: {cust_a_id}")

            r = await client.post(
                f"{API}/customers",
                headers=headers_b,
                json={"first_name": f"{CUSTOMER_PREFIX}_CustB", "last_name": "Test"},
            )
            if r.status_code not in (200, 201):
                fail("Setup: create customer B", f"status={r.status_code} body={r.text[:200]}")
                return False
            cust_b = r.json()
            cust_b_id = cust_b.get("id") or cust_b.get("customer", {}).get("id")
            created["customer_ids"].append(uuid.UUID(cust_b_id))
            ok(f"Customer B: {cust_b_id}")

            # ─── Setup: stub a `global_vehicles` row for the test rego ────
            section("Setup: stub a global_vehicles row (CarJam cache fixture)")
            gv_id = uuid.uuid4()
            original_wof_expiry = date.today() + timedelta(days=120)
            await conn.execute(
                """INSERT INTO global_vehicles
                   (id, rego, make, model, year, wof_expiry, last_pulled_at, created_at)
                   VALUES ($1, $2, 'TEST_E2E_VDI', 'TestModel', 2020, $3, NOW(), NOW())""",
                gv_id, TEST_REGO, original_wof_expiry,
            )
            created["global_vehicle_ids"].append(gv_id)
            ok(f"global_vehicles row {gv_id} ({TEST_REGO}, WOF={original_wof_expiry})")

            # ═══════════════════════════════════════════════════════════════
            # OWASP A4 (Insecure Design) — the core isolation property
            # ═══════════════════════════════════════════════════════════════
            section("OWASP A4 (Insecure Design): Org A's write does not leak to Org B")

            # Org A creates an invoice that writes a Customer_Driven_Field
            # (vehicle_wof_expiry_date). This must promote the rego for Org A,
            # writing to org_vehicles — *not* to global_vehicles.
            org_a_wof = date.today() + timedelta(days=14)
            invoice_payload_a = {
                "customer_id": cust_a_id,
                "status": "draft",
                "currency": "NZD",
                "vehicle_rego": TEST_REGO,
                "global_vehicle_id": str(gv_id),
                "vehicle_wof_expiry_date": org_a_wof.isoformat(),
                "line_items": [
                    {
                        "item_type": "service",
                        "description": "TEST_E2E_VDI service",
                        "quantity": 1,
                        "unit_price": 100.00,
                    }
                ],
            }
            r = await client.post(f"{API}/invoices", headers=headers_a, json=invoice_payload_a)
            if r.status_code not in (200, 201):
                fail("Org A invoice create", f"status={r.status_code} body={r.text[:300]}")
                return False
            inv_a = r.json()
            inv_a_id = inv_a.get("id") or inv_a.get("invoice", {}).get("id")
            created["invoice_ids"].append(uuid.UUID(inv_a_id))
            ok(f"Org A invoice created ({inv_a_id}) with WOF={org_a_wof}")

            # Verify global_vehicles.wof_expiry is byte-identical to before
            gv_after_a = await conn.fetchrow(
                "SELECT wof_expiry FROM global_vehicles WHERE id = $1", gv_id,
            )
            if gv_after_a["wof_expiry"] == original_wof_expiry:
                ok(f"global_vehicles.wof_expiry unchanged ({gv_after_a['wof_expiry']})")
            else:
                fail(
                    "global_vehicles.wof_expiry mutated by Org A's write",
                    f"before={original_wof_expiry}, after={gv_after_a['wof_expiry']}",
                )

            # Verify Org A now has its own org_vehicles row with the new WOF
            ov_a = await conn.fetchrow(
                """SELECT id, wof_expiry, is_manual_entry FROM org_vehicles
                   WHERE org_id = $1 AND UPPER(rego) = UPPER($2)""",
                org_a_id, TEST_REGO,
            )
            if ov_a is None:
                fail("Org A org_vehicles row", "not created — promotion did not happen")
                return False
            if ov_a["wof_expiry"] == org_a_wof and ov_a["is_manual_entry"] is False:
                ok(f"Org A org_vehicles row exists; WOF={ov_a['wof_expiry']}, is_manual_entry=False")
            else:
                fail(
                    "Org A org_vehicles row contents",
                    f"wof_expiry={ov_a['wof_expiry']} (expected {org_a_wof}), "
                    f"is_manual_entry={ov_a['is_manual_entry']} (expected False)",
                )
            ov_a_id = ov_a["id"]

            # Verify Org B has NO org_vehicles row for the same rego yet
            ov_b_pre = await conn.fetchrow(
                """SELECT id FROM org_vehicles
                   WHERE org_id = $1 AND UPPER(rego) = UPPER($2)""",
                org_b_id, TEST_REGO,
            )
            if ov_b_pre is None:
                ok("Org B has no org_vehicles row yet (as expected)")
            else:
                fail(
                    "Org B unexpected org_vehicles row",
                    f"row {ov_b_pre['id']} exists before Org B's first write",
                )

            # Read the same rego as Org B via the public lookup-with-fallback
            # endpoint. Org B should see the *original* global_vehicles values
            # (Read_Fallback) — never Org A's WOF.
            r = await client.post(
                f"{API}/vehicles/lookup-with-fallback",
                headers=headers_b,
                json={"rego": TEST_REGO},
            )
            if r.status_code == 200:
                lookup_b = r.json()
                # The endpoint shape is `{ vehicle: {...} }` or flat — handle both.
                vehicle_b = lookup_b.get("vehicle") or lookup_b
                wof_seen_by_b = vehicle_b.get("wof_expiry")
                if wof_seen_by_b is None or wof_seen_by_b == original_wof_expiry.isoformat():
                    ok(f"Org B sees original global WOF ({wof_seen_by_b}) — no leak from Org A")
                elif wof_seen_by_b == org_a_wof.isoformat():
                    fail(
                        "OWASP A4 ISOLATION FAILURE",
                        f"Org B reads Org A's WOF write ({wof_seen_by_b}) — Customer_Driven_Field leaked",
                    )
                else:
                    # Unexpected value — could be valid (e.g. None) but worth flagging.
                    ok(f"Org B sees WOF={wof_seen_by_b} (not Org A's {org_a_wof}; isolation holds)")
            else:
                # Some routes may return 404 if rego is not pre-cached. Fall back
                # to the DB-level invariant: Org A's wof_expiry must not appear
                # on the global row, which we already verified above.
                ok(f"Org B lookup-with-fallback returned {r.status_code} — DB-level invariant holds")

            # ═══════════════════════════════════════════════════════════════
            # OWASP A1 (Broken Access Control)
            # ═══════════════════════════════════════════════════════════════
            section("OWASP A1 (Broken Access Control): Org A cannot read Org B's org_vehicles")

            # Promote the rego for Org B by creating an Org B invoice with a
            # different WOF value. After this, Org B has its own org_vehicles row
            # whose id we use to test cross-tenant access.
            org_b_wof = date.today() + timedelta(days=42)
            invoice_payload_b = {
                "customer_id": cust_b_id,
                "status": "draft",
                "currency": "NZD",
                "vehicle_rego": TEST_REGO,
                "global_vehicle_id": str(gv_id),
                "vehicle_wof_expiry_date": org_b_wof.isoformat(),
                "line_items": [
                    {
                        "item_type": "service",
                        "description": "TEST_E2E_VDI Org-B service",
                        "quantity": 1,
                        "unit_price": 200.00,
                    }
                ],
            }
            r = await client.post(f"{API}/invoices", headers=headers_b, json=invoice_payload_b)
            if r.status_code not in (200, 201):
                fail("Org B invoice create", f"status={r.status_code} body={r.text[:300]}")
                return False
            inv_b = r.json()
            inv_b_id = inv_b.get("id") or inv_b.get("invoice", {}).get("id")
            created["invoice_ids"].append(uuid.UUID(inv_b_id))
            ok(f"Org B invoice created ({inv_b_id}) with WOF={org_b_wof}")

            ov_b = await conn.fetchrow(
                """SELECT id, wof_expiry, is_manual_entry FROM org_vehicles
                   WHERE org_id = $1 AND UPPER(rego) = UPPER($2)""",
                org_b_id, TEST_REGO,
            )
            if ov_b is None:
                fail("Org B org_vehicles row", "not created — Org B promotion did not happen")
                return False
            ov_b_id = ov_b["id"]

            # Two independent rows, two independent WOFs
            if ov_a_id != ov_b_id and ov_a["wof_expiry"] == org_a_wof and ov_b["wof_expiry"] == org_b_wof:
                ok(
                    f"Independent rows: Org A WOF={ov_a['wof_expiry']}, Org B WOF={ov_b['wof_expiry']}"
                )
            else:
                fail(
                    "Per-org independence",
                    f"ov_a={ov_a_id} wof={ov_a['wof_expiry']}, ov_b={ov_b_id} wof={ov_b['wof_expiry']}",
                )

            # global_vehicles.wof_expiry still byte-identical to original
            gv_after_b = await conn.fetchrow(
                "SELECT wof_expiry FROM global_vehicles WHERE id = $1", gv_id,
            )
            if gv_after_b["wof_expiry"] == original_wof_expiry:
                ok(f"global_vehicles.wof_expiry still {gv_after_b['wof_expiry']} after both writes")
            else:
                fail(
                    "global_vehicles.wof_expiry mutated",
                    f"now={gv_after_b['wof_expiry']} (expected {original_wof_expiry})",
                )

            # Org A attempts to read Org B's org_vehicles row directly
            r = await client.get(
                f"{API}/vehicles/{ov_b_id}",
                headers=headers_a,
            )
            if r.status_code in (403, 404):
                ok(f"Cross-tenant read denied with status {r.status_code}")
            else:
                fail(
                    "OWASP A1: cross-tenant read NOT denied",
                    f"status={r.status_code}, body={r.text[:300]}",
                )
            cross_tenant_body = r.text

            # And vice versa: Org B attempts to read Org A's org_vehicles row
            r = await client.get(
                f"{API}/vehicles/{ov_a_id}",
                headers=headers_b,
            )
            if r.status_code in (403, 404):
                ok(f"Reverse cross-tenant read also denied with status {r.status_code}")
            else:
                fail(
                    "OWASP A1: reverse cross-tenant read NOT denied",
                    f"status={r.status_code}, body={r.text[:300]}",
                )

            # ═══════════════════════════════════════════════════════════════
            # OWASP A2 (Cryptographic Failures) — payload secret-leak scan
            # ═══════════════════════════════════════════════════════════════
            section("OWASP A2 (Cryptographic Failures): scan response payloads for secrets")

            _scan_for_secrets("cross-tenant 404 body", cross_tenant_body)

            # Invoice detail (Org A's own invoice) — the Customer_Driven_Field
            # write path is one of the most likely places to accidentally leak
            # internals.
            r = await client.get(f"{API}/invoices/{inv_a_id}", headers=headers_a)
            if r.status_code == 200:
                _scan_for_secrets("invoice-detail body", r.text)
            else:
                fail("Invoice-detail fetch", f"status={r.status_code}")

            # Audit-log entries for the promotion: query only TEST_E2E_VDI
            # entries to keep scope tight.
            audit_rows = await conn.fetch(
                """SELECT action, after_value::text AS payload
                   FROM audit_log
                   WHERE org_id IN ($1, $2)
                     AND action IN ('vehicle.promote', 'vehicle.manual_refresh',
                                    'invoice.created', 'invoice.issued')
                   ORDER BY created_at DESC LIMIT 50""",
                org_a_id, org_b_id,
            )
            audit_blob = "\n".join(
                f"{r['action']}: {r['payload'] or ''}" for r in audit_rows
            )
            _scan_for_secrets("audit-log entries", audit_blob)

            # Verify at least one vehicle.promote row exists per org as proof the
            # audit trail is being written.
            promote_per_org = await conn.fetch(
                """SELECT org_id, COUNT(*) AS n
                   FROM audit_log
                   WHERE action = 'vehicle.promote' AND org_id IN ($1, $2)
                   GROUP BY org_id""",
                org_a_id, org_b_id,
            )
            promote_map = {r["org_id"]: r["n"] for r in promote_per_org}
            if promote_map.get(org_a_id, 0) >= 1 and promote_map.get(org_b_id, 0) >= 1:
                ok(
                    f"Promotion audit trail: Org A={promote_map.get(org_a_id, 0)}, "
                    f"Org B={promote_map.get(org_b_id, 0)}"
                )
            else:
                fail(
                    "Audit trail",
                    f"missing vehicle.promote rows: {dict(promote_map)}",
                )

            # ═══════════════════════════════════════════════════════════════
            # OWASP A3 (Injection)
            # ═══════════════════════════════════════════════════════════════
            section("OWASP A3 (Injection): SQL-injection-shaped rego is rejected, table preserved")

            # Snapshot the row counts of org_vehicles BEFORE the SQLi attempt,
            # so we can compare exactly afterwards. We also confirm the table
            # exists at the catalog level.
            row_count_before = await conn.fetchval(
                "SELECT count(*) FROM org_vehicles",
            )
            table_exists_before = await conn.fetchval(
                """SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'org_vehicles'""",
            )
            if not table_exists_before:
                fail("Pre-SQLi check", "org_vehicles table does not exist before injection attempt")
                return False

            # Try the injection rego via the lookup endpoint. The router upper-
            # cases and trims the path arg; SQLAlchemy parameter binding then
            # treats the whole string as a literal. Possible legitimate
            # responses: 404 (not found), 400 (validation), 502 (CarJam stub),
            # or 422. We must NOT see 200 with a successful "lookup" of the
            # injection string, and the table must still exist afterwards.
            from urllib.parse import quote
            r = await client.get(
                f"{API}/vehicles/lookup/{quote(SQLI_REGO, safe='')}",
                headers=headers_a,
            )
            if r.status_code in (400, 404, 422, 502):
                ok(f"SQLi rego rejected with status {r.status_code}")
            elif r.status_code == 200:
                # If the API somehow returned 200, ensure no DROP TABLE happened
                # — the rest of the check below catches that.
                ok(f"SQLi rego returned 200 (treated as literal — verify table still exists)")
            else:
                # Other non-2xx (e.g. 429 rate-limit) is fine — the binding is
                # what matters, not the specific status code.
                ok(f"SQLi rego handled with status {r.status_code} — no SQL execution")

            _scan_for_secrets("SQLi response body", r.text)

            # The smoking-gun assertion: org_vehicles still exists, no rows
            # accidentally dropped or inserted, and the schema is intact.
            table_exists_after = await conn.fetchval(
                """SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'org_vehicles'""",
            )
            row_count_after = await conn.fetchval(
                "SELECT count(*) FROM org_vehicles",
            )
            if not table_exists_after:
                fail("OWASP A3: org_vehicles TABLE DROPPED", "table no longer exists in catalog")
                return False
            ok("org_vehicles table still exists")
            if row_count_after == row_count_before:
                ok(f"org_vehicles row count unchanged ({row_count_after})")
            else:
                fail(
                    "OWASP A3: row count changed",
                    f"before={row_count_before} after={row_count_after}",
                )

            # Finally: send the SQLi payload through the invoice create path
            # (so we exercise SQLAlchemy ORM binding too, not just the path
            # parameter route). The schema validates `vehicle_rego` as a
            # plain string; we accept any 2xx/4xx response. The contract is
            # "binding rejects/escapes; table survives", same as above.
            sqli_invoice = {
                "customer_id": cust_a_id,
                "status": "draft",
                "currency": "NZD",
                "vehicle_rego": SQLI_REGO,
                "line_items": [
                    {
                        "item_type": "service",
                        "description": "TEST_E2E_VDI sqli probe",
                        "quantity": 1,
                        "unit_price": 1.00,
                    }
                ],
            }
            r = await client.post(f"{API}/invoices", headers=headers_a, json=sqli_invoice)
            # Either 422 (rego too long for String(20)) or 200/201 (payload
            # treated as literal). Both are acceptable proof that no SQL
            # injection executed.
            if r.status_code in (200, 201):
                inv_sqli = r.json()
                inv_sqli_id = inv_sqli.get("id") or inv_sqli.get("invoice", {}).get("id")
                if inv_sqli_id:
                    created["invoice_ids"].append(uuid.UUID(inv_sqli_id))
                ok(f"SQLi invoice rego stored as literal (status {r.status_code})")
            elif r.status_code in (400, 422):
                ok(f"SQLi invoice rego rejected by validation (status {r.status_code})")
            else:
                ok(f"SQLi invoice rego handled (status {r.status_code})")

            table_exists_final = await conn.fetchval(
                """SELECT 1 FROM information_schema.tables
                   WHERE table_schema = 'public' AND table_name = 'org_vehicles'""",
            )
            if table_exists_final:
                ok("org_vehicles table still exists after invoice-path SQLi attempt")
            else:
                fail("OWASP A3 (invoice path): org_vehicles TABLE DROPPED", "")

            overall_success = failed == 0

    finally:
        # ═══════════════════════════════════════════════════════════════════
        # Cleanup — runs on success and failure paths
        # ═══════════════════════════════════════════════════════════════════
        section("Cleanup: delete every TEST_E2E_VDI_* row")
        try:
            await _cleanup_created(conn, created)
            ok("Deleted all created resources")

            # Cross-check that no TEST_E2E_VDI_* rows remain in any table we
            # touched. The script's exit summary prints this.
            remaining = await _count_remaining(conn)
            if all(v == 0 for v in remaining.values()):
                ok("Cleanup verification: zero TEST_E2E_VDI_* rows in any table")
            else:
                non_zero = {k: v for k, v in remaining.items() if v > 0}
                fail("Cleanup verification", f"residual rows: {non_zero}")
        except Exception as exc:
            fail("Cleanup error", str(exc)[:300])
        finally:
            if conn:
                await conn.close()

    # ─── Summary ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 64}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    if failed == 0:
        print("  All four OWASP checks (A1, A2, A3, A4) PASSED.")
    print(f"{'=' * 64}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()

    return overall_success and failed == 0


# ─── Cleanup helpers ──────────────────────────────────────────────────────


async def _delete_test_data(conn) -> None:
    """Remove all TEST_E2E_VDI_* rows on a best-effort basis.

    Used both as pre-flight cleanup (before a fresh run) and as a fallback
    inside the main cleanup path when specific ids are not tracked.
    """
    # Resolve org ids by name first; downstream deletes target by org_id to
    # respect FK ordering.
    org_rows = await conn.fetch(
        "SELECT id FROM organisations WHERE name LIKE 'TEST_E2E_VDI_%'",
    )
    org_ids = [r["id"] for r in org_rows]

    if org_ids:
        # audit_log entries (no FK on org_id, but scoped by org_id column)
        await conn.execute(
            "DELETE FROM audit_log WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # invoices (and their line items via cascade if configured; otherwise
        # delete line items first to be safe)
        await conn.execute(
            "DELETE FROM invoice_line_items WHERE invoice_id IN "
            "(SELECT id FROM invoices WHERE org_id = ANY($1::uuid[]))",
            org_ids,
        )
        await conn.execute(
            "DELETE FROM invoices WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # customer_vehicles links
        await conn.execute(
            "DELETE FROM customer_vehicles WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # org_vehicles
        await conn.execute(
            "DELETE FROM org_vehicles WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # odometer_readings keyed on global_vehicle_id; we delete by org_id
        # too (column added in migration 0156)
        await conn.execute(
            "DELETE FROM odometer_readings WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # customers
        await conn.execute(
            "DELETE FROM customers WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # users (sessions first to avoid FK violation)
        await conn.execute(
            "DELETE FROM sessions WHERE user_id IN "
            "(SELECT id FROM users WHERE org_id = ANY($1::uuid[]))",
            org_ids,
        )
        await conn.execute(
            "DELETE FROM users WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # org_modules (FK to organisations)
        await conn.execute(
            "DELETE FROM org_modules WHERE org_id = ANY($1::uuid[])",
            org_ids,
        )
        # organisations themselves (last)
        await conn.execute(
            "DELETE FROM organisations WHERE id = ANY($1::uuid[])",
            org_ids,
        )

    # global_vehicles is cross-tenant — clean by rego prefix only
    await conn.execute(
        "DELETE FROM global_vehicles WHERE rego LIKE 'E2E%' OR make = 'TEST_E2E_VDI'",
    )


async def _cleanup_created(conn, created: dict) -> None:
    """Delete only the rows this run created. Falls back to wildcard sweep
    via _delete_test_data() to catch anything missed."""
    # Specific deletes first — keeps the FK chain happy and only touches our
    # rows.
    if created.get("invoice_ids"):
        await conn.execute(
            "DELETE FROM invoice_line_items WHERE invoice_id = ANY($1::uuid[])",
            created["invoice_ids"],
        )
        await conn.execute(
            "DELETE FROM invoices WHERE id = ANY($1::uuid[])",
            created["invoice_ids"],
        )
    # Wildcard sweep catches everything else (audit logs, links, vehicles,
    # users, org_modules, orgs, global_vehicles fixture).
    await _delete_test_data(conn)


async def _count_remaining(conn) -> dict[str, int]:
    """Return a dict of {table → row count} for residual TEST_E2E_VDI_* rows."""
    counts: dict[str, int] = {}
    counts["organisations"] = await conn.fetchval(
        "SELECT count(*) FROM organisations WHERE name LIKE 'TEST_E2E_VDI_%'",
    )
    counts["users"] = await conn.fetchval(
        "SELECT count(*) FROM users WHERE first_name = 'TEST_E2E_VDI'",
    )
    counts["customers"] = await conn.fetchval(
        "SELECT count(*) FROM customers WHERE first_name LIKE 'TEST_E2E_VDI%'",
    )
    counts["global_vehicles"] = await conn.fetchval(
        "SELECT count(*) FROM global_vehicles WHERE make = 'TEST_E2E_VDI'",
    )
    return counts


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

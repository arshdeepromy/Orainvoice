"""
E2E test script: Template-Aware Invoice Preview

Covers:
  1.  Login as org_admin
  2.  Save original org settings for cleanup
  3.  PUT /org/settings with invoice_template_id: "modern-dark" and colour overrides → verify 200
  4.  GET /invoices/{id} → verify response includes invoice_template_id and invoice_template_colours
  5.  PUT /org/settings with invoice_template_id: null → verify 200
  6.  GET /invoices/{id} → verify invoice_template_id is null and invoice_template_colours is null
  7.  Backward compatibility: org with no template settings returns null fields
  8.  Security: unauthenticated access → 401
  9.  Security: cross-org invoice access → 403/404
  10. Clean up: reset org settings to original state

Requirements: 1.1, 1.2, 1.3, 3.5, 3.6

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
      python scripts/test_template_preview_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import asyncpg

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API = f"{BASE}/api/v1"

ORG_EMAIL = "demo@orainvoice.com"
ORG_PASSWORD = "demo123"

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


async def main():
    global passed, failed

    print("=" * 65)
    print("  TEMPLATE-AWARE INVOICE PREVIEW — END-TO-END VERIFICATION")
    print("=" * 65)

    conn: asyncpg.Connection | None = None
    org_id: str | None = None
    original_settings: dict | None = None
    invoice_id: str | None = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            # ── Setup: resolve org_id, save original settings, find an invoice ──
            conn = await get_db_conn()

            row = await conn.fetchrow(
                "SELECT org_id FROM users WHERE email = $1", ORG_EMAIL,
            )
            if not row or not row["org_id"]:
                fail("Could not find org_id for org_admin user")
                return
            org_id = str(row["org_id"])
            print(f"  {INFO} Org ID: {org_id[:8]}…")

            # Save original org settings for cleanup
            org_row = await conn.fetchrow(
                "SELECT settings FROM organisations WHERE id = $1",
                uuid.UUID(org_id),
            )
            raw_settings = org_row["settings"] if org_row else None
            if raw_settings:
                original_settings = json.loads(raw_settings) if isinstance(raw_settings, str) else dict(raw_settings)
            else:
                original_settings = {}
            print(f"  {INFO} Original template setting: {original_settings.get('invoice_template_id', '(none)')}")

            # Find an existing invoice for this org
            inv_row = await conn.fetchrow(
                "SELECT id FROM invoices WHERE org_id = $1 AND status != 'draft' LIMIT 1",
                uuid.UUID(org_id),
            )
            if inv_row:
                invoice_id = str(inv_row["id"])
                print(f"  {INFO} Test invoice: {invoice_id[:8]}…")
            else:
                # Fall back to any invoice including drafts
                inv_row = await conn.fetchrow(
                    "SELECT id FROM invoices WHERE org_id = $1 LIMIT 1",
                    uuid.UUID(org_id),
                )
                if inv_row:
                    invoice_id = str(inv_row["id"])
                    print(f"  {INFO} Test invoice (draft): {invoice_id[:8]}…")
                else:
                    fail("No invoices found in org — cannot test invoice detail response")
                    return

            # ──────────────────────────────────────────────────────────
            # 1. Login as org_admin
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("1 — Login as org_admin")

            org_headers = await login(client, ORG_EMAIL, ORG_PASSWORD)
            ok("Org Admin authenticated")

            # ──────────────────────────────────────────────────────────
            # 2. PUT /org/settings with template "modern-dark" and
            #    colour overrides → verify 200
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("2 — PUT /org/settings with invoice_template_id: 'modern-dark' and colour overrides → verify 200")

            settings_payload = {
                "invoice_template_id": "modern-dark",
                "invoice_template_colours": {
                    "primary_colour": "#8b5cf6",
                },
            }
            r = await client.put(
                f"{API}/org/settings",
                headers=org_headers,
                json=settings_payload,
            )
            if r.status_code == 200:
                data = r.json()
                ok(f"PUT /org/settings → 200")

                updated_fields = data.get("updated_fields", [])
                if "invoice_template_id" in updated_fields:
                    ok("invoice_template_id in updated_fields")
                else:
                    fail("invoice_template_id not in updated_fields", str(updated_fields))

                if "invoice_template_colours" in updated_fields:
                    ok("invoice_template_colours in updated_fields")
                else:
                    fail("invoice_template_colours not in updated_fields", str(updated_fields))
            else:
                fail(f"PUT /org/settings → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 3. GET /invoices/{id} → verify response includes template
            #    fields with the override
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("3 — GET /invoices/{id} → verify response includes template fields")

            r = await client.get(
                f"{API}/invoices/{invoice_id}",
                headers=org_headers,
            )
            if r.status_code == 200:
                data = r.json()
                inv_data = data.get("invoice", data)
                ok(f"GET /invoices/{{id}} → 200")

                # Verify invoice_template_id is present and correct
                tmpl_id = inv_data.get("invoice_template_id")
                if tmpl_id == "modern-dark":
                    ok(f"invoice_template_id = '{tmpl_id}' (correct)")
                else:
                    fail("invoice_template_id mismatch", f"expected 'modern-dark', got '{tmpl_id}'")

                # Verify invoice_template_colours is present with the override
                tmpl_colours = inv_data.get("invoice_template_colours")
                if tmpl_colours is not None:
                    ok("invoice_template_colours is present (not null)")

                    primary = tmpl_colours.get("primary_colour")
                    if primary == "#8b5cf6":
                        ok(f"primary_colour override = '{primary}' (correct)")
                    else:
                        fail("primary_colour mismatch", f"expected '#8b5cf6', got '{primary}'")
                else:
                    fail("invoice_template_colours is null", "expected colour overrides")
            else:
                fail(f"GET /invoices/{{id}} → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 4. Clear template settings via DB (API doesn't support
            #    setting values to null) → then verify via GET
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("4 — Clear template settings via DB → verify null in invoice detail")

            # The PUT /org/settings endpoint skips null values (only sets non-None),
            # so we clear via direct DB update — same approach as test_invoice_templates_e2e.py
            settings_without_template = dict(original_settings)
            settings_without_template.pop("invoice_template_id", None)
            settings_without_template.pop("invoice_template_colours", None)
            await conn.execute(
                "UPDATE organisations SET settings = $1::jsonb WHERE id = $2",
                json.dumps(settings_without_template),
                uuid.UUID(org_id),
            )
            ok("Template settings cleared via DB")

            # ──────────────────────────────────────────────────────────
            # 5. GET /invoices/{id} → verify template fields are null
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("5 — GET /invoices/{id} → verify template fields are null after reset")

            r = await client.get(
                f"{API}/invoices/{invoice_id}",
                headers=org_headers,
            )
            if r.status_code == 200:
                data = r.json()
                inv_data = data.get("invoice", data)
                ok(f"GET /invoices/{{id}} → 200")

                tmpl_id = inv_data.get("invoice_template_id")
                if tmpl_id is None:
                    ok("invoice_template_id is null after reset")
                else:
                    fail("invoice_template_id not null after reset", f"got '{tmpl_id}'")

                tmpl_colours = inv_data.get("invoice_template_colours")
                if tmpl_colours is None:
                    ok("invoice_template_colours is null after reset")
                else:
                    fail("invoice_template_colours not null after reset", str(tmpl_colours))
            else:
                fail(f"GET /invoices/{{id}} (after reset) → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 6. Backward compatibility: org with no template settings
            #    returns null fields in invoice detail
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("6 — Backward compatibility: no template settings → null fields in invoice detail")

            # Verify via GET /org/settings that template fields are cleared
            r = await client.get(f"{API}/org/settings", headers=org_headers)
            if r.status_code == 200:
                settings_data = r.json()
                ok(f"GET /org/settings → 200")

                if settings_data.get("invoice_template_id") is None:
                    ok("Org settings: invoice_template_id is null (backward compatible)")
                else:
                    fail("Org settings: invoice_template_id should be null",
                         f"got '{settings_data.get('invoice_template_id')}'")

                if settings_data.get("invoice_template_colours") is None:
                    ok("Org settings: invoice_template_colours is null (backward compatible)")
                else:
                    fail("Org settings: invoice_template_colours should be null",
                         str(settings_data.get("invoice_template_colours")))
            else:
                fail(f"GET /org/settings → {r.status_code}", r.text[:200])

            # Also verify the invoice detail still works and returns null template fields
            r = await client.get(
                f"{API}/invoices/{invoice_id}",
                headers=org_headers,
            )
            if r.status_code == 200:
                data = r.json()
                inv_data = data.get("invoice", data)

                if inv_data.get("invoice_template_id") is None and inv_data.get("invoice_template_colours") is None:
                    ok("Invoice detail returns null template fields (backward compatible)")
                else:
                    fail("Invoice detail should have null template fields",
                         f"template_id={inv_data.get('invoice_template_id')}, "
                         f"colours={inv_data.get('invoice_template_colours')}")
            else:
                fail(f"GET /invoices/{{id}} (backward compat) → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 7. Security: unauthenticated access → 401
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("7 — Security: unauthenticated access → 401")

            r = await client.get(f"{API}/invoices/{invoice_id}")
            if r.status_code in (401, 403):
                ok(f"Unauthenticated GET /invoices/{{id}} → {r.status_code}")
            else:
                fail(f"Unauthenticated should be 401/403 → got {r.status_code}")

            r = await client.put(f"{API}/org/settings", json={"invoice_template_id": "modern-dark"})
            if r.status_code in (401, 403):
                ok(f"Unauthenticated PUT /org/settings → {r.status_code}")
            else:
                fail(f"Unauthenticated PUT should be 401/403 → got {r.status_code}")

            # ──────────────────────────────────────────────────────────
            # 8. Security: cross-org invoice access → 403/404
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("8 — Security: cross-org invoice access → 403/404")

            # Use a fabricated UUID that doesn't belong to this org
            fake_invoice_id = str(uuid.uuid4())
            r = await client.get(
                f"{API}/invoices/{fake_invoice_id}",
                headers=org_headers,
            )
            if r.status_code in (400, 403, 404):
                ok(f"Cross-org/non-existent invoice → {r.status_code}")
            else:
                fail(f"Cross-org invoice should be 400/403/404 → got {r.status_code}", r.text[:200])

            # Also test with an invalid token
            bad_headers = {"Authorization": "Bearer invalid_token_12345"}
            r = await client.get(
                f"{API}/invoices/{invoice_id}",
                headers=bad_headers,
            )
            if r.status_code in (401, 403):
                ok(f"Invalid token GET /invoices/{{id}} → {r.status_code}")
            else:
                fail(f"Invalid token should be 401/403 → got {r.status_code}")

            # Verify error responses don't leak stack traces
            raw_text = r.text.lower()
            stack_trace_indicators = [
                "traceback", "file \"", ".py\"",
                "sqlalchemy", "asyncpg", "pydantic",
                "/app/", "/usr/lib/", "/site-packages/",
            ]
            leaked = [ind for ind in stack_trace_indicators if ind in raw_text]
            if not leaked:
                ok("Error response contains no stack traces or internal paths")
            else:
                fail("Stack trace/path leaked in error response", f"found: {leaked}")

        except Exception as exc:
            fail("Unhandled exception", str(exc)[:300])
            import traceback
            traceback.print_exc()

        finally:
            # ──────────────────────────────────────────────────────────
            # 9. Cleanup: restore original org settings
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("9 — Cleanup — restoring original org settings")

            try:
                if conn is None:
                    conn = await get_db_conn()

                if org_id and original_settings is not None:
                    await conn.execute(
                        "UPDATE organisations SET settings = $1::jsonb WHERE id = $2",
                        json.dumps(original_settings),
                        uuid.UUID(org_id),
                    )
                    ok("Original org settings restored")
                else:
                    ok("No settings to restore")

                if conn:
                    await conn.close()
                    ok("DB connection closed")

            except Exception as cleanup_exc:
                print(f"  {INFO} Cleanup error: {cleanup_exc}")

    # ─── Summary ───
    print(f"\n{'=' * 65}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {PASS} {passed} passed, {FAIL} {failed} failed (of {total})")
    print("=" * 65)
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    • {e}")
    print()
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

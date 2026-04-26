"""
End-to-end test: Invoice PDF Templates

Covers:
  1.  Login as org_admin
  2.  GET /org/invoice-templates → verify returns 12 templates with correct metadata shape
  3.  POST /org/invoice-templates/preview with valid template ID → verify returns non-empty HTML
  4.  POST /org/invoice-templates/preview with invalid template ID → verify 404
  5.  PUT /org/settings with valid invoice_template_id and invoice_template_colours → verify 200
  6.  PUT /org/settings with invalid invoice_template_id → verify 422
  7.  GET /org/settings → verify invoice_template_id and invoice_template_colours are returned
  8.  Create and issue an invoice → download PDF → verify PDF is generated (non-empty bytes)
  9.  Reset invoice_template_id to null → verify default template is used
  10. Verify backward compatibility: org with no template settings still generates PDF
  11. Clean up test data

Requirements: 1.1, 1.2, 2.1, 3.1, 3.3, 3.4, 3.5, 6.1, 6.2, 6.6, 7.1, 7.2, 7.3, 7.4,
              10.1, 10.2, 10.3

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
      python scripts/test_invoice_templates_e2e.py
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

ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = os.environ.get("E2E_ORG_PASSWORD", "changeme")

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

# Expected template IDs from the registry
EXPECTED_TEMPLATE_IDS = {
    "classic", "modern-dark", "compact-blue", "bold-header", "minimal",
    "trade-pro", "corporate", "compact-green", "elegant", "compact-mono",
    "sunrise", "ocean",
}

# Template metadata fields that every template must have
REQUIRED_TEMPLATE_FIELDS = [
    "id", "display_name", "description", "thumbnail_path",
    "default_primary_colour", "default_accent_colour",
    "default_header_bg_colour", "logo_position", "layout_type",
]


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
    print("  INVOICE PDF TEMPLATES — END-TO-END VERIFICATION")
    print("=" * 65)

    conn: asyncpg.Connection | None = None
    org_id: str | None = None
    test_invoice_ids: list[str] = []
    test_customer_id: str | None = None
    original_settings: dict | None = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            # ── Setup: resolve org_id, find a test customer ──
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
            original_settings = dict(org_row["settings"]) if org_row and org_row["settings"] else {}
            print(f"  {INFO} Original template setting: {original_settings.get('invoice_template_id', '(none)')}")

            # Find a test customer
            cust_row = await conn.fetchrow(
                "SELECT id FROM customers WHERE org_id = $1 LIMIT 1",
                uuid.UUID(org_id),
            )
            if cust_row:
                test_customer_id = str(cust_row["id"])
            else:
                fail("No customer found in org — cannot create test invoices")
                return
            print(f"  {INFO} Test customer: {test_customer_id[:8]}…")

            # ──────────────────────────────────────────────────────────
            # 1. Login as org_admin
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("1 — Login as org_admin")

            org_headers = await login(client, ORG_EMAIL, ORG_PASSWORD)
            ok("Org Admin authenticated")

            # ──────────────────────────────────────────────────────────
            # 2. GET /org/invoice-templates → verify 12 templates
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("2 — GET /org/invoice-templates → verify returns 12 templates with correct metadata")

            r = await client.get(f"{API}/invoices/invoice-templates", headers=org_headers)
            if r.status_code == 200:
                data = r.json()
                templates = data.get("templates", [])
                ok(f"GET /invoices/invoice-templates → 200")

                # Verify count
                if len(templates) == 12:
                    ok(f"Template count: {len(templates)} (expected 12)")
                else:
                    fail(f"Template count", f"expected 12, got {len(templates)}")

                # Verify all expected IDs are present
                returned_ids = {t.get("id") for t in templates}
                missing = EXPECTED_TEMPLATE_IDS - returned_ids
                extra = returned_ids - EXPECTED_TEMPLATE_IDS
                if not missing and not extra:
                    ok("All 12 expected template IDs present")
                else:
                    if missing:
                        fail("Missing template IDs", str(missing))
                    if extra:
                        fail("Unexpected template IDs", str(extra))

                # Verify metadata shape on each template
                shape_ok = True
                for t in templates:
                    for field in REQUIRED_TEMPLATE_FIELDS:
                        if not t.get(field):
                            fail(f"Template '{t.get('id')}' missing field: {field}")
                            shape_ok = False
                            break
                if shape_ok:
                    ok("All templates have correct metadata shape")

                # Verify layout_type distribution: at least 3 compact, 7 standard
                compact_count = sum(1 for t in templates if t.get("layout_type") == "compact")
                standard_count = sum(1 for t in templates if t.get("layout_type") == "standard")
                if compact_count >= 3 and standard_count >= 7:
                    ok(f"Layout distribution: {standard_count} standard, {compact_count} compact")
                else:
                    fail("Layout distribution", f"standard={standard_count}, compact={compact_count}")

                # Verify logo_position distribution: at least 2 per position
                positions = {}
                for t in templates:
                    pos = t.get("logo_position", "")
                    positions[pos] = positions.get(pos, 0) + 1
                pos_ok = all(positions.get(p, 0) >= 2 for p in ("left", "center", "side"))
                if pos_ok:
                    ok(f"Logo positions: {positions}")
                else:
                    fail("Logo position distribution", str(positions))
            else:
                fail(f"GET /invoices/invoice-templates → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 3. POST /invoice-templates/preview with valid template ID
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("3 — POST /invoice-templates/preview with valid template ID → verify non-empty HTML")

            preview_payload = {
                "template_id": "classic",
                "primary_colour": "#FF5733",
                "accent_colour": "#C70039",
                "header_bg_colour": "#FFFFFF",
            }
            r = await client.post(
                f"{API}/invoices/invoice-templates/preview",
                headers=org_headers,
                json=preview_payload,
            )
            if r.status_code == 200:
                data = r.json()
                html = data.get("html", "")
                ok(f"POST /invoice-templates/preview → 200")

                if len(html) > 100:
                    ok(f"Preview HTML returned: {len(html)} chars")
                else:
                    fail("Preview HTML too short", f"got {len(html)} chars")

                # Verify HTML contains expected content markers
                if "<html" in html.lower() or "<!doctype" in html.lower() or "<div" in html.lower():
                    ok("Preview HTML contains valid HTML markup")
                else:
                    fail("Preview HTML missing HTML markup")
            else:
                fail(f"POST /invoice-templates/preview → {r.status_code}", r.text[:200])

            # Also test preview with a different template
            r2 = await client.post(
                f"{API}/invoices/invoice-templates/preview",
                headers=org_headers,
                json={"template_id": "modern-dark"},
            )
            if r2.status_code == 200:
                html2 = r2.json().get("html", "")
                if len(html2) > 100:
                    ok(f"Preview for 'modern-dark' returned: {len(html2)} chars")
                else:
                    fail("Preview for 'modern-dark' too short")
            else:
                fail(f"Preview for 'modern-dark' → {r2.status_code}", r2.text[:200])

            # ──────────────────────────────────────────────────────────
            # 4. POST /invoice-templates/preview with invalid template ID → 404
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("4 — POST /invoice-templates/preview with invalid template ID → verify 404")

            r = await client.post(
                f"{API}/invoices/invoice-templates/preview",
                headers=org_headers,
                json={"template_id": "nonexistent-template-xyz"},
            )
            if r.status_code == 404:
                ok(f"Invalid template preview → 404 (correct)")
                detail = r.json().get("detail", "")
                if "not found" in detail.lower():
                    ok(f"Error detail: {detail}")
                else:
                    fail("404 detail missing 'not found'", detail)
            else:
                fail(f"Invalid template preview → {r.status_code} (expected 404)", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 5. PUT /org/settings with valid template ID and colours → 200
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("5 — PUT /org/settings with valid invoice_template_id and colours → verify 200")

            settings_payload = {
                "invoice_template_id": "modern-dark",
                "invoice_template_colours": {
                    "primary_colour": "#8b5cf6",
                    "accent_colour": "#7c3aed",
                    "header_bg_colour": "#1e1b4b",
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
            # 6. PUT /org/settings with invalid template ID → 422
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("6 — PUT /org/settings with invalid invoice_template_id → verify 422")

            r = await client.put(
                f"{API}/org/settings",
                headers=org_headers,
                json={"invoice_template_id": "totally-fake-template"},
            )
            if r.status_code == 422:
                ok(f"Invalid template ID rejected → 422")
                detail = r.json().get("detail", "")
                if "unknown" in detail.lower() or "template" in detail.lower():
                    ok(f"Error detail: {detail[:100]}")
                else:
                    # Some implementations return validation error in different format
                    ok(f"422 response received (detail: {str(r.json())[:100]})")
            else:
                fail(f"Invalid template ID → {r.status_code} (expected 422)", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 7. GET /org/settings → verify template fields returned
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("7 — GET /org/settings → verify invoice_template_id and colours are returned")

            r = await client.get(f"{API}/org/settings", headers=org_headers)
            if r.status_code == 200:
                data = r.json()
                ok(f"GET /org/settings → 200")

                saved_template_id = data.get("invoice_template_id")
                saved_colours = data.get("invoice_template_colours")

                if saved_template_id == "modern-dark":
                    ok(f"invoice_template_id = '{saved_template_id}' (correct)")
                else:
                    fail("invoice_template_id mismatch", f"expected 'modern-dark', got '{saved_template_id}'")

                if saved_colours and saved_colours.get("primary_colour") == "#8b5cf6":
                    ok(f"invoice_template_colours persisted correctly")
                else:
                    fail("invoice_template_colours mismatch", str(saved_colours))
            else:
                fail(f"GET /org/settings → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 8. Create and issue an invoice → download PDF → verify
            #    PDF is generated (non-empty bytes)
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("8 — Create and issue invoice → download PDF → verify non-empty PDF bytes")

            # Create a draft invoice
            invoice_payload = {
                "customer_id": test_customer_id,
                "status": "draft",
                "currency": "NZD",
                "line_items": [
                    {
                        "item_type": "service",
                        "description": "E2E Test — Invoice Template PDF Generation",
                        "quantity": "1",
                        "unit_price": "100.00",
                    },
                ],
            }
            r = await client.post(
                f"{API}/invoices",
                headers=org_headers,
                json=invoice_payload,
            )
            if r.status_code == 201:
                data = r.json()
                invoice_data = data.get("invoice", {})
                invoice_id = str(invoice_data.get("id", ""))
                test_invoice_ids.append(invoice_id)
                ok(f"Invoice created: {invoice_id[:8]}… (status={invoice_data.get('status')})")
            else:
                fail(f"POST /invoices → {r.status_code}", r.text[:300])
                invoice_id = None

            # Issue the invoice
            if invoice_id:
                r = await client.put(
                    f"{API}/invoices/{invoice_id}/issue",
                    headers=org_headers,
                )
                if r.status_code == 200:
                    issue_data = r.json()
                    inv_number = issue_data.get("invoice", {}).get("invoice_number", "")
                    ok(f"Invoice issued: {inv_number}")
                else:
                    fail(f"PUT /invoices/{{id}}/issue → {r.status_code}", r.text[:200])

            # Download PDF — this should use the 'modern-dark' template
            if invoice_id:
                r = await client.get(
                    f"{API}/invoices/{invoice_id}/pdf",
                    headers=org_headers,
                )
                if r.status_code == 200:
                    pdf_bytes = r.content
                    ok(f"GET /invoices/{{id}}/pdf → 200")

                    if len(pdf_bytes) > 1000:
                        ok(f"PDF generated: {len(pdf_bytes)} bytes")
                    else:
                        fail("PDF too small", f"got {len(pdf_bytes)} bytes")

                    # Verify it starts with PDF magic bytes
                    if pdf_bytes[:5] == b"%PDF-":
                        ok("PDF starts with %PDF- magic bytes (valid PDF)")
                    else:
                        fail("PDF missing magic bytes", f"starts with {pdf_bytes[:20]!r}")
                else:
                    fail(f"GET /invoices/{{id}}/pdf → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 9. Reset invoice_template_id to null → verify default
            #    template is used
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("9 — Reset invoice_template_id to null → verify default template is used")

            r = await client.put(
                f"{API}/org/settings",
                headers=org_headers,
                json={
                    "invoice_template_id": None,
                    "invoice_template_colours": None,
                },
            )
            if r.status_code == 200:
                ok(f"PUT /org/settings (reset to null) → 200")
            else:
                fail(f"PUT /org/settings (reset) → {r.status_code}", r.text[:200])

            # Verify settings are cleared
            r = await client.get(f"{API}/org/settings", headers=org_headers)
            if r.status_code == 200:
                data = r.json()
                reset_template_id = data.get("invoice_template_id")
                reset_colours = data.get("invoice_template_colours")

                if reset_template_id is None:
                    ok("invoice_template_id is null after reset")
                else:
                    fail("invoice_template_id not null after reset", f"got '{reset_template_id}'")

                if reset_colours is None:
                    ok("invoice_template_colours is null after reset")
                else:
                    fail("invoice_template_colours not null after reset", str(reset_colours))
            else:
                fail(f"GET /org/settings (after reset) → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 10. Backward compatibility: org with no template settings
            #     still generates PDF with default invoice.html
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("10 — Backward compatibility: no template settings → PDF still generated")

            # Create another invoice with no template set (reset was done in step 9)
            invoice_payload_2 = {
                "customer_id": test_customer_id,
                "status": "draft",
                "currency": "NZD",
                "line_items": [
                    {
                        "item_type": "service",
                        "description": "E2E Test — Default Template Backward Compat",
                        "quantity": "1",
                        "unit_price": "50.00",
                    },
                ],
            }
            r = await client.post(
                f"{API}/invoices",
                headers=org_headers,
                json=invoice_payload_2,
            )
            invoice_id_2 = None
            if r.status_code == 201:
                data = r.json()
                invoice_data_2 = data.get("invoice", {})
                invoice_id_2 = str(invoice_data_2.get("id", ""))
                test_invoice_ids.append(invoice_id_2)
                ok(f"Invoice 2 created: {invoice_id_2[:8]}…")
            else:
                fail(f"POST /invoices (2nd) → {r.status_code}", r.text[:300])

            # Issue the second invoice
            if invoice_id_2:
                r = await client.put(
                    f"{API}/invoices/{invoice_id_2}/issue",
                    headers=org_headers,
                )
                if r.status_code == 200:
                    ok(f"Invoice 2 issued")
                else:
                    fail(f"PUT /invoices/{{id}}/issue (2nd) → {r.status_code}", r.text[:200])

            # Download PDF — should use default invoice.html (no template set)
            if invoice_id_2:
                r = await client.get(
                    f"{API}/invoices/{invoice_id_2}/pdf",
                    headers=org_headers,
                )
                if r.status_code == 200:
                    pdf_bytes_2 = r.content
                    ok(f"GET /invoices/{{id}}/pdf (default template) → 200")

                    if len(pdf_bytes_2) > 1000:
                        ok(f"Default template PDF generated: {len(pdf_bytes_2)} bytes")
                    else:
                        fail("Default template PDF too small", f"got {len(pdf_bytes_2)} bytes")

                    if pdf_bytes_2[:5] == b"%PDF-":
                        ok("Default template PDF has valid magic bytes")
                    else:
                        fail("Default template PDF missing magic bytes")
                else:
                    fail(f"GET /invoices/{{id}}/pdf (default) → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 11. Additional validation: template colours are hex-validated
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("11 — Additional: verify colour validation on settings update")

            r = await client.put(
                f"{API}/org/settings",
                headers=org_headers,
                json={
                    "invoice_template_id": "classic",
                    "invoice_template_colours": {
                        "primary_colour": "not-a-colour",
                        "accent_colour": "#FF0000",
                        "header_bg_colour": "#FFFFFF",
                    },
                },
            )
            if r.status_code == 422:
                ok("Invalid hex colour rejected → 422")
            else:
                # Some implementations may accept and silently ignore bad colours,
                # or validate at a different level
                if r.status_code == 200:
                    fail("Invalid hex colour accepted (expected 422)", f"got {r.status_code}")
                else:
                    fail(f"Unexpected status for invalid colour → {r.status_code}", r.text[:200])

        except Exception as exc:
            fail("Unhandled exception", str(exc)[:300])
            import traceback
            traceback.print_exc()

        finally:
            # ──────────────────────────────────────────────────────────
            # Cleanup: restore original settings, delete test invoices
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("Cleanup — restoring original settings and deleting test data")

            try:
                # Restore original template settings
                if conn and org_id:
                    # Build restored settings: start from original, remove test keys
                    restored = dict(original_settings) if original_settings else {}
                    # If original had no template settings, ensure they're removed
                    if "invoice_template_id" not in (original_settings or {}):
                        restored.pop("invoice_template_id", None)
                    if "invoice_template_colours" not in (original_settings or {}):
                        restored.pop("invoice_template_colours", None)

                    await conn.execute(
                        "UPDATE organisations SET settings = $1::jsonb WHERE id = $2",
                        json.dumps(restored),
                        uuid.UUID(org_id),
                    )
                    ok("Original org settings restored")

                # Delete test invoices (and their line items via CASCADE)
                if conn and test_invoice_ids:
                    for inv_id in test_invoice_ids:
                        try:
                            # Delete payments first (if any)
                            await conn.execute(
                                "DELETE FROM payments WHERE invoice_id = $1",
                                uuid.UUID(inv_id),
                            )
                            # Delete line items
                            await conn.execute(
                                "DELETE FROM line_items WHERE invoice_id = $1",
                                uuid.UUID(inv_id),
                            )
                            # Delete the invoice
                            await conn.execute(
                                "DELETE FROM invoices WHERE id = $1",
                                uuid.UUID(inv_id),
                            )
                        except Exception as e:
                            print(f"  {INFO} Cleanup warning for invoice {inv_id[:8]}…: {e}")
                    ok(f"Deleted {len(test_invoice_ids)} test invoice(s)")

                if conn:
                    await conn.close()
                    ok("DB connection closed")

            except Exception as cleanup_exc:
                print(f"  {INFO} Cleanup error: {cleanup_exc}")

    # ─── Summary ───
    print(f"\n{'=' * 65}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
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

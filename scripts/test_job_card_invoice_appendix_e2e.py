"""
End-to-end test: Job Card Invoice Appendix

Covers:
  1.  Login as demo@orainvoice.com
  2.  Create a test customer
  3.  Create a job card with line items
  4.  Upload an image attachment to the job card
  5.  Start and stop a timer (time entry)
  6.  Transition job card: open → in_progress → completed
  7.  Convert the completed job card to an invoice
  8.  Verify the invoice record has job_card_appendix_html populated (non-null)
  9.  Generate the invoice PDF and verify it has 2+ pages
  10. Clean up test data

Requirements: 4.1, 4.2, 3.2, 3.3

Run inside container:
  docker exec invoicing-app-1 python scripts/test_job_card_invoice_appendix_e2e.py
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import struct
import sys
import time
import uuid
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import asyncpg

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API = f"{BASE}/api/v1"

DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"

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


def _create_minimal_png() -> bytes:
    """Create a minimal valid 1x1 red PNG image (~68 bytes)."""
    # IHDR chunk
    width = 1
    height = 1
    bit_depth = 8
    color_type = 2  # RGB

    ihdr_data = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc

    # IDAT chunk — single red pixel
    raw_row = b"\x00\xff\x00\x00"  # filter byte + RGB
    compressed = zlib.compress(raw_row)
    idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
    idat_chunk = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc

    # IEND chunk
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend_chunk = struct.pack(">I", 0) + b"IEND" + iend_crc

    # PNG signature + chunks
    png_sig = b"\x89PNG\r\n\x1a\n"
    return png_sig + ihdr_chunk + idat_chunk + iend_chunk


def count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in a PDF by decompressing streams and searching for /Type /Page.

    WeasyPrint generates PDFs with FlateDecode-compressed object streams,
    so we decompress all streams first, then count leaf page objects
    (excluding /Type /Pages which is the page tree node).

    Also checks /Count in the page tree as a fallback.
    """
    text = pdf_bytes.decode("latin-1")

    # Decompress all FlateDecode streams to access compressed objects
    all_text = text
    stream_pattern = re.compile(r"stream\r?\n(.+?)\r?\nendstream", re.DOTALL)
    for match in stream_pattern.finditer(text):
        raw = match.group(1).encode("latin-1")
        try:
            decompressed = zlib.decompress(raw).decode("latin-1", errors="replace")
            all_text += decompressed
        except Exception:
            pass

    # Count /Type /Page (leaf pages, not /Type /Pages tree nodes)
    page_matches = re.findall(r"/Type\s*/Page(?!s)\b", all_text)
    if page_matches:
        return len(page_matches)

    # Fallback: look for /Count in the page tree
    count_matches = re.findall(r"/Count\s+(\d+)", all_text)
    if count_matches:
        return max(int(c) for c in count_matches)

    return 0


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
    print("  JOB CARD INVOICE APPENDIX — END-TO-END VERIFICATION")
    print("=" * 65)

    conn: asyncpg.Connection | None = None
    org_id: str | None = None
    test_customer_id: str | None = None
    test_job_card_id: str | None = None
    test_invoice_id: str | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # ── Setup: resolve org_id ──
            conn = await get_db_conn()

            row = await conn.fetchrow(
                "SELECT org_id FROM users WHERE email = $1", DEMO_EMAIL,
            )
            if not row or not row["org_id"]:
                fail("Could not find org_id for demo user")
                return
            org_id = str(row["org_id"])
            print(f"  {INFO} Org ID: {org_id[:8]}…")

            # ──────────────────────────────────────────────────────────
            # 1. Login as demo user
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("1 — Login as demo@orainvoice.com")

            headers = await login(client, DEMO_EMAIL, DEMO_PASSWORD)
            ok("Demo user authenticated")

            # ──────────────────────────────────────────────────────────
            # 2. Create a test customer
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("2 — Create a test customer")

            customer_payload = {
                "first_name": "E2E-Appendix",
                "last_name": "TestCustomer",
                "email": f"e2e-appendix-{uuid.uuid4().hex[:8]}@test.local",
                "phone": "021-555-0199",
            }
            r = await client.post(
                f"{API}/customers",
                headers=headers,
                json=customer_payload,
            )
            if r.status_code in (200, 201):
                data = r.json()
                # Handle both {customer: {...}} and flat response shapes
                cust_data = data.get("customer", data)
                test_customer_id = str(cust_data["id"])
                ok(f"Customer created: {test_customer_id[:8]}…")
            else:
                fail(f"POST /customers → {r.status_code}", r.text[:300])
                return

            # ──────────────────────────────────────────────────────────
            # 3. Create a job card with line items
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("3 — Create a job card with line items")

            job_card_payload = {
                "customer_id": test_customer_id,
                "description": "E2E test job card for appendix verification",
                "notes": "These are test notes for the appendix E2E test.",
                "vehicle_rego": "TEST123",
                "line_items": [
                    {
                        "item_type": "service",
                        "description": "Brake pad replacement",
                        "quantity": "2",
                        "unit_price": "85.00",
                    },
                    {
                        "item_type": "part",
                        "description": "Brake pads (front set)",
                        "quantity": "1",
                        "unit_price": "120.00",
                    },
                ],
            }
            r = await client.post(
                f"{API}/job-cards",
                headers=headers,
                json=job_card_payload,
            )
            if r.status_code in (200, 201):
                data = r.json()
                jc_data = data.get("job_card", data)
                test_job_card_id = str(jc_data["id"])
                ok(f"Job card created: {test_job_card_id[:8]}… (status={jc_data.get('status')})")
            else:
                fail(f"POST /job-cards → {r.status_code}", r.text[:300])
                return

            # ──────────────────────────────────────────────────────────
            # 4. Upload an image attachment
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("4 — Upload an image attachment to the job card")

            png_bytes = _create_minimal_png()
            files = {
                "file": ("test-photo.png", io.BytesIO(png_bytes), "image/png"),
            }
            r = await client.post(
                f"{API}/job-cards/{test_job_card_id}/attachments",
                headers=headers,
                files=files,
            )
            if r.status_code in (200, 201):
                att_data = r.json()
                att_id = att_data.get("id", "?")
                ok(f"Image attachment uploaded: {str(att_id)[:8]}…")
            else:
                fail(f"POST /job-cards/{{id}}/attachments → {r.status_code}", r.text[:300])
                # Continue — attachment is not strictly required for the test

            # ──────────────────────────────────────────────────────────
            # 5. Start and stop a timer (time entry)
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("5 — Start and stop a timer for a time entry")

            # Transition to in_progress first (required for timer)
            r = await client.put(
                f"{API}/job-cards/{test_job_card_id}",
                headers=headers,
                json={"status": "in_progress"},
            )
            if r.status_code == 200:
                ok("Job card transitioned to in_progress")
            else:
                fail(f"PUT /job-cards/{{id}} (in_progress) → {r.status_code}", r.text[:200])

            # Start timer
            r = await client.post(
                f"{API}/job-cards/{test_job_card_id}/timer/start",
                headers=headers,
            )
            if r.status_code in (200, 201):
                ok("Timer started")
            else:
                fail(f"POST /job-cards/{{id}}/timer/start → {r.status_code}", r.text[:200])

            # Brief pause so duration > 0
            await asyncio.sleep(1)

            # Stop timer
            r = await client.post(
                f"{API}/job-cards/{test_job_card_id}/timer/stop",
                headers=headers,
            )
            if r.status_code == 200:
                ok("Timer stopped")
            else:
                fail(f"POST /job-cards/{{id}}/timer/stop → {r.status_code}", r.text[:200])

            # ──────────────────────────────────────────────────────────
            # 6. Transition job card to completed
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("6 — Transition job card to completed")

            r = await client.put(
                f"{API}/job-cards/{test_job_card_id}",
                headers=headers,
                json={"status": "completed"},
            )
            if r.status_code == 200:
                jc_updated = r.json()
                jc_status = jc_updated.get("job_card", jc_updated).get("status", "?")
                ok(f"Job card status: {jc_status}")
            else:
                fail(f"PUT /job-cards/{{id}} (completed) → {r.status_code}", r.text[:200])
                return

            # ──────────────────────────────────────────────────────────
            # 7. Convert the job card to an invoice
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("7 — Convert the completed job card to an invoice")

            r = await client.post(
                f"{API}/job-cards/{test_job_card_id}/convert",
                headers=headers,
            )
            if r.status_code in (200, 201):
                convert_data = r.json()
                test_invoice_id = str(convert_data.get("invoice_id", ""))
                ok(f"Job card converted to invoice: {test_invoice_id[:8]}…")
            else:
                fail(f"POST /job-cards/{{id}}/convert → {r.status_code}", r.text[:300])
                return

            # ──────────────────────────────────────────────────────────
            # 8. Verify invoice has job_card_appendix_html populated
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("8 — Verify invoice has job_card_appendix_html populated")

            # Check directly in the database for the appendix HTML
            inv_row = await conn.fetchrow(
                "SELECT job_card_appendix_html FROM invoices WHERE id = $1",
                uuid.UUID(test_invoice_id),
            )
            if inv_row is None:
                fail("Invoice not found in database")
            elif inv_row["job_card_appendix_html"] is None:
                fail("job_card_appendix_html is NULL (expected non-null)")
            else:
                html_len = len(inv_row["job_card_appendix_html"])
                ok(f"job_card_appendix_html is populated ({html_len} chars)")

                # Verify the HTML contains expected content
                html = inv_row["job_card_appendix_html"]
                if "Job Card Summary" in html:
                    ok("Appendix HTML contains 'Job Card Summary' header")
                else:
                    fail("Appendix HTML missing 'Job Card Summary' header")

                if "Brake pad replacement" in html:
                    ok("Appendix HTML contains line item description")
                else:
                    fail("Appendix HTML missing line item description")

                if "E2E-Appendix" in html:
                    ok("Appendix HTML contains customer name")
                else:
                    fail("Appendix HTML missing customer name")

                if "test notes" in html.lower():
                    ok("Appendix HTML contains notes text")
                else:
                    fail("Appendix HTML missing notes text")

                # Verify description field is excluded
                if "E2E test job card for appendix verification" in html:
                    fail("Appendix HTML contains description field (should be excluded)")
                else:
                    ok("Description field correctly excluded from appendix")

            # ──────────────────────────────────────────────────────────
            # 9. Generate invoice PDF and verify 2+ pages
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("9 — Generate invoice PDF and verify 2+ pages")

            r = await client.get(
                f"{API}/invoices/{test_invoice_id}/pdf",
                headers=headers,
            )
            if r.status_code == 200:
                pdf_bytes = r.content
                ok(f"GET /invoices/{{id}}/pdf → 200 ({len(pdf_bytes)} bytes)")

                # Verify PDF magic bytes
                if pdf_bytes[:5] == b"%PDF-":
                    ok("PDF starts with %PDF- magic bytes")
                else:
                    fail("PDF missing magic bytes", f"starts with {pdf_bytes[:20]!r}")

                # Count pages
                page_count = count_pdf_pages(pdf_bytes)
                if page_count >= 2:
                    ok(f"PDF has {page_count} pages (expected 2+)")
                else:
                    fail(f"PDF has {page_count} page(s)", "expected 2+ pages (invoice + appendix)")
            else:
                fail(f"GET /invoices/{{id}}/pdf → {r.status_code}", r.text[:300])

        except Exception as exc:
            fail("Unhandled exception", str(exc)[:300])
            import traceback
            traceback.print_exc()

        finally:
            # ──────────────────────────────────────────────────────────
            # 10. Cleanup — delete test data
            # ──────────────────────────────────────────────────────────
            print(f"\n{'─' * 65}")
            print("Cleanup — deleting test data")

            try:
                if conn:
                    # Delete invoice line items and invoice
                    if test_invoice_id:
                        await conn.execute(
                            "DELETE FROM payments WHERE invoice_id = $1",
                            uuid.UUID(test_invoice_id),
                        )
                        await conn.execute(
                            "DELETE FROM line_items WHERE invoice_id = $1",
                            uuid.UUID(test_invoice_id),
                        )
                        await conn.execute(
                            "DELETE FROM invoices WHERE id = $1",
                            uuid.UUID(test_invoice_id),
                        )
                        ok(f"Deleted test invoice {test_invoice_id[:8]}…")

                    # Delete job card attachments, time entries, line items, and job card
                    if test_job_card_id:
                        await conn.execute(
                            "DELETE FROM job_card_attachments WHERE job_card_id = $1",
                            uuid.UUID(test_job_card_id),
                        )
                        await conn.execute(
                            "DELETE FROM time_entries WHERE job_id = $1",
                            uuid.UUID(test_job_card_id),
                        )
                        await conn.execute(
                            "DELETE FROM job_card_items WHERE job_card_id = $1",
                            uuid.UUID(test_job_card_id),
                        )
                        await conn.execute(
                            "DELETE FROM job_cards WHERE id = $1",
                            uuid.UUID(test_job_card_id),
                        )
                        ok(f"Deleted test job card {test_job_card_id[:8]}…")

                    # Delete test customer
                    if test_customer_id:
                        await conn.execute(
                            "DELETE FROM customers WHERE id = $1",
                            uuid.UUID(test_customer_id),
                        )
                        ok(f"Deleted test customer {test_customer_id[:8]}…")

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

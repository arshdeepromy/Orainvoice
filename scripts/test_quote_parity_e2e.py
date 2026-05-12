"""
End-to-end test: Quote ↔ Invoice Parity (Phase 5 + 7)

Covers the key test cases from requirements.md §6:
- TC-AU-HAPPY: Upload JPEG ≤ 20 MB, verify 201 + attachment in list
- TC-AU-SIZE: Upload > 20 MB, verify 413
- TC-AU-MIME: Upload .exe/.zip, verify 400
- TC-AU-COUNT: Upload 6th attachment, verify 400
- TC-AU-ORG404: Cross-org attachment endpoints return 404
- TC-AU-DISPOS: Upload PDF, download, verify Content-Disposition
- TC-AU-DELETE-DRAFT: Delete on draft returns 200
- TC-AU-DELETE-SENT: Delete on sent returns 403
- TC-GST-ROUND: GST-inclusive line item round-trip
- TC-PAY-FIDELITY: POST /quotes with every new field, GET back, verify all match
- TC-SAVE-TERMS: save_terms_as_default updates org settings
- TC-AUTH-401: Attachment endpoints return 401 without auth
- TC-AUTH-403: Non-permitted role returns 403
- Cleanup verification

Usage:
    docker exec invoicing-app-1 python scripts/test_quote_parity_e2e.py
"""

import asyncio
import sys
import uuid

import httpx

BASE = "http://localhost:8000"

# Existing test accounts
DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"

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
                "first_name": "TEST_E2E_Parity",
                "last_name": "Customer",
                "email": f"TEST_E2E_parity_{uuid.uuid4().hex[:8]}@example.com",
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

            # ─── Setup: Create a draft quote for attachment tests ───
            print("\n🔹 Setup: Create draft quote")
            r = await client.post("/api/v1/quotes", headers=headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_Parity Draft",
                "validity_days": 30,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_Parity line item",
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
            # TC-AU-HAPPY — Upload JPEG ≤ 20 MB, verify 201 + in list
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.1: TC-AU-HAPPY — upload JPEG ≤ 20 MB")
            # Create a small fake JPEG (valid JPEG header)
            jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 100
            r = await client.post(
                f"/api/v1/quotes/{quote_id}/attachments",
                headers=headers,
                files={"file": ("test_photo.jpg", jpeg_header, "image/jpeg")},
            )
            if r.status_code == 201:
                ok("Upload JPEG → 201")
                attachment_resp = r.json()
                attachment_obj = attachment_resp.get("attachment", {})
                attachment_id = attachment_obj.get("id")
                if attachment_id:
                    ok(f"Attachment id returned: {attachment_id}")
                else:
                    fail("TC-AU-HAPPY: no attachment id in response", f"{r.text[:200]}")

                # Verify it appears in the list
                r_list = await client.get(
                    f"/api/v1/quotes/{quote_id}/attachments",
                    headers=headers,
                )
                if r_list.status_code == 200:
                    list_data = r_list.json()
                    attachments = list_data.get("attachments", [])
                    if any(a.get("id") == attachment_id for a in attachments):
                        ok("Attachment appears in GET /attachments list")
                    else:
                        fail("TC-AU-HAPPY: attachment not in list", f"ids={[a.get('id') for a in attachments]}")
                else:
                    fail("TC-AU-HAPPY: list endpoint", f"status={r_list.status_code}")
            else:
                fail("TC-AU-HAPPY: expected 201", f"got {r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # TC-AU-SIZE — Upload > 20 MB, verify 413
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.2: TC-AU-SIZE — upload > 20 MB")
            # Create a file just over 20 MB
            big_content = b"\xff\xd8\xff\xe0" + (b"\x00" * (20 * 1024 * 1024 + 1))
            r = await client.post(
                f"/api/v1/quotes/{quote_id}/attachments",
                headers=headers,
                files={"file": ("big_photo.jpg", big_content, "image/jpeg")},
            )
            if r.status_code == 413:
                ok("Upload > 20 MB → 413")
            else:
                fail("TC-AU-SIZE: expected 413", f"got {r.status_code}: {r.text[:200]}")

            # Verify not persisted
            r_list = await client.get(
                f"/api/v1/quotes/{quote_id}/attachments",
                headers=headers,
            )
            if r_list.status_code == 200:
                count_after_size = len(r_list.json().get("attachments", []))
                if count_after_size == 1:  # Only the first JPEG from TC-AU-HAPPY
                    ok("Oversized file not persisted (count still 1)")
                else:
                    fail("TC-AU-SIZE: file may have been persisted", f"count={count_after_size}")

            # ═══════════════════════════════════════════════════════════
            # TC-AU-MIME — Upload .exe/.zip, verify 400
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.3: TC-AU-MIME — upload .exe (invalid MIME)")
            exe_content = b"MZ" + b"\x00" * 100  # Fake EXE header
            r = await client.post(
                f"/api/v1/quotes/{quote_id}/attachments",
                headers=headers,
                files={"file": ("malware.exe", exe_content, "application/x-msdownload")},
            )
            if r.status_code == 400:
                ok("Upload .exe → 400")
            else:
                fail("TC-AU-MIME: expected 400", f"got {r.status_code}: {r.text[:200]}")

            # Also test .zip
            zip_content = b"PK\x03\x04" + b"\x00" * 100
            r = await client.post(
                f"/api/v1/quotes/{quote_id}/attachments",
                headers=headers,
                files={"file": ("archive.zip", zip_content, "application/zip")},
            )
            if r.status_code == 400:
                ok("Upload .zip → 400")
            else:
                fail("TC-AU-MIME: .zip expected 400", f"got {r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # TC-AU-COUNT — Upload 6th attachment, verify 400
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.4: TC-AU-COUNT — 6th attachment returns 400")
            # We already have 1 attachment. Upload 4 more to reach the cap of 5.
            small_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
            for i in range(4):
                r = await client.post(
                    f"/api/v1/quotes/{quote_id}/attachments",
                    headers=headers,
                    files={"file": (f"photo_{i+2}.jpg", small_jpeg, "image/jpeg")},
                )
                if r.status_code != 201:
                    fail(f"TC-AU-COUNT: upload #{i+2} failed", f"status={r.status_code}")
                    break

            # Now try the 6th — should be rejected
            r = await client.post(
                f"/api/v1/quotes/{quote_id}/attachments",
                headers=headers,
                files={"file": ("photo_6.jpg", small_jpeg, "image/jpeg")},
            )
            if r.status_code == 400:
                ok("6th attachment → 400 (count cap enforced)")
            else:
                fail("TC-AU-COUNT: expected 400 for 6th", f"got {r.status_code}: {r.text[:200]}")


            # ═══════════════════════════════════════════════════════════
            # TC-AU-ORG404 — Cross-org attachment endpoints return 404
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.7: TC-AU-ORG404 — cross-org returns 404")
            # Create a second org + user via direct SQL
            second_org_id = uuid.uuid4()
            second_user_id = uuid.uuid4()
            second_email = f"TEST_E2E_org2_{uuid.uuid4().hex[:8]}@example.com"
            second_password = "testpass123"
            pw_hash = bcrypt.hashpw(second_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

            # Get a valid plan_id for the org
            plan_row = await conn.fetchrow("SELECT id FROM subscription_plans LIMIT 1")
            plan_id = plan_row["id"]

            # Create second org
            await conn.execute(
                """INSERT INTO organisations (id, name, status, plan_id, storage_quota_gb, created_at, updated_at)
                   VALUES ($1, 'TEST_E2E_Org2_Parity', 'active', $2, 5, NOW(), NOW())""",
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

            # Login as second org user
            token2 = await login(client, second_email, second_password)
            if not token2:
                fail("TC-AU-ORG404: could not login as second org user")
            else:
                headers2 = {"Authorization": f"Bearer {token2}"}

                # Try to list attachments on first org's quote
                r = await client.get(
                    f"/api/v1/quotes/{quote_id}/attachments",
                    headers=headers2,
                )
                if r.status_code == 404:
                    ok("Cross-org GET /attachments → 404")
                else:
                    fail("TC-AU-ORG404: GET list expected 404", f"got {r.status_code}")

                # Try to download an attachment from first org's quote
                # Use the attachment_id from TC-AU-HAPPY if available
                if attachment_id:
                    r = await client.get(
                        f"/api/v1/quotes/{quote_id}/attachments/{attachment_id}",
                        headers=headers2,
                    )
                    if r.status_code == 404:
                        ok("Cross-org GET /attachments/{id} → 404")
                    else:
                        fail("TC-AU-ORG404: GET file expected 404", f"got {r.status_code}")

                # Try to upload to first org's quote
                r = await client.post(
                    f"/api/v1/quotes/{quote_id}/attachments",
                    headers=headers2,
                    files={"file": ("cross_org.jpg", small_jpeg, "image/jpeg")},
                )
                if r.status_code == 404:
                    ok("Cross-org POST /attachments → 404")
                else:
                    fail("TC-AU-ORG404: POST expected 404", f"got {r.status_code}")

                # Try to delete from first org's quote
                if attachment_id:
                    r = await client.delete(
                        f"/api/v1/quotes/{quote_id}/attachments/{attachment_id}",
                        headers=headers2,
                    )
                    if r.status_code == 404:
                        ok("Cross-org DELETE /attachments/{id} → 404")
                    else:
                        fail("TC-AU-ORG404: DELETE expected 404", f"got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TC-AU-DISPOS — Upload PDF, download, verify Content-Disposition
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.8: TC-AU-DISPOS — Content-Disposition for PDF")
            # Create a fresh draft quote for this test (previous one is at count cap)
            r = await client.post("/api/v1/quotes", headers=headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_Parity Dispos",
                "validity_days": 30,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_Parity dispos item",
                    "quantity": 1,
                    "unit_price": 50.00,
                    "sort_order": 0,
                }],
            })
            if r.status_code not in (200, 201):
                fail("TC-AU-DISPOS: create quote", f"status={r.status_code}")
            else:
                dispos_quote = r.json().get("quote", r.json())
                dispos_quote_id = dispos_quote.get("id")
                created["quote_ids"].append(dispos_quote_id)

                # Upload a PDF
                pdf_content = b"%PDF-1.4 fake pdf content for testing"
                r = await client.post(
                    f"/api/v1/quotes/{dispos_quote_id}/attachments",
                    headers=headers,
                    files={"file": ("test_document.pdf", pdf_content, "application/pdf")},
                )
                if r.status_code == 201:
                    pdf_att_id = r.json().get("attachment", {}).get("id")
                    # Download and check Content-Disposition
                    r_dl = await client.get(
                        f"/api/v1/quotes/{dispos_quote_id}/attachments/{pdf_att_id}",
                        headers=headers,
                    )
                    if r_dl.status_code == 200:
                        cd = r_dl.headers.get("content-disposition", "")
                        expected_cd = 'inline; filename="test_document.pdf"'
                        if cd == expected_cd:
                            ok(f"PDF Content-Disposition: {cd}")
                        else:
                            fail("TC-AU-DISPOS: Content-Disposition mismatch", f"expected={expected_cd!r}, got={cd!r}")
                    else:
                        fail("TC-AU-DISPOS: download failed", f"status={r_dl.status_code}")
                else:
                    fail("TC-AU-DISPOS: upload PDF failed", f"status={r.status_code}: {r.text[:200]}")

            # ═══════════════════════════════════════════════════════════
            # TC-AU-DELETE-DRAFT — Delete on draft returns 200
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.9: TC-AU-DELETE-DRAFT — delete on draft → 200")
            # Use the PDF attachment from the dispos quote (which is still draft)
            if dispos_quote_id and pdf_att_id:
                r = await client.delete(
                    f"/api/v1/quotes/{dispos_quote_id}/attachments/{pdf_att_id}",
                    headers=headers,
                )
                if r.status_code == 200:
                    ok("Delete attachment on draft → 200")
                    # Verify it's gone
                    r_list = await client.get(
                        f"/api/v1/quotes/{dispos_quote_id}/attachments",
                        headers=headers,
                    )
                    if r_list.status_code == 200:
                        remaining = r_list.json().get("attachments", [])
                        if not any(a.get("id") == pdf_att_id for a in remaining):
                            ok("Deleted attachment no longer in list")
                        else:
                            fail("TC-AU-DELETE-DRAFT: attachment still in list")
                else:
                    fail("TC-AU-DELETE-DRAFT: expected 200", f"got {r.status_code}: {r.text[:200]}")
            else:
                fail("TC-AU-DELETE-DRAFT: no attachment to delete (setup failed)")

            # ═══════════════════════════════════════════════════════════
            # TC-AU-DELETE-SENT — Delete on sent returns 403
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.10: TC-AU-DELETE-SENT — delete on sent → 403")
            # Create a new quote, upload an attachment, then mark as sent
            r = await client.post("/api/v1/quotes", headers=headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_Parity Sent",
                "validity_days": 30,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_Parity sent item",
                    "quantity": 1,
                    "unit_price": 75.00,
                    "sort_order": 0,
                }],
            })
            if r.status_code not in (200, 201):
                fail("TC-AU-DELETE-SENT: create quote", f"status={r.status_code}")
            else:
                sent_quote = r.json().get("quote", r.json())
                sent_quote_id = sent_quote.get("id")
                created["quote_ids"].append(sent_quote_id)

                # Upload an attachment while still draft
                r = await client.post(
                    f"/api/v1/quotes/{sent_quote_id}/attachments",
                    headers=headers,
                    files={"file": ("sent_test.jpg", small_jpeg, "image/jpeg")},
                )
                if r.status_code == 201:
                    sent_att_id = r.json().get("attachment", {}).get("id")

                    # Mark quote as sent via SQL
                    await conn.execute(
                        """UPDATE quotes SET status = 'sent',
                           acceptance_token = $1,
                           sent_at = NOW()
                           WHERE id = $2::uuid""",
                        str(uuid.uuid4()), uuid.UUID(sent_quote_id),
                    )

                    # Try to delete — should get 403
                    r = await client.delete(
                        f"/api/v1/quotes/{sent_quote_id}/attachments/{sent_att_id}",
                        headers=headers,
                    )
                    if r.status_code == 403:
                        ok("Delete attachment on sent quote → 403")
                    else:
                        fail("TC-AU-DELETE-SENT: expected 403", f"got {r.status_code}: {r.text[:200]}")
                else:
                    fail("TC-AU-DELETE-SENT: upload failed", f"status={r.status_code}")


            # ═══════════════════════════════════════════════════════════
            # TC-GST-ROUND — GST-inclusive line item round-trip
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.11: TC-GST-ROUND — gst_inclusive round-trip")
            r = await client.post("/api/v1/quotes", headers=headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_Parity GST",
                "validity_days": 30,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_Parity GST inclusive item",
                    "quantity": 1,
                    "unit_price": 100.00,
                    "sort_order": 0,
                    "gst_inclusive": True,
                    "inclusive_price": 115.00,
                }],
            })
            if r.status_code not in (200, 201):
                fail("TC-GST-ROUND: create quote", f"status={r.status_code}: {r.text[:200]}")
            else:
                gst_quote = r.json().get("quote", r.json())
                gst_quote_id = gst_quote.get("id")
                created["quote_ids"].append(gst_quote_id)

                # GET the quote back and verify line item fields
                r_get = await client.get(f"/api/v1/quotes/{gst_quote_id}", headers=headers)
                if r_get.status_code == 200:
                    gst_data = r_get.json()
                    line_items = gst_data.get("line_items", [])
                    if line_items:
                        li = line_items[0]
                        # Verify gst_inclusive is True
                        if li.get("gst_inclusive") is True:
                            ok("gst_inclusive=True round-trips")
                        else:
                            fail("TC-GST-ROUND: gst_inclusive not True", f"got {li.get('gst_inclusive')}")

                        # Verify inclusive_price = 115.00 exactly
                        inc_price = li.get("inclusive_price")
                        if inc_price is not None:
                            inc_price_dec = float(str(inc_price))
                            if abs(inc_price_dec - 115.00) < 0.001:
                                ok("inclusive_price=115.00 round-trips exactly")
                            else:
                                fail("TC-GST-ROUND: inclusive_price drift", f"expected 115.00, got {inc_price}")
                        else:
                            fail("TC-GST-ROUND: inclusive_price is None")

                        # Verify line_total ≈ 1 * (115 / 1.15) = 100.00 ±0.01
                        line_total = float(str(li.get("line_total", 0)))
                        expected_total = 1 * (115.00 / 1.15)  # 100.00
                        if abs(line_total - expected_total) <= 0.01:
                            ok(f"line_total ≈ {expected_total:.2f} (got {line_total:.2f})")
                        else:
                            fail("TC-GST-ROUND: line_total drift", f"expected ≈{expected_total:.2f}, got {line_total:.2f}")
                    else:
                        fail("TC-GST-ROUND: no line items in response")
                else:
                    fail("TC-GST-ROUND: GET quote failed", f"status={r_get.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TC-PAY-FIDELITY — POST with every new field, GET back
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.13: TC-PAY-FIDELITY — full payload fidelity")
            # Get the current user's id for salesperson_id
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", DEMO_EMAIL
            )
            demo_user_id = str(user_row["id"])

            fidelity_payload = {
                "customer_id": customer_id,
                "subject": "TEST_E2E_Parity Fidelity",
                "validity_days": 30,
                "order_number": "TEST_E2E_ORD-001",
                "salesperson_id": demo_user_id,
                "vehicles": [
                    {"rego": "ABC123", "make": "Toyota", "model": "Hilux", "year": 2022, "odometer": 55000},
                    {"rego": "XYZ789", "make": "Ford", "model": "Ranger", "year": 2021, "odometer": 72000},
                ],
                "fluid_usage": [
                    {
                        "stock_item_id": str(uuid.uuid4()),
                        "catalogue_item_id": str(uuid.uuid4()),
                        "litres": 4.5,
                        "item_name": "TEST_E2E Engine Oil 10W-40",
                    },
                ],
                "save_terms_as_default": False,
                "line_items": [{
                    "item_type": "part",
                    "description": "TEST_E2E_Parity fidelity part",
                    "quantity": 2,
                    "unit_price": 45.00,
                    "sort_order": 0,
                    "catalogue_item_id": str(uuid.uuid4()),
                    "stock_item_id": str(uuid.uuid4()),
                    "gst_inclusive": False,
                    "tax_rate": 15,
                }],
            }

            r = await client.post("/api/v1/quotes", headers=headers, json=fidelity_payload)
            if r.status_code not in (200, 201):
                fail("TC-PAY-FIDELITY: create quote", f"status={r.status_code}: {r.text[:200]}")
            else:
                fid_quote = r.json().get("quote", r.json())
                fid_quote_id = fid_quote.get("id")
                created["quote_ids"].append(fid_quote_id)

                # GET the quote back
                r_get = await client.get(f"/api/v1/quotes/{fid_quote_id}", headers=headers)
                if r_get.status_code == 200:
                    fid_data = r_get.json()

                    # Verify order_number
                    if fid_data.get("order_number") == "TEST_E2E_ORD-001":
                        ok("order_number round-trips")
                    else:
                        fail("TC-PAY-FIDELITY: order_number", f"got {fid_data.get('order_number')}")

                    # Verify salesperson_id
                    if fid_data.get("salesperson_id") == demo_user_id:
                        ok("salesperson_id round-trips")
                    else:
                        fail("TC-PAY-FIDELITY: salesperson_id", f"got {fid_data.get('salesperson_id')}")

                    # Verify additional_vehicles
                    vehicles = fid_data.get("additional_vehicles", [])
                    if len(vehicles) == 2:
                        ok(f"additional_vehicles has 2 entries")
                    else:
                        fail("TC-PAY-FIDELITY: additional_vehicles count", f"expected 2, got {len(vehicles)}")

                    # Verify fluid_usage
                    fluids = fid_data.get("fluid_usage", [])
                    if len(fluids) == 1:
                        ok("fluid_usage has 1 entry")
                    else:
                        fail("TC-PAY-FIDELITY: fluid_usage count", f"expected 1, got {len(fluids)}")

                    # Verify line item new fields
                    line_items = fid_data.get("line_items", [])
                    if line_items:
                        li = line_items[0]
                        if li.get("gst_inclusive") is False:
                            ok("line_item.gst_inclusive=False round-trips")
                        else:
                            fail("TC-PAY-FIDELITY: gst_inclusive", f"got {li.get('gst_inclusive')}")

                        tax_rate = li.get("tax_rate")
                        if tax_rate is not None and float(str(tax_rate)) == 15.0:
                            ok("line_item.tax_rate=15 round-trips")
                        else:
                            fail("TC-PAY-FIDELITY: tax_rate", f"got {tax_rate}")
                    else:
                        fail("TC-PAY-FIDELITY: no line items in GET response")
                else:
                    fail("TC-PAY-FIDELITY: GET quote failed", f"status={r_get.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TC-SAVE-TERMS — save_terms_as_default updates org settings
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.16: TC-SAVE-TERMS — save_terms_as_default")
            unique_terms = f"TEST_E2E_Terms_{uuid.uuid4().hex[:8]}"
            r = await client.post("/api/v1/quotes", headers=headers, json={
                "customer_id": customer_id,
                "subject": "TEST_E2E_Parity Terms",
                "validity_days": 30,
                "terms": unique_terms,
                "save_terms_as_default": True,
                "line_items": [{
                    "item_type": "labour",
                    "description": "TEST_E2E_Parity terms item",
                    "quantity": 1,
                    "unit_price": 25.00,
                    "sort_order": 0,
                }],
            })
            if r.status_code not in (200, 201):
                fail("TC-SAVE-TERMS: create quote", f"status={r.status_code}: {r.text[:200]}")
            else:
                terms_quote = r.json().get("quote", r.json())
                terms_quote_id = terms_quote.get("id")
                created["quote_ids"].append(terms_quote_id)

                # Verify org settings were updated
                r_settings = await client.get("/api/v1/org/settings", headers=headers)
                if r_settings.status_code == 200:
                    settings = r_settings.json()
                    saved_terms = settings.get("terms_and_conditions") or settings.get("settings", {}).get("terms_and_conditions")
                    if saved_terms == unique_terms:
                        ok(f"Org settings terms updated to: {unique_terms[:30]}...")
                    else:
                        fail("TC-SAVE-TERMS: terms not updated in settings", f"got {str(saved_terms)[:100]}")
                else:
                    fail("TC-SAVE-TERMS: GET /org/settings failed", f"status={r_settings.status_code}")


            # ═══════════════════════════════════════════════════════════
            # TC-AUTH-401 — Attachment endpoints return 401 without auth
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.17: TC-AUTH-401 — no auth → 401")
            endpoints_401 = [
                ("POST", f"/api/v1/quotes/{quote_id}/attachments"),
                ("GET", f"/api/v1/quotes/{quote_id}/attachments"),
                ("GET", f"/api/v1/quotes/{quote_id}/attachments/{attachment_id}"),
                ("DELETE", f"/api/v1/quotes/{quote_id}/attachments/{attachment_id}"),
            ]
            for method, url in endpoints_401:
                if method == "POST":
                    r = await client.post(url, files={"file": ("test.jpg", small_jpeg, "image/jpeg")})
                elif method == "GET":
                    r = await client.get(url)
                elif method == "DELETE":
                    r = await client.delete(url)
                if r.status_code == 401:
                    ok(f"No auth {method} {url.split('/quotes/')[1][:40]} → 401")
                else:
                    fail(f"TC-AUTH-401: {method} expected 401", f"got {r.status_code}")

            # ═══════════════════════════════════════════════════════════
            # TC-AUTH-403 — Non-permitted role returns 403
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.18: TC-AUTH-403 — non-permitted role → 403")
            # Create a staff_member user (not org_admin or salesperson)
            sm_user_id = uuid.uuid4()
            sm_email = f"TEST_E2E_staff_{uuid.uuid4().hex[:8]}@example.com"
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

                # Test all 4 attachment endpoints
                r = await client.post(
                    f"/api/v1/quotes/{quote_id}/attachments",
                    headers=sm_headers,
                    files={"file": ("test.jpg", small_jpeg, "image/jpeg")},
                )
                if r.status_code == 403:
                    ok("staff_member POST /attachments → 403")
                else:
                    fail("TC-AUTH-403: POST expected 403", f"got {r.status_code}")

                r = await client.get(
                    f"/api/v1/quotes/{quote_id}/attachments",
                    headers=sm_headers,
                )
                if r.status_code == 403:
                    ok("staff_member GET /attachments → 403")
                else:
                    fail("TC-AUTH-403: GET list expected 403", f"got {r.status_code}")

                r = await client.get(
                    f"/api/v1/quotes/{quote_id}/attachments/{attachment_id}",
                    headers=sm_headers,
                )
                if r.status_code == 403:
                    ok("staff_member GET /attachments/{id} → 403")
                else:
                    fail("TC-AUTH-403: GET file expected 403", f"got {r.status_code}")

                r = await client.delete(
                    f"/api/v1/quotes/{quote_id}/attachments/{attachment_id}",
                    headers=sm_headers,
                )
                if r.status_code == 403:
                    ok("staff_member DELETE /attachments/{id} → 403")
                else:
                    fail("TC-AUTH-403: DELETE expected 403", f"got {r.status_code}")
            else:
                fail("TC-AUTH-403: staff_member login failed")

        finally:
            # ═══════════════════════════════════════════════════════════
            # Test 7.19: Cleanup verification
            # ═══════════════════════════════════════════════════════════
            print("\n🔹 Test 7.19: Cleanup — delete all TEST_E2E_ rows")

            if conn is None:
                conn = await asyncpg.connect(
                    host="postgres", port=5432,
                    user="postgres", password="postgres",
                    database="workshoppro",
                )

            try:
                # Delete quote attachments first (child of quotes)
                for qid in created["quote_ids"]:
                    await conn.execute(
                        "DELETE FROM quote_attachments WHERE quote_id = $1::uuid",
                        uuid.UUID(qid),
                    )

                # Delete quotes (child of customers and orgs)
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

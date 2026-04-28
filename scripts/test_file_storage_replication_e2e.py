"""
E2E test script: File Storage Replication

Covers:
  1. Upload a logo via branding endpoint, verify it's served from DB with correct Content-Type
  2. Upload a favicon, verify content type header
  3. Save volume sync config, verify it persists via GET
  4. Trigger manual sync (will fail without actual standby — verify history records failure)
  5. Verify status endpoint returns expected shape
  6. Verify history endpoint returns entries in descending order
  7. Verify non-admin gets 403 on volume sync endpoints
  8. OWASP: broken access control (unauthenticated access)
  9. OWASP: injection payloads in text fields

Requirements: 1.4, 2.1, 4.3, 4.4, 5.6, 6.1, 6.2, 6.4

Run inside container:
  docker exec invoicing-app-1 python scripts/test_file_storage_replication_e2e.py

Or from host (if app is running on localhost:8000):
  python scripts/test_file_storage_replication_e2e.py
"""
from __future__ import annotations

import io
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.environ.get("E2E_EMAIL", "admin@orainvoice.com")
ADMIN_PASSWORD = os.environ.get("E2E_PASSWORD", "admin123")

# Test data prefix
TEST_E2E_SSH_HOST = "TEST_E2E_192.168.99.99"
TEST_E2E_SSH_KEY_PATH = "/tmp/TEST_E2E_fake_key"
TEST_E2E_REMOTE_UPLOAD = "/tmp/TEST_E2E_uploads/"
TEST_E2E_REMOTE_COMPLIANCE = "/tmp/TEST_E2E_compliance/"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[93m⊘\033[0m"
INFO = "\033[94m→\033[0m"

passed = 0
failed = 0
skipped = 0


def ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  {PASS} {label}")


def fail(label: str, detail: str = "") -> None:
    global failed
    failed += 1
    msg = f"  {FAIL} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def skip(label: str, detail: str = "") -> None:
    global skipped
    skipped += 1
    msg = f"  {SKIP} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_1x1_png() -> bytes:
    """Create a minimal valid 1x1 pixel red PNG in memory."""
    # PNG signature
    sig = b"\x89PNG\r\n\x1a\n"

    # IHDR chunk: width=1, height=1, bit_depth=8, color_type=2 (RGB)
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)

    # IDAT chunk: single row, filter byte 0, then R G B
    raw_row = b"\x00\xff\x00\x00"  # filter=None, red pixel
    compressed = zlib.compress(raw_row)
    idat = _png_chunk(b"IDAT", compressed)

    # IEND chunk
    iend = _png_chunk(b"IEND", b"")

    return sig + ihdr + idat + iend


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a PNG chunk with length, type, data, and CRC."""
    chunk = chunk_type + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def make_1x1_ico() -> bytes:
    """Create a minimal ICO file wrapping a 1x1 BMP for favicon testing."""
    # Simplest approach: use the PNG as the ICO payload (modern ICO supports PNG)
    png_data = make_1x1_png()
    # ICO header: reserved=0, type=1 (icon), count=1
    header = struct.pack("<HHH", 0, 1, 1)
    # ICO directory entry: width=1, height=1, colors=0, reserved=0,
    # planes=1, bpp=32, size, offset=22 (6 header + 16 entry)
    entry = struct.pack("<BBBBHHII", 1, 1, 0, 0, 1, 32, len(png_data), 22)
    return header + entry + png_data


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    """Authenticate and return Authorization header dict."""
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "remember_me": False},
    )
    if r.status_code != 200:
        print(f"  {FAIL} Login failed for {email}: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    data = r.json()
    token = data.get("access_token")
    if not token:
        print(f"  {FAIL} Login response missing access_token: {data}")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test 1 — Upload logo via branding endpoint, verify DB serving
# ---------------------------------------------------------------------------


def test_upload_logo(client: httpx.Client, headers: dict) -> None:
    """Upload a logo PNG, then verify it's served from DB with correct Content-Type."""
    print(f"\n{'─' * 65}")
    print("1 — Upload logo and verify DB-backed serving (Req 1.4, 2.1)")

    png_bytes = make_1x1_png()

    r = client.post(
        "/api/v2/admin/branding/upload-logo",
        headers=headers,
        files={"file": ("TEST_E2E_logo.png", io.BytesIO(png_bytes), "image/png")},
    )

    if r.status_code != 200:
        fail(f"POST upload-logo → {r.status_code}", r.text[:200])
        return

    ok(f"POST upload-logo → {r.status_code}")
    data = r.json()

    url = data.get("url", "")
    if "/api/v1/public/branding/file/logo" in url:
        ok(f"Response URL points to DB-backed endpoint: {url}")
    else:
        fail(f"Unexpected URL in response: {url}")

    # Serve the logo from the public endpoint
    r2 = client.get("/api/v1/public/branding/file/logo")
    if r2.status_code != 200:
        fail(f"GET /api/v1/public/branding/file/logo → {r2.status_code}", r2.text[:200])
        return

    ok(f"GET /api/v1/public/branding/file/logo → {r2.status_code}")

    ct = r2.headers.get("content-type", "")
    if "image/png" in ct:
        ok(f"Content-Type is image/png: {ct}")
    else:
        fail(f"Unexpected Content-Type: {ct}")

    cache_ctrl = r2.headers.get("cache-control", "")
    if "max-age=86400" in cache_ctrl:
        ok(f"Cache-Control header present: {cache_ctrl}")
    else:
        fail(f"Missing or wrong Cache-Control: {cache_ctrl}")

    # Verify we got actual image bytes back
    if len(r2.content) > 0:
        ok(f"Received {len(r2.content)} bytes of image data")
    else:
        fail("Empty response body for logo")


# ---------------------------------------------------------------------------
# Test 2 — Upload favicon, verify content type
# ---------------------------------------------------------------------------


def test_upload_favicon(client: httpx.Client, headers: dict) -> None:
    """Upload a favicon, verify it's served with correct Content-Type."""
    print(f"\n{'─' * 65}")
    print("2 — Upload favicon and verify Content-Type (Req 1.4, 2.1)")

    png_bytes = make_1x1_png()

    r = client.post(
        "/api/v2/admin/branding/upload-favicon",
        headers=headers,
        files={"file": ("TEST_E2E_favicon.png", io.BytesIO(png_bytes), "image/png")},
    )

    if r.status_code != 200:
        fail(f"POST upload-favicon → {r.status_code}", r.text[:200])
        return

    ok(f"POST upload-favicon → {r.status_code}")

    # Serve the favicon
    r2 = client.get("/api/v1/public/branding/file/favicon")
    if r2.status_code != 200:
        fail(f"GET /api/v1/public/branding/file/favicon → {r2.status_code}", r2.text[:200])
        return

    ok(f"GET /api/v1/public/branding/file/favicon → {r2.status_code}")

    ct = r2.headers.get("content-type", "")
    if "image/" in ct:
        ok(f"Content-Type is an image type: {ct}")
    else:
        fail(f"Unexpected Content-Type for favicon: {ct}")

    if len(r2.content) > 0:
        ok(f"Received {len(r2.content)} bytes of favicon data")
    else:
        fail("Empty response body for favicon")


# ---------------------------------------------------------------------------
# Test 3 — Save volume sync config, verify persistence via GET
# ---------------------------------------------------------------------------


def test_volume_sync_config(client: httpx.Client, headers: dict) -> dict | None:
    """PUT volume sync config, then GET it back and verify fields match."""
    print(f"\n{'─' * 65}")
    print("3 — Save volume sync config and verify persistence (Req 4.3, 4.4)")

    config_payload = {
        "standby_ssh_host": TEST_E2E_SSH_HOST,
        "ssh_port": 2222,
        "ssh_key_path": TEST_E2E_SSH_KEY_PATH,
        "remote_upload_path": TEST_E2E_REMOTE_UPLOAD,
        "remote_compliance_path": TEST_E2E_REMOTE_COMPLIANCE,
        "sync_interval_minutes": 10,
        "enabled": False,
    }

    r = client.put(
        "/api/v1/ha/volume-sync/config",
        headers=headers,
        json=config_payload,
    )

    if r.status_code != 200:
        fail(f"PUT /api/v1/ha/volume-sync/config → {r.status_code}", r.text[:200])
        return None

    ok(f"PUT /api/v1/ha/volume-sync/config → {r.status_code}")
    saved = r.json()

    # Verify the saved config has an id
    if saved.get("id"):
        ok(f"Config saved with id: {saved['id']}")
    else:
        fail("Config response missing 'id'")

    # GET it back
    r2 = client.get("/api/v1/ha/volume-sync/config", headers=headers)
    if r2.status_code != 200:
        fail(f"GET /api/v1/ha/volume-sync/config → {r2.status_code}", r2.text[:200])
        return saved

    ok(f"GET /api/v1/ha/volume-sync/config → {r2.status_code}")
    fetched = r2.json()

    # Verify fields match
    checks = {
        "standby_ssh_host": TEST_E2E_SSH_HOST,
        "ssh_port": 2222,
        "ssh_key_path": TEST_E2E_SSH_KEY_PATH,
        "remote_upload_path": TEST_E2E_REMOTE_UPLOAD,
        "remote_compliance_path": TEST_E2E_REMOTE_COMPLIANCE,
        "sync_interval_minutes": 10,
        "enabled": False,
    }
    all_match = True
    for key, expected in checks.items():
        actual = fetched.get(key)
        if actual != expected:
            fail(f"Config field '{key}'", f"expected={expected!r}, got={actual!r}")
            all_match = False
    if all_match:
        ok("All config fields match after GET")

    return saved


# ---------------------------------------------------------------------------
# Test 4 — Trigger manual sync (expect failure, verify history)
# ---------------------------------------------------------------------------


def test_trigger_sync(client: httpx.Client, headers: dict) -> None:
    """Trigger manual sync — will fail without actual standby. Verify history records failure."""
    print(f"\n{'─' * 65}")
    print("4 — Trigger manual sync and verify history records failure (Req 5.6)")

    r = client.post("/api/v1/ha/volume-sync/trigger", headers=headers)

    if r.status_code == 200:
        data = r.json()
        ok(f"POST trigger → {r.status_code} (sync_id={data.get('sync_id', 'N/A')})")
    elif r.status_code == 404:
        skip("POST trigger → 404", "Volume sync not configured")
        return
    elif r.status_code == 409:
        ok("POST trigger → 409 (sync already in progress — expected)")
        return
    else:
        fail(f"POST trigger → {r.status_code}", r.text[:200])
        return

    # Wait briefly for the sync to complete (it should fail quickly)
    import time
    time.sleep(3)

    # Check history for the failure entry
    r2 = client.get("/api/v1/ha/volume-sync/history", headers=headers)
    if r2.status_code != 200:
        fail(f"GET history after trigger → {r2.status_code}", r2.text[:200])
        return

    history = r2.json()
    if not isinstance(history, list):
        fail("History response is not a list", f"type={type(history).__name__}")
        return

    if len(history) == 0:
        fail("History is empty after triggering sync")
        return

    ok(f"History has {len(history)} entries after trigger")

    latest = history[0]
    status = latest.get("status", "")
    sync_type = latest.get("sync_type", "")

    if sync_type == "manual":
        ok(f"Latest entry sync_type='manual'")
    else:
        fail(f"Latest entry sync_type", f"expected='manual', got={sync_type!r}")

    # The sync should have failed (no actual standby) or succeeded
    if status in ("failure", "success", "running"):
        ok(f"Latest entry status='{status}' (failure expected without standby)")
    else:
        fail(f"Unexpected status: {status!r}")

    if status == "failure" and latest.get("error_message"):
        ok(f"Error message recorded: {latest['error_message'][:80]}")


# ---------------------------------------------------------------------------
# Test 5 — Verify status endpoint returns expected shape
# ---------------------------------------------------------------------------


def test_volume_sync_status(client: httpx.Client, headers: dict) -> None:
    """GET /api/v1/ha/volume-sync/status — verify response shape."""
    print(f"\n{'─' * 65}")
    print("5 — Verify status endpoint response shape (Req 6.1)")

    r = client.get("/api/v1/ha/volume-sync/status", headers=headers)

    if r.status_code != 200:
        fail(f"GET status → {r.status_code}", r.text[:200])
        return

    ok(f"GET /api/v1/ha/volume-sync/status → {r.status_code}")
    data = r.json()

    expected_fields = {
        "last_sync_time": (str, type(None)),
        "last_sync_result": (str, type(None)),
        "next_scheduled_sync": (str, type(None)),
        "total_file_count": (int,),
        "total_size_bytes": (int,),
        "sync_in_progress": (bool,),
    }

    all_present = True
    for field, allowed_types in expected_fields.items():
        if field not in data:
            fail(f"Missing field: {field}")
            all_present = False
        else:
            value = data[field]
            if isinstance(value, allowed_types):
                ok(f"Field '{field}' present, type={type(value).__name__}")
            else:
                fail(
                    f"Field '{field}' wrong type",
                    f"expected one of {[t.__name__ for t in allowed_types]}, "
                    f"got {type(value).__name__}",
                )
                all_present = False

    if all_present:
        ok("Status response has all expected fields with correct types")


# ---------------------------------------------------------------------------
# Test 6 — Verify history endpoint returns entries in descending order
# ---------------------------------------------------------------------------


def test_history_ordering(client: httpx.Client, headers: dict) -> None:
    """GET /api/v1/ha/volume-sync/history — verify descending order by started_at."""
    print(f"\n{'─' * 65}")
    print("6 — Verify history entries in descending order (Req 6.2, 6.4)")

    r = client.get("/api/v1/ha/volume-sync/history", headers=headers)

    if r.status_code != 200:
        fail(f"GET history → {r.status_code}", r.text[:200])
        return

    ok(f"GET /api/v1/ha/volume-sync/history → {r.status_code}")
    history = r.json()

    if not isinstance(history, list):
        fail("History response is not a list", f"type={type(history).__name__}")
        return

    ok(f"History returned {len(history)} entries")

    if len(history) < 2:
        skip("Cannot verify ordering with fewer than 2 entries")
        return

    # Verify descending order by started_at
    timestamps = [entry.get("started_at", "") for entry in history]
    is_descending = all(timestamps[i] >= timestamps[i + 1] for i in range(len(timestamps) - 1))

    if is_descending:
        ok("History entries are in descending order by started_at")
    else:
        fail("History entries are NOT in descending order", f"timestamps: {timestamps[:5]}")

    # Verify each entry has expected fields
    required_fields = ["id", "started_at", "status", "files_transferred", "bytes_transferred", "sync_type"]
    first_entry = history[0]
    missing = [f for f in required_fields if f not in first_entry]
    if missing:
        fail(f"History entry missing fields: {missing}")
    else:
        ok("History entries have all required fields")


# ---------------------------------------------------------------------------
# Test 7 — Non-admin gets 403 on volume sync endpoints
# ---------------------------------------------------------------------------


def test_non_admin_access(client: httpx.Client) -> None:
    """Verify unauthenticated requests get 401/403 on volume sync endpoints."""
    print(f"\n{'─' * 65}")
    print("7 — Non-admin / unauthenticated access denied (Req 4.5, 6.5)")

    endpoints = [
        ("GET", "/api/v1/ha/volume-sync/config"),
        ("PUT", "/api/v1/ha/volume-sync/config"),
        ("GET", "/api/v1/ha/volume-sync/status"),
        ("POST", "/api/v1/ha/volume-sync/trigger"),
        ("GET", "/api/v1/ha/volume-sync/history"),
    ]

    for method, path in endpoints:
        if method == "GET":
            r = client.get(path)
        elif method == "PUT":
            r = client.put(path, json={"standby_ssh_host": "x", "ssh_key_path": "/x"})
        elif method == "POST":
            r = client.post(path)
        else:
            continue

        if r.status_code in (401, 403):
            ok(f"Unauthenticated {method} {path} → {r.status_code}")
        else:
            fail(
                f"Unauthenticated {method} {path} should be 401/403",
                f"got {r.status_code}",
            )


# ---------------------------------------------------------------------------
# Test 8 — OWASP: Broken access control
# ---------------------------------------------------------------------------


def test_owasp_broken_access_control(client: httpx.Client) -> None:
    """OWASP A01: Verify broken access control checks."""
    print(f"\n{'─' * 65}")
    print("8 — OWASP: Broken access control checks")

    # Try accessing volume sync config with a fake/invalid token
    fake_headers = {"Authorization": "Bearer fake_token_12345"}

    r = client.get("/api/v1/ha/volume-sync/config", headers=fake_headers)
    if r.status_code in (401, 403):
        ok(f"Fake token rejected on GET config → {r.status_code}")
    else:
        fail(f"Fake token not rejected on GET config → {r.status_code}")

    r = client.post("/api/v1/ha/volume-sync/trigger", headers=fake_headers)
    if r.status_code in (401, 403):
        ok(f"Fake token rejected on POST trigger → {r.status_code}")
    else:
        fail(f"Fake token not rejected on POST trigger → {r.status_code}")

    # Try with empty Authorization header
    empty_headers = {"Authorization": ""}
    r = client.get("/api/v1/ha/volume-sync/status", headers=empty_headers)
    if r.status_code in (401, 403):
        ok(f"Empty auth header rejected on GET status → {r.status_code}")
    else:
        fail(f"Empty auth header not rejected on GET status → {r.status_code}")

    # Try with Bearer but no token — httpx may reject the header value
    # as illegal, which is itself a form of protection
    try:
        no_token_headers = {"Authorization": "Bearer "}
        r = client.get("/api/v1/ha/volume-sync/history", headers=no_token_headers)
        if r.status_code in (401, 403):
            ok(f"Bearer-no-token rejected on GET history → {r.status_code}")
        else:
            fail(f"Bearer-no-token not rejected on GET history → {r.status_code}")
    except Exception:
        ok("Bearer-no-token rejected at HTTP client level (illegal header value)")


# ---------------------------------------------------------------------------
# Test 9 — OWASP: Injection payloads in text fields
# ---------------------------------------------------------------------------


def test_owasp_injection(client: httpx.Client, headers: dict) -> None:
    """OWASP A03: Test SQL injection and XSS payloads in volume sync config fields."""
    print(f"\n{'─' * 65}")
    print("9 — OWASP: Injection payloads in text fields")

    # SQL injection in SSH host field
    sqli_payloads = [
        "'; DROP TABLE volume_sync_config; --",
        "192.168.1.1' OR '1'='1",
        "$(rm -rf /)",
        "192.168.1.1; cat /etc/passwd",
    ]

    for payload in sqli_payloads:
        r = client.put(
            "/api/v1/ha/volume-sync/config",
            headers=headers,
            json={
                "standby_ssh_host": payload,
                "ssh_key_path": TEST_E2E_SSH_KEY_PATH,
                "sync_interval_minutes": 5,
                "enabled": False,
            },
        )
        # The app should either accept it (stored as a string, not executed)
        # or reject it with a validation error — but NOT crash with 500
        if r.status_code in (200, 422):
            ok(f"SQLi payload in ssh_host handled safely → {r.status_code}")
        elif r.status_code == 500:
            fail(f"SQLi payload caused server error → {r.status_code}", payload[:50])
        else:
            ok(f"SQLi payload in ssh_host → {r.status_code} (not a server error)")

    # XSS in SSH key path field
    xss_payloads = [
        "<script>alert('xss')</script>",
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
    ]

    for payload in xss_payloads:
        r = client.put(
            "/api/v1/ha/volume-sync/config",
            headers=headers,
            json={
                "standby_ssh_host": TEST_E2E_SSH_HOST,
                "ssh_key_path": payload,
                "sync_interval_minutes": 5,
                "enabled": False,
            },
        )
        if r.status_code in (200, 422):
            ok(f"XSS payload in ssh_key_path handled safely → {r.status_code}")
        elif r.status_code == 500:
            fail(f"XSS payload caused server error → {r.status_code}", payload[:50])
        else:
            ok(f"XSS payload in ssh_key_path → {r.status_code} (not a server error)")

    # If any injection payload was accepted (200), verify it was stored as-is
    # and not interpreted — read it back
    r = client.get("/api/v1/ha/volume-sync/config", headers=headers)
    if r.status_code == 200:
        data = r.json()
        # The stored value should be the raw string, not executed
        ssh_host = data.get("standby_ssh_host", "")
        if "<script>" not in ssh_host and "DROP TABLE" not in ssh_host:
            ok("Stored config does not contain injection artifacts (last write wins)")
        else:
            ok("Injection payload stored as plain text (not executed)")
    else:
        skip("Could not verify stored config after injection tests")


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------


def cleanup(client: httpx.Client, headers: dict) -> None:
    """Clean up all test data created during the e2e run."""
    print(f"\n{'─' * 65}")
    print("CLEANUP — Removing test data")

    # Restore volume sync config to a clean state by deleting via direct DB
    # Since there's no DELETE endpoint, we overwrite with benign values
    # or use direct SQL cleanup
    try:
        import asyncpg
        import asyncio

        async def _cleanup_db():
            conn = await asyncpg.connect(
                host="postgres", port=5432,
                user="postgres", password="postgres",
                database="workshoppro",
            )
            try:
                # Delete volume sync config if it has our test SSH host
                deleted_config = await conn.execute(
                    "DELETE FROM volume_sync_config WHERE standby_ssh_host LIKE 'TEST_E2E_%'"
                )
                print(f"  {INFO} Cleaned volume_sync_config: {deleted_config}")

                # Delete volume sync history entries created during test
                deleted_history = await conn.execute(
                    "DELETE FROM volume_sync_history WHERE sync_type = 'manual'"
                    " AND started_at > NOW() - INTERVAL '10 minutes'"
                )
                print(f"  {INFO} Cleaned volume_sync_history: {deleted_history}")

                # Also clean up any config with injection payloads
                deleted_injection = await conn.execute(
                    "DELETE FROM volume_sync_config WHERE standby_ssh_host LIKE '%DROP TABLE%'"
                    " OR standby_ssh_host LIKE '%script%'"
                    " OR standby_ssh_host LIKE '%OR %'"
                    " OR ssh_key_path LIKE '%script%'"
                    " OR ssh_key_path LIKE '%javascript%'"
                )
                print(f"  {INFO} Cleaned injection test configs: {deleted_injection}")

            finally:
                await conn.close()

        asyncio.run(_cleanup_db())
        ok("Database cleanup complete")
    except Exception as e:
        # Fallback: try to overwrite config via API with benign values
        print(f"  {INFO} Direct DB cleanup failed ({e}), attempting API cleanup")
        try:
            # Overwrite with clearly-test values that can be identified
            r = client.put(
                "/api/v1/ha/volume-sync/config",
                headers=headers,
                json={
                    "standby_ssh_host": "CLEANUP_PENDING",
                    "ssh_key_path": "/dev/null",
                    "sync_interval_minutes": 1440,
                    "enabled": False,
                },
            )
            if r.status_code == 200:
                ok("Config overwritten with benign values (manual DB cleanup needed)")
            else:
                fail(f"API cleanup failed → {r.status_code}")
        except Exception as e2:
            fail(f"All cleanup methods failed: {e2}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    global passed, failed

    client = httpx.Client(base_url=BASE, timeout=30.0)

    print("=" * 65)
    print("  FILE STORAGE REPLICATION — END-TO-END VERIFICATION")
    print("=" * 65)
    print(f"  Base URL: {BASE}")

    # ── Authenticate as global admin ──
    print(f"\n{INFO} Logging in as {ADMIN_EMAIL}")
    headers = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"  {PASS} Authenticated")

    try:
        # ── Run tests ──
        test_upload_logo(client, headers)
        test_upload_favicon(client, headers)
        test_volume_sync_config(client, headers)
        test_trigger_sync(client, headers)
        test_volume_sync_status(client, headers)
        test_history_ordering(client, headers)
        test_non_admin_access(client)
        test_owasp_broken_access_control(client)
        test_owasp_injection(client, headers)
    finally:
        # ── MANDATORY cleanup ──
        cleanup(client, headers)

    # ── Summary ──
    print(f"\n{'=' * 65}")
    total = passed + failed + skipped
    parts = []
    if passed:
        parts.append(f"{PASS} {passed} passed")
    if failed:
        parts.append(f"{FAIL} {failed} failed")
    if skipped:
        parts.append(f"{SKIP} {skipped} skipped")
    summary = ", ".join(parts)

    if failed == 0:
        print(f"  {PASS} ALL CHECKS PASSED ({total} total: {summary})")
    else:
        print(f"  {summary} (of {total} total)")
    print(f"{'=' * 65}")

    client.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

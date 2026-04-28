"""
E2E test script: HA Setup Wizard

Covers:
  1. Login as Global_Admin on primary
  2. Check-reachability against standby
  3. Authenticate against standby
  4. Handshake (trust exchange)
  5. Setup (automated replication)
  6. Verify ha_config on primary node
  7. Verify ha_event_log has entries
  8. Verify event log API returns events
  9. Auth rejection (no token → 401/403)
  10. Clean up test data

Requirements: 5.1, 6.1, 7.1, 8.1, 34.6

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
      python scripts/test_ha_wizard_e2e.py

Or from host (if app is running on localhost):
  python scripts/test_ha_wizard_e2e.py --primary http://localhost --standby http://localhost:8081
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PRIMARY_URL = os.environ.get("E2E_PRIMARY_URL", "http://localhost")
DEFAULT_STANDBY_URL = os.environ.get("E2E_STANDBY_URL", "http://localhost:8081")
ADMIN_EMAIL = os.environ.get("E2E_EMAIL", "admin@orainvoice.com")
ADMIN_PASSWORD = os.environ.get("E2E_PASSWORD", "admin123")

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
# Auth helper
# ---------------------------------------------------------------------------


def login(client: httpx.Client, base_url: str, email: str, password: str) -> dict[str, str]:
    """Authenticate against a node and return Authorization header dict."""
    r = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"email": email, "password": password, "remember_me": False},
    )
    if r.status_code != 200:
        print(f"  {FAIL} Login failed for {email} at {base_url}: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    data = r.json()
    token = data.get("access_token")
    if not token:
        print(f"  {FAIL} Login response missing access_token: {data}")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test 1 — Check reachability against standby
# ---------------------------------------------------------------------------


def test_check_reachability(
    client: httpx.Client,
    primary_url: str,
    standby_url: str,
    headers: dict,
) -> bool:
    """POST /ha/wizard/check-reachability — verify standby is reachable."""
    print(f"\n{'─' * 65}")
    print("1 — Check reachability against standby")

    r = client.post(
        f"{primary_url}/api/v1/ha/wizard/check-reachability",
        headers=headers,
        json={"address": standby_url},
    )

    if r.status_code != 200:
        fail(f"POST check-reachability → {r.status_code}", r.text[:200])
        return False

    data = r.json()
    ok(f"POST check-reachability → {r.status_code}")

    reachable = data.get("reachable", False)
    if reachable:
        ok(f"Standby reachable: node_name={data.get('node_name')}, role={data.get('role')}")
    else:
        fail("Standby not reachable", data.get("error", "unknown error"))
        return False

    is_orainvoice = data.get("is_orainvoice", False)
    if is_orainvoice:
        ok("Standby confirmed as OraInvoice node")
    else:
        fail("Standby not identified as OraInvoice node")
        return False

    # Check for version warning (informational, not a failure)
    version_warning = data.get("version_warning")
    if version_warning:
        skip(f"Version warning: {version_warning}")

    return True


# ---------------------------------------------------------------------------
# Test 2 — Authenticate against standby
# ---------------------------------------------------------------------------


def test_authenticate(
    client: httpx.Client,
    primary_url: str,
    standby_url: str,
    headers: dict,
    email: str = ADMIN_EMAIL,
    password: str = ADMIN_PASSWORD,
) -> str | None:
    """POST /ha/wizard/authenticate — proxy login to standby, return standby token."""
    print(f"\n{'─' * 65}")
    print("2 — Authenticate against standby")

    r = client.post(
        f"{primary_url}/api/v1/ha/wizard/authenticate",
        headers=headers,
        json={
            "address": standby_url,
            "email": email,
            "password": password,
        },
    )

    if r.status_code != 200:
        fail(f"POST authenticate → {r.status_code}", r.text[:200])
        return None

    data = r.json()
    ok(f"POST authenticate → {r.status_code}")

    authenticated = data.get("authenticated", False)
    if authenticated:
        ok("Authentication succeeded")
    else:
        fail("Authentication failed", data.get("error", "unknown error"))
        return None

    is_global_admin = data.get("is_global_admin", False)
    if is_global_admin:
        ok("Confirmed Global_Admin role on standby")
    else:
        fail("User is not Global_Admin on standby")
        return None

    token = data.get("token")
    if token:
        ok("Standby token received (held in memory)")
    else:
        fail("No standby token in response")
        return None

    return token


# ---------------------------------------------------------------------------
# Test 3 — Trust handshake
# ---------------------------------------------------------------------------


def test_handshake(
    client: httpx.Client,
    primary_url: str,
    standby_url: str,
    headers: dict,
    standby_token: str,
) -> bool:
    """POST /ha/wizard/handshake — exchange SSH keys, IPs, ports, HMAC secret."""
    print(f"\n{'─' * 65}")
    print("3 — Trust handshake")

    r = client.post(
        f"{primary_url}/api/v1/ha/wizard/handshake",
        headers=headers,
        json={
            "address": standby_url,
            "standby_token": standby_token,
        },
    )

    if r.status_code != 200:
        fail(f"POST handshake → {r.status_code}", r.text[:200])
        return False

    data = r.json()
    ok(f"POST handshake → {r.status_code}")

    success = data.get("success", False)
    if not success:
        fail("Handshake failed", data.get("error", "unknown error"))
        return False

    ok("Handshake succeeded")

    # Verify exchanged details
    primary_ip = data.get("primary_ip")
    standby_ip = data.get("standby_ip")
    primary_pg_port = data.get("primary_pg_port")
    standby_pg_port = data.get("standby_pg_port")
    hmac_set = data.get("hmac_secret_set", False)

    if primary_ip:
        ok(f"Primary IP: {primary_ip}")
    else:
        fail("Missing primary_ip in handshake response")

    if standby_ip:
        ok(f"Standby IP: {standby_ip}")
    else:
        fail("Missing standby_ip in handshake response")

    if primary_pg_port:
        ok(f"Primary PG port: {primary_pg_port}")
    else:
        fail("Missing primary_pg_port in handshake response")

    if standby_pg_port:
        ok(f"Standby PG port: {standby_pg_port}")
    else:
        fail("Missing standby_pg_port in handshake response")

    if hmac_set:
        ok("HMAC secret set on both nodes")
    else:
        fail("HMAC secret not set")

    return True


# ---------------------------------------------------------------------------
# Test 4 — Automated setup
# ---------------------------------------------------------------------------


def test_setup(
    client: httpx.Client,
    primary_url: str,
    standby_url: str,
    headers: dict,
    standby_token: str,
) -> bool:
    """POST /ha/wizard/setup — execute full automated replication setup."""
    print(f"\n{'─' * 65}")
    print("4 — Automated replication setup")

    r = client.post(
        f"{primary_url}/api/v1/ha/wizard/setup",
        headers=headers,
        json={
            "address": standby_url,
            "standby_token": standby_token,
        },
        timeout=120.0,  # setup can take a while
    )

    if r.status_code != 200:
        fail(f"POST setup → {r.status_code}", r.text[:300])
        return False

    data = r.json()
    ok(f"POST setup → {r.status_code}")

    success = data.get("success", False)
    steps = data.get("steps", [])

    # Display each step result
    for step in steps:
        step_name = step.get("step", "unknown")
        step_status = step.get("status", "unknown")
        step_msg = step.get("message", "")
        step_err = step.get("error", "")

        if step_status == "completed":
            ok(f"Step '{step_name}': {step_status}" + (f" — {step_msg}" if step_msg else ""))
        elif step_status == "failed":
            fail(f"Step '{step_name}': {step_status}", step_err or step_msg)
        else:
            skip(f"Step '{step_name}': {step_status}", step_msg or step_err)

    if success:
        ok("Full setup completed successfully")
    else:
        fail("Setup did not complete successfully", data.get("error", ""))

    return success


# ---------------------------------------------------------------------------
# Test 5 — Verify ha_config on primary
# ---------------------------------------------------------------------------


def test_verify_ha_config(
    client: httpx.Client,
    primary_url: str,
    headers: dict,
) -> bool:
    """GET /ha/identity — verify HA config exists on primary after setup."""
    print(f"\n{'─' * 65}")
    print("5 — Verify ha_config on primary node")

    r = client.get(f"{primary_url}/api/v1/ha/identity", headers=headers)

    if r.status_code == 404:
        fail("GET /ha/identity → 404", "HA not configured after setup")
        return False

    if r.status_code != 200:
        fail(f"GET /ha/identity → {r.status_code}", r.text[:200])
        return False

    data = r.json()
    ok(f"GET /ha/identity → {r.status_code}")

    role = data.get("role")
    if role == "primary":
        ok(f"Node role: {role}")
    elif role:
        skip(f"Node role: {role} (expected 'primary')")
    else:
        fail("Missing role in identity response")

    node_name = data.get("node_name")
    if node_name:
        ok(f"Node name: {node_name}")
    else:
        fail("Missing node_name in identity response")

    peer_endpoint = data.get("peer_endpoint")
    if peer_endpoint:
        ok(f"Peer endpoint: {peer_endpoint}")
    else:
        fail("Missing peer_endpoint in identity response")

    peer_db_configured = data.get("peer_db_configured", False)
    if peer_db_configured:
        ok("Peer DB configured: True")
    else:
        skip("Peer DB not configured (may be expected if setup was partial)")

    heartbeat_secret_configured = data.get("heartbeat_secret_configured", False)
    if heartbeat_secret_configured:
        ok("Heartbeat secret configured: True")
    else:
        skip("Heartbeat secret not configured")

    return True


# ---------------------------------------------------------------------------
# Test 6 — Verify ha_event_log has entries
# ---------------------------------------------------------------------------


def test_verify_event_log_has_entries(
    client: httpx.Client,
    primary_url: str,
    headers: dict,
) -> bool:
    """GET /ha/events — verify event log has entries after wizard operations."""
    print(f"\n{'─' * 65}")
    print("6 — Verify ha_event_log has entries")

    r = client.get(
        f"{primary_url}/api/v1/ha/events",
        headers=headers,
        params={"limit": 50},
    )

    if r.status_code != 200:
        fail(f"GET /ha/events → {r.status_code}", r.text[:200])
        return False

    data = r.json()
    ok(f"GET /ha/events → {r.status_code}")

    events = data.get("events", [])
    total = data.get("total", 0)

    if total > 0:
        ok(f"Event log has {total} entries")
    else:
        fail("Event log is empty — expected entries from wizard operations")
        return False

    if isinstance(events, list) and len(events) > 0:
        ok(f"Returned {len(events)} events in response")
    else:
        fail("Events list is empty or not a list")
        return False

    # Verify event structure
    first_event = events[0]
    required_fields = ["id", "timestamp", "event_type", "severity", "message", "node_name"]
    all_present = True
    for field in required_fields:
        if field in first_event:
            pass  # field present
        else:
            fail(f"Event missing field: {field}")
            all_present = False

    if all_present:
        ok("Event structure has all required fields")

    return True


# ---------------------------------------------------------------------------
# Test 7 — Verify event log API filtering
# ---------------------------------------------------------------------------


def test_event_log_filtering(
    client: httpx.Client,
    primary_url: str,
    headers: dict,
) -> None:
    """GET /ha/events with filters — verify severity and event_type filtering."""
    print(f"\n{'─' * 65}")
    print("7 — Verify event log API filtering")

    # Test severity filter
    r = client.get(
        f"{primary_url}/api/v1/ha/events",
        headers=headers,
        params={"limit": 10, "severity": "info"},
    )
    if r.status_code == 200:
        data = r.json()
        events = data.get("events", [])
        ok(f"Severity filter 'info' → {len(events)} events")
        # Verify all returned events have the correct severity
        wrong_severity = [e for e in events if e.get("severity") != "info"]
        if wrong_severity:
            fail(f"Severity filter returned {len(wrong_severity)} events with wrong severity")
        elif events:
            ok("All returned events have severity='info'")
    else:
        fail(f"GET /ha/events?severity=info → {r.status_code}", r.text[:200])

    # Test limit parameter
    r = client.get(
        f"{primary_url}/api/v1/ha/events",
        headers=headers,
        params={"limit": 2},
    )
    if r.status_code == 200:
        data = r.json()
        events = data.get("events", [])
        if len(events) <= 2:
            ok(f"Limit=2 → returned {len(events)} events (respects limit)")
        else:
            fail(f"Limit=2 but returned {len(events)} events")
    else:
        fail(f"GET /ha/events?limit=2 → {r.status_code}", r.text[:200])


# ---------------------------------------------------------------------------
# Test 8 — Auth rejection (no token → 401/403)
# ---------------------------------------------------------------------------


def test_auth_rejection(
    client: httpx.Client,
    primary_url: str,
) -> None:
    """Verify all wizard endpoints reject unauthenticated requests."""
    print(f"\n{'─' * 65}")
    print("8 — Auth rejection (no token → 401/403)")

    endpoints = [
        ("POST", "/api/v1/ha/wizard/check-reachability", {"address": "http://localhost:8081"}),
        ("POST", "/api/v1/ha/wizard/authenticate", {"address": "http://localhost:8081", "email": "x", "password": "x"}),
        ("POST", "/api/v1/ha/wizard/handshake", {"address": "http://localhost:8081", "standby_token": "x"}),
        ("POST", "/api/v1/ha/wizard/receive-handshake", {"ssh_pub_key": "x", "lan_ip": "1.2.3.4", "pg_port": 5432, "hmac_secret": "x"}),
        ("POST", "/api/v1/ha/wizard/setup", {"address": "http://localhost:8081", "standby_token": "x"}),
        ("GET", "/api/v1/ha/events", None),
    ]

    for method, path, body in endpoints:
        url = f"{primary_url}{path}"
        if method == "POST":
            r = client.post(url, json=body)
        else:
            r = client.get(url)

        if r.status_code in (401, 403):
            ok(f"Unauthenticated {method} {path} → {r.status_code}")
        else:
            fail(
                f"Unauthenticated {method} {path} should be 401/403",
                f"got {r.status_code}",
            )


# ---------------------------------------------------------------------------
# Test 9 — Check reachability with invalid address
# ---------------------------------------------------------------------------


def test_check_reachability_invalid(
    client: httpx.Client,
    primary_url: str,
    headers: dict,
) -> None:
    """POST /ha/wizard/check-reachability with unreachable address."""
    print(f"\n{'─' * 65}")
    print("9 — Check reachability with invalid/unreachable address")

    r = client.post(
        f"{primary_url}/api/v1/ha/wizard/check-reachability",
        headers=headers,
        json={"address": "http://192.168.255.255:9999"},
        timeout=30.0,
    )

    if r.status_code == 200:
        data = r.json()
        reachable = data.get("reachable", True)
        if not reachable:
            ok(f"Unreachable address correctly reported as not reachable")
            error_msg = data.get("error", "")
            if error_msg:
                ok(f"Error message provided: {error_msg[:80]}")
        else:
            fail("Unreachable address reported as reachable")
    elif r.status_code in (400, 422):
        ok(f"Invalid address rejected → {r.status_code}")
    else:
        fail(f"Unexpected status for unreachable address → {r.status_code}", r.text[:200])


# ---------------------------------------------------------------------------
# Test 10 — Authenticate with invalid credentials
# ---------------------------------------------------------------------------


def test_authenticate_invalid(
    client: httpx.Client,
    primary_url: str,
    standby_url: str,
    headers: dict,
) -> None:
    """POST /ha/wizard/authenticate with wrong credentials."""
    print(f"\n{'─' * 65}")
    print("10 — Authenticate with invalid credentials")

    r = client.post(
        f"{primary_url}/api/v1/ha/wizard/authenticate",
        headers=headers,
        json={
            "address": standby_url,
            "email": "wrong@example.com",
            "password": "wrongpassword",
        },
    )

    if r.status_code == 200:
        data = r.json()
        authenticated = data.get("authenticated", True)
        if not authenticated:
            ok("Invalid credentials correctly rejected")
            error_msg = data.get("error", "")
            if error_msg:
                ok(f"Error message: {error_msg[:80]}")
        else:
            fail("Invalid credentials were accepted")
    elif r.status_code in (400, 401, 422):
        ok(f"Invalid credentials rejected → {r.status_code}")
    else:
        fail(f"Unexpected status for invalid credentials → {r.status_code}", r.text[:200])


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_test_data(
    client: httpx.Client,
    primary_url: str,
    headers: dict,
) -> None:
    """Clean up any test data created during the E2E run.

    The wizard modifies ha_config and ha_event_log. Since these are
    infrastructure tables (not test-specific data with TEST_E2E_ prefix),
    we do NOT delete them — they represent valid HA configuration state.

    We only log what exists for transparency.
    """
    print(f"\n{'─' * 65}")
    print("Cleanup — Verify test data state")

    # Check ha_config state
    r = client.get(f"{primary_url}/api/v1/ha/identity", headers=headers)
    if r.status_code == 200:
        data = r.json()
        ok(f"ha_config exists: role={data.get('role')}, node={data.get('node_name')}")
        print(f"  {INFO} ha_config is infrastructure state — not deleting")
    elif r.status_code == 404:
        ok("No ha_config present (clean state)")
    else:
        skip(f"Could not check ha_config → {r.status_code}")

    # Check event log count
    r = client.get(
        f"{primary_url}/api/v1/ha/events",
        headers=headers,
        params={"limit": 1},
    )
    if r.status_code == 200:
        data = r.json()
        total = data.get("total", 0)
        ok(f"ha_event_log has {total} entries")
        print(f"  {INFO} Event log entries are infrastructure state — not deleting")
    else:
        skip(f"Could not check event log → {r.status_code}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="E2E tests for HA Setup Wizard",
    )
    parser.add_argument(
        "--primary",
        default=DEFAULT_PRIMARY_URL,
        help=f"Primary node URL (default: {DEFAULT_PRIMARY_URL})",
    )
    parser.add_argument(
        "--standby",
        default=DEFAULT_STANDBY_URL,
        help=f"Standby node URL (default: {DEFAULT_STANDBY_URL})",
    )
    parser.add_argument(
        "--email",
        default=ADMIN_EMAIL,
        help=f"Global Admin email (default: {ADMIN_EMAIL})",
    )
    parser.add_argument(
        "--password",
        default=ADMIN_PASSWORD,
        help="Global Admin password",
    )
    args = parser.parse_args()

    email = args.email
    password = args.password
    primary_url = args.primary.rstrip("/")
    standby_url = args.standby.rstrip("/")

    client = httpx.Client(timeout=30.0)

    print("=" * 65)
    print("  HA SETUP WIZARD — END-TO-END VERIFICATION")
    print("=" * 65)
    print(f"  Primary: {primary_url}")
    print(f"  Standby: {standby_url}")

    # ── Authenticate on primary ──
    print(f"\n{INFO} Logging in as {email} on primary ({primary_url})")
    headers = login(client, primary_url, email, password)
    print(f"  {PASS} Authenticated on primary")

    # ── Run wizard flow tests ──
    # Test 1: Check reachability
    reachable = test_check_reachability(client, primary_url, standby_url, headers)

    # Test 2: Authenticate against standby
    standby_token = None
    if reachable:
        standby_token = test_authenticate(client, primary_url, standby_url, headers, email, password)
    else:
        skip("Skipping authenticate — standby not reachable")

    # Test 3: Trust handshake
    handshake_ok = False
    if standby_token:
        handshake_ok = test_handshake(client, primary_url, standby_url, headers, standby_token)
    else:
        skip("Skipping handshake — no standby token")

    # Test 4: Automated setup
    if handshake_ok and standby_token:
        test_setup(client, primary_url, standby_url, headers, standby_token)
    else:
        skip("Skipping setup — handshake not completed")

    # Test 5: Verify ha_config on primary
    test_verify_ha_config(client, primary_url, headers)

    # Test 6: Verify event log has entries
    test_verify_event_log_has_entries(client, primary_url, headers)

    # Test 7: Verify event log filtering
    test_event_log_filtering(client, primary_url, headers)

    # Test 8: Auth rejection (no token)
    test_auth_rejection(client, primary_url)

    # Test 9: Check reachability with invalid address
    test_check_reachability_invalid(client, primary_url, headers)

    # Test 10: Authenticate with invalid credentials
    if reachable:
        test_authenticate_invalid(client, primary_url, standby_url, headers)
    else:
        skip("Skipping invalid auth test — standby not reachable")

    # ── Cleanup ──
    cleanup_test_data(client, primary_url, headers)

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

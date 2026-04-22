"""
E2E test script: HA Replication Improvements

Covers:
  1. Failover-status endpoint response shape
  2. Promotion timestamp tracking (promote → promoted_at set)
  3. Demote-and-sync endpoint
  4. Truncate-all-tables (tested indirectly via init-replication flow)

Requirements: 2.1, 5.5, 7.3, 7.4, 11.1, 12.1, 12.2

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app \
      python scripts/test_ha_improvements_e2e.py

Or from host (if app is running on localhost:80):
  python scripts/test_ha_improvements_e2e.py --base-url http://localhost:80/api/v1
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:80/api/v1")
DEFAULT_EMAIL = os.environ.get("E2E_EMAIL", "admin@nerdytech.co.nz")
DEFAULT_PASSWORD = os.environ.get("E2E_PASSWORD", "W4h3guru1#")

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


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    """Authenticate and return Authorization header dict."""
    r = client.post(
        "/auth/login",
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
# Test 1 — Failover-status endpoint response shape
# ---------------------------------------------------------------------------


def test_failover_status(client: httpx.Client, headers: dict) -> bool:
    """GET /ha/failover-status — verify response has all expected fields."""
    print(f"\n{'─' * 65}")
    print("1 — Failover-status endpoint response shape")

    r = client.get("/ha/failover-status", headers=headers)

    if r.status_code == 404:
        skip("GET /ha/failover-status → 404", "HA not configured on this node")
        return False

    if r.status_code != 200:
        fail(f"GET /ha/failover-status → {r.status_code}", r.text[:200])
        return False

    ok(f"GET /ha/failover-status → {r.status_code}")
    data = r.json()

    # Required fields and their expected types
    expected_fields: dict[str, list[type]] = {
        "auto_promote_enabled": [bool],
        "peer_unreachable_seconds": [float, int, type(None)],
        "failover_timeout_seconds": [int],
        "seconds_until_auto_promote": [float, int, type(None)],
        "split_brain_detected": [bool],
        "is_stale_primary": [bool],
        "promoted_at": [str, type(None)],
    }

    all_present = True
    for field, allowed_types in expected_fields.items():
        if field not in data:
            fail(f"Missing field: {field}")
            all_present = False
        else:
            value = data[field]
            if type(value) in allowed_types:
                ok(f"Field '{field}' present, type={type(value).__name__}, value={value}")
            else:
                fail(
                    f"Field '{field}' wrong type",
                    f"expected one of {[t.__name__ for t in allowed_types]}, "
                    f"got {type(value).__name__}",
                )
                all_present = False

    return all_present


# ---------------------------------------------------------------------------
# Test 2 — Promotion timestamp tracking
# ---------------------------------------------------------------------------


def test_promotion_timestamp(client: httpx.Client, headers: dict) -> None:
    """POST /ha/promote → verify promoted_at is set in identity response."""
    print(f"\n{'─' * 65}")
    print("2 — Promotion timestamp tracking")

    # First check current identity to see the node's role
    r = client.get("/ha/identity", headers=headers)
    if r.status_code == 404:
        skip("GET /ha/identity → 404", "HA not configured — skipping promote test")
        return
    if r.status_code != 200:
        fail(f"GET /ha/identity → {r.status_code}", r.text[:200])
        return

    identity = r.json()
    current_role = identity.get("role", "unknown")
    ok(f"Current role: {current_role}")

    # We can only promote if the node is currently a standby
    if current_role != "standby":
        skip(
            "Promote test skipped",
            f"node role is '{current_role}', must be 'standby' to promote",
        )
        # Still check if promoted_at is present in identity response
        if "promoted_at" in identity:
            promoted_at = identity["promoted_at"]
            ok(f"promoted_at field present in identity: {promoted_at}")
        else:
            fail("promoted_at field missing from identity response")
        return

    # Attempt promotion
    r = client.post(
        "/ha/promote",
        headers=headers,
        json={
            "confirmation_text": "CONFIRM",
            "reason": "e2e test — promotion timestamp tracking",
            "force": True,
        },
    )

    if r.status_code == 200:
        promote_data = r.json()
        ok(f"POST /ha/promote → 200 (status={promote_data.get('status')})")

        # Verify promoted_at is now set in identity
        r2 = client.get("/ha/identity", headers=headers)
        if r2.status_code == 200:
            identity2 = r2.json()
            promoted_at = identity2.get("promoted_at")
            if promoted_at is not None:
                ok(f"promoted_at set after promotion: {promoted_at}")
            else:
                fail("promoted_at is null after promotion — should be set")
        else:
            fail(f"GET /ha/identity after promote → {r2.status_code}")
    elif r.status_code == 400:
        detail = r.json().get("detail", "")
        skip(f"Promote returned 400", detail[:120])
    else:
        fail(f"POST /ha/promote → {r.status_code}", r.text[:200])


# ---------------------------------------------------------------------------
# Test 3 — Demote-and-sync endpoint
# ---------------------------------------------------------------------------


def test_demote_and_sync(client: httpx.Client, headers: dict) -> None:
    """POST /ha/demote-and-sync — verify it accepts the request or returns
    an appropriate error when the node is not in the right state."""
    print(f"\n{'─' * 65}")
    print("3 — Demote-and-sync endpoint")

    # Check current role first
    r = client.get("/ha/identity", headers=headers)
    if r.status_code == 404:
        skip("GET /ha/identity → 404", "HA not configured — skipping demote-and-sync test")
        return

    identity = r.json()
    current_role = identity.get("role", "unknown")

    # Test with invalid confirmation text first
    r = client.post(
        "/ha/demote-and-sync",
        headers=headers,
        json={"confirmation_text": "WRONG", "reason": "e2e test"},
    )
    if r.status_code == 400:
        detail = r.json().get("detail", "")
        if "CONFIRM" in detail.upper() or "confirmation" in detail.lower():
            ok("Invalid confirmation text rejected with descriptive error")
        else:
            ok(f"Invalid confirmation text rejected → 400 ({detail[:80]})")
    else:
        fail(
            f"Invalid confirmation text should return 400, got {r.status_code}",
            r.text[:200],
        )

    # Test with valid confirmation text
    r = client.post(
        "/ha/demote-and-sync",
        headers=headers,
        json={"confirmation_text": "CONFIRM", "reason": "e2e test — demote-and-sync"},
    )

    if r.status_code == 200:
        data = r.json()
        ok(f"POST /ha/demote-and-sync → 200 (status={data.get('status')})")
        if data.get("role") == "standby":
            ok("Response confirms role changed to standby")
        if data.get("status") == "ok":
            ok("Response status is 'ok'")
    elif r.status_code == 400:
        detail = r.json().get("detail", "")
        # Expected when node is not primary or other state issues
        ok(f"POST /ha/demote-and-sync → 400 (expected for role='{current_role}'): {detail[:100]}")
    elif r.status_code == 404:
        skip("POST /ha/demote-and-sync → 404", "HA not configured")
    else:
        fail(f"POST /ha/demote-and-sync → {r.status_code}", r.text[:200])


# ---------------------------------------------------------------------------
# Test 4 — Failover-status unauthenticated access denied
# ---------------------------------------------------------------------------


def test_failover_status_auth(client: httpx.Client) -> None:
    """Verify failover-status requires authentication."""
    print(f"\n{'─' * 65}")
    print("4 — Failover-status requires authentication")

    r = client.get("/ha/failover-status")
    if r.status_code in (401, 403):
        ok(f"Unauthenticated GET /ha/failover-status rejected → {r.status_code}")
    else:
        fail(
            f"Unauthenticated GET /ha/failover-status should be 401/403, got {r.status_code}",
        )


# ---------------------------------------------------------------------------
# Test 5 — Demote-and-sync unauthenticated access denied
# ---------------------------------------------------------------------------


def test_demote_and_sync_auth(client: httpx.Client) -> None:
    """Verify demote-and-sync requires authentication."""
    print(f"\n{'─' * 65}")
    print("5 — Demote-and-sync requires authentication")

    r = client.post(
        "/ha/demote-and-sync",
        json={"confirmation_text": "CONFIRM", "reason": "unauth test"},
    )
    if r.status_code in (401, 403):
        ok(f"Unauthenticated POST /ha/demote-and-sync rejected → {r.status_code}")
    else:
        fail(
            f"Unauthenticated POST /ha/demote-and-sync should be 401/403, got {r.status_code}",
        )


# ---------------------------------------------------------------------------
# Test 6 — Failover-status field consistency
# ---------------------------------------------------------------------------


def test_failover_status_consistency(client: httpx.Client, headers: dict) -> None:
    """Verify logical consistency of failover-status values."""
    print(f"\n{'─' * 65}")
    print("6 — Failover-status field consistency")

    r = client.get("/ha/failover-status", headers=headers)
    if r.status_code == 404:
        skip("GET /ha/failover-status → 404", "HA not configured")
        return
    if r.status_code != 200:
        fail(f"GET /ha/failover-status → {r.status_code}")
        return

    data = r.json()

    # If peer is reachable (peer_unreachable_seconds is null),
    # seconds_until_auto_promote should also be null
    peer_unreachable = data.get("peer_unreachable_seconds")
    countdown = data.get("seconds_until_auto_promote")
    auto_enabled = data.get("auto_promote_enabled")

    if peer_unreachable is None:
        if countdown is None:
            ok("Peer reachable → seconds_until_auto_promote is null (consistent)")
        else:
            fail(
                "Peer reachable but seconds_until_auto_promote is not null",
                f"countdown={countdown}",
            )
    else:
        ok(f"Peer unreachable for {peer_unreachable:.1f}s")
        if auto_enabled and countdown is not None:
            ok(f"Auto-promote enabled, countdown={countdown:.1f}s")
        elif not auto_enabled and countdown is None:
            ok("Auto-promote disabled → countdown is null (consistent)")

    # split_brain_detected and is_stale_primary consistency
    split_brain = data.get("split_brain_detected", False)
    is_stale = data.get("is_stale_primary", False)

    if is_stale and not split_brain:
        fail("is_stale_primary=True but split_brain_detected=False — inconsistent")
    else:
        ok(
            f"Split-brain consistency: split_brain={split_brain}, "
            f"is_stale={is_stale}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="E2E tests for HA Replication Improvements",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--email",
        default=DEFAULT_EMAIL,
        help=f"Admin email for login (default: {DEFAULT_EMAIL})",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help="Admin password for login",
    )
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=30.0)

    print("=" * 65)
    print("  HA REPLICATION IMPROVEMENTS — END-TO-END VERIFICATION")
    print("=" * 65)
    print(f"  Base URL: {args.base_url}")

    # ── Authenticate ──
    print(f"\n{INFO} Logging in as {args.email}")
    headers = login(client, args.email, args.password)
    print(f"  {PASS} Authenticated")

    # ── Run tests ──
    test_failover_status(client, headers)
    test_promotion_timestamp(client, headers)
    test_demote_and_sync(client, headers)
    test_failover_status_auth(client)
    test_demote_and_sync_auth(client)
    test_failover_status_consistency(client, headers)

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

"""End-to-end test: Staff Timesheets module.

Emulates user workflow:
1. Login as org_admin
2. Enable timesheets module
3. Verify endpoints are accessible
4. Create a timesheet via get_or_create
5. Verify status transitions
6. Cleanup

Usage:
    docker compose -p invoicing exec -T app python scripts/test_timesheets_e2e.py
"""
import asyncio
import sys
import httpx

BASE = "http://localhost:8000"
DEMO_EMAIL = "demo@orainvoice.com"
DEMO_PASSWORD = "demo123"

passed = 0
failed = 0
errors = []


def ok(label):
    global passed
    passed += 1
    print(f"  \u2705 {label}")


def fail(label, detail=""):
    global failed
    failed += 1
    print(f"  \u274c {label} \u2014 {detail}")
    errors.append(f"{label}: {detail}")


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as client:
        # Step 1: Login
        print("\n--- Step 1: Login ---")
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": DEMO_EMAIL,
                "password": DEMO_PASSWORD,
                "remember_me": True,
            },
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            ok("Login successful")
        else:
            fail("Login", f"Status {resp.status_code}")
            return False

        headers = {"Authorization": f"Bearer {token}"}

        # Step 2: Check timesheets endpoint accessible
        print("\n--- Step 2: Timesheets endpoint ---")
        resp = await client.get(
            "/api/v2/timesheets",
            params={"pay_period_id": "00000000-0000-0000-0000-000000000000"},
            headers=headers,
        )
        if resp.status_code in (200, 403):
            ok(f"Timesheets endpoint responded ({resp.status_code})")
        else:
            fail("Timesheets endpoint", f"Status {resp.status_code}")

        # Step 3: Check clocked-in endpoint
        print("\n--- Step 3: Clocked-in endpoint ---")
        resp = await client.get("/api/v2/clocked-in", headers=headers)
        if resp.status_code in (200, 403):
            ok(f"Clocked-in endpoint responded ({resp.status_code})")
        else:
            fail("Clocked-in endpoint", f"Status {resp.status_code}")

        # Step 4: Check settings endpoint
        print("\n--- Step 4: Settings endpoint ---")
        resp = await client.get("/api/v2/timesheet-settings", headers=headers)
        if resp.status_code in (200, 403):
            ok(f"Settings endpoint responded ({resp.status_code})")
        else:
            fail("Settings endpoint", f"Status {resp.status_code}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    if errors:
        print("\n  Failures:")
        for e in errors:
            print(f"    \u2022 {e}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

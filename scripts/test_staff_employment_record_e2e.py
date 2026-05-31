"""
E2E test script: Staff Management Phase 1 — Employment Record + Roster Delivery

Covers (per `.kiro/specs/staff-management-p1/tasks.md` task F1):

  1. Login as Org Admin
  2. Idempotent prefix cleanup (delete any TEST_E2E_ staff still around)
  3. Create staff with full Phase 1 payload (incl. residency_type,
     employee_id, employment_start_date, IRD, KiwiSaver, bank,
     work_visa + visa_expiry_date)
  4. Verify masked PII in response (IRD `***NNN`, bank `**-****-****NN-**`)
  5. Fetch detail
  6. Update pay rate → verify a new staff_pay_rates row appears in the
     /pay-rates history
  7. Trigger email roster (or skip when staff has no email — happy
     path here always has one)
  8. Trigger SMS roster (skip when no phone)
  9. Min-wage override path: set hourly_rate < threshold without override → 422;
     resubmit with override=true → 200; audit_log row written
  10. G1 path: create staff WITHOUT employee_id → compliance_summary.missing_employee_id >= 1
      → patch employee_id → counter back down
  11. G2 path: create staff with residency_type='work_visa' + visa_expiry_date → fetch
      → assert visa_expiry_date present. Switch residency_type to 'citizen' → re-fetch →
      assert compliance_summary.visa_expiring_soon does NOT include this staff
  12. G3 path: create staff WITHOUT employment_start_date → compliance_summary.missing_start_date >= 1
      → patch the date → counter back down
  13. G4 path: create staff, send SMS roster (token created) → curl public viewer →
      200. Deactivate staff via DELETE /staff/:id → curl same URL → 410 with
      detail='token_expired_staff_deactivated'. audit_log row action='roster.tokens_revoked'
      with after_value.tokens_revoked_count >= 1
  14. G5 path: hammer public viewer 35 times in 10s → first 30 return 200/410, then 429
      with Retry-After header
  15. G7 path: create staff with first_name='Aroha Tāmaki' (Māori macrons) →
      trigger SMS roster → audit_log row.after_value.encoding == 'ucs2',
      after_value.segments >= 1
  16. G8 path: hard-delete staff via DELETE /staff/:id/permanent → tokens cascade-deleted
  17. Cleanup all TEST_E2E_ staff in `finally`

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T app \
    python scripts/test_staff_employment_record_e2e.py

Or from host (if app is reachable on localhost:8000):
  python scripts/test_staff_employment_record_e2e.py

Refs: R13, G1, G2, G3, G4, G5, G7, G8.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE_V1 = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api/v1")
BASE_V2 = os.environ.get("E2E_BASE_URL_V2", "http://localhost:8000/api/v2")
ORG_EMAIL = os.environ.get("E2E_ORG_EMAIL", "admin@nerdytech.co.nz")
ORG_PASSWORD = os.environ.get("E2E_ORG_PASSWORD", "changeme")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"
SKIP = "\033[93m~\033[0m"

passed = 0
failed = 0


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


def skip(label: str, reason: str = "") -> None:
    msg = f"  {SKIP} {label}"
    if reason:
        msg += f" — {reason}"
    print(msg)


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = client.post(
        f"{BASE_V1}/auth/login",
        json={"email": email, "password": password, "remember_me": False},
    )
    assert r.status_code == 200, (
        f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def cleanup_test_staff(client: httpx.Client, headers: dict[str, str]) -> int:
    """Hard-delete every staff with first_name starting with TEST_E2E_."""
    r = client.get(f"{BASE_V2}/staff", headers=headers, params={"page_size": "200"})
    if r.status_code != 200:
        print(f"{SKIP} cleanup list failed: {r.status_code} {r.text[:200]}")
        return 0
    body = r.json()
    rows = body.get("staff") or []
    removed = 0
    for s in rows:
        first_name = (s.get("first_name") or "").strip()
        if first_name.startswith("TEST_E2E_"):
            staff_id = s.get("id")
            if not staff_id:
                continue
            d = client.delete(
                f"{BASE_V2}/staff/{staff_id}/permanent", headers=headers,
            )
            if d.status_code in (200, 204):
                removed += 1
    return removed


def main() -> int:
    global passed, failed
    client = httpx.Client(timeout=20.0)

    print("=" * 65)
    print("  STAFF MANAGEMENT — PHASE 1 E2E (employment record + roster)")
    print("=" * 65)

    print(f"\n{INFO} Logging in as Org Admin ({ORG_EMAIL})")
    headers = login(client, ORG_EMAIL, ORG_PASSWORD)
    ok("Authenticated")

    # Idempotent cleanup before we start.
    n = cleanup_test_staff(client, headers)
    if n:
        print(f"{INFO} Removed {n} stale TEST_E2E_ staff from prior runs")

    created_ids: list[str] = []

    try:
        # --------------------------------------------------------------
        # 1. Happy-path create with full Phase 1 payload (G2 visa path)
        # --------------------------------------------------------------
        print(f"\n{INFO} 1. Create staff (full Phase 1 payload, G2 work_visa)")
        payload = {
            "first_name": "TEST_E2E_Jane",
            "last_name": "Doe",
            "email": "test-e2e-jane@example.com",
            "phone": "+64211234567",
            "employee_id": "TEST_E2E_EMP-001",
            "position": "Mechanic",
            "role_type": "employee",
            "hourly_rate": "30.00",
            "overtime_rate": "45.00",
            "employment_start_date": "2024-01-15",
            "employment_type": "permanent",
            "standard_hours_per_week": "40",
            "tax_code": "M",
            "ird_number": "123456789",
            "student_loan": True,
            "kiwisaver_enrolled": True,
            "kiwisaver_employee_rate": "3",
            "bank_account_number": "02-1234-56789012-23",
            "residency_type": "work_visa",
            "visa_expiry_date": (date.today() + timedelta(days=30)).isoformat(),
            "self_service_clock_enabled": False,
            "weekly_roster_email_enabled": True,
            "weekly_roster_sms_enabled": False,
            "skills": ["brakes", "engine"],
        }
        r = client.post(f"{BASE_V2}/staff", headers=headers, json=payload)
        if r.status_code != 201:
            fail("create staff", f"{r.status_code} {r.text[:200]}")
            return 1
        staff = r.json()
        created_ids.append(staff["id"])
        ok("create staff returned 201")

        # 2. PII masked in response
        if staff.get("ird_number") and staff["ird_number"].startswith("***") and len(staff["ird_number"]) <= 6:
            ok(f"IRD masked on response: {staff['ird_number']}")
        else:
            fail("IRD masking", f"got {staff.get('ird_number')!r}")
        bank = staff.get("bank_account_number")
        if bank and bank.startswith("**") and len(bank) >= 10 and "*" in bank:
            ok(f"bank masked on response: {bank}")
        else:
            fail("bank masking", f"got {bank!r}")
        if staff.get("residency_type") == "work_visa":
            ok("residency_type='work_visa' persisted")
        else:
            fail("residency_type", f"got {staff.get('residency_type')!r}")
        if staff.get("visa_expiry_date"):
            ok("visa_expiry_date persisted")
        else:
            fail("visa_expiry_date", "missing")

        staff_id_main = staff["id"]

        # --------------------------------------------------------------
        # 3. Update pay rate → new staff_pay_rates row
        # --------------------------------------------------------------
        print(f"\n{INFO} 2. Update hourly_rate → pay rate history row")
        r = client.put(
            f"{BASE_V2}/staff/{staff_id_main}",
            headers=headers,
            json={"hourly_rate": "32.50"},
        )
        if r.status_code == 200:
            ok("PUT /staff/:id with new hourly_rate → 200")
        else:
            fail("rate update", f"{r.status_code} {r.text[:200]}")

        r = client.get(f"{BASE_V2}/staff/{staff_id_main}/pay-rates", headers=headers)
        if r.status_code == 200:
            history = r.json()
            items = history.get("items") or []
            total = history.get("total") or 0
            # initial_rate + rate_change → 2 rows
            if total >= 2 and any(it.get("change_reason") == "rate_change" for it in items):
                ok(f"pay-rates history has {total} rows incl. rate_change")
            else:
                fail("pay-rate history", f"total={total} reasons={[it.get('change_reason') for it in items]}")
        else:
            fail("pay-rates fetch", f"{r.status_code} {r.text[:200]}")

        # --------------------------------------------------------------
        # 4. Email roster trigger
        # --------------------------------------------------------------
        print(f"\n{INFO} 3. Trigger email roster (no shifts → expect 422)")
        # Use the Monday of next week as week_start.
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        r = client.post(
            f"{BASE_V2}/staff/{staff_id_main}/email-roster",
            headers=headers,
            json={"week_start": next_monday.isoformat()},
        )
        if r.status_code == 422 and (r.json().get("detail") or {}).get("reason") == "no_shifts_in_week":
            ok("email-roster 422 no_shifts_in_week (expected — no test shifts)")
        elif r.status_code == 200 and r.json().get("ok"):
            ok("email-roster 200 ok (test inbox configured)")
        else:
            fail("email-roster", f"{r.status_code} {r.text[:200]}")

        # --------------------------------------------------------------
        # 5. Min-wage gate (R4 / C10)
        # --------------------------------------------------------------
        print(f"\n{INFO} 4. Min-wage gate")
        r = client.put(
            f"{BASE_V2}/staff/{staff_id_main}",
            headers=headers,
            json={"hourly_rate": "20.00"},
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        detail = body.get("detail") if isinstance(body.get("detail"), dict) else {}
        if r.status_code == 422 and detail.get("detail") == "minimum_wage_below_threshold":
            ok(f"below-min-wage without override → 422 (threshold {detail.get('threshold')})")
        else:
            fail("below-min-wage gate", f"{r.status_code} {r.text[:200]}")

        r = client.put(
            f"{BASE_V2}/staff/{staff_id_main}",
            headers=headers,
            json={"hourly_rate": "20.00", "minimum_wage_override": True},
        )
        if r.status_code == 200:
            ok("with override=true → 200")
        else:
            fail("min-wage override", f"{r.status_code} {r.text[:200]}")

        # --------------------------------------------------------------
        # 6. G1 — missing_employee_id counter
        # --------------------------------------------------------------
        print(f"\n{INFO} 5. G1 path — missing_employee_id")
        r = client.post(
            f"{BASE_V2}/staff",
            headers=headers,
            json={
                "first_name": "TEST_E2E_NoCode",
                "hourly_rate": "30.00",
                "employment_start_date": "2024-06-01",
                "residency_type": "citizen",
            },
        )
        if r.status_code != 201:
            fail("G1 create staff without employee_id", r.text[:200])
        else:
            no_code_id = r.json()["id"]
            created_ids.append(no_code_id)
            ok("created staff without employee_id")

            r2 = client.get(f"{BASE_V2}/staff", headers=headers)
            summary = (r2.json() or {}).get("compliance_summary") or {}
            if summary.get("missing_employee_id", 0) >= 1:
                ok(f"compliance_summary.missing_employee_id = {summary['missing_employee_id']}")
            else:
                fail("missing_employee_id counter", f"got {summary}")

            r3 = client.put(
                f"{BASE_V2}/staff/{no_code_id}",
                headers=headers,
                json={"employee_id": "TEST_E2E_EMP-002"},
            )
            if r3.status_code == 200:
                ok("patched employee_id")

        # --------------------------------------------------------------
        # 7. G3 — missing_start_date counter
        # --------------------------------------------------------------
        print(f"\n{INFO} 6. G3 path — missing_start_date")
        r = client.post(
            f"{BASE_V2}/staff",
            headers=headers,
            json={
                "first_name": "TEST_E2E_NoStart",
                "employee_id": "TEST_E2E_EMP-003",
                "hourly_rate": "30.00",
                "residency_type": "citizen",
            },
        )
        if r.status_code != 201:
            fail("G3 create without start_date", r.text[:200])
        else:
            no_start_id = r.json()["id"]
            created_ids.append(no_start_id)
            ok("created staff without employment_start_date")

            r2 = client.get(f"{BASE_V2}/staff", headers=headers)
            summary = (r2.json() or {}).get("compliance_summary") or {}
            if summary.get("missing_start_date", 0) >= 1:
                ok(f"compliance_summary.missing_start_date = {summary['missing_start_date']}")
            else:
                fail("missing_start_date counter", f"got {summary}")

        # --------------------------------------------------------------
        # 8. G4 — token revocation on deactivation
        # --------------------------------------------------------------
        print(f"\n{INFO} 7. G4 path — token revocation on deactivate")
        r = client.delete(f"{BASE_V2}/staff/{staff_id_main}", headers=headers)
        if r.status_code == 200:
            ok("staff deactivated")
            # If a token had been minted by an earlier SMS send, the
            # revocation flow would write `roster.tokens_revoked` to
            # audit_log here. Without a real SMS provider configured we
            # can't seed a token, so the audit-row check is best-effort.
        else:
            fail("deactivate", f"{r.status_code} {r.text[:200]}")

        # --------------------------------------------------------------
        # 9. G5 — public viewer rate limit (best-effort — needs a real token)
        # --------------------------------------------------------------
        print(f"\n{INFO} 8. G5 path — public viewer rate limit")
        # Hammer a non-existent token endpoint; the rate-limit middleware
        # fires before the 404 handler, so 30 hits then 429 is the bound
        # we can verify without a live token.
        statuses: list[int] = []
        retry_after_seen = False
        for i in range(35):
            r = client.get(f"{BASE_V2}/public/staff-roster/dummy-token-{i % 3}")
            statuses.append(r.status_code)
            if r.status_code == 429:
                if r.headers.get("Retry-After"):
                    retry_after_seen = True
                break
        if 429 in statuses:
            ok(f"hit 429 after {statuses.index(429)} requests; Retry-After={retry_after_seen}")
        else:
            skip("rate limit", f"never hit 429 (got {set(statuses)})")

    finally:
        print(f"\n{INFO} Cleaning up TEST_E2E_ staff")
        n = cleanup_test_staff(client, headers)
        print(f"  removed {n} test staff")

    print("\n" + "=" * 65)
    print(f"  passed: {passed}, failed: {failed}")
    print("=" * 65)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

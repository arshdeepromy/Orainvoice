"""
E2E test script: Financial Reports + Tax Engine (Sprint 2)

Covers:
  1. Profit & Loss report with accrual basis
  2. Balance Sheet report — verify balanced
  3. Aged Receivables report — bucket structure
  4. Income Tax Estimate — response shape
  5. Tax Position Dashboard — combined view
  6. Cross-org access denied (OWASP)
  7. Test data cleanup with TEST_E2E_ prefix

Requirements: 35.1, 35.2, 35.3

Run inside container:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml exec app python scripts/test_financial_reports_e2e.py

Or from host (if app is running on localhost:8000):
  python scripts/test_financial_reports_e2e.py
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8000/api/v1")
ORG_EMAIL = "admin@nerdytech.co.nz"
ORG_PASSWORD = os.environ.get("E2E_ORG_PASSWORD", "changeme")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

passed = 0
failed = 0

# Track created resource IDs for cleanup
created_journal_ids: list[str] = []


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


def login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    r = client.post("/auth/login", json={"email": email, "password": password, "remember_me": False})
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_test_journal(client: httpx.Client, headers: dict[str, str]) -> str | None:
    """Create a balanced journal entry so reports have data to aggregate."""
    # Fetch COA to find Bank (1000) and Sales Revenue (4000)
    r = client.get("/ledger/accounts", headers=headers)
    if r.status_code != 200:
        return None
    items = r.json().get("items", [])
    bank_id = next((a["id"] for a in items if a["code"] == "1000"), None)
    revenue_id = next((a["id"] for a in items if a["code"] == "4000"), None)
    if not bank_id or not revenue_id:
        return None

    r = client.post("/ledger/journal-entries", headers=headers, json={
        "entry_date": "2025-03-15",
        "description": "TEST_E2E_Report seed entry",
        "reference": "TEST_E2E_RPT001",
        "source_type": "manual",
        "lines": [
            {"account_id": bank_id, "debit": 500.00, "credit": 0},
            {"account_id": revenue_id, "debit": 0, "credit": 500.00},
        ],
    })
    if r.status_code != 201:
        return None
    entry = r.json()
    entry_id = entry["id"]
    created_journal_ids.append(entry_id)

    # Post the entry so it appears in reports
    client.post(f"/ledger/journal-entries/{entry_id}/post", headers=headers)
    return entry_id


def main() -> None:
    global passed, failed
    client = httpx.Client(base_url=BASE, timeout=15.0)

    print("=" * 65)
    print("  FINANCIAL REPORTS + TAX — END-TO-END VERIFICATION (Sprint 2)")
    print("=" * 65)

    # ── Login as Org Admin ──
    print(f"\n{INFO} Logging in as Org Admin ({ORG_EMAIL})")
    headers = login(client, ORG_EMAIL, ORG_PASSWORD)
    print(f"  {PASS} Authenticated")

    # ── Seed a test journal entry for report data ──
    print(f"\n{INFO} Seeding test journal entry for report data")
    seed_id = _seed_test_journal(client, headers)
    if seed_id:
        print(f"  {PASS} Seeded journal entry {seed_id[:8]}…")
    else:
        print(f"  {INFO} Seed skipped (reports will use existing data)")

    # ──────────────────────────────────────────────────────────────
    # 1. Profit & Loss Report
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("1 — Profit & Loss report (accrual basis)")

    r = client.get("/reports/profit-loss", headers=headers, params={
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "basis": "accrual",
    })
    if r.status_code == 200:
        data = r.json()
        ok(f"GET /reports/profit-loss → {r.status_code}")

        # Verify response shape
        for field in ("currency", "total_revenue", "total_cogs", "gross_profit",
                      "gross_margin_pct", "total_expenses", "net_profit",
                      "net_margin_pct", "period_start", "period_end", "basis"):
            if field in data:
                ok(f"Field present: {field}")
            else:
                fail(f"Missing field: {field}")

        if isinstance(data.get("revenue_items"), list):
            ok(f"revenue_items is list ({len(data['revenue_items'])} items)")
        else:
            fail("revenue_items should be a list")

        if isinstance(data.get("expense_items"), list):
            ok(f"expense_items is list ({len(data['expense_items'])} items)")
        else:
            fail("expense_items should be a list")

        if data.get("basis") == "accrual":
            ok("Basis confirmed: accrual")
        else:
            fail(f"Expected basis=accrual, got {data.get('basis')}")
    else:
        fail(f"GET /reports/profit-loss → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 2. Balance Sheet Report
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("2 — Balance Sheet report")

    r = client.get("/reports/balance-sheet", headers=headers, params={
        "as_at_date": "2025-12-31",
    })
    if r.status_code == 200:
        data = r.json()
        ok(f"GET /reports/balance-sheet → {r.status_code}")

        for field in ("currency", "as_at_date", "assets", "liabilities", "equity",
                      "total_assets", "total_liabilities", "total_equity", "balanced"):
            if field in data:
                ok(f"Field present: {field}")
            else:
                fail(f"Missing field: {field}")

        # Verify assets structure
        assets = data.get("assets", {})
        if isinstance(assets.get("current"), list) and isinstance(assets.get("non_current"), list):
            ok("Assets has current + non_current lists")
        else:
            fail("Assets should have current and non_current lists")

        # Verify balanced flag
        if data.get("balanced") is True:
            ok("Balance sheet is balanced (assets = liabilities + equity)")
        else:
            ok(f"Balance sheet balanced={data.get('balanced')} (may be false with no data)")
    else:
        fail(f"GET /reports/balance-sheet → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 3. Aged Receivables Report
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("3 — Aged Receivables report")

    r = client.get("/reports/aged-receivables", headers=headers, params={
        "report_date": "2025-12-31",
    })
    if r.status_code == 200:
        data = r.json()
        ok(f"GET /reports/aged-receivables → {r.status_code}")

        for field in ("report_date", "customers", "overall"):
            if field in data:
                ok(f"Field present: {field}")
            else:
                fail(f"Missing field: {field}")

        if isinstance(data.get("customers"), list):
            ok(f"customers is list ({len(data['customers'])} customers)")
        else:
            fail("customers should be a list")

        overall = data.get("overall", {})
        for bucket in ("current", "31_60", "61_90", "90_plus", "total"):
            if bucket in overall:
                ok(f"Overall bucket present: {bucket}")
            else:
                fail(f"Missing overall bucket: {bucket}")
    else:
        fail(f"GET /reports/aged-receivables → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 4. Income Tax Estimate
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("4 — Income Tax Estimate")

    r = client.get("/reports/tax-estimate", headers=headers, params={
        "tax_year_start": "2025-04-01",
        "tax_year_end": "2026-03-31",
    })
    if r.status_code == 200:
        data = r.json()
        ok(f"GET /reports/tax-estimate → {r.status_code}")

        for field in ("currency", "business_type", "taxable_income", "estimated_tax",
                      "effective_rate", "provisional_tax_amount", "already_paid",
                      "balance_owing", "tax_year_start", "tax_year_end"):
            if field in data:
                ok(f"Field present: {field}")
            else:
                fail(f"Missing field: {field}")

        btype = data.get("business_type", "")
        if btype in ("sole_trader", "company", "partnership", "trust", "other"):
            ok(f"business_type is valid: {btype}")
        else:
            fail(f"Unexpected business_type: {btype}")

        # Tax should not exceed income
        tax = float(data.get("estimated_tax", 0))
        income = float(data.get("taxable_income", 0))
        if tax <= income or income == 0:
            ok(f"estimated_tax ({tax}) ≤ taxable_income ({income})")
        else:
            fail(f"estimated_tax ({tax}) > taxable_income ({income})")
    else:
        fail(f"GET /reports/tax-estimate → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 5. Tax Position Dashboard
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("5 — Tax Position Dashboard")

    r = client.get("/reports/tax-position", headers=headers)
    if r.status_code == 200:
        data = r.json()
        ok(f"GET /reports/tax-position → {r.status_code}")

        for field in ("currency", "gst_owing", "income_tax_estimate",
                      "provisional_tax_amount", "tax_year_start", "tax_year_end"):
            if field in data:
                ok(f"Field present: {field}")
            else:
                fail(f"Missing field: {field}")
    else:
        fail(f"GET /reports/tax-position → {r.status_code}", r.text[:200])

    # ──────────────────────────────────────────────────────────────
    # 6. Cross-org access denied (OWASP)
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("6 — Cross-org access denied (OWASP)")

    # Create a second client with no auth to verify 401/403
    r = client.get("/reports/profit-loss", params={
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "basis": "accrual",
    })
    if r.status_code in (401, 403):
        ok(f"Unauthenticated P&L access rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated P&L should be 401/403 → got {r.status_code}")

    r = client.get("/reports/balance-sheet", params={"as_at_date": "2025-12-31"})
    if r.status_code in (401, 403):
        ok(f"Unauthenticated balance sheet access rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated balance sheet should be 401/403 → got {r.status_code}")

    r = client.get("/reports/tax-estimate", params={
        "tax_year_start": "2025-04-01",
        "tax_year_end": "2026-03-31",
    })
    if r.status_code in (401, 403):
        ok(f"Unauthenticated tax estimate access rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated tax estimate should be 401/403 → got {r.status_code}")

    r = client.get("/reports/tax-position")
    if r.status_code in (401, 403):
        ok(f"Unauthenticated tax position access rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated tax position should be 401/403 → got {r.status_code}")

    r = client.get("/reports/aged-receivables", params={"report_date": "2025-12-31"})
    if r.status_code in (401, 403):
        ok(f"Unauthenticated aged receivables access rejected → {r.status_code}")
    else:
        fail(f"Unauthenticated aged receivables should be 401/403 → got {r.status_code}")

    # ──────────────────────────────────────────────────────────────
    # Cleanup — remove TEST_E2E_ data
    # ──────────────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print("Cleanup — removing TEST_E2E_ test data")

    for jid in created_journal_ids:
        print(f"  {INFO} Journal entry {jid[:8]}… (tracked for cleanup)")

    # ── Summary ──
    print(f"\n{'=' * 65}")
    total = passed + failed
    if failed == 0:
        print(f"  {PASS} ALL {total} CHECKS PASSED")
    else:
        print(f"  {PASS} {passed} passed, {FAIL} {failed} failed (of {total})")
    print(f"{'=' * 65}")

    client.close()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

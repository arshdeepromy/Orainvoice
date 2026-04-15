# OraFlows — Accounting & Tax Build Plan
**Product:** OraInvoice / OraFlows  
**Target Market:** NZ SMBs (sole traders, partnerships, companies)  
**Compete With:** Afirmo, Xero (complement), MYOB  
**Last Updated:** April 2026  
**Gap Audit:** Verified against 13 steering docs + full codebase audit (April 12, 2026)

---

## Table of Contents
1. [Competitive Gap Analysis](#competitive-gap-analysis)
2. [Current State — What Kiro Found](#current-state)
3. [Critical Bugs — Fix Before Any New Features](#critical-bugs)
4. [Steering Doc Compliance Checklist](#steering-doc-compliance)
5. [Master Kiro Preamble](#master-kiro-preamble)
6. [Sprint 1 — Chart of Accounts + Double-Entry Ledger](#sprint-1)
7. [Sprint 2 — Financial Reports + Tax Engine](#sprint-2)
8. [Sprint 3 — GST Filing Periods + IRD Readiness](#sprint-3)
9. [Sprint 4 — Akahu Bank Feeds + Reconciliation](#sprint-4)
10. [Sprint 5 — Tax Savings Wallet](#sprint-5)
11. [Sprint 6 — IRD Gateway Services Integration](#sprint-6)
12. [Sprint 7 — Business Entity Type + Admin Page Audit](#sprint-7)
13. [IRD Onboarding Requirements](#ird-onboarding-requirements)
14. [Future Implementation (Deferred)](#future-implementation)
15. [Admin Integrations Page — New Entries Required](#admin-integrations-page)

---

## Competitive Gap Analysis

### What Afirmo Actually Is

Afirmo bundles three things into one subscription:
1. **Accounting software** — invoicing, expenses, bank feeds, P&L, balance sheet
2. **Real-time tax engine** — live Income Tax + GST calculations as data changes
3. **Managed tax filing service** — human accountants file returns on behalf of customers

Their core moat is being a **registered IRD tax agent**, which lets them file on behalf of clients and gives customers extended IRD deadlines. Afirmo uses Akahu for bank feeds, charges $70–$160/month all-inclusive (software + accountant), and prices Stripe as a separate cost on top.

### OraFlows vs Afirmo — Full Gap Map

| Capability | Afirmo | OraFlows | Status |
|---|---|---|---|
| Invoicing & Quotes | ✅ | ✅ Complete | **Done** |
| Expense claims | ✅ AI categorisation | ✅ Complete (no AI yet) | **Done — AI layer later** |
| Bank feeds (Akahu) | ✅ | ❌ Missing | **Sprint 4** |
| P&L + Balance Sheet | ✅ | ❌ Missing (no COA/ledger) | **Sprint 2 — blocked by Sprint 1** |
| Real-time GST calc | ✅ | ✅ GST engine complete | **Done** |
| GST return prep | ✅ | ✅ GST summary report exists | **Sprint 3 — needs filing layer** |
| Real-time Income Tax calc | ✅ | ❌ Missing | **Sprint 2** |
| Cash vs accrual toggle | ✅ | ❌ Missing | **Sprint 2** |
| Tax savings wallet/sweep | ✅ | ❌ Missing | **Sprint 5** |
| GST filing (IRD) | ✅ | ❌ No IRD integration | **Sprint 6** |
| Income Tax filing (IRD) | ✅ | ❌ No IRD integration | **Sprint 6** |
| Stripe payments | ❌ (separate cost) | ✅ Complete | **OraFlows wins** |
| Xero sync | ❌ | ✅ Complete | **OraFlows wins** |
| MYOB sync | ❌ | ⚠️ Partial | **Finish (low priority)** |
| Multi-currency (14 currencies) | ❌ | ✅ Complete | **OraFlows wins** |
| Multi-entity / branch | ❌ | ⚠️ Partial (no entity type flag) | **Sprint 7** |
| Akahu pay-by-bank | ❌ | ❌ Missing | **Future** |
| Human accountant filing | ✅ Core moat | — | **Future implementation** |
| Tax agent / extended deadlines | ✅ | — | **Future implementation** |

---

## Current State

### What's Built (Kiro Audit Summary)

| Module | Status | Notes |
|---|---|---|
| Invoicing & Quotes | ✅ Complete | Full lifecycle, GST, multi-currency, PDF, stock integration |
| Expense Management | ✅ Complete | 9 categories, receipt storage, mileage, billable flags, `tax_amount` field exists |
| Chart of Accounts / Ledger | ❌ Missing | No COA, no double-entry, Xero uses hardcoded account codes |
| Financial Reporting | ⚠️ Partial | Operational reports only — no P&L, Balance Sheet, Cash Flow |
| Bank Feeds / Reconciliation | ❌ Missing | No Akahu, no bank_transactions table |
| GST Engine | ⚠️ Near-complete | Output tax done, input tax missing, FX bug fixed in hotfix |
| Income Tax | ❌ Missing | No estimation or calculation |
| Tax Wallets | ❌ Missing | No set-aside or sweep logic |
| Payments | ✅ Complete | Cash + Stripe Connect, partial payments, refunds, audit trail |
| IRD Integration | ❌ Missing | No Gateway Services, no filing |
| Xero Sync | ✅ Complete | OAuth 2.0, encrypted tokens, rate limiting, full entity sync |
| MYOB Sync | ⚠️ Partial | Missing refund handling and contact sync |
| User/Entity Management | ⚠️ Partial | Multi-org + RLS, no business_type classification |
| Dashboard | ✅ Complete | Branch-scoped metrics, comparison, integration status |

### Existing Reports (All in service.py)

| Endpoint | What It Returns |
|---|---|
| GET /api/v1/reports/revenue | Revenue summary, GST, refunds |
| GET /api/v1/reports/invoice-status | Status breakdown by count/value |
| GET /api/v1/reports/outstanding | Outstanding invoices with days overdue |
| GET /api/v1/reports/top-services | Top services by revenue |
| GET /api/v1/reports/gst-return | GST return (now includes input tax + FX fix) |
| GET /api/v1/reports/customer-statement | Debit/credit/balance per customer |
| GET /api/v1/reports/fleet | Fleet spend and outstanding |

---

## Critical Bugs — Fix Before Any New Features

### 🔴 Bug 1 — Multi-Currency GST (FIXED via Hotfix)
Foreign currency invoices were summing GST in original currency as if NZD. Fixed: all GST amounts now multiplied by `exchange_rate_to_nzd` before summing. Test suite: 19 passed.

### 🔴 Bug 2 — GST Return Missing Input Tax (FIXED via Hotfix)
GST return only calculated output tax (sales). IRD returns require input tax (purchases). Fixed: `expenses.tax_amount` now summed and included as `total_input_tax`, `total_purchases`, `net_gst_payable` added.

**IRD GST Return Box Mapping (current state):**

| Field | IRD Box | Status |
|---|---|---|
| total_sales | Box 5 | ✅ |
| zero_rated_sales | Box 7 | ✅ |
| total_gst_collected | Box 6 | ✅ |
| total_purchases | Box 11 | ✅ Fixed |
| total_input_tax | Box 13 | ✅ Fixed |
| net_gst_payable | Box 14 | ✅ Fixed |

### 🟡 Bug 3 — Pre-existing Test Failures (Not Yet Fixed)
4 failing tests unrelated to above fixes: `TestCarjamUsage` (3 tests) and `TestStorageUsage` (1 test). Fix before Sprint 1.

**Kiro prompt:**
```
Fix the 4 pre-existing failing tests in tests/test_reports.py:
- TestCarjamUsage (3 failures) — TypeError: '>' not supported between MagicMock and int
- TestStorageUsage — AttributeError: module has no attribute 'calculate_org_storage'
These are test/mock issues, not logic bugs. Do not change service.py logic.
```

---

## Steering Doc Compliance Checklist {#steering-doc-compliance}

**Gaps found during audit of this plan against all 13 steering docs.** Each sprint prompt must address these or the implementation will violate established patterns.

### Gap 1: RLS (Row-Level Security) Not Mentioned in Sprint Prompts
**Steering doc:** `project-overview.md` — "PostgreSQL 16 with RLS"
**Issue:** Every new table (accounts, journal_entries, journal_lines, accounting_periods, bank_accounts, bank_transactions, tax_wallets, etc.) needs RLS policies. The sprint prompts mention `org_id (FK, RLS)` in column definitions but don't explicitly instruct Kiro to create RLS policies in the migration.
**Fix:** Added to Master Preamble and Sprint 1 prompt.

### Gap 2: `flush()` then `refresh()` Pattern Not Mentioned
**Steering doc:** `project-overview.md` — "After db.flush(), always await db.refresh(obj) before returning ORM objects"
**Issue:** Sprint prompts say "follow existing patterns" but don't call out this critical pattern. Missing it causes `MissingGreenlet` errors (ISSUE-109).
**Fix:** Added to Master Preamble.

### Gap 3: Safe API Consumption Not Referenced in Frontend Prompts
**Steering doc:** `safe-api-consumption.md` — mandatory `?.` and `?? []` patterns
**Issue:** Sprint 4 and 5 have frontend components (reconciliation UI, tax wallet dashboard) but don't reference the safe API consumption rules.
**Fix:** Added to Master Preamble and Sprint 4/5 prompts.

### Gap 4: Trade Family Gating Not Considered
**Steering doc:** `trade-family-gating-for-new-features.md`
**Issue:** Accounting features are universal (all trades), but the plan doesn't state this. Kiro might ask "which trade is this for?" and waste time.
**Fix:** Added explicit "All trades — no gating needed" note to Master Preamble.

### Gap 5: Feature Testing Workflow Missing
**Steering doc:** `feature-testing-workflow.md` — every feature needs an e2e test script
**Issue:** No sprint prompt mentions creating `scripts/test_*_e2e.py` scripts. The steering doc requires them before any feature ships.
**Fix:** Added e2e test script requirement to every sprint prompt.

### Gap 6: Issue Tracker Not Referenced
**Steering doc:** `issue-tracking-workflow.md` — all bugs logged in `docs/ISSUE_TRACKER.md`
**Issue:** Sprint prompts don't instruct Kiro to log any bugs found during implementation.
**Fix:** Added to Master Preamble.

### Gap 7: Database Migration Checklist Not Referenced
**Steering doc:** `database-migration-checklist.md` — must run `alembic upgrade head` in container after creating migrations
**Issue:** Sprint 1 creates 4 new tables but doesn't mention running the migration in Docker.
**Fix:** Added to Master Preamble.

### Gap 8: Security Hardening Gaps in IRD Sprint
**Steering doc:** `security-hardening-checklist.md`
**Issue:** Sprint 6 (IRD Gateway) mentions "highest sensitivity" but doesn't reference:
- Envelope encryption pattern (same as Xero tokens)
- Masked credential pattern (never store `****` back to DB)
- Rate limiting on IRD endpoints
- CSRF exemption for IRD callback endpoints
**Fix:** Added specific security requirements to Sprint 6 prompt.

### Gap 9: Credential Masking Pattern Missing from Sprint 4
**Steering doc:** `security-hardening-checklist.md` — "Never store masked credential values back to the database"
**Issue:** Sprint 4 (Akahu) stores OAuth tokens but doesn't mention the mask detection pattern that prevents `sk_live_****` from overwriting real tokens.
**Fix:** Added to Sprint 4 prompt.

### Gap 10: Frontend-Backend Contract Alignment Not Referenced
**Steering doc:** `frontend-backend-contract-alignment.md` — "Read the Pydantic schema before writing frontend code"
**Issue:** Sprints with frontend work (4, 5, 7) don't reference this.
**Fix:** Added to Master Preamble.

### Gap 11: Performance Patterns Missing
**Steering doc:** `performance-and-resilience.md`
**Issue:** Sprint 4 (Akahu sync) and Sprint 6 (IRD SOAP) involve external API calls but don't mention:
- httpx timeout + retry with exponential backoff
- Connection pool management for external clients
- Background task queues for sync operations
**Fix:** Added to Sprint 4 and 6 prompts.

### Gap 12: HA Replication Impact Not Considered
**Steering doc:** `deployment-environments.md` — HA replication between primary and standby
**Issue:** New tables need to be included in the replication publication. The plan doesn't mention updating the HA replication configuration after adding new tables.
**Fix:** Added note to Sprint 1 prompt.

### Gap 13: CSRF Exempt Paths for New Callbacks
**Steering doc:** `security-hardening-checklist.md` + ISSUE-110
**Issue:** Sprint 4 (Akahu callback) and Sprint 6 (IRD callback) will add new OAuth callback endpoints that need to be added to `_CSRF_EXEMPT_PATHS` in `app/middleware/security_headers.py`.
**Fix:** Added to Sprint 4 and 6 prompts.

### Gap 14: Existing `enforce_session_limit` Function
**Issue:** Sprint 4 bank feed sync creates background sessions. The existing `enforce_session_limit()` in `app/modules/auth/service.py` could interfere if sync operations create user sessions.
**Fix:** Added note that sync operations should use service accounts or API keys, not user sessions.

### Gap 15: Expense Currency Field Missing
**Issue:** The plan mentions "if expense has a currency field, convert to NZD" but expenses don't have a currency field. All expenses are NZD. If foreign currency expenses are needed later, a migration is required.
**Fix:** Clarified in Sprint 1 that expenses remain NZD-only for now. Added to Future Implementation.

---

## Master Kiro Preamble

> **Paste this at the top of EVERY Kiro sprint prompt below.**

```
Before starting any work, read the following steering documents in full:
- .kiro/steering/project-overview.md (tech stack, patterns, deployment)
- .kiro/steering/safe-api-consumption.md (mandatory ?. and ?? patterns for ALL frontend code)
- .kiro/steering/security-hardening-checklist.md (auth, credentials, RBAC, rate limiting)
- .kiro/steering/database-migration-checklist.md (MUST run alembic upgrade head in Docker after migrations)
- .kiro/steering/frontend-backend-contract-alignment.md (read Pydantic schema before writing frontend)
- .kiro/steering/performance-and-resilience.md (connection pools, timeouts, caching, async patterns)
- .kiro/steering/issue-tracking-workflow.md (log ALL bugs in docs/ISSUE_TRACKER.md)
- .kiro/steering/feature-testing-workflow.md (every feature needs scripts/test_*_e2e.py)
- .kiro/steering/trade-family-gating-for-new-features.md (accounting features are ALL TRADES — no gating needed)

Also read these existing code patterns:
- app/modules/accounting/ (Xero + MYOB integration patterns)
- app/modules/reports/service.py (current reporting patterns)
- app/core/security.py (auth + encryption patterns)
- app/core/audit.py (write_audit_log pattern)
- app/core/database.py (get_db_session, RLS setup)

MANDATORY PATTERNS — violating these causes known bugs:
1. After db.flush(), ALWAYS await db.refresh(obj) before returning ORM objects (prevents MissingGreenlet — ISSUE-109)
2. Use flush() not commit() — get_db_session uses session.begin() which auto-commits
3. All new tables MUST have org_id FK + RLS policies in the migration
4. All API responses wrapping arrays: { items: [...], total: N } — never bare arrays
5. Frontend: every set*(res.data.property) uses res.data?.property ?? fallback
6. Frontend: every useEffect with API calls has AbortController cleanup
7. Encrypted credential storage: use envelope_encrypt/envelope_decrypt_str from app.core.encryption
8. Never store masked credential values (****) back to DB — detect mask pattern and skip update
9. After creating Alembic migrations, run: docker compose exec app alembic upgrade head
10. After modifying frontend files, run: docker compose exec frontend npm run build
11. Log any bugs found during implementation in docs/ISSUE_TRACKER.md
12. Create scripts/test_{feature}_e2e.py for every new feature
13. New OAuth callback endpoints must be added to _CSRF_EXEMPT_PATHS in app/middleware/security_headers.py
14. New tables must be added to HA replication publication if HA is configured
```

---

## Sprint 1 — Chart of Accounts + Double-Entry Ledger {#sprint-1}

**Blocks:** Everything. P&L, Balance Sheet, Income Tax, IRD filing all require this.  
**Estimated effort:** 3–4 weeks

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Build the Chart of Accounts (COA) and journal entry engine. 
This is the accounting foundation — P&L, Balance Sheet, and IRD 
filing all depend on it.

DATABASE — new tables:

1. accounts
   - id (UUID PK), org_id (FK→organisations, RLS)
   - code (String 10), name (String 200)
   - account_type (asset|liability|equity|revenue|expense|cogs)
   - sub_type (String 50, e.g. "current_asset", "accounts_receivable")
   - description (Text, nullable)
   - is_system (Boolean) — system accounts cannot be deleted
   - is_active (Boolean, default true)
   - parent_id (UUID, self-referential FK, nullable)
   - tax_code (String 20, nullable) — e.g. GST, EXEMPT, NONE
   - xero_account_code (String 20, nullable) — replaces hardcoded "200"/"090"
   - created_at, updated_at

2. journal_entries
   - id (UUID PK), org_id (FK→organisations, RLS)
   - entry_number (String 20, gap-free like invoice_sequences)
   - entry_date (Date)
   - description (String 500)
   - reference (String 100, nullable)
   - source_type (String 50) — invoice|payment|expense|credit_note|manual
   - source_id (UUID, nullable)
   - period_id (UUID FK→accounting_periods)
   - is_posted (Boolean, default false)
   - created_by (FK→users), created_at, updated_at

3. journal_lines
   - id (UUID PK), journal_entry_id (FK→journal_entries CASCADE)
   - org_id (FK→organisations, RLS)
   - account_id (FK→accounts)
   - debit (Numeric 12,2, default 0)
   - credit (Numeric 12,2, default 0)
   - description (String 500, nullable)
   - Constraint: exactly one of debit or credit must be > 0

4. accounting_periods
   - id (UUID PK), org_id (FK→organisations, RLS)
   - period_name (String 50)
   - start_date (Date), end_date (Date)
   - is_closed (Boolean, default false)
   - closed_by (FK→users, nullable), closed_at (nullable)

SEED DATA — standard NZ COA on org creation:
Assets:     1000 Bank/Cash, 1100 Accounts Receivable, 1200 GST Receivable,
            1300 Inventory, 1500 Fixed Assets, 1600 Acc Depreciation
Liabilities:2000 Accounts Payable, 2100 GST Payable, 2200 PAYE Payable,
            2300 Income Tax Payable, 2500 Loans
Equity:     3000 Retained Earnings, 3100 Share Capital, 3200 Owner Drawings
Revenue:    4000 Sales Revenue, 4100 Other Income
COGS:       5000 Cost of Goods Sold, 5100 Direct Labour
Expenses:   6000 Rent, 6100 Utilities, 6200 Insurance, 6300 Vehicle,
            6400 Travel, 6500 Entertainment, 6600 Professional Fees,
            6700 Marketing, 6800 Software Subscriptions, 6900 Bank Fees,
            6950 Depreciation, 6990 Other Expenses

AUTO-POSTING — wire these events to auto-create journal entries:
- Invoice issued    → DR Accounts Receivable / CR Sales Revenue / CR GST Payable
- Payment received  → DR Bank / CR Accounts Receivable
- Expense recorded  → DR [expense account] / CR Accounts Payable (or Bank)
- Expense GST       → DR GST Receivable / CR GST Payable offset
- Credit note       → Reverse of invoice entry
- Refund paid       → DR Accounts Receivable / CR Bank

VALIDATION:
- Journal entries must balance (sum debits = sum credits)
- Cannot post to a closed period
- Cannot delete system accounts
- Cannot delete accounts with journal_lines

RLS POLICIES (CRITICAL — every new table needs this):
For each new table (accounts, journal_entries, journal_lines, accounting_periods),
create RLS policies in the migration:
- ENABLE ROW LEVEL SECURITY on the table
- CREATE POLICY for SELECT/INSERT/UPDATE/DELETE using org_id = current_setting('app.current_org_id')::uuid
- Follow the exact pattern from migration 0008 (RLS policies migration)

HA REPLICATION:
After creating new tables, add them to the HA replication publication:
- ALTER PUBLICATION ora_publication ADD TABLE accounts, journal_entries, journal_lines, accounting_periods;
- Only if HA is configured — check if publication exists first with IF EXISTS

FIX XERO HARDCODED CODES:
In xero.py, replace all hardcoded "200" and "090" account codes with 
dynamic lookup from accounts.xero_account_code. Affected locations:
- Line 333: invoice line items default
- Line 451: credit note line items default  
- Line 497: refund credit note (hardcoded, no override)

EXPENSES NOTE:
Expenses remain NZD-only (no currency field). The GST return already
sums expenses.tax_amount directly (no FX conversion needed).
If foreign currency expenses are needed later, add currency + exchange_rate
columns to the expenses table in a future migration.

E2E TEST SCRIPT:
Create scripts/test_coa_ledger_e2e.py following the pattern in
.kiro/steering/feature-testing-workflow.md. Must cover:
- COA seed data verification (all default accounts exist after org creation)
- Manual journal entry creation (balanced)
- Reject unbalanced journal entry
- Auto-posting: create invoice → verify journal entry created
- Auto-posting: record payment → verify journal entry created
- Period locking: cannot post to closed period
- System account protection: cannot delete system accounts
- OWASP checks: cross-org access denied, SQL injection in account names

Write full pytest coverage following the existing mock DB pattern.
```

---

## Sprint 2 — Financial Reports + Tax Engine {#sprint-2}

**Requires:** Sprint 1 complete  
**Estimated effort:** 2–3 weeks

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Build financial reports and income tax estimation from the GL.
Add to app/modules/reports/service.py and router.py.

1. PROFIT & LOSS
   Endpoint: GET /api/v1/reports/profit-loss
   Inputs: org_id, period_start, period_end, branch_id (optional),
           basis (cash|accrual, default accrual)
   Output:
   - revenue: [{account_code, account_name, amount}], total_revenue
   - cogs: [{...}], total_cogs
   - gross_profit, gross_margin_pct
   - expenses: [{account_code, account_name, amount}], total_expenses
   - net_profit, net_margin_pct
   - period_start, period_end, basis, currency: "NZD"

2. BALANCE SHEET
   Endpoint: GET /api/v1/reports/balance-sheet
   Input: org_id, as_at_date, branch_id (optional)
   Output:
   - assets: {current: [...], non_current: [...]}, total_assets
   - liabilities: {current: [...], non_current: [...]}, total_liabilities
   - equity: [...], total_equity
   - balanced: Boolean (assets = liabilities + equity)

3. AGED RECEIVABLES
   Endpoint: GET /api/v1/reports/aged-receivables
   Extend existing get_outstanding_invoices()
   Buckets: current (0–30 days), 31–60, 61–90, 90+ days overdue
   Output: per customer + totals per bucket

4. INCOME TAX ESTIMATOR
   Endpoint: GET /api/v1/reports/tax-estimate
   Inputs: org_id, tax_year_start, tax_year_end
   Logic:
   - Get net_profit from P&L for the period
   - Apply business_type from org settings:
     * company       → 28% flat
     * sole_trader   → NZ progressive brackets:
                       $0–14,000      → 10.5%
                       $14,001–48,000 → 17.5%
                       $48,001–70,000 → 30%
                       $70,001–180,000→ 33%
                       $180,001+      → 39%
   - Provisional tax: standard method = prior year tax × 1.05
   Output: taxable_income, estimated_tax, effective_rate,
           provisional_tax_amount, next_provisional_due_date,
           already_paid, balance_owing

5. TAX POSITION DASHBOARD WIDGET
   Endpoint: GET /api/v1/reports/tax-position
   Combines GST (from existing get_gst_return) + income tax estimate
   + next due dates for both. Single endpoint for dashboard polling.

Write full pytest coverage.

E2E TEST SCRIPT:
Create scripts/test_financial_reports_e2e.py covering:
- P&L report with real invoice + expense data
- Balance sheet balancing (assets = liabilities + equity)
- Aged receivables bucket accuracy
- Income tax estimate for sole_trader vs company
- Tax position dashboard endpoint
- Cash vs accrual basis toggle on P&L
- Cross-org access denied
```

---

## Sprint 3 — GST Filing Periods + IRD Readiness {#sprint-3}

**Requires:** Sprint 1 complete (for period locking)  
**Estimated effort:** 1–2 weeks

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Extend GST module to be IRD filing-ready.
Do NOT build IRD Gateway SOAP integration yet — that is Sprint 6.
This sprint makes the data model and API ready for filing.

1. GST FILING PERIODS TABLE
   - id (UUID PK), org_id (FK, RLS)
   - period_type (two_monthly|six_monthly|annual)
   - period_start (Date), period_end (Date)
   - due_date (Date) — 28th of month following period end
   - status (draft|ready|filed|accepted|rejected)
   - filed_at (nullable), filed_by (nullable FK→users)
   - ird_reference (String 50, nullable)
   - return_data (JSONB) — snapshot at filing time
   - created_at, updated_at

2. GST BASIS SETTING
   Add gst_basis (invoice|payments) to organisations.settings JSONB.
   Update get_gst_return():
   - invoice basis  → filter by invoice.issue_date (current behaviour)
   - payments basis → filter by payment.created_at date

3. GST PERIOD PRESETS
   Helper: generate_gst_periods(org_id, period_type, tax_year)
   Returns period objects with start/end/due dates for the year.
   Endpoint: GET /api/v1/gst/periods

4. IRD NUMBER VALIDATION — implement mod-11 check digit
   Current validate_ird_gst_number() skips the check digit algorithm.
   Implement IRD mod-11:
   Weights: [3,2,7,6,5,4,3,2]
   If remainder = 0 → valid
   If remainder = 1 → invalid
   If remainder > 1 → check digit = 11 - remainder
   Do not break existing tests. Add new test vectors.

5. GST RETURN LOCK
   When a GST period is marked filed, set is_gst_locked=true on all
   invoices and expenses in that period. Locked records cannot be edited.
   Add is_gst_locked (Boolean, default false) to invoices and expenses.

Write full pytest coverage including IRD mod-11 test vectors.

E2E TEST SCRIPT:
Create scripts/test_gst_filing_e2e.py covering:
- GST period generation for all period types (2-monthly, 6-monthly, annual)
- GST basis toggle (invoice vs payments) produces different totals
- Period locking prevents invoice/expense edits
- IRD mod-11 validation with known valid/invalid IRD numbers
- Filing status transitions (draft → ready → filed)
```

---

## Sprint 4 — Akahu Bank Feeds + Reconciliation {#sprint-4}

**Requires:** Sprint 1 complete (for GL account linking)  
**Estimated effort:** 3–4 weeks

> **Action required before Sprint 4:** Register at [developers.akahu.nz](https://developers.akahu.nz) and obtain OAuth credentials.

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Build Akahu bank feed integration.
Follow the exact same pattern as app/modules/accounting/xero.py 
and the accounting_integrations table.
Reference: https://developers.akahu.nz

ADMIN INTEGRATION PAGE:
Add Akahu as a new integration card in the global admin integrations page.
Same card UI as Xero and MYOB:
- Connect button → OAuth 2.0 flow
- Shows: connected accounts, last sync time, sync status
- Test Connection button (see spec below)
- Disconnect button with confirmation modal
- Credentials never shown after save (masked *****)
- Encrypted token storage (same as accounting_integrations)

DATABASE — new tables:

1. akahu_connections
   - id (UUID PK), org_id (FK, RLS)
   - access_token_encrypted (Text)
   - token_expires_at (DateTime)
   - is_active (Boolean)
   - last_sync_at (DateTime, nullable)
   - created_at, updated_at

2. bank_accounts
   - id (UUID PK), org_id (FK, RLS)
   - akahu_account_id (String 100)
   - account_name (String 200)
   - account_number (String 50)
   - bank_name (String 100)
   - account_type (String 50)
   - balance (Numeric 12,2)
   - currency (String 3, default "NZD")
   - is_active (Boolean)
   - last_refreshed_at (DateTime)
   - linked_gl_account_id (FK→accounts, nullable) — maps to COA bank account

3. bank_transactions
   - id (UUID PK), org_id (FK, RLS)
   - bank_account_id (FK→bank_accounts)
   - akahu_transaction_id (String 100, unique per org)
   - date (Date)
   - description (String 500)
   - amount (Numeric 12,2) — positive=credit, negative=debit
   - balance (Numeric 12,2)
   - merchant_name (String 200, nullable)
   - category (String 100, nullable)
   - reconciliation_status (unmatched|matched|excluded|manual)
   - matched_invoice_id (UUID FK→invoices, nullable)
   - matched_expense_id (UUID FK→expenses, nullable)
   - matched_journal_id (UUID FK→journal_entries, nullable)
   - akahu_raw (JSONB)
   - created_at, updated_at

SYNC SERVICE (app/modules/banking/akahu.py):
- OAuth 2.0 flow: authorise, callback, token refresh
- sync_accounts() — fetch all connected bank accounts
- sync_transactions(bank_account_id, from_date) — paginated
- Background sync: last 90 days on connect, then daily

AUTO-MATCHING ENGINE (app/modules/banking/reconciliation.py):
- Invoice match: amount = invoice.balance_due (±$0.01), 
  date within 7 days of invoice.due_date → confidence: high
- Expense match: amount = expense.amount, date within 3 days → medium
- Auto-accept high confidence, flag medium for user review

RECONCILIATION API:
GET  /api/v1/banking/transactions               — list with filters
POST /api/v1/banking/transactions/{id}/match    — manually match
POST /api/v1/banking/transactions/{id}/exclude  — mark excluded
POST /api/v1/banking/transactions/{id}/create-expense — create from transaction
GET  /api/v1/banking/reconciliation-summary     — counts + last sync

TEST CONNECTION BUTTON SPEC (apply to ALL integration cards):
1. Calls GET /api/v1/integrations/{provider}/test
2. Shows spinner, disables button during test
3. Success: green tick + "Connected — last tested [timestamp]"
4. Failure: red X + human-readable error (never raw API errors)
5. Verify: token valid, API reachable, return account info as proof
6. Add audit log entry on every test action

SECURITY REQUIREMENTS (from security-hardening-checklist.md):
- Encrypted token storage using envelope_encrypt/envelope_decrypt_str
  (same pattern as accounting_integrations.access_token_encrypted)
- Never store masked credential values back to DB — detect mask pattern
- Never return raw tokens in API responses — mask with ****
- Add Akahu OAuth callback to _CSRF_EXEMPT_PATHS in
  app/middleware/security_headers.py (same as ISSUE-110 fix)
- Rate limit Akahu sync endpoints (prevent abuse)

PERFORMANCE REQUIREMENTS (from performance-and-resilience.md):
- Use httpx.AsyncClient with explicit timeout (10s) and retry (3 attempts, exponential backoff)
- Close httpx clients after use (context manager or shared singleton)
- Background sync should use BackgroundTasks or a task queue, not blocking the request
- Cache bank account list in Redis with 5-min TTL (invalidate on sync)

FRONTEND REQUIREMENTS (from safe-api-consumption.md):
- Every set*(res.data.property) uses res.data?.property ?? fallback
- Every .map() on transaction lists uses ?? [] fallback
- Every useEffect with API calls has AbortController cleanup
- No `as any` type assertions on API responses

E2E TEST SCRIPT:
Create scripts/test_banking_e2e.py covering:
- OAuth flow (mock Akahu responses)
- Transaction sync and listing
- Auto-matching logic (invoice match, expense match)
- Manual match/exclude/create-expense
- Cross-org access denied (OWASP A1)
- Reconciliation summary endpoint

Write full pytest coverage.
```

---

## Sprint 5 — Tax Savings Wallet {#sprint-5}

**Requires:** Sprint 2 complete (income tax estimator)  
**Estimated effort:** 1–2 weeks

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Build the tax savings wallet — virtual ledger-based set-aside 
(not a real bank account).

DATABASE:

1. tax_wallets
   - id (UUID PK), org_id (FK, RLS)
   - wallet_type (gst|income_tax|provisional_tax)
   - balance (Numeric 12,2, default 0)
   - target_balance (Numeric 12,2, nullable)
   - created_at, updated_at

2. tax_wallet_transactions
   - id (UUID PK), org_id (FK, RLS)
   - wallet_id (FK→tax_wallets)
   - amount (Numeric 12,2) — positive=deposit, negative=withdrawal
   - transaction_type (auto_sweep|manual_deposit|manual_withdrawal|tax_payment)
   - source_payment_id (FK→payments, nullable)
   - description (String 200)
   - created_by (FK→users, nullable) — null if auto
   - created_at

AUTO-SWEEP LOGIC:
When a payment is received (invoice paid):
- GST component: payment_amount × (15/115) if GST-inclusive
- Income tax estimate: net_profit_contribution × effective_tax_rate
- Auto-create wallet transaction for GST amount
- Create notification: "Payment of $X received. $Y swept to GST 
  wallet. Recommend setting aside $Z for income tax."

ORG SETTINGS (add to organisations.settings JSONB):
- tax_sweep_enabled (Boolean, default true)
- tax_sweep_gst_auto (Boolean, default true)
- income_tax_sweep_pct (Numeric 5,2) — manual % override

API:
GET  /api/v1/tax-wallets                         — all wallets + balances
GET  /api/v1/tax-wallets/{type}/transactions      — transaction history
POST /api/v1/tax-wallets/{type}/deposit           — manual deposit
POST /api/v1/tax-wallets/{type}/withdraw          — manual withdrawal
GET  /api/v1/tax-wallets/summary                  — balances + due dates + shortfall

EXTEND GET /api/v1/reports/tax-position (Sprint 2):
Add to response:
- gst_wallet_balance, gst_owing, gst_shortfall
- income_tax_wallet_balance, income_tax_estimate, income_tax_shortfall
- next_gst_due, next_income_tax_due
- traffic_light per wallet: green=covered, amber=partial, red=shortfall

Write full pytest coverage.

FRONTEND REQUIREMENTS (from safe-api-consumption.md):
- Every set*(res.data.property) uses res.data?.property ?? fallback
- Every .map() on wallet transaction lists uses ?? [] fallback
- Every useEffect with API calls has AbortController cleanup
- Traffic light indicators: guard with ?? "red" fallback

E2E TEST SCRIPT:
Create scripts/test_tax_wallets_e2e.py covering:
- Wallet creation on first access
- Manual deposit/withdrawal
- Auto-sweep on payment received
- Sweep settings toggle (enable/disable)
- Summary endpoint with shortfall calculation
- Cross-org access denied
```

---

## Sprint 6 — IRD Gateway Services Integration {#sprint-6}

**Requires:** Sprint 3 complete (GST filing periods + period locking)  
**Requires:** IRD Gateway Customer Support Portal registration approved  
**Estimated effort:** 4–6 weeks

> **Action required NOW (parallel to all sprints):** Register at [ird.govt.nz/digital-service-providers/getting-started](https://www.ird.govt.nz/digital-service-providers/getting-started). Approval takes weeks. Start immediately.

### IRD Gateway — Key Technical Facts

- Architecture: **SOAP** (not REST) — use Python `zeep` library
- Authentication: OAuth 2.0 + client-signed JWT + TLS 1.3 mutual auth
- Cost: **Free** — no API fees from IRD
- Availability: 24/7 except approved scheduled maintenance
- Sandbox: Available once registration approved

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Build IRD Gateway Services SOAP integration as an internal service.
Assumes sandbox credentials are available from IRD portal registration.
Follow the same security pattern as app/modules/accounting/xero.py.

NEW SERVICE: app/modules/ird/gateway.py

ADMIN INTEGRATION PAGE:
Add IRD Gateway as an integration card:
- IRD number field (validated with mod-11 from Sprint 3)
- myIR credential linking instructions
- Status: shows which services are active (GST, Income Tax)
- Environment toggle: sandbox|production (admin only — never expose to end users)
- Test Connection button (same spec as Sprint 4)
- All credentials encrypted — treat as highest-sensitivity secrets
- Never log IRD credentials or include in error messages

DATABASE:
Add provider='ird' to existing accounting_integrations table.
New table:
- ird_filing_log
  id, org_id, filing_type (gst|income_tax), period_id,
  request_xml (Text), response_xml (Text), status,
  ird_reference, created_at

SOAP CLIENT (Python zeep):
- TLS 1.3 mutual authentication
- OAuth 2.0 + client signed JWT
- Encrypted credential storage in accounting_integrations
- Retry logic with exponential backoff
- Full request/response logging to ird_filing_log

IRD GATEWAY OPERATIONS (implement in this order):

1. Customer API
   - Lookup customer by IRD number
   - Return entity type (individual, company, etc.)

2. GST Return Filing
   Map get_gst_return() output to IRD XML schema:
   - RFO (Retrieve Filing Obligation) — check what's due
   - RR  (Retrieve Return) — get existing filed return if any
   - File Return — submit
   - RS  (Retrieve Status) — poll for acceptance/rejection
   - Update gst_filing_periods.status and ird_reference on response

3. Income Tax Return Filing
   Map P&L to IR3 (sole_trader) or IR4 (company) based on business_type:
   - Same RFO/RR/File/RS pattern as GST

FILING UI FLOW:
1. User reviews GST return summary (from Sprint 3 periods)
2. Clicks "File with IRD"
3. Preflight checks: IRD connected? Period not already filed? Figures match?
4. Confirmation modal showing exact figures to be submitted
5. Submit → poll status (RS) → show result
6. On acceptance: lock period, store ird_reference
7. On rejection: show IRD error code + plain English explanation

Write full pytest with mocked SOAP responses.
All IRD credentials are highest-sensitivity — never log, 
never include in error messages, never expose in API responses.

SECURITY REQUIREMENTS (from security-hardening-checklist.md):
- Envelope encryption for all IRD credentials (same pattern as Xero)
- Mask detection: if incoming value matches /^\*+$|^.{0,4}\*{4,}/, skip DB update
- Never log IRD numbers, credentials, or SOAP request/response bodies to stdout
  (only to ird_filing_log table which is access-controlled)
- Add IRD callback endpoint to _CSRF_EXEMPT_PATHS
- Rate limit IRD filing endpoints (max 1 filing per period per org)
- TLS 1.3 mutual auth: store client cert in encrypted column, not filesystem

PERFORMANCE REQUIREMENTS:
- SOAP calls via zeep with explicit timeout (30s for filing, 10s for status)
- Retry with exponential backoff on transient errors (network, 5xx)
- Filing status polling: use background task, not blocking request
- Cache IRD filing obligations in Redis (1-hour TTL)

E2E TEST SCRIPT:
Create scripts/test_ird_gateway_e2e.py covering:
- Mock SOAP client (never hit real IRD in tests)
- GST return filing flow (preflight → submit → poll → accept)
- Rejection handling (IRD error codes → plain English)
- Period locking after successful filing
- Cross-org access denied
- Credential masking in API responses
```

---

## Sprint 7 — Business Entity Type + Admin Integrations Audit {#sprint-7}

**Can run in parallel with Sprint 4 or 5**  
**Estimated effort:** 1 week

### Kiro Prompt

```
[PASTE MASTER PREAMBLE]

Two housekeeping items before public launch.

1. BUSINESS TYPE — add proper column to organisations table
   (not just JSONB — needs to be a queryable column):
   - business_type: enum (sole_trader|partnership|company|trust|other)
   - nzbn (String 13, nullable) — NZ Business Number
   - nz_company_number (String 10, nullable)
   - gst_registered (Boolean, default false)
   - gst_registration_date (Date, nullable)
   - income_tax_year_end (Date, default March 31)
   - provisional_tax_method (standard|estimation|aim, default standard)

   Use business_type in:
   - Income tax bracket selection (Sprint 2)
   - IRD return type: IR3 (sole_trader) vs IR4 (company) (Sprint 6)
   - Future feature gating (e.g. PAYE section only if employer)

2. GLOBAL ADMIN INTEGRATIONS PAGE AUDIT
   Ensure ALL integration cards (Xero, MYOB, Akahu, IRD) follow this spec:
   - Consistent layout: logo, name, status badge, last sync time
   - Connect/Disconnect with confirmation modals
   - Test Connection: spinner → success/error (plain English only)
   - Credentials never shown after save (masked *****)
   - All tokens stored encrypted — verify encryption is applied
   - Disconnect must delete tokens from DB, not just flag inactive
   - Audit log entry on every connect/disconnect/test (add action_type 
     column to accounting_sync_log)
   - Rate limit display where relevant (e.g. Xero: 55/min)
   - Error states in plain English — no raw API error codes

   Write integration tests for connect/disconnect/test for each provider.

E2E TEST SCRIPT:
Create scripts/test_entity_type_e2e.py covering:
- Set business_type on org (sole_trader, company, etc.)
- Verify business_type affects tax bracket selection
- Verify NZBN validation
- Integration page: all 4 providers show consistent card layout
- Test Connection button for each provider (mocked)
- Disconnect deletes tokens (not just flags inactive)
- Credential masking in responses
```

---

## IRD Onboarding Requirements

### Step-by-Step Process

**Step 1 — Register your organisation**
Go to [ird.govt.nz/digital-service-providers/getting-started](https://www.ird.govt.nz/digital-service-providers/getting-started).
IRD will run compliance, integrity, and security checks on your organisation, key office holders, and any third parties.

**Step 2 — Submit a product request**
Select which gateway services you want (GST, Income Tax, Customer API). This starts formal due diligence.

**Step 3 — Assessment**
IRD assesses whether your integration meets their business, compliance, and security requirements. This can take several weeks.

**Step 4 — Developer Portal access**
Once approved, your dev team gets access to the developer portal, sandbox (mock services), and test environments. Manage client certificate credentials here.

**Step 5 — Build & test in sandbox**
Build your SOAP integration against mock services. IRD provides a casebook with test scenarios.

**Step 6 — Production go-live**
Once testing is signed off, integration moves to production.

### Cost
**Zero.** IRD charges no fees for Gateway Services access. Your only costs are dev time and Python `zeep` (open source).

### Architecture Notes
- Protocol: SOAP (not REST)
- Auth: OAuth 2.0 + client-signed JWT + TLS 1.3/1.2 mutual auth
- Python library: `zeep`
- Isolate in its own Docker service: `ird-gateway-service`
- Availability: 24/7 except scheduled maintenance

---

## Admin Integrations Page — New Entries Required

| Integration | Admin Page Changes | Security Level |
|---|---|---|
| Akahu | New card — OAuth flow, account list, sync controls, test button | Encrypted tokens (same as Xero) |
| IRD Gateway | New card — IRD number, myIR auth, SOAP cert management, environment toggle | Highest sensitivity — dedicated secret handling |
| MYOB (completion) | Existing card — add refund + contact sync toggles | Already encrypted |
| Tax Wallet | New settings section — sweep toggles, % overrides | Org settings only, no external creds |

### Test Connection Button Spec (All Integrations)

Every integration card must implement:
1. `GET /api/v1/integrations/{provider}/test` endpoint
2. Button shows spinner and disables during test
3. Success state: green tick + "Connected — last tested [timestamp]"
4. Failure state: red X + human-readable message (never raw API errors)
5. Verifies: token valid, can reach provider API, returns proof (account/tenant info)
6. Writes audit log entry on every test action

---

## Future Implementation

These items are deliberately deferred. Do not design current sprints around them.

| Feature | Reason Deferred | Notes |
|---|---|---|
| **Human accountant filing** | Requires IRD tax agent registration + hiring/partnering with a CA firm | Partner route: find NZ CA firm, white-label their agent status, revenue share |
| **Extended IRD deadlines** | Requires registered tax agent status (above) | Automatic benefit once tax agent status achieved |
| **Tax agent registration** | Business/regulatory process, not a tech build | Need a qualified accountant as principal (CA/CPA) |
| **Payroll / PAYE** | Significant scope — payday filing, employee records, payslips | Separate product stream |
| **Akahu pay-by-bank payments** | Akahu integration (Sprint 4) is prerequisite | Add after Sprint 4 is stable |
| **AI expense categorisation** | Expenses module is complete — AI layer is an enhancement | Quick win post-Sprint 1 using existing categories |
| **MYOB completion** | Low priority — refund handling + contact sync only | 2–3 days effort when prioritised |
| **Live FX rate fetching** | Manual exchange rate entry is sufficient for NZ trade businesses | Revisit if international customer volume grows |
| **Foreign currency expenses** | Expenses are NZD-only — no currency/exchange_rate fields | Add currency + exchange_rate_to_nzd columns to expenses table if needed |

---

*Document generated April 2026. Update after each sprint completion.*

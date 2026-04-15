# Implementation Plan: OraFlows Accounting & Tax

## Overview

This plan implements OraFlows Accounting & Tax across 7 sprints in strict dependency order. Sprint 1 (COA + Ledger) is the foundation — all other sprints depend on it. Each sprint creates database migrations, ORM models, Pydantic schemas, service layer, API router, property tests, unit tests, and an e2e test script. Frontend components are added where applicable (Sprints 1–5, 7).

The implementation language is Python 3.11 (FastAPI backend) and TypeScript (React frontend).

## Tasks

- [x] 1. Sprint 1 — Chart of Accounts + Double-Entry Ledger (Foundation)
  - [x] 1.0 Register `accounting` module in module_registry and gate all new endpoints
    - Add `accounting` to `module_registry` seed data (if not already present) with `is_core = false`
    - Add `"/api/v1/ledger": "accounting"` and `"/api/v1/gst": "accounting"` and `"/api/v1/banking": "accounting"` and `"/api/v1/tax-wallets": "accounting"` and `"/api/v1/ird": "accounting"` to `MODULE_ENDPOINT_MAP` in `app/middleware/modules.py`
    - All new frontend pages/nav items must be wrapped with `isEnabled('accounting')` check from `useModules()` context — hidden when module is disabled
    - All new sidebar nav items must include `module: 'accounting'` in the nav item config
    - This ensures orgs that haven't enabled accounting see no accounting UI or API access
    - _Requirements: Cross-cutting — module gating_

  - [x] 1.1 Create Alembic migration for `accounts`, `journal_entries`, `journal_lines`, `accounting_periods` tables
    - Create `alembic/versions/0140_oraflows_accounting_ledger.py`
    - Define all 4 tables with columns, constraints, and indexes per design SQL
    - Enable RLS on each table and create org_id isolation policies (pattern from migration 0008)
    - Add tables to HA replication publication if exists: `ALTER PUBLICATION ora_publication ADD TABLE ...`
    - Seed standard NZ COA (30 accounts from design seed data table) via `INSERT INTO accounts` in migration
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 2.1, 2.6, 2.7, 3.1, 3.4, 3.5, 32.1, 36.1_

  - [x] 1.2 Create ORM models in `app/modules/ledger/models.py`
    - Define `Account`, `JournalEntry`, `JournalLine`, `AccountingPeriod` SQLAlchemy models
    - Follow mapped_column pattern from design (UUID PKs, org_id FK, table args with constraints)
    - Add relationships: JournalEntry → JournalLine (cascade delete), Account → JournalLine
    - _Requirements: 1.2, 2.1, 2.2, 3.1_

  - [x] 1.3 Create Pydantic schemas in `app/modules/ledger/schemas.py`
    - `AccountCreate`, `AccountUpdate`, `AccountResponse` (with code, name, account_type, sub_type, is_system, is_active, parent_id, tax_code, xero_account_code)
    - `JournalEntryCreate`, `JournalEntryResponse`, `JournalLineCreate`, `JournalLineResponse`
    - `AccountingPeriodCreate`, `AccountingPeriodResponse`
    - Wrap list responses in `{items: [...], total: N}` envelope
    - _Requirements: 1.2, 2.1, 2.2, 3.1_

  - [x] 1.4 Implement ledger service in `app/modules/ledger/service.py`
    - COA CRUD: `list_accounts`, `create_account`, `update_account`, `delete_account` (reject system/in-use)
    - COA seeding: `seed_coa_for_org(db, org_id)` — insert 30 default NZ accounts
    - Journal engine: `create_journal_entry`, `post_journal_entry` (validate debits=credits, reject closed period)
    - Period management: `list_periods`, `create_period`, `close_period` (record closed_by, closed_at)
    - Gap-free entry_number sequence per org (same pattern as invoice_sequences)
    - Use `flush()` then `await db.refresh(obj)` before returning ORM objects
    - _Requirements: 1.1, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 3.1, 3.2, 3.3, 3.5_

  - [x] 1.5 Implement auto-posting engine in `app/modules/ledger/auto_poster.py`
    - `auto_post_invoice(db, invoice)` — DR 1100 / CR 4000 + CR 2100 (GST), convert FX via exchange_rate_to_nzd
    - `auto_post_payment(db, payment, invoice)` — DR 1000 / CR 1100
    - `auto_post_expense(db, expense)` — DR 6xxx / CR 2000, DR 1200 for tax_amount
    - `auto_post_credit_note(db, credit_note, invoice)` — reverse of invoice entry
    - `auto_post_refund(db, payment, invoice)` — DR 1100 / CR 1000
    - All entries set source_type + source_id, validate balance before posting
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 1.6 Wire auto-poster calls into existing service functions
    - `app/modules/invoices/service.py::issue_invoice()` → call `auto_post_invoice`
    - `app/modules/payments/service.py::record_payment()` → call `auto_post_payment`
    - `app/modules/expenses/service.py::create_expense()` → call `auto_post_expense`
    - `app/modules/invoices/service.py::create_credit_note()` → call `auto_post_credit_note`
    - `app/modules/payments/service.py::record_refund()` → call `auto_post_refund`
    - Wire COA seeding into org creation flow (call `seed_coa_for_org` when new org is created)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 1.7 Fix Xero hardcoded account codes in `app/modules/accounting/xero.py`
    - Replace hardcoded "200" and "090" with dynamic lookup from `accounts.xero_account_code`
    - Fall back to defaults (200 for sales, 090 for bank) when xero_account_code is null
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 1.8 Create ledger API router in `app/modules/ledger/router.py`
    - `GET /api/v1/ledger/accounts` — list COA (filterable by type, active)
    - `POST /api/v1/ledger/accounts` — create custom account
    - `PUT /api/v1/ledger/accounts/{id}` — update account
    - `DELETE /api/v1/ledger/accounts/{id}` — delete (reject system/in-use)
    - `GET /api/v1/ledger/journal-entries` — list entries (filterable by date, source_type)
    - `POST /api/v1/ledger/journal-entries` — create manual journal entry
    - `GET /api/v1/ledger/journal-entries/{id}` — get entry with lines
    - `POST /api/v1/ledger/journal-entries/{id}/post` — post a draft entry
    - `GET /api/v1/ledger/periods` — list accounting periods
    - `POST /api/v1/ledger/periods` — create period
    - `POST /api/v1/ledger/periods/{id}/close` — close period
    - Register router in `app/main.py`
    - _Requirements: 1.1–1.7, 2.1–2.7, 3.1–3.5_

  - [x] 1.9 Write property tests for Sprint 1 (Properties 1–10) in `tests/test_oraflows_accounting_property.py`
    - **Property 1: Journal Entry Balance Invariant** — sum(debits) = sum(credits) for any entry
    - **Validates: Requirements 2.3, 2.4**
    - **Property 2: Auto-Posted Entries Always Balance** — auto-poster templates never produce unbalanced entries
    - **Validates: Requirements 4.7**
    - **Property 3: Closed Period Rejects Posting** — posting to closed period always rejected
    - **Validates: Requirements 2.5, 3.2**
    - **Property 4: Accounting Period Date Ordering** — start_date < end_date enforced
    - **Validates: Requirements 3.5**
    - **Property 5: System Account Deletion Protection** — is_system=true or has journal_lines → reject delete
    - **Validates: Requirements 1.5, 1.6**
    - **Property 6: Account Code Uniqueness Per Org** — duplicate (org_id, code) rejected
    - **Validates: Requirements 1.3**
    - **Property 7: Invoice Auto-Post Correctness** — DR 1100 = (N+G)×R, CR 4000 = N×R, CR 2100 = G×R
    - **Validates: Requirements 4.1, 4.6, 4.8**
    - **Property 8: Payment Auto-Post Correctness** — DR 1000 = A, CR 1100 = A
    - **Validates: Requirements 4.2, 4.6**
    - **Property 9: Expense Auto-Post Correctness** — DR 6xxx = (E-T), DR 1200 = T, CR 2000 = E
    - **Validates: Requirements 4.3, 4.6**
    - **Property 10: Credit Note Auto-Post Reversal** — reverses original invoice posting
    - **Validates: Requirements 4.4, 4.6**

  - [x] 1.10 Write unit tests in `tests/test_ledger_unit.py`
    - COA seed data verification (all 30 accounts exist after org creation)
    - Manual journal entry creation (balanced) and rejection (unbalanced with imbalance amount in error)
    - Auto-posting: invoice → verify journal entry with correct accounts and amounts
    - Auto-posting: payment → verify journal entry
    - Auto-posting: expense with GST → verify DR expense + DR GST Receivable + CR AP
    - Period close → verify closed_by and closed_at recorded
    - System account deletion rejection
    - Account with journal_lines deletion rejection
    - Xero account code fallback behavior (null xero_account_code → default codes)
    - FX invoice auto-posting (exchange_rate_to_nzd conversion)
    - _Requirements: 1.1–1.7, 2.1–2.7, 3.1–3.5, 4.1–4.8, 5.1–5.3_

  - [x] 1.11 Create e2e test script `scripts/test_coa_ledger_e2e.py`
    - COA seed data verification, manual journal CRUD, auto-posting flows
    - Period locking, system account protection, OWASP cross-org access denied
    - Test data cleanup with TEST_E2E_ prefix
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 1.12 Create frontend pages for accounting in `frontend/src/pages/accounting/`
    - `ChartOfAccounts.tsx` — COA list with CRUD (create/edit/delete custom accounts)
    - `JournalEntries.tsx` — journal entry list with create manual entry form
    - `JournalEntryDetail.tsx` — single entry with lines display
    - `AccountingPeriods.tsx` — period list with close action
    - Add accounting routes to `frontend/src/App.tsx` and navigation
    - Follow safe API consumption patterns: `?.`, `?? []`, `?? 0`, AbortController cleanup
    - _Requirements: 34.1, 34.2, 34.3, 34.4_

  - [x] 1.13 Checkpoint — Sprint 1
    - Run all property tests: `python -m pytest tests/test_oraflows_accounting_property.py -v`
    - Run unit tests: `python -m pytest tests/test_ledger_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_coa_ledger_e2e.py`
    - Run migration in dev container: `docker compose exec app alembic upgrade head`
    - Rebuild frontend in dev container: `docker compose exec frontend npm run build`
    - Verify no existing data affected — existing invoices, payments, expenses unchanged
    - Git commit: `git add -A && git commit -m "feat: Sprint 1 — COA + Double-Entry Ledger"`
    - Ensure all tests pass, ask the user if questions arise.

  - [x] 1.14 Write Playwright browser tests in `tests/e2e/frontend/accounting.spec.ts`
    - Test COA page loads with seeded accounts visible
    - Test create custom account form submission
    - Test manual journal entry creation with balanced lines
    - Test accounting periods list and close action
    - Test module gating: accounting nav hidden when module disabled
    - Follow existing Playwright patterns from `tests/e2e/frontend/auth.spec.ts`

- [x] 2. Sprint 2 — Financial Reports + Tax Engine (requires Sprint 1)
  - [x] 2.1 Implement financial report services in `app/modules/reports/service.py`
    - `get_profit_loss(db, org_id, period_start, period_end, basis, branch_id)` — aggregate journal_lines by account type (revenue, cogs, expense), compute gross_profit, net_profit, margins
    - `get_balance_sheet(db, org_id, as_at_date, branch_id)` — aggregate all journal_lines up to date for asset/liability/equity, compute balanced boolean
    - `get_aged_receivables(db, org_id, report_date)` — group outstanding invoices into 0–30, 31–60, 61–90, 90+ day buckets with per-customer and overall totals
    - `get_tax_estimate(db, org_id, tax_year_start, tax_year_end)` — derive taxable_income from P&L net_profit, apply NZ brackets (sole_trader progressive / company 28% flat), compute provisional_tax (prior year × 1.05)
    - `get_tax_position(db, org_id)` — combine GST owing + income tax estimate + next due dates
    - Cash vs accrual basis: accrual = by entry_date, cash = source_type='payment' only
    - _Requirements: 6.1–6.7, 7.1–7.5, 8.1–8.3, 9.1–9.6, 10.1, 10.2_

  - [x] 2.2 Create Pydantic schemas for reports in `app/modules/reports/schemas.py`
    - `ProfitLossResponse` (revenue items, total_revenue, cogs items, total_cogs, gross_profit, gross_margin_pct, expense items, total_expenses, net_profit, net_margin_pct, period_start, period_end, basis, currency)
    - `BalanceSheetResponse` (assets current/non_current, liabilities current/non_current, equity, totals, balanced boolean)
    - `AgedReceivablesResponse` (customers with bucket amounts, overall totals per bucket)
    - `TaxEstimateResponse` (taxable_income, estimated_tax, effective_rate, provisional_tax_amount, next_provisional_due_date, already_paid, balance_owing)
    - `TaxPositionResponse` (gst_owing, income_tax_estimate, next_gst_due, next_income_tax_due)
    - _Requirements: 6.2, 7.2, 8.1, 9.5, 10.1_

  - [x] 2.3 Add report endpoints to `app/modules/reports/router.py`
    - `GET /api/v1/reports/profit-loss` — P&L with date range, basis, branch filter
    - `GET /api/v1/reports/balance-sheet` — Balance Sheet with as_at_date, branch filter
    - `GET /api/v1/reports/aged-receivables` — Aged receivables by customer
    - `GET /api/v1/reports/tax-estimate` — Income tax estimate for tax year
    - `GET /api/v1/reports/tax-position` — Combined GST + income tax dashboard
    - _Requirements: 6.1–6.7, 7.1–7.5, 8.1–8.3, 9.1–9.6, 10.1, 10.2_

  - [x] 2.4 Write property tests for Sprint 2 (Properties 11–18) in `tests/test_oraflows_accounting_property.py`
    - **Property 11: Balance Sheet Accounting Equation** — total_assets = total_liabilities + total_equity
    - **Validates: Requirements 7.3, 7.4**
    - **Property 12: P&L Aggregation by Account Type** — revenue/cogs/expense correctly aggregated, net_profit = revenue - cogs - expenses
    - **Validates: Requirements 6.1, 6.2**
    - **Property 13: P&L Cash vs Accrual Basis Filtering** — accrual by entry_date, cash by payment source_type only
    - **Validates: Requirements 6.3, 6.4, 12.4**
    - **Property 14: Aged Receivables Bucketing** — each invoice in exactly one bucket, per-customer totals = sum of invoices
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - **Property 15: Company Tax Rate** — estimated_tax = income × 0.28 for company
    - **Validates: Requirements 9.1**
    - **Property 16: Sole Trader Progressive Tax Brackets** — correct bracket application
    - **Validates: Requirements 9.2**
    - **Property 17: Tax Cannot Exceed Income** — estimated_tax ≤ taxable_income
    - **Validates: Requirements 9.6**
    - **Property 18: Provisional Tax Calculation** — provisional = prior_year_tax × 1.05
    - **Validates: Requirements 9.4**

  - [x] 2.5 Write unit tests in `tests/test_reports_financial_unit.py`
    - P&L with known invoice + expense data, verify line items and totals
    - Balance sheet with known entries, verify balanced = true
    - Tax estimate at bracket boundaries ($0, $14,000, $48,000, $70,000, $180,000)
    - Cash vs accrual toggle produces different totals when payment dates differ from invoice dates
    - Aged receivables bucket accuracy with invoices at boundary days (30, 31, 60, 61, 90, 91)
    - Tax position endpoint returns within 2 seconds
    - _Requirements: 6.1–6.7, 7.1–7.5, 8.1–8.3, 9.1–9.6, 10.1, 10.2_

  - [x] 2.6 Create e2e test script `scripts/test_financial_reports_e2e.py`
    - P&L with real invoice + expense data, balance sheet balancing, aged receivables accuracy
    - Income tax estimate for sole_trader vs company, tax position dashboard
    - Cross-org access denied, test data cleanup with TEST_E2E_ prefix
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 2.7 Create frontend report pages
    - `frontend/src/pages/reports/ProfitAndLoss.tsx` — P&L report with date range picker, basis toggle, branch filter
    - `frontend/src/pages/reports/BalanceSheet.tsx` — Balance Sheet with as_at_date picker, branch filter
    - `frontend/src/pages/reports/AgedReceivables.tsx` — Aged receivables table with customer breakdown
    - Follow safe API consumption patterns: `?.`, `?? []`, `?? 0`, AbortController cleanup
    - _Requirements: 34.1, 34.2, 34.3, 34.4_

  - [x] 2.8 Checkpoint — Sprint 2
    - Run property tests: `python -m pytest tests/test_oraflows_accounting_property.py -k "property_11 or property_12 or property_13 or property_14 or property_15 or property_16 or property_17 or property_18" -v`
    - Run unit tests: `python -m pytest tests/test_reports_financial_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_financial_reports_e2e.py`
    - Rebuild frontend: `docker compose exec frontend npm run build`
    - Git commit: `git add -A && git commit -m "feat: Sprint 2 — Financial Reports + Tax Engine"`
    - Ensure all tests pass, ask the user if questions arise.

  - [x] 2.9 Write Playwright browser tests in `tests/e2e/frontend/financial-reports.spec.ts`
    - Test P&L report page loads with date range picker and basis toggle
    - Test Balance Sheet page loads and shows balanced indicator
    - Test Aged Receivables page loads with bucket columns
    - Test module gating: report pages hidden when accounting module disabled

- [x] 3. Sprint 3 — GST Filing Periods + IRD Readiness (requires Sprint 1)
  - [x] 3.1 Create Alembic migration for `gst_filing_periods` table and invoice/expense lock columns
    - Create `alembic/versions/0141_gst_filing_periods.py`
    - Define `gst_filing_periods` table with all columns, constraints, and RLS per design SQL
    - `ALTER TABLE invoices ADD COLUMN is_gst_locked BOOLEAN NOT NULL DEFAULT false`
    - `ALTER TABLE expenses ADD COLUMN is_gst_locked BOOLEAN NOT NULL DEFAULT false`
    - Add `gst_filing_periods` to HA replication publication if exists
    - _Requirements: 11.1, 11.3, 14.4, 32.1, 36.1_

  - [x] 3.2 Create ORM model in `app/modules/ledger/models.py` (extend)
    - Add `GstFilingPeriod` model with period_type, period_start, period_end, due_date, status, filed_at, filed_by, ird_reference, return_data (JSONB)
    - Add `is_gst_locked` column to existing Invoice and Expense models
    - _Requirements: 11.1, 14.4_

  - [x] 3.3 Create Pydantic schemas for GST filing in `app/modules/ledger/schemas.py` (extend)
    - `GstFilingPeriodResponse`, `GstPeriodGenerateRequest`, `GstPeriodReadyRequest`
    - _Requirements: 11.1, 11.2_

  - [x] 3.4 Implement GST filing service in `app/modules/ledger/service.py` (extend)
    - `generate_gst_periods(db, org_id, period_type, tax_year)` — create period objects with correct dates, due_date = 28th of month after period_end
    - `list_gst_periods(db, org_id)`, `get_gst_period(db, org_id, period_id)`
    - `mark_period_ready(db, org_id, period_id)` — enforce status transition draft → ready
    - `lock_gst_period(db, org_id, period_id)` — set is_gst_locked=true on invoices/expenses in range
    - Enforce valid status transitions: draft → ready → filed → accepted|rejected
    - Add `gst_basis` setting to organisations.settings JSONB (invoice|payments)
    - Update `get_gst_return()` in `app/modules/reports/service.py` to respect gst_basis setting
    - _Requirements: 11.1, 11.2, 11.4, 12.1, 12.2, 12.3, 14.1_

  - [x] 3.5 Implement IRD mod-11 validation in `app/modules/ledger/service.py`
    - `validate_ird_number(ird: str) -> bool` — weights [3,2,7,6,5,4,3,2], mod-11 algorithm per design pseudocode
    - Handle 8 and 9 digit IRD numbers (pad to 9)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 3.6 Implement GST lock enforcement in existing services
    - `app/modules/invoices/service.py` — reject edits when `is_gst_locked = true` with GST_LOCKED error
    - `app/modules/expenses/service.py` — reject edits when `is_gst_locked = true` with GST_LOCKED error
    - _Requirements: 14.2, 14.3_

  - [x] 3.7 Add GST filing endpoints to `app/modules/ledger/router.py` (extend)
    - `GET /api/v1/gst/periods` — list GST filing periods
    - `POST /api/v1/gst/periods/generate` — generate periods for a tax year
    - `GET /api/v1/gst/periods/{id}` — get period detail with return data
    - `POST /api/v1/gst/periods/{id}/ready` — mark period as ready
    - `POST /api/v1/gst/periods/{id}/lock` — lock invoices/expenses in period
    - _Requirements: 11.1–11.4, 14.1_

  - [x] 3.8 Write property tests for Sprint 3 (Properties 19–23) in `tests/test_oraflows_accounting_property.py`
    - **Property 19: GST Period Date Generation** — non-overlapping, cover full year, correct due_dates, correct count per type
    - **Validates: Requirements 11.2**
    - **Property 20: GST Filing Status Transitions** — only draft→ready→filed→accepted|rejected valid
    - **Validates: Requirements 11.4**
    - **Property 21: IRD Mod-11 Validation** — weights, remainder logic, known valid/invalid numbers
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5**
    - **Property 22: GST Lock on Filing** — filed period → all invoices/expenses locked, locked entities reject edits
    - **Validates: Requirements 14.1, 14.2, 14.3**
    - **Property 23: GST Basis Filtering** — invoice basis by issue_date, payments basis by payment.created_at
    - **Validates: Requirements 12.2, 12.3, 12.4**

  - [x] 3.9 Write unit tests in `tests/test_gst_filing_unit.py`
    - GST period generation for all period types (2-monthly=6 periods, 6-monthly=2, annual=1)
    - Due date calculation (28th of month following period_end)
    - IRD mod-11 with known valid (49-091-850) and invalid (12-345-678) numbers
    - GST basis toggle produces different totals when payment dates differ from invoice dates
    - GST lock prevents invoice/expense edits
    - Invalid status transitions rejected
    - _Requirements: 11.1–11.4, 12.1–12.4, 13.1–13.5, 14.1–14.4_

  - [x] 3.10 Create e2e test script `scripts/test_gst_filing_e2e.py`
    - Period generation, basis toggle, period locking, IRD mod-11 validation
    - Filing status transitions, cross-org access denied, test data cleanup
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 3.11 Create frontend GST pages
    - `frontend/src/pages/tax/GstPeriods.tsx` — GST filing periods list with status badges
    - `frontend/src/pages/tax/GstFilingDetail.tsx` — single period detail with return data and file action
    - Follow safe API consumption patterns
    - _Requirements: 34.1, 34.2, 34.3, 34.4_

  - [x] 3.12 Checkpoint — Sprint 3
    - Run property tests for Sprint 3 (Properties 19–23)
    - Run unit tests: `python -m pytest tests/test_gst_filing_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_gst_filing_e2e.py`
    - Run migration: `docker compose exec app alembic upgrade head`
    - Rebuild frontend: `docker compose exec frontend npm run build`
    - Git commit: `git add -A && git commit -m "feat: Sprint 3 — GST Filing Periods + IRD Readiness"`
    - Ensure all tests pass, ask the user if questions arise.

  - [x] 3.13 Write Playwright browser tests in `tests/e2e/frontend/gst-filing.spec.ts`
    - Test GST periods page loads with period list
    - Test GST filing detail page shows return data
    - Test GST basis toggle in settings
    - Test module gating: GST pages hidden when accounting module disabled

- [x] 4. Sprint 4 — Akahu Bank Feeds + Reconciliation (requires Sprint 1)
  - [x] 4.1 Create Alembic migration for `akahu_connections`, `bank_accounts`, `bank_transactions` tables
    - Create `alembic/versions/0142_banking_tables.py`
    - Define all 3 tables with columns, constraints (unique akahu IDs, one-match CHECK), and indexes per design SQL
    - Enable RLS on each table and create org_id isolation policies
    - Add tables to HA replication publication if exists
    - _Requirements: 15.6, 16.4, 17.6, 18.5, 32.1, 36.1_

  - [x] 4.2 Create ORM models in `app/modules/banking/models.py`
    - `AkahuConnection` (access_token_encrypted as BYTEA, token_expires_at, is_active, last_sync_at)
    - `BankAccount` (akahu_account_id, account_name, account_number, bank_name, balance, linked_gl_account_id FK→accounts)
    - `BankTransaction` (akahu_transaction_id, date, description, amount, reconciliation_status, matched_invoice_id/matched_expense_id/matched_journal_id)
    - _Requirements: 15.6, 16.1, 17.3_

  - [x] 4.3 Create Pydantic schemas in `app/modules/banking/schemas.py`
    - `AkahuConnectionResponse` (masked tokens), `BankAccountResponse`, `BankAccountLinkRequest`
    - `BankTransactionResponse`, `BankTransactionMatchRequest`, `ReconciliationSummaryResponse`
    - Wrap list responses in `{items: [...], total: N}` envelope
    - _Requirements: 15.4, 16.1, 17.3, 19.1_

  - [x] 4.4 Implement Akahu OAuth + sync service in `app/modules/banking/akahu.py`
    - OAuth 2.0 flow: `initiate_connection`, `handle_callback`, `refresh_token` — follow xero.py pattern
    - `sync_accounts(db, org_id)` — fetch bank accounts from Akahu API, upsert to bank_accounts table
    - `sync_transactions(db, org_id, bank_account_id, from_date)` — paginated transaction import
    - Store tokens with `envelope_encrypt`, decrypt with `envelope_decrypt_str`
    - Mask tokens in responses, detect mask pattern on update to prevent overwrite
    - Use `httpx.AsyncClient` with 10s timeout, 3 retries with exponential backoff
    - Initial sync: last 90 days; subsequent: daily via BackgroundTasks
    - Cache bank account list in Redis with 5-min TTL
    - Add Akahu callback to `_CSRF_EXEMPT_PATHS` in `app/middleware/security_headers.py`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 16.1, 16.2, 16.3, 17.1, 17.2, 17.3, 17.4, 17.5, 33.1, 33.2, 33.3_

  - [x] 4.5 Implement reconciliation engine in `app/modules/banking/reconciliation.py`
    - `run_auto_matching(db, org_id)` — iterate unmatched transactions
    - Invoice match: positive amount ≈ balance_due (±$0.01) AND date within 7 days of due_date → high confidence → auto-accept
    - Expense match: negative amount = expense.amount AND date within 3 days → medium confidence → flag for review
    - Multiple matches → remain unmatched
    - Enforce single FK constraint (only one of matched_invoice_id/matched_expense_id/matched_journal_id)
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5_

  - [x] 4.6 Implement banking service in `app/modules/banking/service.py`
    - `list_bank_accounts`, `link_bank_account_to_gl`, `list_transactions` (with filters)
    - `manually_match_transaction`, `exclude_transaction`, `create_expense_from_transaction`
    - `get_reconciliation_summary` — match counts by status + last sync timestamp
    - Write audit log on connect/disconnect/test actions
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 37.1_

  - [x] 4.7 Create banking API router in `app/modules/banking/router.py`
    - `GET /api/v1/banking/connect` — initiate Akahu OAuth
    - `GET /api/v1/banking/callback` — Akahu OAuth callback
    - `GET /api/v1/banking/accounts` — list connected bank accounts
    - `POST /api/v1/banking/accounts/{id}/link` — link to GL account
    - `POST /api/v1/banking/sync` — trigger manual sync
    - `GET /api/v1/banking/transactions` — list transactions (filterable)
    - `POST /api/v1/banking/transactions/{id}/match` — manual match
    - `POST /api/v1/banking/transactions/{id}/exclude` — exclude transaction
    - `POST /api/v1/banking/transactions/{id}/create-expense` — create expense from transaction
    - `GET /api/v1/banking/reconciliation-summary` — match counts + last sync
    - Register router in `app/main.py`
    - _Requirements: 15.1, 16.1, 17.1, 19.1–19.6_

  - [x] 4.8 Write property tests for Sprint 4 (Properties 24–26, 33–36) in `tests/test_oraflows_accounting_property.py`
    - **Property 24: Reconciliation High Confidence Match** — |amount - balance_due| ≤ 0.01 AND within 7 days → auto-accept
    - **Validates: Requirements 18.1, 18.3**
    - **Property 25: Reconciliation Medium Confidence Match** — expense amount match within 3 days → flag for review, NOT auto-accept
    - **Validates: Requirements 18.2, 18.4**
    - **Property 26: Matched Transaction Single FK Constraint** — at most one of matched_invoice_id/matched_expense_id/matched_journal_id non-null
    - **Validates: Requirements 18.5**
    - **Property 33: RLS Isolation Across All New Tables** — org A data not visible to org B
    - **Validates: Requirements 1.4, 2.6, 3.4, 11.3, 15.6, 16.4, 17.6, 19.6, 20.3, 22.4, 28.2, 32.1**
    - **Property 34: Credential Encryption Round-Trip** — envelope_encrypt then envelope_decrypt_str returns original
    - **Validates: Requirements 15.2, 24.2, 33.1**
    - **Property 35: Credential Masking in API Responses** — raw tokens never in responses
    - **Validates: Requirements 15.4, 25.2, 31.6, 33.2**
    - **Property 36: Mask Detection Prevents Overwrite** — masked values skip DB update
    - **Validates: Requirements 15.5, 25.3, 33.3**

  - [x] 4.9 Write unit tests in `tests/test_banking_unit.py`
    - Akahu OAuth mock flow (initiate, callback, token storage)
    - Transaction sync with mock Akahu responses
    - Auto-matching: exact amount match within date window → high confidence
    - Auto-matching: expense match within 3 days → medium confidence
    - Auto-matching: multiple potential matches → remain unmatched
    - Manual match, exclude, create-expense-from-transaction flows
    - Credential masking in responses, mask detection on update
    - _Requirements: 15.1–15.6, 16.1–16.4, 17.1–17.6, 18.1–18.5, 19.1–19.6_

  - [x] 4.10 Create e2e test script `scripts/test_banking_e2e.py`
    - OAuth flow (mock), transaction sync, auto-matching, manual reconciliation
    - Credential masking, cross-org access denied, test data cleanup
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 4.11 Create frontend banking pages
    - `frontend/src/pages/banking/BankAccounts.tsx` — connected accounts list with link-to-GL action
    - `frontend/src/pages/banking/BankTransactions.tsx` — transaction list with match/exclude/create-expense actions
    - `frontend/src/pages/banking/ReconciliationDashboard.tsx` — summary with match counts, last sync, status breakdown
    - Add banking routes to `frontend/src/App.tsx` and navigation
    - Follow safe API consumption patterns: `?.`, `?? []`, `?? 0`, AbortController cleanup
    - _Requirements: 34.1, 34.2, 34.3, 34.4_

  - [x] 4.12 Checkpoint — Sprint 4
    - Run property tests for Sprint 4 (Properties 24–26, 33–36)
    - Run unit tests: `python -m pytest tests/test_banking_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_banking_e2e.py`
    - Run migration: `docker compose exec app alembic upgrade head`
    - Rebuild frontend: `docker compose exec frontend npm run build`
    - Git commit: `git add -A && git commit -m "feat: Sprint 4 — Akahu Bank Feeds + Reconciliation"`
    - Ensure all tests pass, ask the user if questions arise.

  - [x] 4.13 Write Playwright browser tests in `tests/e2e/frontend/banking.spec.ts`
    - Test bank accounts page loads
    - Test bank transactions page with filter controls
    - Test reconciliation dashboard summary display
    - Test match/exclude/create-expense actions on transactions
    - Test module gating: banking pages hidden when accounting module disabled

- [x] 5. Sprint 5 — Tax Savings Wallets (requires Sprint 2)
  - [x] 5.1 Create Alembic migration for `tax_wallets` and `tax_wallet_transactions` tables
    - Create `alembic/versions/0143_tax_wallets.py`
    - Define both tables with columns, constraints (unique org+type, wallet_type CHECK, tx_type CHECK), and RLS per design SQL
    - Add tables to HA replication publication if exists
    - Add `tax_sweep_enabled`, `tax_sweep_gst_auto`, `income_tax_sweep_pct` to organisations.settings JSONB defaults
    - _Requirements: 20.1, 20.2, 20.3, 32.1, 36.1_

  - [x] 5.2 Create ORM models in `app/modules/tax_wallets/models.py`
    - `TaxWallet` (wallet_type, balance, target_balance, org_id with RLS)
    - `TaxWalletTransaction` (amount, transaction_type, source_payment_id, description, created_by)
    - _Requirements: 20.1, 20.2_

  - [x] 5.3 Create Pydantic schemas in `app/modules/tax_wallets/schemas.py`
    - `TaxWalletResponse`, `WalletTransactionResponse`, `WalletDepositRequest`, `WalletWithdrawRequest`
    - `TaxWalletSummaryResponse` (balances, due_dates, shortfall, traffic_light per wallet)
    - Wrap list responses in `{items: [...], total: N}` envelope
    - _Requirements: 20.1, 22.1, 22.2, 23.1, 23.2_

  - [x] 5.4 Implement tax wallet service in `app/modules/tax_wallets/service.py`
    - `list_wallets(db, org_id)`, `get_wallet_transactions(db, org_id, wallet_type)`
    - `manual_deposit(db, org_id, wallet_type, amount, description, user_id)` — create tx, update balance
    - `manual_withdrawal(db, org_id, wallet_type, amount, description, user_id)` — reject if amount > balance
    - `get_wallet_summary(db, org_id)` — balances, due dates, shortfall, traffic light (green ≥ 100%, amber 50–99%, red < 50%)
    - `sweep_on_payment(db, org_id, payment, invoice)` — GST sweep = payment × (15/115), income tax sweep = payment × effective_rate
    - Respect `tax_sweep_enabled` and `tax_sweep_gst_auto` settings
    - Create notification on auto-sweep: "Payment of $X received. $Y swept to GST wallet."
    - Ensure wallet.balance always equals sum of wallet transactions (invariant)
    - _Requirements: 20.1–20.4, 21.1–21.5, 22.1–22.4, 23.1, 23.2_

  - [x] 5.5 Wire auto-sweep into payment flow
    - `app/modules/payments/service.py::record_payment()` → call `sweep_on_payment` after auto_post_payment
    - Only sweep if `tax_sweep_enabled` is true in org settings
    - _Requirements: 21.1, 21.2, 21.4, 21.5_

  - [x] 5.6 Extend tax position endpoint in `app/modules/reports/service.py`
    - Update `get_tax_position` to include gst_wallet_balance, gst_owing, gst_shortfall, income_tax_wallet_balance, income_tax_estimate, income_tax_shortfall, traffic_light per wallet
    - _Requirements: 23.1, 23.2_

  - [x] 5.7 Create tax wallet API router in `app/modules/tax_wallets/router.py`
    - `GET /api/v1/tax-wallets` — list all wallets with balances
    - `GET /api/v1/tax-wallets/{type}/transactions` — transaction history per wallet
    - `POST /api/v1/tax-wallets/{type}/deposit` — manual deposit
    - `POST /api/v1/tax-wallets/{type}/withdraw` — manual withdrawal
    - `GET /api/v1/tax-wallets/summary` — balances + due dates + shortfall + traffic light
    - Register router in `app/main.py`
    - _Requirements: 22.1, 22.2, 22.3, 22.4_

  - [x] 5.8 Write property tests for Sprint 5 (Properties 27–32) in `tests/test_oraflows_accounting_property.py`
    - **Property 27: Tax Wallet Balance Invariant** — balance = sum of all wallet transaction amounts
    - **Validates: Requirements 20.4**
    - **Property 28: GST Auto-Sweep Calculation** — deposit = payment × (15/115), rounded to 2dp
    - **Validates: Requirements 21.1**
    - **Property 29: Income Tax Auto-Sweep Calculation** — deposit = payment × effective_tax_rate
    - **Validates: Requirements 21.2**
    - **Property 30: Sweep Settings Toggle** — sweep_enabled=false → no transactions; gst_auto=false → skip GST only
    - **Validates: Requirements 21.4, 21.5**
    - **Property 31: Wallet Withdrawal Floor** — withdrawal > balance → rejected, balance never < 0
    - **Validates: Requirements 22.3**
    - **Property 32: Traffic Light Indicator** — green ≥ 100%, amber 50–99%, red < 50%
    - **Validates: Requirements 23.2**

  - [x] 5.9 Write unit tests in `tests/test_tax_wallets_unit.py`
    - Wallet creation on first access, manual deposit/withdrawal flow
    - Auto-sweep with $0 payment (no transaction created)
    - Auto-sweep with disabled settings (no transaction created)
    - Withdrawal exceeding balance rejected with INSUFFICIENT_BALANCE error
    - Traffic light at boundary values (exactly 50%, exactly 100%)
    - Notification created on auto-sweep
    - _Requirements: 20.1–20.4, 21.1–21.5, 22.1–22.4, 23.1, 23.2_

  - [x] 5.10 Create e2e test script `scripts/test_tax_wallets_e2e.py`
    - Wallet CRUD, auto-sweep on payment, manual deposit/withdrawal
    - Summary with traffic lights, cross-org access denied, test data cleanup
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 5.11 Create frontend tax wallet page
    - `frontend/src/pages/tax/TaxWallets.tsx` — wallet balances, transaction history, deposit/withdraw actions, traffic light indicators
    - `frontend/src/pages/tax/TaxPosition.tsx` — combined dashboard widget (GST + income tax + wallets)
    - Follow safe API consumption patterns: `?.`, `?? []`, `?? 0`, AbortController cleanup
    - _Requirements: 34.1, 34.2, 34.3, 34.4_

  - [x] 5.12 Checkpoint — Sprint 5
    - Run property tests for Sprint 5 (Properties 27–32)
    - Run unit tests: `python -m pytest tests/test_tax_wallets_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_tax_wallets_e2e.py`
    - Run migration: `docker compose exec app alembic upgrade head`
    - Rebuild frontend: `docker compose exec frontend npm run build`
    - Git commit: `git add -A && git commit -m "feat: Sprint 5 — Tax Savings Wallets"`
    - Ensure all tests pass, ask the user if questions arise.

  - [x] 5.13 Write Playwright browser tests in `tests/e2e/frontend/tax-wallets.spec.ts`
    - Test tax wallets page loads with wallet balances
    - Test manual deposit/withdrawal forms
    - Test traffic light indicators display correctly
    - Test tax position dashboard widget
    - Test module gating: tax wallet pages hidden when accounting module disabled

- [x] 6. Sprint 6 — IRD Gateway SOAP Integration (requires Sprint 3)
  - [x] 6.1 Create Alembic migration for `ird_filing_log` table
    - Create `alembic/versions/0144_ird_filing_log.py`
    - Define `ird_filing_log` table with columns, constraints, and RLS per design SQL
    - Add table to HA replication publication if exists
    - _Requirements: 28.1, 28.2, 32.1, 36.1_

  - [x] 6.2 Create ORM model in `app/modules/ird/models.py`
    - `IrdFilingLog` (filing_type, period_id, request_xml, response_xml, status, ird_reference, org_id with RLS)
    - _Requirements: 28.1_

  - [x] 6.3 Create Pydantic schemas in `app/modules/ird/schemas.py`
    - `IrdConnectRequest` (ird_number validated by mod-11, credentials)
    - `IrdStatusResponse`, `IrdPreflightResponse`, `IrdFilingResponse`, `IrdFilingLogResponse`
    - Mask all credentials in responses
    - _Requirements: 25.1, 25.2, 28.1_

  - [x] 6.4 Implement IRD SOAP client in `app/modules/ird/gateway.py`
    - Use `zeep` library with `httpx` transport, TLS 1.3 mutual auth, OAuth 2.0 + client-signed JWT
    - `retrieve_filing_obligation(period_id)` — RFO operation
    - `retrieve_return(period_id)` — RR operation (check existing filed return)
    - `file_return(return_data)` — submit GST or income tax return
    - `retrieve_status(filing_id)` — RS operation (poll status)
    - Timeouts: 30s for filing, 10s for status checks
    - Retry: 3 attempts with exponential backoff on transient errors (network, HTTP 5xx)
    - Log all request/response XML to `ird_filing_log` table (never stdout)
    - Return structured errors with IRD error code + plain English explanation
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6_

  - [x] 6.5 Implement IRD filing service in `app/modules/ird/service.py`
    - `connect_ird(db, org_id, ird_number, credentials)` — validate IRD number (mod-11), store encrypted credentials in accounting_integrations (provider='ird')
    - `get_ird_status(db, org_id)` — connection status + active services
    - `preflight_gst(db, org_id, period_id)` — call RFO + RR, return obligation status
    - `file_gst_return(db, org_id, period_id)` — map get_gst_return() to IRD XML, submit, poll status, update GST period status + ird_reference, trigger GST lock on acceptance
    - `file_income_tax(db, org_id, tax_year)` — map P&L to IR3 (sole_trader) or IR4 (company), submit
    - `get_filing_log(db, org_id)` — list filing audit log
    - Rate limit: max 1 filing per period per org
    - Store TLS client certificates in encrypted DB column (not filesystem)
    - Mask credentials, detect mask pattern on update
    - Write audit log on all filing actions
    - _Requirements: 24.1–24.6, 25.1–25.6, 26.1–26.7, 27.1–27.4, 28.1–28.3, 33.1–33.3, 37.1, 37.2_

  - [x] 6.6 Create IRD API router in `app/modules/ird/router.py`
    - `POST /api/v1/ird/connect` — store IRD credentials (encrypted)
    - `GET /api/v1/ird/status` — connection status + active services
    - `POST /api/v1/ird/gst/preflight/{period_id}` — preflight check (RFO + RR)
    - `POST /api/v1/ird/gst/file/{period_id}` — submit GST return
    - `GET /api/v1/ird/gst/status/{period_id}` — poll filing status
    - `POST /api/v1/ird/income-tax/file` — submit income tax return
    - `GET /api/v1/ird/filing-log` — filing audit log
    - Add IRD callback to `_CSRF_EXEMPT_PATHS` in `app/middleware/security_headers.py`
    - Register router in `app/main.py`
    - _Requirements: 24.1–24.6, 25.1–25.6, 26.1–26.7, 27.1–27.4, 28.1–28.3_

  - [x] 6.7 Write property tests for Sprint 6 (Properties 38, 40) in `tests/test_oraflows_accounting_property.py`
    - **Property 38: IRD Filing Rate Limit** — max 1 filing per period per org, second attempt rejected
    - **Validates: Requirements 25.5**
    - **Property 40: GST Return XML Serialization Round-Trip** — serialize to IRD XML and parse back produces equivalent data
    - **Validates: Requirements 26.3**

  - [x] 6.8 Write unit tests in `tests/test_ird_gateway_unit.py`
    - Mock SOAP responses for RFO, RR, File Return, RS operations
    - GST XML mapping for specific return data (verify IRD box mapping)
    - Income tax filing: IR3 for sole_trader, IR4 for company
    - Error code to plain English mapping
    - Rate limiting: second filing for same period rejected
    - Credential encryption/masking in responses
    - Retry logic on transient errors (mock network failure, HTTP 503)
    - Timeout enforcement (30s filing, 10s status)
    - _Requirements: 24.1–24.6, 25.1–25.6, 26.1–26.7, 27.1–27.4, 28.1–28.3_

  - [x] 6.9 Create e2e test script `scripts/test_ird_gateway_e2e.py`
    - IRD connect (mock), preflight, GST filing (mock SOAP), status polling
    - Filing log audit trail, rate limiting, cross-org access denied, test data cleanup
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 6.10 Checkpoint — Sprint 6
    - Run property tests for Sprint 6 (Properties 38, 40)
    - Run unit tests: `python -m pytest tests/test_ird_gateway_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_ird_gateway_e2e.py`
    - Run migration: `docker compose exec app alembic upgrade head`
    - Git commit: `git add -A && git commit -m "feat: Sprint 6 — IRD Gateway SOAP Integration"`
    - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Sprint 7 — Business Entity Type + Admin Integrations Audit (parallel with Sprint 4/5)
  - [x] 7.1 Create Alembic migration for organisation business entity columns
    - Create `alembic/versions/0145_business_entity_type.py`
    - `ALTER TABLE organisations ADD COLUMN business_type VARCHAR(20) DEFAULT 'sole_trader'`
    - Add `nzbn` (VARCHAR 13), `nz_company_number` (VARCHAR 10), `gst_registered` (BOOLEAN default false), `gst_registration_date` (DATE), `income_tax_year_end` (DATE default '2026-03-31'), `provisional_tax_method` (VARCHAR 20 default 'standard')
    - Add CHECK constraints for business_type and provisional_tax_method per design SQL
    - _Requirements: 29.1, 29.2_

  - [x] 7.2 Update Organisation ORM model and schemas
    - Add `business_type`, `nzbn`, `nz_company_number`, `gst_registered`, `gst_registration_date`, `income_tax_year_end`, `provisional_tax_method` to Organisation model
    - Create `BusinessTypeUpdateRequest` schema with NZBN validation (exactly 13 digits)
    - Update `OrganisationResponse` schema to include new fields
    - _Requirements: 29.1, 29.2, 30.1, 30.2_

  - [x] 7.3 Implement business type service and NZBN validation
    - `set_business_type(db, org_id, business_type, nzbn, nz_company_number)` in org service
    - `validate_nzbn(nzbn: str) -> bool` — exactly 13 digits, reject all others with descriptive error
    - Ensure tax estimator reads `business_type` from org (sole_trader → progressive brackets, company → 28% flat)
    - Ensure IRD gateway reads `business_type` for return type (sole_trader → IR3, company → IR4)
    - _Requirements: 29.1–29.6, 30.1, 30.2_

  - [x] 7.4 Add business type endpoint to existing org router
    - `PUT /api/v1/organisations/{id}/business-type` — set business type + NZBN
    - _Requirements: 29.1, 30.1_

  - [x] 7.5 Implement admin integrations audit — consistent Integration_Card behavior
    - Add `GET /api/v1/integrations/{provider}/test` endpoint — test connection for any provider (Xero, MYOB, Akahu, IRD)
    - Verify token valid, API reachable, return account info as proof
    - Show spinner during test, green tick + timestamp on success, red X + human-readable error on failure
    - Disconnect: delete stored tokens from DB (not just flag inactive), show confirmation modal
    - Write audit log on every connect/disconnect/test action
    - Mask all credentials in API responses
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5, 31.6, 37.1, 37.2_

  - [x] 7.6 Write property tests for Sprint 7 (Properties 37, 39) in `tests/test_oraflows_accounting_property.py`
    - **Property 37: NZBN Validation** — accept exactly 13 digits, reject all others
    - **Validates: Requirements 30.1, 30.2**
    - **Property 39: Audit Logging for Sensitive Operations** — all sensitive ops create audit log with user_id, org_id, action_type, entity_id
    - **Validates: Requirements 31.5, 37.1, 37.2**

  - [x] 7.7 Write unit tests in `tests/test_entity_type_unit.py`
    - Business type setting affects tax calculation (sole_trader → progressive, company → 28%)
    - Business type setting affects IRD return type (sole_trader → IR3, company → IR4)
    - NZBN edge cases: 12 digits rejected, 14 digits rejected, letters rejected, 13 digits accepted
    - Integration card disconnect deletes tokens from DB
    - Test connection returns structured success/failure
    - Audit log entries created for connect/disconnect/test
    - _Requirements: 29.1–29.6, 30.1, 30.2, 31.1–31.6, 37.1, 37.2_

  - [x] 7.8 Create e2e test script `scripts/test_entity_type_e2e.py`
    - Business type CRUD, NZBN validation, integration card test connection
    - Audit logging, cross-org access denied, test data cleanup
    - _Requirements: 35.1, 35.2, 35.3_

  - [x] 7.9 Update frontend settings pages
    - `frontend/src/pages/settings/BusinessSettings.tsx` — add business_type dropdown, NZBN field, gst_registered toggle, income_tax_year_end picker, provisional_tax_method dropdown
    - `frontend/src/pages/settings/IntegrationsSettings.tsx` — add Akahu and IRD integration cards with consistent layout (logo, status badge, connect/disconnect/test buttons, confirmation modal)
    - Follow safe API consumption patterns: `?.`, `?? []`, `?? 0`, AbortController cleanup
    - _Requirements: 25.1, 29.1, 29.2, 31.1–31.6, 34.1–34.4_

  - [x] 7.10 Checkpoint — Sprint 7
    - Run property tests for Sprint 7 (Properties 37, 39)
    - Run unit tests: `python -m pytest tests/test_entity_type_unit.py -v`
    - Run e2e script: `docker compose exec app python scripts/test_entity_type_e2e.py`
    - Run migration: `docker compose exec app alembic upgrade head`
    - Rebuild frontend: `docker compose exec frontend npm run build`
    - Git commit: `git add -A && git commit -m "feat: Sprint 7 — Business Entity Type + Admin Audit"`
    - Ensure all tests pass, ask the user if questions arise.

  - [x] 7.11 Write Playwright browser tests in `tests/e2e/frontend/entity-type.spec.ts`
    - Test business settings page with business_type dropdown and NZBN field
    - Test integrations page shows all 4 provider cards (Xero, MYOB, Akahu, IRD)
    - Test connect/disconnect/test buttons on integration cards
    - Test module gating: accounting-related settings hidden when module disabled

- [x] 8. Final Checkpoint — Full Integration Verification
  - Run ALL property tests: `python -m pytest tests/test_oraflows_accounting_property.py -v`
  - Run ALL unit tests: `python -m pytest tests/test_ledger_unit.py tests/test_reports_financial_unit.py tests/test_gst_filing_unit.py tests/test_banking_unit.py tests/test_tax_wallets_unit.py tests/test_ird_gateway_unit.py tests/test_entity_type_unit.py -v`
  - Run ALL e2e scripts: `for f in scripts/test_coa_ledger_e2e.py scripts/test_financial_reports_e2e.py scripts/test_gst_filing_e2e.py scripts/test_banking_e2e.py scripts/test_tax_wallets_e2e.py scripts/test_ird_gateway_e2e.py scripts/test_entity_type_e2e.py; do docker compose exec app python $f; done`
  - Run ALL Playwright tests: `npx playwright test tests/e2e/frontend/accounting.spec.ts tests/e2e/frontend/financial-reports.spec.ts tests/e2e/frontend/gst-filing.spec.ts tests/e2e/frontend/banking.spec.ts tests/e2e/frontend/tax-wallets.spec.ts tests/e2e/frontend/entity-type.spec.ts`
  - Run existing test suite to verify no regressions: `python -m pytest tests/ -v --ignore=tests/e2e`
  - Verify end-to-end flow: org creation → COA seeded → invoice issued → auto-posted → payment received → auto-posted + auto-swept → P&L reflects → balance sheet balances → GST period generated → GST filed → IRD accepted
  - Verify RLS isolation across all 11 new tables
  - Verify module gating: all accounting features hidden when `accounting` module is disabled for an org
  - Verify existing functionality unaffected: invoices, payments, expenses, quotes, Xero sync all still work
  - Final git commit: `git add -A && git commit -m "feat: OraFlows Accounting & Tax — all 7 sprints complete"`
  - Push to remote: `git push origin main`
  - Ensure all tests pass, ask the user if questions arise.

## Deployment Notes

### Local Dev Container Rebuild (after each sprint)
```bash
# Run migration (idempotent — safe to re-run)
docker compose exec app alembic upgrade head
# Rebuild frontend
docker compose exec frontend npm run build
# Restart app to pick up new code
docker compose restart app
# Verify app starts cleanly
docker compose logs app --tail 10
```

### Production Deployment (manual — follow .kiro/steering/deployment-environments.md)
All migrations use `IF NOT EXISTS` / `DO $$ BEGIN ... END $$` patterns for idempotency.
No existing data is modified — all changes are additive (new tables, new columns with defaults).
The `accounting` module is disabled by default — orgs must explicitly enable it.
Existing invoices, payments, expenses, customers, and Xero sync are completely unaffected.

**Pre-deployment checklist:**
1. Backup prod database (see deployment-environments.md Step 2)
2. Sync code to Pi via tar+SSH
3. Rebuild containers: `docker compose -f docker-compose.yml -f docker-compose.pi.yml up --build -d`
4. Migrations run automatically via docker entrypoint (`alembic upgrade head`)
5. Verify app starts: `docker compose logs app --tail 20`
6. Verify existing functionality: login, create invoice, record payment — all still work
7. Enable `accounting` module for the org via admin panel to activate new features

### Data Safety Guarantees
- All migrations are idempotent (`IF NOT EXISTS`, `DO $$ BEGIN ... END $$`)
- No existing tables are dropped or renamed
- No existing columns are removed or have their types changed
- New columns on existing tables (is_gst_locked, business_type, etc.) have DEFAULT values — no null constraint violations on existing rows
- COA seed data is inserted per-org on demand (not retroactively for existing orgs)
- Auto-posting only fires on NEW events after deployment — existing invoices/payments are not retroactively posted
- Module gating ensures accounting features are invisible until explicitly enabled

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each sprint
- Property tests validate universal correctness properties from the design document (40 properties total)
- Unit tests validate specific examples, edge cases, and error conditions
- E2e test scripts follow the pattern in `.kiro/steering/feature-testing-workflow.md`
- Playwright browser tests follow the pattern in `tests/e2e/frontend/auth.spec.ts`
- All new tables require RLS policies and HA replication publication updates
- All credential storage uses envelope encryption from `app.core.encryption`
- All API responses wrap arrays in `{items: [...], total: N}` — never bare arrays
- Frontend follows safe API consumption patterns from `.kiro/steering/safe-api-consumption.md`
- All accounting features are gated behind the `accounting` module — disabled by default
- All frontend pages/nav items use `isEnabled('accounting')` from `useModules()` context
- All new API endpoints are registered in `MODULE_ENDPOINT_MAP` in `app/middleware/modules.py`
- Migration numbering continues from current head (0140 for security settings)
- Git commits happen at each sprint checkpoint — push to remote after final checkpoint
- Prod deployment follows `.kiro/steering/deployment-environments.md` procedure

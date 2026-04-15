# Requirements Document

## Introduction

OraFlows Accounting & Tax is a comprehensive accounting, tax estimation, bank feed, and IRD filing feature set for OraInvoice. It transforms OraInvoice from an invoicing platform into a full NZ-compliant accounting solution competing with Afirmo and complementing Xero. The feature spans 7 sprints in strict dependency order, covering: a double-entry general ledger, financial reporting, GST filing readiness, Akahu bank feeds with reconciliation, tax savings wallets, IRD Gateway SOAP integration, and business entity classification. All features are multi-tenant with RLS, encrypted credential storage, and NZ tax compliance.

## Glossary

- **Ledger**: The double-entry general ledger (GL) recording all financial transactions as balanced journal entries
- **COA**: Chart of Accounts — the hierarchical list of accounts (assets, liabilities, equity, revenue, expenses, COGS) used by the Ledger
- **Account**: A single entry in the COA with a code, name, type, and optional parent for hierarchy
- **Journal_Entry**: A posted or draft transaction in the Ledger consisting of two or more Journal_Lines that must balance (total debits = total credits)
- **Journal_Line**: A single debit or credit line within a Journal_Entry, linked to an Account
- **Accounting_Period**: A date-bounded period (e.g. month, quarter, year) that can be closed to prevent further postings
- **Auto_Poster**: The service that automatically creates Journal_Entries when invoices, payments, expenses, credit notes, or refunds are recorded
- **P_and_L_Report**: Profit and Loss report — revenue minus COGS minus expenses for a date range
- **Balance_Sheet_Report**: Assets, liabilities, and equity as at a specific date; must always balance (assets = liabilities + equity)
- **Aged_Receivables_Report**: Outstanding invoices grouped into ageing buckets (current, 31–60, 61–90, 90+ days)
- **Tax_Estimator**: The income tax estimation engine applying NZ tax brackets (sole trader progressive rates or 28% company flat rate)
- **Tax_Position_Widget**: A dashboard endpoint combining GST owing, income tax estimate, wallet balances, and next due dates
- **GST_Filing_Period**: A date-bounded GST return period (two-monthly, six-monthly, or annual) with status tracking from draft through to IRD acceptance
- **GST_Basis**: The accounting basis for GST — invoice basis (by issue date) or payments basis (by payment date)
- **IRD_Mod11**: The IRD number validation algorithm using weighted mod-11 check digit verification
- **GST_Lock**: A flag on invoices and expenses preventing edits after the GST period has been filed
- **Akahu**: A NZ open banking API provider used for bank feed integration (OAuth 2.0)
- **Bank_Account**: A bank account connected via Akahu, linked to a GL Account in the COA
- **Bank_Transaction**: A transaction imported from Akahu with reconciliation status tracking
- **Reconciliation_Engine**: The auto-matching service that pairs Bank_Transactions with invoices or expenses by amount and date proximity
- **Tax_Wallet**: A virtual ledger-based set-aside tracking GST and income tax savings (not a real bank account)
- **Wallet_Transaction**: A deposit or withdrawal in a Tax_Wallet, created by auto-sweep or manual action
- **Auto_Sweep**: The automatic process that moves GST and income tax portions of received payments into Tax_Wallets
- **IRD_Gateway**: The IRD SOAP-based API for filing GST returns and income tax returns electronically
- **SOAP_Client**: The Python zeep-based client for communicating with IRD Gateway Services
- **Filing_Log**: An audit record of every IRD Gateway request/response for compliance
- **Business_Type**: The legal entity classification of an organisation (sole_trader, partnership, company, trust, other) affecting tax rates and IRD return types
- **NZBN**: New Zealand Business Number — a 13-digit unique business identifier
- **Integration_Card**: A UI component on the admin integrations page representing a connected external service (Xero, MYOB, Akahu, IRD)
- **Envelope_Encryption**: The credential encryption pattern using a data-encryption key (DEK) encrypted by a key-encryption key (KEK), as implemented in app.core.encryption

## Requirements

---

### Sprint 1 — Chart of Accounts + Double-Entry Ledger (Foundation)

> **Dependency:** None — this is the foundation. All other sprints depend on Sprint 1.

---

### Requirement 1: Chart of Accounts Data Model

**User Story:** As a business owner, I want a standard NZ chart of accounts created for my organisation, so that all financial transactions can be categorised correctly.

#### Acceptance Criteria

1. WHEN a new organisation is created, THE COA SHALL seed a standard NZ chart of accounts containing accounts for assets (1000–1600), liabilities (2000–2500), equity (3000–3200), revenue (4000–4100), COGS (5000–5100), and expenses (6000–6990)
2. THE Account SHALL store code (String 10), name (String 200), account_type (asset, liability, equity, revenue, expense, cogs), sub_type (String 50), description, is_system flag, is_active flag, parent_id for hierarchy, tax_code, and xero_account_code
3. THE COA SHALL enforce a unique constraint on (org_id, code) so that no two accounts in the same organisation share a code
4. THE COA SHALL enforce RLS policies on the accounts table using org_id = current_setting('app.current_org_id')::uuid
5. WHEN a user attempts to delete a system account (is_system = true), THE COA SHALL reject the deletion with a descriptive error
6. WHEN a user attempts to delete an account that has associated Journal_Lines, THE COA SHALL reject the deletion with a descriptive error
7. THE COA SHALL support self-referential parent_id for hierarchical account grouping

---

### Requirement 2: Journal Entry Engine

**User Story:** As a business owner, I want all financial events recorded as balanced double-entry journal entries, so that my books are always accurate and auditable.

#### Acceptance Criteria

1. THE Ledger SHALL store Journal_Entries with entry_number (gap-free sequence per org), entry_date, description, reference, source_type (invoice, payment, expense, credit_note, manual), source_id, period_id, is_posted flag, and created_by
2. THE Ledger SHALL store Journal_Lines with account_id, debit amount, credit amount, and description, where exactly one of debit or credit is greater than zero per line
3. WHEN a Journal_Entry is posted, THE Ledger SHALL validate that the sum of all debit amounts equals the sum of all credit amounts across all Journal_Lines in that entry
4. IF a Journal_Entry does not balance (debits ≠ credits), THEN THE Ledger SHALL reject the posting with a descriptive error including the imbalance amount
5. WHEN a user attempts to post a Journal_Entry to a closed Accounting_Period, THE Ledger SHALL reject the posting with a descriptive error
6. THE Ledger SHALL enforce RLS policies on journal_entries and journal_lines tables using org_id
7. THE Ledger SHALL use Numeric(12,2) precision for all monetary amounts

---

### Requirement 3: Accounting Periods

**User Story:** As a business owner, I want to close accounting periods so that historical financial data cannot be accidentally modified.

#### Acceptance Criteria

1. THE Accounting_Period SHALL store period_name, start_date, end_date, is_closed flag, closed_by user reference, and closed_at timestamp
2. WHEN an Accounting_Period is closed, THE Ledger SHALL prevent any new Journal_Entries from being posted to that period
3. WHEN an Accounting_Period is closed, THE Accounting_Period SHALL record the user who closed it and the timestamp
4. THE Accounting_Period SHALL enforce RLS policies using org_id
5. THE Accounting_Period SHALL enforce that start_date is before end_date

---

### Requirement 4: Auto-Posting Engine

**User Story:** As a business owner, I want journal entries created automatically when I issue invoices, receive payments, or record expenses, so that my ledger stays up to date without manual bookkeeping.

#### Acceptance Criteria

1. WHEN an invoice is issued, THE Auto_Poster SHALL create a Journal_Entry debiting Accounts Receivable (1100) and crediting Sales Revenue (4000) for the net amount, and crediting GST Payable (2100) for the GST amount
2. WHEN a payment is received against an invoice, THE Auto_Poster SHALL create a Journal_Entry debiting Bank/Cash (1000) and crediting Accounts Receivable (1100)
3. WHEN an expense is recorded, THE Auto_Poster SHALL create a Journal_Entry debiting the mapped expense account and crediting Accounts Payable (2000) or Bank/Cash (1000), with GST Receivable (1200) debited for the tax_amount
4. WHEN a credit note is issued, THE Auto_Poster SHALL create a Journal_Entry reversing the original invoice entry
5. WHEN a refund is paid, THE Auto_Poster SHALL create a Journal_Entry debiting Accounts Receivable (1100) and crediting Bank/Cash (1000)
6. FOR ALL auto-posted Journal_Entries, THE Auto_Poster SHALL set source_type and source_id to link back to the originating entity
7. FOR ALL auto-posted Journal_Entries, THE Ledger SHALL validate that debits equal credits (invariant: every auto-posted entry balances)
8. WHEN an invoice has a foreign currency with exchange_rate_to_nzd, THE Auto_Poster SHALL convert amounts to NZD before posting to the Ledger

---

### Requirement 5: Xero Account Code Migration

**User Story:** As a developer, I want Xero sync to use dynamic account codes from the COA instead of hardcoded values, so that users can customise their Xero mapping.

#### Acceptance Criteria

1. THE Xero_Sync SHALL read account codes from accounts.xero_account_code instead of using hardcoded "200" and "090" values
2. WHEN an account has no xero_account_code set, THE Xero_Sync SHALL fall back to the default codes (200 for sales, 090 for bank)
3. THE COA seed data SHALL populate xero_account_code on the standard accounts matching current Xero defaults

---


### Sprint 2 — Financial Reports + Tax Engine

> **Dependency:** Requires Sprint 1 (COA + Ledger) complete. P&L and Balance Sheet query the journal_lines table.

---

### Requirement 6: Profit and Loss Report

**User Story:** As a business owner, I want to generate a Profit and Loss report for any date range, so that I can see my revenue, costs, and net profit.

#### Acceptance Criteria

1. WHEN a user requests a P&L report with a date range, THE P_and_L_Report SHALL aggregate Journal_Lines by account for revenue, COGS, and expense account types within that range
2. THE P_and_L_Report SHALL return revenue line items, total_revenue, COGS line items, total_cogs, gross_profit, gross_margin_pct, expense line items, total_expenses, net_profit, and net_margin_pct
3. WHEN the basis parameter is "accrual", THE P_and_L_Report SHALL include Journal_Entries by entry_date regardless of payment status
4. WHEN the basis parameter is "cash", THE P_and_L_Report SHALL include only Journal_Entries linked to received payments (source_type = payment)
5. WHEN a branch_id filter is provided, THE P_and_L_Report SHALL include only Journal_Entries originating from that branch
6. THE P_and_L_Report SHALL return all monetary amounts in NZD
7. THE P_and_L_Report SHALL enforce RLS so that users can only view reports for their own organisation

---

### Requirement 7: Balance Sheet Report

**User Story:** As a business owner, I want to generate a Balance Sheet as at any date, so that I can see my financial position.

#### Acceptance Criteria

1. WHEN a user requests a Balance Sheet with an as_at_date, THE Balance_Sheet_Report SHALL aggregate all Journal_Lines up to and including that date for asset, liability, and equity account types
2. THE Balance_Sheet_Report SHALL return assets grouped into current and non_current, liabilities grouped into current and non_current, equity items, and totals for each group
3. THE Balance_Sheet_Report SHALL include a "balanced" boolean field that is true when total_assets equals total_liabilities plus total_equity
4. FOR ALL valid Balance Sheet reports, THE Balance_Sheet_Report SHALL satisfy the accounting equation: total_assets = total_liabilities + total_equity (invariant)
5. WHEN a branch_id filter is provided, THE Balance_Sheet_Report SHALL include only Journal_Entries originating from that branch

---

### Requirement 8: Aged Receivables Report

**User Story:** As a business owner, I want to see outstanding invoices grouped by age, so that I can prioritise collections.

#### Acceptance Criteria

1. THE Aged_Receivables_Report SHALL group outstanding invoices into buckets: current (0–30 days), 31–60 days, 61–90 days, and 90+ days overdue
2. THE Aged_Receivables_Report SHALL return per-customer totals and overall totals for each ageing bucket
3. THE Aged_Receivables_Report SHALL calculate days overdue from the invoice due_date relative to the report date

---

### Requirement 9: Income Tax Estimator

**User Story:** As a business owner, I want to see an estimated income tax liability based on my net profit, so that I can plan for tax payments.

#### Acceptance Criteria

1. WHEN the organisation business_type is "company", THE Tax_Estimator SHALL apply a flat 28% tax rate to taxable income
2. WHEN the organisation business_type is "sole_trader", THE Tax_Estimator SHALL apply NZ progressive tax brackets: 10.5% on $0–$14,000; 17.5% on $14,001–$48,000; 30% on $48,001–$70,000; 33% on $70,001–$180,000; 39% on $180,001+
3. THE Tax_Estimator SHALL derive taxable_income from the net_profit returned by the P_and_L_Report for the specified tax year
4. THE Tax_Estimator SHALL calculate provisional_tax_amount using the standard method (prior year tax × 1.05)
5. THE Tax_Estimator SHALL return taxable_income, estimated_tax, effective_rate, provisional_tax_amount, next_provisional_due_date, already_paid, and balance_owing
6. FOR ALL tax calculations, THE Tax_Estimator SHALL produce estimated_tax less than or equal to taxable_income (metamorphic: tax cannot exceed income)

---

### Requirement 10: Tax Position Dashboard Widget

**User Story:** As a business owner, I want a single dashboard view showing my GST and income tax position with upcoming due dates, so that I can stay on top of obligations.

#### Acceptance Criteria

1. THE Tax_Position_Widget SHALL combine GST owing (from existing get_gst_return), income tax estimate (from Tax_Estimator), and next due dates for both into a single API response
2. THE Tax_Position_Widget SHALL return the response within 2 seconds for dashboard polling use

---

### Sprint 3 — GST Filing Periods + IRD Readiness

> **Dependency:** Requires Sprint 1 (Accounting_Periods for period locking). Blocks Sprint 6 (IRD Gateway filing).

---

### Requirement 11: GST Filing Periods

**User Story:** As a business owner, I want GST filing periods generated automatically based on my filing frequency, so that I can track which periods are due and which have been filed.

#### Acceptance Criteria

1. THE GST_Filing_Period SHALL store period_type (two_monthly, six_monthly, annual), period_start, period_end, due_date, status (draft, ready, filed, accepted, rejected), filed_at, filed_by, ird_reference, and return_data (JSONB snapshot)
2. WHEN a user requests GST periods for a tax year, THE GST_Filing_Period SHALL generate period objects with correct start_date, end_date, and due_date (28th of the month following period end)
3. THE GST_Filing_Period SHALL enforce RLS policies using org_id
4. THE GST_Filing_Period SHALL enforce valid status transitions: draft → ready → filed → accepted or rejected

---

### Requirement 12: GST Basis Setting

**User Story:** As a business owner, I want to choose between invoice basis and payments basis for GST, so that my GST return matches my IRD registration.

#### Acceptance Criteria

1. THE GST_Basis SHALL be stored as a setting (invoice or payments) in the organisations.settings JSONB field
2. WHEN gst_basis is "invoice", THE GST return calculation SHALL filter transactions by invoice.issue_date
3. WHEN gst_basis is "payments", THE GST return calculation SHALL filter transactions by payment.created_at date
4. WHEN gst_basis is changed, THE GST return calculation SHALL produce different totals for the same period if payments and invoice dates differ

---

### Requirement 13: IRD Number Validation (Mod-11)

**User Story:** As a business owner, I want my IRD number validated using the official algorithm, so that filing errors from invalid numbers are prevented.

#### Acceptance Criteria

1. THE IRD_Mod11 validator SHALL apply weights [3, 2, 7, 6, 5, 4, 3, 2] to the first 8 digits of the IRD number and compute the weighted sum modulo 11
2. WHEN the remainder is 0, THE IRD_Mod11 validator SHALL accept the IRD number as valid
3. WHEN the remainder is 1, THE IRD_Mod11 validator SHALL reject the IRD number as invalid
4. WHEN the remainder is greater than 1, THE IRD_Mod11 validator SHALL verify the check digit equals 11 minus the remainder
5. FOR ALL valid IRD numbers, THE IRD_Mod11 validator SHALL return true, and for all invalid IRD numbers, THE IRD_Mod11 validator SHALL return false (round-trip: validate(format(valid_ird)) = true)

---

### Requirement 14: GST Period Locking

**User Story:** As a business owner, I want invoices and expenses locked after a GST period is filed, so that filed figures cannot be accidentally changed.

#### Acceptance Criteria

1. WHEN a GST_Filing_Period status transitions to "filed", THE GST_Lock SHALL set is_gst_locked = true on all invoices and expenses within that period's date range
2. WHILE an invoice has is_gst_locked = true, THE Invoice service SHALL reject any edit attempts with a descriptive error
3. WHILE an expense has is_gst_locked = true, THE Expense service SHALL reject any edit attempts with a descriptive error
4. THE GST_Lock SHALL add is_gst_locked (Boolean, default false) columns to the invoices and expenses tables

---

### Sprint 4 — Akahu Bank Feeds + Reconciliation

> **Dependency:** Requires Sprint 1 (COA for GL account linking). Can run in parallel with Sprint 2/3 after Sprint 1 is complete.

---

### Requirement 15: Akahu OAuth Connection

**User Story:** As a business owner, I want to connect my bank accounts via Akahu, so that transactions are imported automatically.

#### Acceptance Criteria

1. WHEN a user initiates Akahu connection, THE Akahu integration SHALL perform an OAuth 2.0 authorization flow following the same pattern as app/modules/accounting/xero.py
2. THE Akahu integration SHALL store access tokens using envelope encryption (envelope_encrypt from app.core.encryption)
3. THE Akahu integration SHALL add the OAuth callback endpoint to _CSRF_EXEMPT_PATHS in app/middleware/security_headers.py
4. THE Akahu integration SHALL mask all tokens in API responses (return masked values, never raw tokens)
5. WHEN a masked credential value is submitted back to the API, THE Akahu integration SHALL detect the mask pattern and skip the database update (never overwrite real tokens with mask strings)
6. THE Akahu integration SHALL store connection data in an akahu_connections table with RLS policies using org_id

---

### Requirement 16: Bank Account Sync

**User Story:** As a business owner, I want my connected bank accounts listed with current balances, so that I can see my cash position.

#### Acceptance Criteria

1. WHEN an Akahu connection is established, THE Bank_Account sync SHALL fetch all connected bank accounts and store them with akahu_account_id, account_name, account_number, bank_name, account_type, balance, and currency
2. THE Bank_Account SHALL support linking to a GL Account via linked_gl_account_id (FK to accounts table) for reconciliation posting
3. THE Bank_Account SHALL cache the account list in Redis with a 5-minute TTL, invalidated on sync
4. THE Bank_Account SHALL enforce RLS policies using org_id

---

### Requirement 17: Bank Transaction Sync

**User Story:** As a business owner, I want bank transactions imported automatically, so that I can reconcile them against invoices and expenses.

#### Acceptance Criteria

1. WHEN an Akahu connection is first established, THE Bank_Transaction sync SHALL import the last 90 days of transactions
2. AFTER initial sync, THE Bank_Transaction sync SHALL run daily to import new transactions
3. THE Bank_Transaction SHALL store akahu_transaction_id (unique per org), date, description, amount (positive = credit, negative = debit), balance, merchant_name, category, reconciliation_status, and the raw Akahu JSON payload
4. THE Bank_Transaction sync SHALL use httpx.AsyncClient with a 10-second timeout and 3 retry attempts with exponential backoff
5. THE Bank_Transaction sync SHALL run as a background task (FastAPI BackgroundTasks), not blocking the HTTP request
6. THE Bank_Transaction SHALL enforce RLS policies using org_id

---

### Requirement 18: Auto-Matching Reconciliation Engine

**User Story:** As a business owner, I want bank transactions automatically matched to invoices and expenses, so that reconciliation requires minimal manual effort.

#### Acceptance Criteria

1. WHEN a bank transaction amount matches an invoice balance_due within ±$0.01 and the transaction date is within 7 days of the invoice due_date, THE Reconciliation_Engine SHALL flag the match as high confidence
2. WHEN a bank transaction amount matches an expense amount and the transaction date is within 3 days of the expense date, THE Reconciliation_Engine SHALL flag the match as medium confidence
3. THE Reconciliation_Engine SHALL auto-accept high confidence matches and set reconciliation_status to "matched"
4. THE Reconciliation_Engine SHALL flag medium confidence matches for user review without auto-accepting
5. FOR ALL matched transactions, THE Reconciliation_Engine SHALL set exactly one of matched_invoice_id, matched_expense_id, or matched_journal_id (never more than one)

---

### Requirement 19: Reconciliation API

**User Story:** As a business owner, I want to manually match, exclude, or create expenses from unmatched bank transactions, so that I can complete reconciliation.

#### Acceptance Criteria

1. THE Reconciliation API SHALL provide endpoints to list transactions with filters, manually match a transaction, exclude a transaction, and create an expense from a transaction
2. WHEN a user manually matches a transaction, THE Reconciliation API SHALL update reconciliation_status to "matched" and set the appropriate matched entity FK
3. WHEN a user excludes a transaction, THE Reconciliation API SHALL update reconciliation_status to "excluded"
4. WHEN a user creates an expense from a transaction, THE Reconciliation API SHALL create an Expense record and link it via matched_expense_id
5. THE Reconciliation API SHALL provide a summary endpoint returning match counts by status and last sync timestamp
6. THE Reconciliation API SHALL enforce RLS so that users can only access transactions belonging to their organisation

---


### Sprint 5 — Tax Savings Wallet

> **Dependency:** Requires Sprint 2 (Tax_Estimator for income tax rate calculation). Requires Sprint 1 (Ledger for wallet transaction recording).

---

### Requirement 20: Tax Wallet Data Model

**User Story:** As a business owner, I want virtual tax savings wallets for GST and income tax, so that I can set aside money for upcoming tax obligations.

#### Acceptance Criteria

1. THE Tax_Wallet SHALL store wallet_type (gst, income_tax, provisional_tax), balance (Numeric 12,2 default 0), and target_balance
2. THE Wallet_Transaction SHALL store amount (positive = deposit, negative = withdrawal), transaction_type (auto_sweep, manual_deposit, manual_withdrawal, tax_payment), source_payment_id, description, and created_by
3. THE Tax_Wallet SHALL enforce RLS policies using org_id
4. FOR ALL Tax_Wallets, THE Tax_Wallet balance SHALL equal the sum of all Wallet_Transaction amounts for that wallet (invariant: balance = sum of transactions)

---

### Requirement 21: Auto-Sweep on Payment Received

**User Story:** As a business owner, I want GST and income tax portions automatically swept into savings wallets when I receive payments, so that I always have tax money set aside.

#### Acceptance Criteria

1. WHEN a payment is received against a GST-inclusive invoice, THE Auto_Sweep SHALL calculate the GST component as payment_amount × (15/115) and create a Wallet_Transaction depositing that amount into the GST wallet
2. WHEN a payment is received, THE Auto_Sweep SHALL calculate the income tax component using the organisation's effective_tax_rate from the Tax_Estimator and create a Wallet_Transaction depositing that amount into the income tax wallet
3. WHEN auto-sweep creates wallet transactions, THE Auto_Sweep SHALL create a notification: "Payment of $X received. $Y swept to GST wallet. Recommend setting aside $Z for income tax."
4. WHILE tax_sweep_enabled is false in organisation settings, THE Auto_Sweep SHALL skip all automatic wallet transactions
5. WHILE tax_sweep_gst_auto is false in organisation settings, THE Auto_Sweep SHALL skip GST auto-sweep but still process income tax sweep if enabled

---

### Requirement 22: Tax Wallet API

**User Story:** As a business owner, I want to view wallet balances, make manual deposits and withdrawals, and see my tax shortfall, so that I can manage my tax savings.

#### Acceptance Criteria

1. THE Tax_Wallet API SHALL provide endpoints to list all wallets with balances, view transaction history per wallet type, make manual deposits, and make manual withdrawals
2. THE Tax_Wallet API SHALL provide a summary endpoint returning balances, due dates, shortfall amounts, and a traffic light indicator per wallet (green = covered, amber = partial, red = shortfall)
3. WHEN a manual withdrawal would cause the wallet balance to go below zero, THE Tax_Wallet API SHALL reject the withdrawal with a descriptive error
4. THE Tax_Wallet API SHALL enforce RLS so that users can only access wallets belonging to their organisation

---

### Requirement 23: Tax Position Extension

**User Story:** As a business owner, I want the tax position dashboard to include wallet balances and shortfall indicators, so that I can see my complete tax picture at a glance.

#### Acceptance Criteria

1. THE Tax_Position_Widget (from Sprint 2) SHALL be extended to include gst_wallet_balance, gst_owing, gst_shortfall, income_tax_wallet_balance, income_tax_estimate, income_tax_shortfall, next_gst_due, and next_income_tax_due
2. THE Tax_Position_Widget SHALL include a traffic_light field per wallet: "green" when wallet balance covers the obligation, "amber" when wallet covers 50–99%, and "red" when wallet covers less than 50%

---

### Sprint 6 — IRD Gateway Services Integration

> **Dependency:** Requires Sprint 3 (GST Filing Periods + period locking). Requires IRD Gateway Customer Support Portal registration approved (external dependency — start registration immediately).

---

### Requirement 24: IRD Gateway SOAP Client

**User Story:** As a developer, I want a reusable SOAP client for IRD Gateway Services, so that GST and income tax returns can be filed electronically.

#### Acceptance Criteria

1. THE SOAP_Client SHALL use the Python zeep library with TLS 1.3 mutual authentication and OAuth 2.0 + client-signed JWT
2. THE SOAP_Client SHALL store all IRD credentials using envelope encryption in the accounting_integrations table (provider = 'ird')
3. THE SOAP_Client SHALL implement retry logic with exponential backoff (3 attempts) for transient errors (network failures, HTTP 5xx)
4. THE SOAP_Client SHALL use explicit timeouts: 30 seconds for filing operations, 10 seconds for status checks
5. THE SOAP_Client SHALL log all request/response XML to the ird_filing_log table (never to stdout or application logs)
6. IF the SOAP_Client encounters a non-transient error, THEN THE SOAP_Client SHALL return a structured error with the IRD error code and a plain English explanation

---

### Requirement 25: IRD Credential Management

**User Story:** As a business owner, I want to securely connect my IRD account to OraFlows, so that returns can be filed on my behalf.

#### Acceptance Criteria

1. THE IRD integration SHALL add an Integration_Card to the admin integrations page with IRD number field (validated by IRD_Mod11), myIR credential linking instructions, active services display, and environment toggle (sandbox/production)
2. THE IRD integration SHALL store all credentials using envelope encryption and mask all credentials in API responses
3. WHEN a masked credential value is submitted back to the API, THE IRD integration SHALL detect the mask pattern and skip the database update
4. THE IRD integration SHALL add the IRD callback endpoint to _CSRF_EXEMPT_PATHS
5. THE IRD integration SHALL rate-limit filing endpoints to a maximum of 1 filing per period per organisation
6. THE IRD integration SHALL store TLS client certificates in an encrypted database column, not on the filesystem

---

### Requirement 26: GST Return Filing via IRD Gateway

**User Story:** As a business owner, I want to file my GST return directly to IRD from OraFlows, so that I do not need to use myIR separately.

#### Acceptance Criteria

1. WHEN a user initiates GST filing, THE IRD_Gateway SHALL call RFO (Retrieve Filing Obligation) to verify the period is due
2. WHEN a user initiates GST filing, THE IRD_Gateway SHALL call RR (Retrieve Return) to check for any existing filed return
3. WHEN the user confirms filing, THE IRD_Gateway SHALL map the get_gst_return() output to the IRD XML schema and submit the return
4. AFTER submission, THE IRD_Gateway SHALL poll RS (Retrieve Status) using a background task until acceptance or rejection is received
5. WHEN IRD accepts the return, THE IRD_Gateway SHALL update the GST_Filing_Period status to "accepted", store the ird_reference, and trigger GST_Lock on the period
6. WHEN IRD rejects the return, THE IRD_Gateway SHALL update the GST_Filing_Period status to "rejected" and display the IRD error code with a plain English explanation
7. THE IRD_Gateway SHALL show a confirmation modal with exact figures before submission

---

### Requirement 27: Income Tax Return Filing via IRD Gateway

**User Story:** As a business owner, I want to file my income tax return directly to IRD from OraFlows, so that I can complete my tax obligations in one place.

#### Acceptance Criteria

1. WHEN the organisation business_type is "sole_trader", THE IRD_Gateway SHALL map P&L data to the IR3 return format
2. WHEN the organisation business_type is "company", THE IRD_Gateway SHALL map P&L data to the IR4 return format
3. THE IRD_Gateway SHALL follow the same RFO → RR → File → RS pattern as GST filing
4. AFTER successful filing, THE IRD_Gateway SHALL store the ird_reference and update the filing status

---

### Requirement 28: Filing Audit Log

**User Story:** As a business owner, I want a complete audit trail of all IRD filings, so that I have evidence of submissions for compliance purposes.

#### Acceptance Criteria

1. THE Filing_Log SHALL record every IRD Gateway interaction including filing_type (gst, income_tax), period_id, request_xml, response_xml, status, ird_reference, and created_at
2. THE Filing_Log SHALL enforce RLS policies using org_id
3. THE Filing_Log SHALL retain records indefinitely (no automatic purging) for IRD compliance

---

### Sprint 7 — Business Entity Type + Admin Integrations Audit

> **Dependency:** Can run in parallel with Sprint 4 or 5. Affects Sprint 2 (tax brackets) and Sprint 6 (return type selection) retroactively.

---

### Requirement 29: Business Entity Type Classification

**User Story:** As a business owner, I want to set my business entity type (sole trader, company, etc.), so that tax calculations and IRD return types are correct for my situation.

#### Acceptance Criteria

1. THE Organisation SHALL store business_type as a queryable column (not JSONB) with values: sole_trader, partnership, company, trust, other
2. THE Organisation SHALL store nzbn (String 13, nullable), nz_company_number (String 10, nullable), gst_registered (Boolean, default false), gst_registration_date (Date, nullable), income_tax_year_end (Date, default March 31), and provisional_tax_method (standard, estimation, aim, default standard)
3. WHEN business_type is set to "sole_trader", THE Tax_Estimator SHALL use NZ progressive tax brackets
4. WHEN business_type is set to "company", THE Tax_Estimator SHALL use the 28% flat rate
5. WHEN business_type is set to "sole_trader", THE IRD_Gateway SHALL use the IR3 return format
6. WHEN business_type is set to "company", THE IRD_Gateway SHALL use the IR4 return format

---

### Requirement 30: NZBN Validation

**User Story:** As a business owner, I want my NZBN validated on entry, so that incorrect business numbers are caught early.

#### Acceptance Criteria

1. WHEN a user enters an NZBN, THE Organisation service SHALL validate that the NZBN is exactly 13 digits
2. IF an invalid NZBN is provided, THEN THE Organisation service SHALL return a descriptive validation error

---

### Requirement 31: Admin Integrations Page Consistency Audit

**User Story:** As a business owner, I want all integration cards (Xero, MYOB, Akahu, IRD) to have a consistent layout and behaviour, so that managing integrations is intuitive.

#### Acceptance Criteria

1. THE Integration_Card for each provider (Xero, MYOB, Akahu, IRD) SHALL display: provider logo, name, status badge, and last sync time in a consistent layout
2. THE Integration_Card SHALL provide Connect and Disconnect buttons, where Disconnect shows a confirmation modal before proceeding
3. THE Integration_Card SHALL provide a Test Connection button that shows a spinner during testing, a green tick with timestamp on success, and a red X with a human-readable error message on failure (never raw API error codes)
4. WHEN a user disconnects an integration, THE Integration_Card SHALL delete stored tokens from the database (not just flag as inactive)
5. THE Integration_Card SHALL write an audit log entry on every connect, disconnect, and test connection action
6. THE Integration_Card SHALL mask all stored credentials in API responses (never return raw tokens or secrets)

---

## Cross-Cutting Requirements (All Sprints)

---

### Requirement 32: Row-Level Security

**User Story:** As a platform operator, I want all accounting data isolated per organisation, so that no organisation can access another's financial data.

#### Acceptance Criteria

1. FOR ALL new tables (accounts, journal_entries, journal_lines, accounting_periods, gst_filing_periods, akahu_connections, bank_accounts, bank_transactions, tax_wallets, tax_wallet_transactions, ird_filing_log), THE Database migration SHALL enable RLS and create policies using org_id = current_setting('app.current_org_id')::uuid
2. THE RLS policies SHALL follow the exact pattern from migration 0008

---

### Requirement 33: Encrypted Credential Storage

**User Story:** As a platform operator, I want all external service credentials encrypted at rest, so that a database breach does not expose API tokens.

#### Acceptance Criteria

1. FOR ALL external service tokens (Akahu access tokens, IRD credentials, TLS client certificates), THE credential storage SHALL use envelope_encrypt/envelope_decrypt_str from app.core.encryption
2. THE credential storage SHALL mask all credentials in API responses using the pattern from security-hardening-checklist.md
3. WHEN a masked value (matching /^\*+$|^.{0,4}\*{4,}/) is submitted via API, THE credential storage SHALL detect the mask and skip the database update

---

### Requirement 34: Safe Frontend API Consumption

**User Story:** As a developer, I want all frontend code to follow safe API consumption patterns, so that undefined API responses do not crash the UI.

#### Acceptance Criteria

1. FOR ALL frontend components consuming accounting API data, THE Frontend SHALL use optional chaining (?.) and nullish coalescing (?? []) on all array properties from API responses
2. FOR ALL frontend components displaying monetary values from API data, THE Frontend SHALL use nullish coalescing (?? 0) before calling .toLocaleString() or .toFixed()
3. FOR ALL useEffect hooks making API calls, THE Frontend SHALL implement AbortController cleanup
4. THE Frontend SHALL use TypeScript generics on API calls instead of "as any" type assertions

---

### Requirement 35: End-to-End Test Scripts

**User Story:** As a developer, I want e2e test scripts for every sprint, so that features are verified before deployment.

#### Acceptance Criteria

1. FOR EACH sprint, THE test suite SHALL include a scripts/test_{feature}_e2e.py script following the pattern in .kiro/steering/feature-testing-workflow.md
2. THE e2e test scripts SHALL cover authentication flow, CRUD operations, edge cases, and OWASP security checks (broken access control, injection, data integrity)
3. THE e2e test scripts SHALL clean up test data after execution using a recognizable TEST_E2E_ prefix

---

### Requirement 36: HA Replication Compatibility

**User Story:** As a platform operator, I want new tables included in HA replication, so that the standby database stays in sync.

#### Acceptance Criteria

1. WHEN new tables are created, THE Database migration SHALL add them to the HA replication publication (ALTER PUBLICATION ora_publication ADD TABLE ...) if the publication exists
2. THE migration SHALL check for publication existence before attempting to add tables (idempotent)

---

### Requirement 37: Audit Logging

**User Story:** As a platform operator, I want all sensitive accounting operations logged, so that there is a complete audit trail for compliance.

#### Acceptance Criteria

1. THE Audit service SHALL log all integration connect/disconnect/test actions, all GST and income tax filing actions, all period close/lock actions, and all credential access events using the write_audit_log pattern from app.core.audit
2. THE Audit service SHALL include the user_id, org_id, action_type, and relevant entity_id in each log entry

---

## Dependency Map

```
Sprint 1: COA + Ledger (FOUNDATION)
  ├── Sprint 2: Financial Reports + Tax Engine (requires Sprint 1)
  │     └── Sprint 5: Tax Savings Wallet (requires Sprint 2)
  ├── Sprint 3: GST Filing Periods + IRD Readiness (requires Sprint 1)
  │     └── Sprint 6: IRD Gateway Integration (requires Sprint 3 + IRD registration)
  ├── Sprint 4: Akahu Bank Feeds + Reconciliation (requires Sprint 1)
  └── Sprint 7: Business Entity Type + Admin Audit (can parallel with Sprint 4/5)
```

| Sprint | Blocks | Blocked By |
|---|---|---|
| 1 — COA + Ledger | Sprints 2, 3, 4, 5, 6 | Nothing |
| 2 — Reports + Tax Engine | Sprint 5 | Sprint 1 |
| 3 — GST Filing + IRD Readiness | Sprint 6 | Sprint 1 |
| 4 — Akahu Bank Feeds | Nothing | Sprint 1 |
| 5 — Tax Savings Wallet | Nothing | Sprint 2 |
| 6 — IRD Gateway | Nothing | Sprint 3 + IRD registration |
| 7 — Entity Type + Admin Audit | Nothing | Nothing (parallel with 4/5) |

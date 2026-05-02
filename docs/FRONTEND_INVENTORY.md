# Frontend Inventory Report

> Generated 2026-05-02. Covers end-user facing screens only. Admin/platform pages excluded unless noted.

---

## 1. All Pages / Screens

### Public / Guest Pages (no auth required)

| Route | Component | File |
|-------|-----------|------|
| `/` | LandingPage | `pages/public/LandingPage.tsx` |
| `/privacy` | PrivacyPage | `pages/public/PrivacyPage.tsx` |
| `/trades` | TradesPage | `pages/public/TradesPage.tsx` |
| `/login` | Login | `pages/auth/Login.tsx` |
| `/signup` | SignupWizard (lazy, Stripe) | `pages/auth/SignupWizard.tsx` |
| `/mfa-verify` | MfaVerify | `pages/auth/MfaVerify.tsx` |
| `/forgot-password` | PasswordResetRequest | `pages/auth/PasswordResetRequest.tsx` |
| `/reset-password` | PasswordResetComplete | `pages/auth/PasswordResetComplete.tsx` |
| `/verify-email` | VerifyEmail | `pages/auth/VerifyEmail.tsx` |
| `/portal/:token` | PortalPage | `pages/portal/PortalPage.tsx` |
| `/pay/:token` | InvoicePaymentPage (Stripe) | `pages/public/InvoicePaymentPage.tsx` |

### Org Pages (RequireAuth + OrgLayout)

| Route | Component | Module Gate | Notes |
|-------|-----------|-------------|-------|
| `/dashboard` | Dashboard | — | Redirects kiosk → `/kiosk`, global admin → `/admin/dashboard` |
| `/customers` | CustomerList | — | |
| `/customers/new` | CustomerCreate | — | |
| `/customers/:id` | CustomerProfile | — | |
| `/vehicles` | VehicleList | `vehicles` + RequireAutomotive | |
| `/vehicles/:id` | VehicleProfile | `vehicles` + RequireAutomotive | |
| `/invoices` | InvoiceList | — | |
| `/invoices/new` | InvoiceList | — | Opens create sheet |
| `/invoices/:id` | InvoiceList | — | Opens detail panel |
| `/invoices/:id/edit` | InvoiceCreate | — | |
| `/quotes` | QuoteList | `quotes` | |
| `/quotes/new` | QuoteCreate | `quotes` | |
| `/quotes/:id` | QuoteDetail | `quotes` | |
| `/quotes/:id/edit` | QuoteCreate | `quotes` | |
| `/job-cards` | JobCardList | `jobs` | |
| `/job-cards/new` | JobCardCreate | `jobs` | |
| `/job-cards/:id` | JobCardDetail | `jobs` | |
| `/jobs` | JobsPage | `jobs` | Jobs v2 list |
| `/jobs/board` | JobBoard | `jobs` | Kanban view |
| `/jobs/:id` | JobDetail | `jobs` | |
| `/bookings` | BookingCalendarPage | `bookings` | |
| `/inventory` | InventoryPage | `inventory` | |
| `/items` | ItemsPage | `inventory` | |
| `/catalogue` | CataloguePage | `inventory` | |
| `/staff` | StaffList | `staff` | |
| `/staff/:id` | StaffDetail | `staff` | |
| `/projects` | ProjectList | `projects` | |
| `/projects/:id` | ProjectDashboard | `projects` | |
| `/expenses` | ExpenseList | `expenses` | |
| `/time-tracking` | TimeSheet | `time_tracking` | |
| `/schedule` | ScheduleCalendar | `scheduling` | |
| `/pos` | POSScreen | `pos` | |
| `/recurring` | RecurringList | `recurring_invoices` | |
| `/purchase-orders` | POList | `purchase_orders` | |
| `/purchase-orders/:id` | PODetail | `purchase_orders` | |
| `/progress-claims` | ProgressClaimList | `progress_claims` | Construction |
| `/variations` | VariationList | `variations` | Construction |
| `/retentions` | RetentionSummary | `retentions` | Construction |
| `/floor-plan` | FloorPlan | `tables` | Hospitality |
| `/kitchen` | KitchenDisplay | `kitchen_display` | Hospitality |
| `/franchise` | FranchiseDashboard | `franchise` | |
| `/locations` | LocationList | `franchise` | |
| `/locations/:id` | LocationDetail | `franchise` | |
| `/stock-transfers` | StockTransfers | `franchise` | |
| `/branch-transfers` | BranchStockTransfers | `branch_management` | |
| `/staff-schedule` | StaffSchedule | `branch_management` | adminOnly |
| `/assets` | AssetList | `assets` | |
| `/assets/:id` | AssetDetail | `assets` | |
| `/compliance` | ComplianceDashboard | `compliance_docs` | |
| `/loyalty` | LoyaltyConfig | `loyalty` | |
| `/ecommerce` | WooCommerceSetup | `ecommerce` | |
| `/claims` | ClaimsList | `customer_claims` | |
| `/claims/new` | ClaimCreateForm | `customer_claims` | |
| `/claims/:id` | ClaimDetail | `customer_claims` | |
| `/claims/reports` | ClaimsReports | `customer_claims` | |
| `/accounting` | ChartOfAccounts | `accounting` | |
| `/accounting/journal-entries` | JournalEntries | `accounting` | |
| `/accounting/journal-entries/:id` | JournalEntryDetail | `accounting` | |
| `/accounting/periods` | AccountingPeriods | `accounting` | |
| `/reports/profit-loss` | ProfitAndLoss | `accounting` | |
| `/reports/balance-sheet` | BalanceSheet | `accounting` | |
| `/reports/aged-receivables` | AgedReceivables | `accounting` | |
| `/tax/gst-periods` | GstPeriods | `accounting` | |
| `/tax/gst-periods/:id` | GstFilingDetail | `accounting` | |
| `/tax/wallets` | TaxWallets | `accounting` | |
| `/tax/position` | TaxPosition | `accounting` | |
| `/banking/accounts` | BankAccounts | `accounting` | |
| `/banking/transactions` | BankTransactions | `accounting` | |
| `/banking/reconciliation` | ReconciliationDashboard | `accounting` | |
| `/reports` | ReportsPage | — | |
| `/notifications` | NotificationsPage | — | |
| `/data` | DataPage | — | Import/export |
| `/settings` | OrgSettingsPage | — | RequireOrgAdmin |
| `/settings/online-payments` | OnlinePaymentsSettings | — | RequireOrgAdmin |
| `/setup` | SetupWizard | — | |
| `/setup-guide` | SetupGuide | — | |
| `/onboarding` | OnboardingWizard | — | |

### Standalone / Special Pages

| Route | Component | Notes |
|-------|-----------|-------|
| `/kiosk` | KioskPage | RequireAuth, outside OrgLayout, `isKiosk` role |
| `/sms` | SmsChat.tsx (file exists) | **MISSING ROUTE** — in navItems but not in App.tsx |

### Admin Pages (RequireGlobalAdmin — excluded from end-user scope)

Prefix `/admin/*`: dashboard, organisations, users, plans, feature-flags, analytics, settings, security, errors, notifications, branding, migration, live-migration, ha-replication, audit-log, reports, integrations, trade-families, branches, profile.

---

## 2. All Components

### Layout Components

| Component | File | Purpose |
|-----------|------|---------|
| OrgLayout | `layouts/OrgLayout.tsx` | Sidebar + header shell for all org pages |
| AdminLayout | `layouts/AdminLayout.tsx` | Shell for global admin pages |

### Navigation / Chrome

| Component | File | Purpose |
|-----------|------|---------|
| GlobalSearchBar | `components/search/` | Ctrl+K overlay search |
| BranchSelector | `components/branch/BranchSelector.tsx` | Header dropdown for multi-branch |
| BlockingPaymentModal | `components/billing/BlockingPaymentModal.tsx` | Blocks UI when payment method expired |
| ExpiringPaymentWarningModal | `components/billing/ExpiringPaymentWarningModal.tsx` | Warning banner, dismissible |
| NotificationBadge | `pages/compliance/NotificationBadge.tsx` | Badge count on Compliance nav item |

### Module Gating Components

| Component | File | Usage |
|-----------|------|-------|
| ModuleRoute | `components/common/ModuleRoute.tsx` | Route-level: renders `<FeatureNotAvailable>` if module disabled |
| ModuleGate | `components/common/ModuleGate.tsx` | Inline conditional render by module slug |
| FeatureGate | `components/common/FeatureGate.tsx` | Inline conditional render by feature flag key |
| ModulePageWrapper | `components/common/ModulePageWrapper.tsx` | Combines ModuleRoute + FeatureGate + ErrorBoundary + Suspense |

### UI Primitives

Located in `components/ui/`. Key exports: `Spinner`, `Button`, `Badge`, `Modal`, `Table`, `Card`, `Input`, `Select`, `Textarea`, `Toast`, `Tooltip`, `Dropdown`, `Tabs`, `EmptyState`.

### Common Shared Components

| Component | File | Purpose |
|-----------|------|---------|
| ErrorBoundary | `components/ErrorBoundary.tsx` | Multi-level (`app`, `page`) error boundary with retry |
| FeatureNotAvailable | `components/common/FeatureNotAvailable.tsx` | Shown when module is disabled |
| InstallPromptBanner | `components/pwa/InstallPromptBanner.tsx` | PWA install banner |

---

## 3. Data Models (Frontend Types)

### Auth

```ts
interface LoginRequest { email: string; password: string; remember_me?: boolean }
interface TokenResponse { access_token: string; refresh_token?: string; token_type: 'bearer' }
interface MFARequiredResponse { mfa_required: true; mfa_token: string; mfa_methods: string[] }
interface User { id: string; email: string; name: string; role: UserRole; mfa_methods: string[]; has_password: boolean }
type UserRole = 'org_admin' | 'branch_admin' | 'staff' | 'global_admin' | 'kiosk'
```

### Organisation / Tenant

```ts
interface OrgSettings {
  id: string; name: string; currency: string; timezone: string;
  gst_rate: number; gst_registered: boolean; gst_number?: string;
  default_payment_terms: string; trade_family?: string; trade_category?: string;
  branding: OrgBranding; locale: string;
}
interface OrgBranding {
  logo_url?: string; name?: string; primary_color?: string; secondary_color?: string;
  sidebar_display_mode: 'icon_and_name' | 'name_only' | 'icon_only';
}
interface ModuleInfo { slug: string; enabled: boolean; name: string }
```

### Customer

```ts
interface Customer {
  id: string; first_name: string; last_name?: string; email?: string;
  mobile_phone?: string; work_phone?: string; customer_type: 'individual' | 'business';
  company_name?: string; display_name: string; currency: string;
  payment_terms: PaymentTerms; enable_portal: boolean;
  billing_address?: Address; contact_persons: ContactPerson[];
  balance_due: number; total_invoiced: number; created_at: string;
}
type PaymentTerms = 'due_on_receipt' | 'net_7' | 'net_15' | 'net_30' | 'net_45' | 'net_60' | 'net_90'
```

### Invoice

```ts
interface Invoice {
  id: string; invoice_number: string; status: InvoiceStatus;
  customer: Customer; issue_date: string; due_date?: string;
  subtotal: number; gst_amount: number; total: number; amount_due: number;
  currency: string; notes_internal?: string; notes_customer?: string;
  line_items: LineItem[]; payments: Payment[]; credit_notes: CreditNote[];
  vehicle_rego?: string; vehicle_make?: string; vehicle_model?: string;
  payment_page_url?: string; org_name: string; org_logo_url?: string;
  created_at: string; updated_at: string;
}
type InvoiceStatus = 'draft' | 'sent' | 'issued' | 'partially_paid' | 'paid' | 'overdue' | 'voided' | 'refunded' | 'partially_refunded'
interface LineItem {
  id: string; item_type: 'labour' | 'part' | 'fee' | 'other';
  description: string; quantity: number; unit_price?: number;
  rate?: number; hours?: number; hourly_rate?: number;
  discount_type?: 'percent' | 'fixed'; discount_value?: number;
  is_gst_exempt: boolean; line_total: number; sort_order: number;
}
```

### Quote

```ts
interface Quote {
  id: string; quote_number: string; status: 'draft' | 'sent' | 'accepted' | 'declined' | 'expired';
  customer: Customer; valid_until?: string;
  subtotal: number; gst_amount: number; total: number;
  line_items: LineItem[]; notes_customer?: string;
}
```

### Job Card (v1)

```ts
interface JobCard {
  id: string; status: 'open' | 'in_progress' | 'completed' | 'invoiced';
  customer: Customer; vehicle_rego?: string; description?: string; notes?: string;
  line_items: LineItem[]; service_type_id?: string; service_type_values?: Record<string, unknown>;
  timer_start?: string; timer_elapsed_seconds: number;
  created_at: string; updated_at: string;
}
```

### Job (v2)

```ts
interface Job {
  id: string; title: string; status: JobStatus;
  customer?: Customer; project_id?: string; template_id?: string;
  description?: string; priority: 'low' | 'normal' | 'high' | 'urgent';
  scheduled_start?: string; scheduled_end?: string;
  checklist: ChecklistItem[]; internal_notes?: string; customer_notes?: string;
  created_at: string; updated_at: string;
}
type JobStatus = 'draft' | 'scheduled' | 'in_progress' | 'on_hold' | 'completed' | 'invoiced' | 'cancelled'
const VALID_TRANSITIONS: Record<JobStatus, JobStatus[]> = {
  draft: ['scheduled', 'in_progress', 'cancelled'],
  scheduled: ['in_progress', 'on_hold', 'cancelled'],
  in_progress: ['on_hold', 'completed', 'cancelled'],
  on_hold: ['in_progress', 'cancelled'],
  completed: ['invoiced'],
  invoiced: [],
  cancelled: [],
}
```

### Booking

```ts
interface Booking {
  id: string; status: 'pending' | 'confirmed' | 'cancelled' | 'completed';
  customer_name: string; customer_email?: string; customer_phone?: string;
  staff_id?: string; service_type?: string;
  start_time: string; end_time: string; notes?: string;
  converted_job_id?: string; converted_invoice_id?: string;
}
interface TimeSlot { start_time: string; end_time: string; available: boolean }
```

### Vehicle (Automotive)

```ts
interface Vehicle {
  id: string; rego: string; make?: string; model?: string; year?: number;
  colour?: string; vin?: string; chassis?: string; engine_no?: string;
  transmission?: string; wof_expiry?: string; rego_expiry?: string;
  odometer?: number; source: 'cache' | 'carjam';
}
```

### Expense

```ts
interface Expense {
  id: string; org_id: string; job_id?: string; project_id?: string; customer_id?: string;
  date: string; description: string; amount: number; tax_amount: number;
  category: string; reference_number?: string; receipt_file_key?: string;
  is_billable: boolean; is_invoiced: boolean; expense_type: 'expense' | 'mileage';
  created_at: string; updated_at: string;
}
```

### Staff

```ts
interface StaffMember {
  id: string; first_name: string; last_name: string; email: string; phone?: string;
  employee_id?: string; position?: string; reporting_to?: string;
  shift_start?: string; shift_end?: string;
  role_type: 'employee' | 'contractor';
  hourly_rate?: number; overtime_rate?: number;
  availability_schedule?: Record<string, unknown>; skills: string[];
}
```

### Claim

```ts
interface Claim {
  id: string; reference: string;
  claim_type: 'warranty' | 'defect' | 'service_redo' | 'exchange' | 'refund_request';
  status: 'open' | 'investigating' | 'approved' | 'rejected' | 'resolved';
  customer: Customer; description: string;
  invoice_id?: string; job_card_id?: string; line_item_ids?: string[];
  resolution_type?: 'partial_refund' | 'full_refund' | 'credit_note' | 'redo_service' | 'exchange' | 'no_action';
  labour_cost: number; parts_cost: number; write_off_cost: number;
  timeline: ClaimAction[];
}
```

### Recurring Invoice

```ts
type RecurringFrequency = 'weekly' | 'fortnightly' | 'monthly' | 'quarterly' | 'annually'
interface RecurringSchedule {
  id: string; frequency: RecurringFrequency; next_run_date: string;
  customer: Customer; template_line_items: LineItem[];
}
```

---

## 4. Navigation Structure

### Context Provider Tree (App.tsx)

```
ErrorBoundary (app)
  BrowserRouter
    LocaleProvider            ← i18n, 10 locales
      PlatformBrandingProvider ← platform-level branding (SaaS white-label)
        ThemeProvider          ← data-theme on <html>; Classic / Violet
          AuthProvider         ← JWT, user, role, isAuthenticated
            TenantProvider     ← OrgSettings, tradeFamily, CSS vars
              ModuleProvider   ← GET /api/v2/modules → isEnabled()
                FeatureFlagProvider ← GET /api/v2/flags → flags{}
                  BranchProvider ← selectedBranchId, isBranchLocked
                    AppRoutes
```

### Route Guards (nested in App.tsx)

| Guard | Component | Behaviour |
|-------|-----------|-----------|
| `GuestOnly` | Inline fn | Authenticated users → `/dashboard` or `/admin/dashboard`; kiosk → `/kiosk` |
| `RequireAuth` | Inline fn | Unauthenticated → `/login` |
| `RequireGlobalAdmin` | Inline fn | Non-global-admin → `/dashboard` |
| `RequireOrgAdmin` | Inline fn | `branch_admin` role → `/dashboard` |
| `RequireAutomotive` | Inline fn | Non-automotive tradeFamily → `/dashboard` |

### OrgLayout Sidebar Nav (39 items, filtered at runtime)

Order as defined in `navItems` array:

1. Dashboard (always)
2. Customers (always)
3. Vehicles (module: `vehicles`, flagKey: `vehicles`, tradeFamily: `automotive-transport`)
4. Invoices (always)
5. Quotes (module: `quotes`, flagKey: `quotes`)
6. Job Cards (module: `jobs`, flagKey: `jobs`)
7. Jobs (module: `jobs`, flagKey: `jobs`)
8. Bookings (module: `bookings`, flagKey: `bookings`)
9. Inventory (module: `inventory`, flagKey: `inventory`)
10. Items (module: `inventory`)
11. Catalogue (module: `inventory`)
12. Staff (module: `staff`, flagKey: `staff`)
13. Projects (module: `projects`, flagKey: `projects`)
14. Expenses (module: `expenses`, flagKey: `expenses`)
15. Time Tracking (module: `time_tracking`, flagKey: `time_tracking`)
16. Schedule (module: `scheduling`, flagKey: `scheduling`)
17. POS (module: `pos`, flagKey: `pos`)
18. Recurring (module: `recurring_invoices`, flagKey: `recurring`)
19. Purchase Orders (module: `purchase_orders`, flagKey: `purchase_orders`)
20. Progress Claims (module: `progress_claims`, flagKey: `progress_claims`)
21. Variations (module: `variations`, flagKey: `variations`)
22. Retentions (module: `retentions`, flagKey: `retentions`)
23. Floor Plan (module: `tables`, flagKey: `tables`)
24. Kitchen Display (module: `kitchen_display`, flagKey: `kitchen_display`)
25. Franchise (module: `franchise`, flagKey: `franchise`)
26. Branch Transfers (module: `branch_management`, adminOnly: true)
27. Staff Schedule (module: `branch_management`, adminOnly: true)
28. Assets (module: `assets`, flagKey: `assets`)
29. Compliance (module: `compliance_docs`, flagKey: `compliance_docs`)
30. Loyalty (module: `loyalty`, flagKey: `loyalty`)
31. Ecommerce (module: `ecommerce`, flagKey: `ecommerce`)
32. SMS (module: `sms`, flagKey: `sms`) ← **NO ROUTE IN APP.TSX**
33. Claims (module: `customer_claims`)
34. Accounting (module: `accounting`)
35. Banking (module: `accounting`)
36. Tax (module: `accounting`)
37. Notifications (always)
38. Data (always)
39. Reports (always)
40. Settings (adminOnly: true — shown to org_admin/global_admin only)

### Header Quick Actions

Visible based on module/flag gating. Filtered same as navItems:
- New Booking → `/bookings` (state: `{ openNew: true }`)
- New Job Card → `/job-cards/new`
- New Quote → `/quotes/new`
- New Invoice → `/invoices/new`
- New Customer → `/customers/new`

---

## 5. Forms

### Auth Forms

| Form | Fields |
|------|--------|
| Login | email, password, remember_me checkbox |
| Signup Wizard | multi-step: org name, trade, plan, card (Stripe Elements) |
| Forgot Password | email |
| Reset Password | token (query param), new_password, confirm_password |
| MFA Verify | code (6-digit), method (sms/email/totp) |

### Customer Forms

| Form | Key Fields |
|------|-----------|
| Customer Create/Edit | first_name\*, last_name, email, mobile_phone, customer_type (individual/business), company_name, display_name, work_phone, currency, payment_terms, enable_portal, billing_address (street, city, region, postcode, country), contact_persons[] |

### Invoice Forms

| Form | Key Fields |
|------|-----------|
| Invoice Create/Edit | customer_id\*, issue_date, due_date, vehicle_rego (automotive), line_items[], notes_internal, notes_customer (alias: customer_notes), discount_type, discount_value, currency |
| Line Item | item_type, description, quantity, unit_price/rate, hours, hourly_rate, discount_type, discount_value, is_gst_exempt, sort_order |

### Quote Forms

Same structure as Invoice form, plus: valid_until date.

### Job Card Form

customer_id\*, vehicle_rego, description, notes, line_items[], service_type_id, service_type_values

### Job (v2) Form

title\*, customer_id, project_id, template_id, description, priority (low/normal/high/urgent), scheduled_start, scheduled_end, checklist[], internal_notes, customer_notes

### Booking Form

customer_name\*, customer_email, customer_phone, staff_id, service_type, start_time\*, end_time\*, notes

### Expense Form

job_id, project_id, customer_id, date\*, description\*, amount\* (>0), tax_amount, category\*, reference_number, receipt (file upload), is_billable, expense_type (expense/mileage)

### Staff Form

first_name\*, last_name\*, email\*, phone, employee_id, position, reporting_to, shift_start (HH:MM), shift_end (HH:MM), role_type (employee/contractor), hourly_rate, overtime_rate, availability_schedule, skills[]

### Claim Form

customer_id\*, claim_type\*, description\*, invoice_id (optional), job_card_id (optional), line_item_ids[]

### Settings Form (OrgSettingsPage tabs)

Tabs include: Profile, Branding, Notifications, Team, Billing/Subscription, Integrations, Templates.

---

## 6. Tables / Lists

| Screen | Key Columns | Filters / Sort |
|--------|-------------|----------------|
| CustomerList | Name, Email, Phone, Type, Balance Due, Created | Search, customer_type filter |
| InvoiceList | Invoice #, Customer, Date, Due, Status, Total, Amount Due | Status filter, date range, search |
| QuoteList | Quote #, Customer, Date, Valid Until, Status, Total | Status filter, search |
| JobCardList | #, Customer, Vehicle, Status, Created | Status filter, search |
| JobsPage | Title, Customer, Status, Priority, Scheduled Start | Status, priority filters |
| JobBoard | Kanban columns by JobStatus | Drag-drop status change |
| BookingCalendarPage | Calendar grid; list view: Customer, Service, Staff, Time, Status | Date nav, staff filter |
| InventoryPage | SKU, Name, Category, Stock, Unit Price, Reorder Level | Category filter, search |
| StaffList | Name, Email, Role Type, Position, Rate | Search |
| ProjectList | Name, Customer, Status, Budget, Start/End | Status filter |
| ExpenseList | Date, Description, Amount, Category, Customer, Billable, Invoiced | Date range, category, billable filter |
| TimeSheet | Date, Staff, Job/Project, Hours, Rate, Billable | Date range, staff filter |
| RecurringList | Customer, Frequency, Next Run, Amount | Frequency filter |
| POList | PO #, Supplier, Status, Amount, Date | Status filter |
| ClaimsList | Reference, Customer, Type, Status, Created | Status, type filters |
| AssetList | Name, Category, Serial, Status, Assigned To | Status filter |
| ComplianceDashboard | Doc name, Expiry, Status, Assigned | Status filter; badge count in nav |
| AgedReceivables | Customer, 0-30, 31-60, 61-90, 90+ days | Sort by column |
| BankTransactions | Date, Description, Amount, Account, Reconciled | Date range, account filter |
| GstPeriods | Period, Start, End, GST Collected, GST Paid, Net, Filed | Status filter |

---

## 7. Auth Flow

### Login Flow

1. `POST /api/v1/auth/login` with `{ email, password, remember_me }`
2. **Success (no MFA)**: returns `{ access_token, refresh_token }` → store access token in memory; refresh token stored in httpOnly cookie (web) or SecureStore (mobile)
3. **MFA required**: returns `{ mfa_required: true, mfa_token, mfa_methods[] }` → redirect to `/mfa-verify`
4. On MFA verify: `POST /api/v1/auth/mfa/send` then `POST /api/v1/auth/mfa/verify` → returns same token pair as step 2

### Token Refresh

- Axios interceptor on 401: calls `POST /api/v1/auth/refresh` with the httpOnly cookie
- Deduplication mutex prevents parallel refresh storms
- On failure: clears state, navigates to `/login`

### Role Redirects

| Role | Post-login destination |
|------|----------------------|
| `global_admin` | `/admin/dashboard` |
| `kiosk` | `/kiosk` |
| `org_admin` / `branch_admin` / `staff` | `/dashboard` |

### Session Guards Summary

- `GuestOnly`: if authenticated, redirects based on role
- `RequireAuth`: unauthenticated → `/login`
- `RequireGlobalAdmin`: non-global-admin → `/dashboard`
- `RequireOrgAdmin`: `branch_admin` → `/dashboard`
- `RequireAutomotive`: non-automotive org → `/dashboard`

### Logout

`POST /api/v1/auth/logout` → clears in-memory access token + refreshes cookie → navigate to `/login`

### MFA Methods

Supported: `sms`, `email`, `totp` (authenticator app), WebAuthn/Passkeys (registration at `/settings?tab=profile`)

### Email Verification

`GET /verify-email?token=...` → `POST /api/v1/auth/verify-email`

---

## 8. Module Gating Logic — CRITICAL

### Three-Layer System

**Layer 1 — ModuleContext** (`contexts/ModuleContext.tsx`)
- Fetches `GET /api/v2/modules` on authenticated session start
- Returns `ModuleInfo[]` with `{ slug, enabled, name }`
- Exposes `isEnabled(slug: string): boolean`

**Layer 2 — FeatureFlagContext** (`contexts/FeatureFlagContext.tsx`)
- Fetches `GET /api/v2/flags` on authenticated session start
- Returns `Record<string, boolean>` flag map
- Exposes `flags` object and `useFlag(key): boolean`

**Layer 3 — Component Wrappers**

| Component | File | How to use |
|-----------|------|-----------|
| `ModuleRoute` | `components/common/ModuleRoute.tsx` | Wraps a `<Route>` element; renders `<FeatureNotAvailable>` if `!isEnabled(moduleSlug)` |
| `ModuleGate` | `components/common/ModuleGate.tsx` | Inline: `<ModuleGate module="x">children</ModuleGate>` or `fallback` prop |
| `FeatureGate` | `components/common/FeatureGate.tsx` | Inline: `<FeatureGate flag="x">children</FeatureGate>` |
| `ModulePageWrapper` | `components/common/ModulePageWrapper.tsx` | Full page: module guard + flag check + ErrorBoundary + Suspense |

### Nav Item Visibility Logic (OrgLayout)

```ts
visibleNavItems = navItems.filter(item => {
  if (item.adminOnly && role !== 'org_admin' && role !== 'global_admin') return false
  if (item.tradeFamily && (tradeFamily ?? 'automotive-transport') !== item.tradeFamily) return false
  if (item.module) return isEnabled(item.module)      // module check takes priority
  if (item.flagKey && !flags[item.flagKey]) return false
  return true
})
```

### Module Slugs Reference

| Slug | Nav Label | Notes |
|------|-----------|-------|
| `vehicles` | Vehicles | Also requires `tradeFamily === 'automotive-transport'` |
| `quotes` | Quotes | |
| `jobs` | Job Cards + Jobs | Shared slug for both v1 job cards and v2 jobs |
| `bookings` | Bookings | |
| `inventory` | Inventory + Items + Catalogue | |
| `staff` | Staff | |
| `projects` | Projects | |
| `expenses` | Expenses | |
| `time_tracking` | Time Tracking | |
| `scheduling` | Schedule | |
| `pos` | POS | |
| `recurring_invoices` | Recurring | |
| `purchase_orders` | Purchase Orders | |
| `progress_claims` | Progress Claims | Construction vertical |
| `variations` | Variations | Construction vertical |
| `retentions` | Retentions | Construction vertical |
| `tables` | Floor Plan | Hospitality vertical |
| `kitchen_display` | Kitchen Display | Hospitality vertical |
| `franchise` | Franchise + Locations + Stock Transfers | |
| `branch_management` | Branch Transfers + Staff Schedule | adminOnly items |
| `assets` | Assets | |
| `compliance_docs` | Compliance | |
| `loyalty` | Loyalty | |
| `ecommerce` | Ecommerce | |
| `sms` | SMS | Nav item exists; **no route defined** |
| `customer_claims` | Claims | |
| `accounting` | Accounting + Banking + Tax | |

### Trade Family Gating

`tradeFamily` is sourced from `TenantContext` (org settings). When null, treated as `'automotive-transport'` for backward compatibility.

Only `'automotive-transport'` orgs see the Vehicles nav item and `/vehicles/*` routes (`RequireAutomotive` guard wraps those routes at the router level).

---

## 9. Frontend Logic to Preserve

### Token Refresh Mutex

Axios interceptors use a mutex (single in-flight refresh promise) to prevent parallel 401 responses from each triggering their own refresh call. Critical to preserve — removing it causes token invalidation storms.

### Offline POS Queue

`POSScreen` uses `localStorage` to queue transactions when `navigator.onLine` is false. `OfflineContext` tracks connectivity state. Queued items are replayed on reconnect. **Do not refactor to in-memory state** — localStorage survives page refresh which is critical for this use case.

### TenantContext Branding Application

`applyBrandingCssVars()` in `TenantContext` applies `--color-primary` and `--color-secondary` as CSS vars on `:root` when org settings load. These override theme defaults. **Must run after org settings fetch**, not before.

### InvoiceList as Detail Panel

`/invoices`, `/invoices/:id`, and `/invoices/new` all render `InvoiceList`. The list component reads route params / location state to open the correct panel. This single-component pattern is intentional — **do not split into separate components** without also updating all three routes.

### GST Calculation

- Default NZ rate: 15% (configurable per org via `OrgSettings.gst_rate`)
- GST-exclusive by default: `gst = subtotal * rate`
- Line-item level: `is_gst_exempt` flag skips GST for that line
- High-value threshold: `NZD 1000.00` — triggers additional compliance fields
- All monetary values stored and transmitted as strings/Decimal to avoid float rounding

### Job v2 State Machine

Enforce `VALID_TRANSITIONS` on the frontend before calling `POST /api/v2/jobs/:id/status`. Do not allow buttons/actions for invalid transitions. Backend also validates but frontend should match to prevent confusing 422 errors.

### Automotive-Specific Fields

Invoices for automotive orgs include: `vehicle_rego`, `vehicle_make`, `vehicle_model`, `vehicle_year`, `odometer_in`, `odometer_out`. These fields are only shown when `tradeFamily === 'automotive-transport'`.

### Progress Claim Calculations

```
revised_contract = original_contract + sum(approved_variations)
this_period_amount = this_period_percent * revised_contract / 100
retention_amount = this_period_amount * retention_rate / 100
amount_due = this_period_amount - retention_amount - previous_claimed
```

These calculations must match backend; frontend shows live preview as user inputs values.

### BranchContext Scoping

When a branch is selected via `BranchSelector`, all API requests include a branch filter. `isBranchLocked` is true for `branch_admin` role (auto-scoped to their branch, selector hidden). Data fetches must pass `branch_id` param when branch context is active.

### i18n / TerminologyContext

`LocaleProvider` supports 10 locales: `en, hi, mi, de, fr, es, pt, ar, ja, zh`. `TerminologyContext` allows orgs to override labels (e.g. "Job Card" → "Work Order"). All user-facing labels should go through the terminology system, not hardcoded strings.

### Global Admin "View as Org" Mode

`sessionStorage.getItem('admin_view_as_org')` determines if a global admin is impersonating an org. OrgLayout shows a blue banner with org name and "Back to Admin" button. The `/dashboard` route checks this flag to decide which dashboard to render.

---

## 10. Color Scheme and Typography

### Themes

Two themes defined in `frontend/src/styles/themes.css`, toggled via `data-theme` on `<html>`:

#### Classic Theme (default)

| Variable | Value | Usage |
|----------|-------|-------|
| `--sidebar-bg` | `#ffffff` | Sidebar background |
| `--sidebar-text` | `#374151` | Nav item text |
| `--sidebar-active-bg` | `#eff6ff` | Active nav item background |
| `--sidebar-active-text` | `#2563eb` | Active nav item text |
| `--sidebar-active-border` | `#2563eb` | Active nav item left border |
| `--sidebar-border` | `#e5e7eb` | Sidebar right border |
| `--color-primary` | `#2563eb` | Primary accent (buttons, links) |
| `--color-primary-hover` | `#1d4ed8` | Primary hover |
| `--content-bg` | `#f9fafb` | Page content background |
| `--card-bg` | `#ffffff` | Card/panel background |
| `--card-border` | `#e5e7eb` | Card border |
| `--card-radius` | `0.375rem` | Card border radius |
| `--input-border` | `#d1d5db` | Form input border |
| `--input-focus-ring` | `#93bbfd` | Focus ring colour |
| `--btn-danger-bg` | `#dc2626` | Destructive button |
| `--transition-speed` | `150ms` | UI transition duration |

#### Violet Theme

| Variable | Value | Notes vs Classic |
|----------|-------|-----------------|
| `--sidebar-bg` | `#1e1b4b` | Dark indigo sidebar |
| `--sidebar-text` | `rgba(255,255,255,0.75)` | Light text on dark |
| `--sidebar-active-bg` | `rgba(139,92,246,0.25)` | Purple tint |
| `--sidebar-active-border` | `#8b5cf6` | Purple border |
| `--color-primary` | `#7c3aed` | Purple accent |
| `--card-radius` | `0.75rem` | More rounded cards |
| `--input-radius` | `0.5rem` | More rounded inputs |
| `--transition-speed` | `200ms` | Slightly slower transitions |

The Violet theme also globally remaps Tailwind `bg-blue-600` and related classes to purple equivalents via `!important` overrides in the CSS file.

### Org Branding Override

`TenantContext.applyBrandingCssVars()` overrides `--color-primary` and `--color-secondary` from org settings at runtime. Default primary: `#2563eb`, default secondary: `#1e40af`.

### Typography

- Base font: system-ui / Tailwind default (no custom font loaded)
- Base text: `text-gray-900` (`#111827`)
- Muted text: `text-gray-500` (`#6b7280`)
- Headings: `font-semibold` or `font-bold`
- Form inputs: `h-[42px]` enforced globally in `index.css`
- Nav items: `min-h-[44px]` for touch accessibility

---

## 11. API Base URL and Key Endpoints

### Base URL

`VITE_API_BASE_URL` (env var) — typically `http://localhost:8000` in dev, production domain in prod.

### Auth (`/api/v1/auth/`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/login` | Email/password login |
| POST | `/refresh` | Refresh access token (httpOnly cookie) |
| POST | `/logout` | Invalidate session |
| POST | `/mfa/send` | Send MFA code |
| POST | `/mfa/verify` | Verify MFA code → full tokens |
| POST | `/register` | New org signup |
| POST | `/forgot-password` | Send reset email |
| POST | `/reset-password` | Complete reset |
| POST | `/verify-email` | Verify email token |
| GET | `/me` | Current user profile |

### Core Modules (`/api/v1/`)

| Prefix | Key Endpoints |
|--------|--------------|
| `/customers` | CRUD, search, portal toggle |
| `/invoices` | CRUD, send, void, list |
| `/payments` | Record payment, list |
| `/quotes` | CRUD, send, accept/decline |
| `/job-cards` | CRUD, status change, timer |
| `/bookings` | CRUD, availability slots |
| `/inventory` | Stock items CRUD, adjustments |
| `/reports` | Various report exports |
| `/portal` | Public portal endpoints |
| `/claims` | CRUD, status transitions |
| `/dashboard` | Summary stats, today's bookings |
| `/ledger` | Ledger entries |
| `/gst` | GST period management |
| `/banking` | Bank accounts, transactions |

### Extended Modules (`/api/v2/`)

| Prefix | Key Endpoints |
|--------|--------------|
| `/modules` | `GET /` → `ModuleInfo[]` |
| `/flags` | `GET /` → `Record<string, boolean>` |
| `/jobs` | CRUD, status change, board view |
| `/time-entries` | CRUD, timer start/stop |
| `/projects` | CRUD, summary |
| `/expenses` | CRUD, mileage |
| `/purchase-orders` | CRUD, approve |
| `/staff` | CRUD |
| `/bookings` | CRUD (v2 bookings) |
| `/suppliers` | CRUD |
| `/pos` | Sale transactions, queue |
| `/uploads` | File upload (receipts, attachments) |

### Public Endpoints (no auth)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/portal/:token` | Portal access by token |
| GET/POST | `/portal/:token/invoices` | Portal invoice list/pay |
| GET | `/pay/:token` | Public invoice payment page data |
| POST | `/pay/:token/stripe` | Stripe payment intent creation |

### Org Settings

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/org/settings` | Fetch org settings + branding |
| PATCH | `/org/settings` | Update settings |

---

## 12. Third-Party Integrations

### Stripe

- **Use**: Subscription payments (signup), online invoice payments (Stripe Connect)
- **Frontend**: `@stripe/stripe-js`, `@stripe/react-stripe-js` (Stripe Elements)
- **Key files**: `pages/auth/SignupWizard.tsx` (subscription), `pages/public/InvoicePaymentPage.tsx` (pay page), `pages/settings/OnlinePaymentsSettings.tsx` (Connect onboarding)
- **Note**: Lazy-loaded to prevent ad-blocker crashes on page load
- **Backend proxy**: Stripe Connect per-org accounts; frontend never holds secret key

### Firebase

- **Use**: Phone Auth / SMS MFA (invisible reCAPTCHA)
- **Config vars**: `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`
- **Behaviour**: reCAPTCHA badge hidden via `.grecaptcha-badge { visibility: hidden }` in `index.css`

### CarJam (NZ Vehicle Lookup)

- **Use**: Automotive orgs — lookup vehicle details by rego plate
- **Frontend**: calls backend proxy endpoint, never CarJam directly
- **Backend env**: `CARJAM_API_KEY`
- **Response**: make, model, year, colour, WOF expiry, rego expiry, odometer

### Google OAuth

- **Use**: Social login ("Sign in with Google")
- **Config**: `VITE_GOOGLE_CLIENT_ID`
- **Backend env**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

### WebAuthn / Passkeys

- **Use**: Passwordless login / strong 2nd factor
- **Config**: `WEBAUTHN_RP_ID` (backend), typically the apex domain
- **Frontend**: browser WebAuthn API; registration + assertion flows in settings

### WooCommerce

- **Use**: Ecommerce integration (sync products/orders)
- **Frontend**: `pages/ecommerce/WooCommerceSetup.tsx` (module: `ecommerce`)
- **Config**: store URL + consumer key/secret stored per-org in backend

### i18n (react-i18next)

- **Use**: 10 locale strings (en, hi, mi, de, fr, es, pt, ar, ja, zh)
- **Frontend**: `LocaleProvider` wrapping entire app; `useTranslation()` hook

### PWA / Capacitor

- **PWA**: `InstallPromptBanner` component, service worker, `manifest.json`
- **Capacitor**: Native iOS/Android wrapper for mobile app builds
- **Relevant**: `frontend/capacitor.config.ts`, `android/` directory

### Sentry (inferred)

- Error boundaries at app + page level suggest structured error reporting
- `ErrorBoundary` component wraps all lazy-loaded pages

---

## Known Gaps / Items to Review

1. **`/sms` route missing**: `SmsChat.tsx` exists in pages, nav item defined (module: `sms`, flagKey: `sms`), but no `<Route path="/sms">` exists in `App.tsx`.
2. **`/portal/:token/payment-success`**: No route defined for post-payment success redirect (CP-005).
3. **Portal VehicleHistory**: `VehicleHistory.tsx` typed to receive array but backend returns `{ branding, vehicles }` object — will crash on `.map()` (CP-002).
4. **Portal `PortalInfo` type mismatch**: Frontend type does not match `PortalAccessResponse` backend schema (CP-001).
5. **Dashboard SQL bug (ISSUE-144)**: `get_todays_bookings` joins on `bookings.customer_id` which does not exist (column is `customer_name`).
6. **Rate limiter double-response (ISSUE-145)**: `rate_limit.py` except block calls `self.app()` instead of `raise`, causing ASGI double-response.

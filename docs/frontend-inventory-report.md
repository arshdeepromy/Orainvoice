# OraInvoice Frontend Codebase — Complete Inventory Report

**Generated**: 2026-04-30
**Purpose**: Full inventory of end-user facing pages, components, data models, navigation, forms, module gating, and design tokens.

---

## 1. Architecture Overview

### Tech Stack
- React 18 + TypeScript + Vite 6
- Tailwind CSS (default config, no custom theme extensions)
- Axios HTTP client (baseURL: `/api/v1`)
- React Router DOM v7

### Core Contexts (State Management)
- **AuthContext** — User auth, roles, MFA, JWT handling
- **ModuleContext** — Feature module gating (enabled/disabled per org)
- **BranchContext** — Multi-branch selection, branch-scoped filtering
- **TenantContext** — Org settings (branding, GST, invoice config, trade family)
- **FeatureFlagContext** — Feature flags
- **LocaleContext** — Internationalization
- **ThemeContext** — Dark mode
- **PlatformBrandingContext** — Global platform branding

### Layouts
- **OrgLayout** — Main layout with sidebar nav, header, quick actions, branch selector, user menu
- **AdminLayout** — Global admin layout (EXCLUDED from this report)
- **PortalLayout** — Public customer portal layout

### API Client
- Axios-based with JWT Bearer token injection
- X-Branch-Id header from localStorage
- 401 refresh token rotation with global mutex
- Safe response handling: all arrays wrapped in objects, `?.` and `?? []` everywhere

---

## 2. All Pages/Screens (End-User Facing)

### Authentication and Public Pages

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/login` | Login | Login form | Email/password login, Google OAuth, Passkey login | `POST /auth/login`, `POST /auth/login/google`, `POST /auth/login/passkey` |
| `/login/mfa` | MfaVerify | MFA challenge | Enter TOTP/SMS code, select method | `POST /auth/mfa/verify` |
| `/signup` | SignupWizard | Registration form + Stripe payment | Create account, select plan, enter payment | `POST /auth/register`, Stripe Elements |
| `/forgot-password` | PasswordResetRequest | Email form | Request password reset | `POST /auth/password-reset/request` |
| `/reset-password` | PasswordResetComplete | New password form | Set new password | `POST /auth/password-reset/complete` |
| `/verify-email` | VerifyEmail | Verification status | Auto-verify via token | `POST /auth/verify-email` |
| `/` | LandingPage | Marketing content, features, pricing | Navigate to signup/login, request demo | None |
| `/privacy` | PrivacyPage | Privacy policy text | Read | None |
| `/trades` | TradesPage | Trade family descriptions | Browse trades | None |
| `/pay/:token` | InvoicePaymentPage | Public invoice view | Pay invoice via Stripe | `GET /public/invoice/:token`, Stripe |

### Dashboard

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/dashboard` | Dashboard | Revenue stats, recent invoices, overdue count, job summary | View metrics, navigate to sections | `GET /dashboard/stats`, `GET /invoices?status=overdue` |

### Invoices

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/invoices` | InvoiceList | Invoice list (left sidebar) + detail preview (right panel) with POS receipt | Search, filter by status, paginate, select invoice, send email, mark as sent, void, duplicate, download PDF, print, print POS receipt, record payment, create credit note, process refund, share link, delete, view attachments | `GET /invoices`, `GET /invoices/:id`, `POST /invoices/:id/email`, `PUT /invoices/:id/issue`, `PUT /invoices/:id/void`, `POST /invoices/:id/duplicate`, `GET /invoices/:id/pdf`, `POST /payments/cash`, `POST /invoices/:id/share`, `POST /invoices/bulk-delete`, `GET /invoices/:id/attachments`, `DELETE /invoices/:id/attachments/:aid`, `POST /invoices/:id/send-reminder` |
| `/invoices/new` | InvoiceCreate | Invoice creation form | Select customer, add vehicles, add line items (from catalogue/inventory/labour), set discounts, GST, shipping, terms, attach files, save as draft, save and send, mark paid and email | `POST /invoices`, `GET /catalogue/items`, `GET /org/salespeople`, `GET /inventory/stock-items`, `GET /catalogue/labour-rates`, `POST /invoices/:id/attachments`, `GET /payments/online-payments/status` |
| `/invoices/:id/edit` | InvoiceCreate (edit mode) | Existing invoice data pre-filled | Edit all fields, upload new attachments, delete existing attachments | `GET /invoices/:id`, `PUT /invoices/:id`, `GET /invoices/:id/attachments`, `DELETE /invoices/:id/attachments/:aid`, `POST /invoices/:id/attachments` |

### Customers

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/customers` | CustomerList | Customer table with name, email, phone, company, receivables, credits | Search, paginate, create, edit, view detail, configure WOF/service reminders, delete | `GET /customers`, `POST /customers`, `PUT /customers/:id`, `DELETE /customers/:id`, `GET /customers/:id/reminders`, `PUT /customers/:id/reminders`, `PUT /customers/:id/vehicle-dates` |
| `/customers/new` | CustomerCreate | Customer creation form | Fill name, email, phone, company, address, save | `POST /customers` |
| `/customers/:id` | CustomerProfile | Full customer profile, invoice history, vehicle history, communication log | View details, edit, view linked invoices/vehicles | `GET /customers/:id`, `GET /invoices?customer_id=:id`, `GET /vehicles?customer_id=:id` |

### Quotes (Module: `quotes`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/quotes` | QuoteList | Quote list with status, customer, total | Search, filter, create, view detail | `GET /quotes` |
| `/quotes/new` | QuoteCreate | Quote creation form | Add line items, set terms, save, send | `POST /quotes` |
| `/quotes/:id` | QuoteDetail | Quote detail with line items, status | Send, convert to invoice, edit, duplicate | `GET /quotes/:id`, `POST /quotes/:id/convert`, `POST /quotes/:id/email` |

### Job Cards (Module: `jobs`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/job-cards` | JobCardList | Job card list with status, customer, vehicle, assigned staff | Search, filter, create, view detail | `GET /job-cards` |
| `/job-cards/new` | JobCardCreate | Job card creation form | Select customer, vehicle, add parts/labour, assign staff, save | `POST /job-cards` |
| `/job-cards/:id` | JobCardDetail | Full job card with parts, labour, notes, attachments, status history | Edit, add parts/labour, upload attachments, complete job (creates invoice), assign | `GET /job-cards/:id`, `PUT /job-cards/:id`, `POST /job-cards/:id/complete`, `POST /job-cards/:id/attachments` |
| `/jobs` | JobsPage | Active jobs board with live timers | Start/stop timer, assign to me, take over, confirm done | `GET /job-cards?status=open,in_progress`, `POST /job-cards/:id/start-timer`, `POST /job-cards/:id/stop-timer`, `PUT /job-cards/:id/assign`, `POST /job-cards/:id/complete` |

### Vehicles (Module: `vehicles`, Trade: `automotive-transport`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/vehicles` | VehicleList | Vehicle table with rego, make, model, year, WOF expiry, owner | Search by rego, paginate, view profile | `GET /vehicles` |
| `/vehicles/:id` | VehicleProfile | Full vehicle detail, service history, WOF/rego expiry, linked customer | View history, edit dates | `GET /vehicles/:id` |

### Bookings (Module: `bookings`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/bookings` | BookingCalendarPage | Calendar view of bookings | Create booking, edit, delete, drag-and-drop reschedule, create job from booking | `GET /bookings`, `POST /bookings`, `PUT /bookings/:id`, `DELETE /bookings/:id` |

### Inventory (Module: `inventory`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/inventory` | InventoryPage | Tabbed view: Stock Levels, Usage History, Update Log, Reorder Alerts, Suppliers | View stock, adjust quantities, set reorder points, manage suppliers, CSV import | `GET /inventory/stock-items`, `POST /inventory/stock-items`, `PUT /inventory/stock-items/:id`, `POST /inventory/stock-items/:id/adjust`, `GET /inventory/suppliers`, `POST /inventory/import` |
| `/items` | ItemsPage | Catalogue items, labour rates, service types | Create/edit catalogue items, set prices, manage labour rates | `GET /catalogue/items`, `POST /catalogue/items`, `PUT /catalogue/items/:id`, `GET /catalogue/labour-rates` |

### Staff (Module: `staff`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/staff` | StaffList | Staff table with name, role, branch, status | Create, edit, deactivate staff | `GET /api/v2/staff`, `POST /api/v2/staff`, `PUT /api/v2/staff/:id` |

### Projects (Module: `projects`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/projects` | ProjectList | Project list with name, status, budget, progress | Create, view dashboard | `GET /projects` |
| `/projects/:id` | ProjectDashboard | Project detail, financials, tasks, progress | Edit, add tasks, track budget | `GET /projects/:id` |

### Expenses (Module: `expenses`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/expenses` | ExpenseList | Expense table with date, category, amount, receipt | Create, edit, attach receipt, categorize | `GET /api/v2/expenses`, `POST /api/v2/expenses` |

### Time Tracking (Module: `time_tracking`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/time-tracking` | TimeSheet | Timesheet entries by date/job | Clock in/out, add manual entries, view totals | `GET /api/v2/time-entries`, `POST /api/v2/time-entries` |

### Schedule (Module: `scheduling`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/schedule` | ScheduleCalendar | Visual calendar of staff/bay schedules | Create/edit schedule entries, drag-and-drop | `GET /api/v2/schedule`, `POST /api/v2/schedule` |

### POS (Module: `pos`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/pos` | POSScreen | Product grid, order panel, payment panel | Add items to order, apply discounts, process payment, print receipt | `GET /catalogue/items`, `POST /invoices`, `POST /payments/cash` |

### Recurring Invoices (Module: `recurring_invoices`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/recurring` | RecurringList | Recurring invoice templates with frequency, next date | Create, edit, pause, resume, delete | `GET /api/v2/recurring`, `POST /api/v2/recurring` |

### Purchase Orders (Module: `purchase_orders`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/purchase-orders` | POList | PO list with supplier, status, total | Create, view detail | `GET /api/v2/purchase-orders` |
| `/purchase-orders/:id` | PODetail | PO detail with line items, delivery status | Edit, receive stock, mark complete | `GET /api/v2/purchase-orders/:id`, `PUT /api/v2/purchase-orders/:id` |

### Construction Pages (Module: `progress_claims`, `variations`, `retentions`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/progress-claims` | ProgressClaimList | Progress claims with project, amount, status | Create, submit, approve | `GET /progress-claims` |
| `/variations` | VariationList | Contract variations with description, cost impact | Create, approve, reject | `GET /variations` |
| `/retentions` | RetentionSummary | Retention amounts by project | View, release retention | `GET /retentions` |

### Hospitality Pages (Module: `tables`, `kitchen_display`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/floor-plan` | FloorPlan | Table layout, reservations | Manage tables, seat customers, manage reservations | `GET /tables`, `POST /reservations` |
| `/kitchen` | KitchenDisplay | Active orders for kitchen staff | Mark items ready, view order queue | `GET /kitchen/orders`, `PUT /kitchen/orders/:id` |

### Franchise (Module: `franchise`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/franchise` | FranchiseDashboard | Multi-location overview | View location performance | `GET /api/v2/franchise/dashboard` |
| `/franchise/locations` | LocationList | Location list | Manage locations | `GET /api/v2/franchise/locations` |
| `/franchise/transfers` | StockTransfers | Inter-location stock transfers | Create, approve transfers | `GET /api/v2/franchise/transfers` |

### Assets (Module: `assets`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/assets` | AssetList | Asset table with name, category, value, depreciation | Create, edit, view detail | `GET /assets` |
| `/assets/:id` | AssetDetail | Asset detail with depreciation schedule, maintenance log | Edit, record maintenance | `GET /assets/:id` |

### Compliance (Module: `compliance_docs`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/compliance` | ComplianceDashboard | Document list with expiry dates, status badges, summary cards | Upload documents, edit, delete, preview, filter by status | `GET /api/v2/compliance-docs`, `POST /api/v2/compliance-docs`, `DELETE /api/v2/compliance-docs/:id` |

### SMS (Module: `sms`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/sms` | SmsChat | SMS conversation threads | Send/receive SMS, view usage | `GET /sms/conversations`, `POST /sms/send` |

### Accounting (Module: `accounting`)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/accounting` | ChartOfAccounts | Chart of accounts tree | Create/edit accounts | `GET /accounting/accounts` |
| `/accounting/journals` | JournalEntries | Journal entry list | Create manual entries | `GET /accounting/journals` |
| `/banking/accounts` | BankAccounts | Bank account list with balances | Add accounts, view transactions | `GET /banking/accounts` |
| `/banking/transactions` | BankTransactions | Transaction list | Categorize, reconcile | `GET /banking/transactions` |
| `/banking/reconciliation` | ReconciliationDashboard | Reconciliation status | Match transactions | `GET /banking/reconciliation` |
| `/tax/gst-periods` | GstPeriods | GST filing periods | File GST return | `GET /tax/gst-periods` |
| `/tax/wallets` | TaxWallets | Tax wallet balances | View tax position | `GET /tax/wallets` |

### Reports

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/reports` | ReportsPage | Report hub with categories | Select report type, set date range, export PDF/CSV | Various `/reports/*` endpoints |

Report types: Revenue Summary, P&L, Balance Sheet, Aged Receivables, Customer Statement, Invoice Status, Outstanding Invoices, Job Report, Project Report, Fleet Report, Inventory Report, Hospitality Report, POS Report, CarJam Usage, SMS Usage, Storage Usage, GST Return, Tax Return, Top Services.

### Notifications

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/notifications` | NotificationsPage | Notification preferences, overdue rules, reminder templates, WOF/rego reminders | Configure notification channels, set overdue rules, edit templates | `GET /notifications/preferences`, `PUT /notifications/preferences`, `GET /notifications/overdue-rules`, `PUT /notifications/overdue-rules` |

### Data Import/Export

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/data` | DataPage | Import/export hub | Import CSV, export data, bulk JSON import | `POST /data/import`, `GET /data/export` |

### Customer Portal (Public)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/portal` | PortalPage | Customer self-service: invoices, payments, quotes, bookings, vehicle history | View invoices, pay online, accept quotes, book appointments | Portal-specific endpoints |

### Kiosk

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/kiosk` | KioskPage | Check-in screen | Customer self check-in | `POST /kiosk/check-in` |

### Settings (End-User Facing — org_admin role)

| Route | Page Component | Data Displayed | User Actions | API Endpoints |
|-------|---------------|----------------|--------------|---------------|
| `/settings` | Settings | Settings hub with tabs | Navigate to setting sections | Various |
| `/settings?tab=online-payments` | OnlinePaymentsSettings | Stripe connection status | Connect/disconnect Stripe | `GET /payments/online-payments/status`, `POST /payments/online-payments/connect` |

**Note**: Settings page is gated to `org_admin` role. It includes org branding, business settings, branch management, billing, integrations, security/MFA, modules, webhooks, invoice templates, and printer settings.

---

## 3. Data Models (UI Types)

### Invoice
```typescript
{
  id: string
  invoice_number: string | null
  status: 'draft' | 'issued' | 'partially_paid' | 'paid' | 'overdue' | 'voided' | 'refunded' | 'partially_refunded'
  customer_id: string
  customer?: Customer
  vehicle?: Vehicle
  vehicle_rego?: string
  vehicle_make?: string
  vehicle_model?: string
  vehicle_year?: number
  vehicle_odometer?: number
  additional_vehicles?: { rego, make, model, year, wof_expiry, odometer }[]
  line_items: LineItem[]
  subtotal: number
  subtotal_ex_gst?: number
  gst_amount: number
  total: number
  total_incl_gst?: number
  discount_type: 'percentage' | 'fixed' | null
  discount_value: number | null
  discount_amount: number
  amount_paid: number
  balance_due: number
  notes_internal: string | null
  notes_customer: string | null
  issue_date: string | null
  due_date: string | null
  created_at: string
  void_reason?: string
  payments?: PaymentRecord[]
  credit_notes?: CreditNote[]
  org_name, org_logo_url, org_address, org_phone, org_email, org_website: string
  org_gst_number?: string
  payment_terms?: string
  salesperson_name?: string
  attachment_count?: number
  invoice_template_id?: string
  invoice_template_colours?: { primary_colour, accent_colour, header_bg_colour }
  has_stripe_payment?: boolean
  branch_id?: string
}
```

### LineItem
```typescript
{
  id: string
  item_type: string          // 'service' | 'part' | 'labour'
  description: string
  part_number?: string
  quantity: number
  unit_price: number
  hours?: number
  hourly_rate?: number
  is_gst_exempt?: boolean
  discount_type: 'percentage' | 'fixed' | null
  discount_value: number | null
  warranty_note?: string
  line_total: number
  gst_amount?: number
  gst_inclusive?: boolean
  inclusive_price?: number
  catalogue_item_id?: string
  stock_item_id?: string
}
```

### Customer
```typescript
{
  id: string
  first_name: string
  last_name: string
  company_name?: string
  display_name?: string
  email: string
  phone: string
  mobile_phone?: string
  work_phone?: string
  address?: string
  customer_type?: string
  receivables?: number
  unused_credits?: number
  reminders_enabled?: boolean
  branch_id?: string
  linked_vehicles?: LinkedVehicle[]
}
```

### Vehicle
```typescript
{
  id: string
  rego: string
  make: string
  model: string
  year: number | null
  colour: string
  body_type: string
  fuel_type: string
  engine_size: string
  wof_expiry: string | null
  registration_expiry: string | null
  odometer: number | null
  service_due_date?: string | null
}
```

### JobCard
```typescript
{
  id: string
  customer_name: string | null
  vehicle_rego: string | null
  status: 'open' | 'in_progress' | 'completed' | 'invoiced'
  description: string | null
  assigned_to: string | null
  assigned_to_name: string | null
  assigned_to_user_id: string | null
  created_at: string
}
```

### PaymentRecord
```typescript
{
  id: string
  date: string
  amount: number
  method: 'cash' | 'stripe' | 'eftpos' | 'bank_transfer' | 'card' | 'cheque'
  recorded_by: string
  note?: string
  is_refund?: boolean
  refund_note?: string
}
```

### CreditNote
```typescript
{
  id: string
  reference_number: string
  amount: number
  reason: string
  created_at: string
}
```

### InvoiceAttachment
```typescript
{
  id: string
  file_name: string
  mime_type: string
  file_size: number
  created_at: string
  uploaded_by_name?: string
}
```

### CatalogueItem
```typescript
{
  id: string
  name: string
  description?: string
  default_price: number
  gst_applicable: boolean
  gst_inclusive?: boolean
  category?: string
  sku?: string
}
```

### StockItem
```typescript
{
  id: string
  catalogue_item_id: string
  catalogue_type: string       // 'part' | 'tyre' | 'fluid'
  item_name: string
  part_number: string | null
  brand: string | null
  subtitle: string | null
  current_quantity: number
  reserved_quantity: number
  available_quantity: number
  sell_price: number | null
  cost_per_unit: number | null
  gst_mode: string | null      // 'inclusive' | 'exclusive' | 'exempt'
  supplier_name: string | null
  location: string | null
}
```

### AuthUser
```typescript
{
  id: string
  email: string
  name: string
  role: 'global_admin' | 'org_admin' | 'branch_admin' | 'salesperson' | 'kiosk'
  org_id: string | null
  branch_ids?: string[]
}
```

### ModuleInfo
```typescript
{
  slug: string
  display_name: string
  description: string
  category: string
  is_core: boolean
  is_enabled: boolean
}
```

---

## 4. Navigation Structure

### Sidebar Navigation (OrgLayout)

The sidebar shows nav items filtered by: module enabled + feature flag + trade family + user role.

**Always visible (no module gate):**
- Dashboard (`/dashboard`)
- Customers (`/customers`)
- Invoices (`/invoices`)
- Notifications (`/notifications`)
- Data (`/data`)
- Reports (`/reports`)

**Module-gated:**
- Vehicles (`/vehicles`) — module: `vehicles`, trade: `automotive-transport`
- Quotes (`/quotes`) — module: `quotes`
- Job Cards (`/job-cards`) — module: `jobs`
- Jobs (`/jobs`) — module: `jobs`
- Bookings (`/bookings`) — module: `bookings`
- Inventory (`/inventory`) — module: `inventory`
- Items/Catalogue (`/items`, `/catalogue`) — module: `inventory`
- Staff (`/staff`) — module: `staff`
- Projects (`/projects`) — module: `projects`
- Expenses (`/expenses`) — module: `expenses`
- Time Tracking (`/time-tracking`) — module: `time_tracking`
- Schedule (`/schedule`) — module: `scheduling`
- POS (`/pos`) — module: `pos`
- Recurring (`/recurring`) — module: `recurring_invoices`
- Purchase Orders (`/purchase-orders`) — module: `purchase_orders`
- Progress Claims (`/progress-claims`) — module: `progress_claims`
- Variations (`/variations`) — module: `variations`
- Retentions (`/retentions`) — module: `retentions`
- Floor Plan (`/floor-plan`) — module: `tables`
- Kitchen Display (`/kitchen`) — module: `kitchen_display`
- Franchise (`/franchise`) — module: `franchise`
- Branch Transfers (`/branch-transfers`) — module: `branch_management`, adminOnly
- Staff Schedule (`/staff-schedule`) — module: `branch_management`, adminOnly
- Assets (`/assets`) — module: `assets`
- Compliance (`/compliance`) — module: `compliance_docs`
- Loyalty (`/loyalty`) — module: `loyalty`
- Ecommerce (`/ecommerce`) — module: `ecommerce`
- SMS (`/sms`) — module: `sms`
- Claims (`/claims`) — module: `customer_claims`
- Accounting (`/accounting`) — module: `accounting`
- Banking (`/banking/accounts`) — module: `accounting`
- Tax (`/tax/gst-periods`) — module: `accounting`

**Admin-only (org_admin role):**
- Settings (`/settings`)

### Header Quick Actions
- New Booking (module: `bookings`)
- New Job Card (module: `jobs`)
- New Quote (module: `quotes`)
- New Invoice (always visible)
- New Customer (always visible)

### Header Elements
- Global search bar (Ctrl+K)
- Branch selector (when branch_management module enabled)
- Compliance notification badge
- User menu (profile, logout)

---

## 5. Key Forms

### Invoice Create Form
- **Fields**: Customer (search/select), Vehicles (search/select, multiple), Invoice Date, Due Date, Payment Terms (dropdown), Salesperson (dropdown), Subject, GST Number (auto from org), Order Number, Line Items (description, quantity, rate, tax, amount), Discount (% or $), Shipping Charges, Adjustment, Customer Notes, Terms & Conditions, Attachments (file upload, max 5, 20MB each), Payment Method (cash/eftpos/bank_transfer/stripe), Make Recurring (checkbox)
- **Validation**: Customer required, at least one line item with description
- **Submits to**: `POST /invoices` (create) or `PUT /invoices/:id` (edit)
- **Client-side calculations**: Line amount = qty × rate, subtotal, discount amount, GST (15%, handles inclusive/exclusive/exempt), total

### Customer Create Form
- **Fields**: First Name (required), Last Name, Company Name, Email, Phone, Mobile Phone, Work Phone, Address
- **Validation**: First name required
- **Submits to**: `POST /customers`

### Job Card Create Form
- **Fields**: Customer (search), Vehicle (search), Description, Service Type, Assigned Staff, Parts (from inventory), Labour entries
- **Submits to**: `POST /job-cards`

### Quote Create Form
- **Fields**: Customer, Line Items, Discount, Terms, Notes, Expiry Date
- **Submits to**: `POST /quotes`

### Booking Form
- **Fields**: Customer, Date, Time, Duration, Service Type, Staff, Notes
- **Submits to**: `POST /bookings`

### Record Payment Form (Modal)
- **Fields**: Amount (pre-filled with balance due), Payment Method (cash/eftpos/bank_transfer/card/cheque), Note
- **Validation**: Amount > 0
- **Submits to**: `POST /payments/cash`

### Void Invoice Form (Modal)
- **Fields**: Reason (textarea, required)
- **Submits to**: `PUT /invoices/:id/void`

### Credit Note Form (Modal)
- **Fields**: Amount (max: creditable amount), Reason
- **Submits to**: `POST /invoices/:id/credit-notes`

### Refund Form (Modal)
- **Fields**: Amount (max: refundable amount), Reason, Method
- **Submits to**: `POST /invoices/:id/refund`

---

## 6. Tables/Lists

### Invoice List (Sidebar)
- **Columns**: Customer name, invoice number, date, total (NZD), status badge, due date indicator, Stripe payment icon, attachment count badge (paperclip), delete button
- **Filters**: Status dropdown (All, Draft, Issued, Partially Paid, Paid, Overdue, Voided, Refunded, Partially Refunded)
- **Search**: Free text (customer name, invoice number, rego)
- **Pagination**: 25 per page
- **Sorting**: Created date descending

### Customer List
- **Columns**: Name, Company, Email, Phone, Receivables, Unused Credits, Branch
- **Filters**: None (search only)
- **Search**: Free text (name, phone, email, company, rego)
- **Pagination**: 10 per page (configurable)

### Job Card List
- **Columns**: Customer, Vehicle Rego, Status, Description, Assigned To, Created Date
- **Filters**: Status
- **Sorting**: In-progress first, then open, by created date descending

### Inventory Stock Levels
- **Columns**: Item Name, Part Number, Brand, Type, Available Qty, Reserved Qty, Sell Price, Supplier, Location
- **Filters**: Type (all/part/tyre), search
- **Actions**: Add to invoice, adjust stock

---

## 7. Auth Flow

### Login
1. User enters email + password → `POST /auth/login`
2. If MFA required → redirect to `/login/mfa` with session token
3. MFA verify (TOTP, SMS, email, passkey, backup code) → `POST /auth/mfa/verify`
4. On success → JWT access token (in memory) + refresh token (httpOnly cookie)
5. Redirect to `/dashboard`

### Registration
1. User fills signup form (name, email, password, business name)
2. Selects plan (Mech Pro Plan — $60 NZD/month)
3. Enters payment via Stripe Elements
4. `POST /auth/register` → creates org + user + subscription
5. Email verification sent
6. Redirect to onboarding wizard

### Token Refresh
- Access token stored in memory (not localStorage)
- Refresh token in httpOnly cookie
- On 401 → automatic refresh via `POST /auth/token/refresh` with global mutex
- If refresh fails → logout

### Roles (End-User)
| Role | Access |
|------|--------|
| `org_admin` | Full access to all org features + settings |
| `branch_admin` | Branch-scoped access, no org settings |
| `salesperson` | Standard user, no admin features |
| `kiosk` | Kiosk check-in screen only |

---

## 8. Module Gating Logic

### How It Works
1. **ModuleProvider** fetches `GET /api/v2/modules` on login (skipped for global_admin)
2. Returns array of `{ slug, is_enabled }` for the org
3. **`useModules().isEnabled(slug)`** — returns true/false
4. When outside ModuleProvider (global_admin), `isEnabled()` always returns true

### Gating Mechanisms

**Route-level: `ModuleRoute`**
```tsx
<Route path="/vehicles/*" element={<ModuleRoute moduleSlug="vehicles"><VehicleList /></ModuleRoute>} />
```
- Loading → shows Spinner
- Disabled → shows `FeatureNotAvailable` page
- Enabled → renders children

**Component-level: `ModuleGate`**
```tsx
<ModuleGate module="vehicles">
  <VehicleSection />
</ModuleGate>
```
- Disabled → renders nothing (hidden)
- Enabled → renders children

**Sidebar filtering (OrgLayout)**
```typescript
navItems.filter(item => {
  if (item.module && !isEnabled(item.module)) return false
  if (item.flagKey && !flags[item.flagKey]) return false
  if (item.tradeFamily && tradeFamily !== item.tradeFamily) return false
  if (item.adminOnly && role !== 'org_admin') return false
  return true
})
```

### All Gated Modules
| Module Slug | Controls | Trade Family |
|-------------|----------|--------------|
| `vehicles` | Vehicle pages, CarJam lookup | automotive-transport |
| `quotes` | Quote creation and management | all |
| `jobs` | Job cards, jobs board, timers | all |
| `bookings` | Booking calendar | all |
| `inventory` | Stock management, catalogue | all |
| `staff` | Staff management | all |
| `projects` | Project tracking | all |
| `expenses` | Expense tracking | all |
| `time_tracking` | Time sheets | all |
| `scheduling` | Schedule calendar | all |
| `pos` | Point of sale | all |
| `recurring_invoices` | Recurring invoices | all |
| `purchase_orders` | Purchase orders | all |
| `progress_claims` | Progress claims | construction |
| `variations` | Contract variations | construction |
| `retentions` | Retention tracking | construction |
| `tables` | Floor plan / table management | hospitality |
| `kitchen_display` | Kitchen display system | hospitality |
| `franchise` | Franchise management | all |
| `branch_management` | Branch transfers, staff schedule | all |
| `assets` | Asset tracking | all |
| `compliance_docs` | Compliance documents | all |
| `loyalty` | Loyalty program | all |
| `ecommerce` | WooCommerce integration | all |
| `sms` | SMS messaging | all |
| `customer_claims` | Customer claims | all |
| `accounting` | Accounting, banking, tax | all |

---

## 9. Frontend Logic to Preserve

### Invoice Calculations (InvoiceCreate.tsx)
```typescript
// Subtotal
const subTotal = lineItems.reduce((sum, item) => sum + item.amount, 0)

// Discount
const discountAmount = discountType === 'percentage'
  ? (subTotal * discountValue / 100)
  : discountValue

// GST — handles inclusive/exclusive/exempt per line item
const taxAmount = lineItems.reduce((sum, item) => {
  if (item.tax_rate <= 0) return sum
  if (item.gst_inclusive && item.inclusive_price) {
    const inclTotal = Math.round(item.quantity * item.inclusive_price * 100) / 100
    const gst = Math.round((inclTotal - item.amount) * 100) / 100
    return sum + gst
  }
  return sum + Math.round(item.amount * item.tax_rate) / 100
}, 0)

// Total
const total = afterDiscount + taxAmount + shippingCharges + adjustment
```

### Invoice Status Colors
```typescript
const STATUS_CONFIG = {
  draft:              { label: 'DRAFT',              color: 'text-gray-500' },
  issued:             { label: 'ISSUED',             color: 'text-blue-600' },
  partially_paid:     { label: 'PARTIALLY PAID',     color: 'text-amber-600' },
  paid:               { label: 'PAID',               color: 'text-emerald-600' },
  overdue:            { label: 'OVERDUE',             color: 'text-red-600' },
  voided:             { label: 'VOIDED',              color: 'text-gray-400' },
  refunded:           { label: 'REFUNDED',            color: 'text-orange-600' },
  partially_refunded: { label: 'PARTIALLY REFUNDED',  color: 'text-orange-600' },
}
```

### Job Card Sorting
```typescript
// in_progress first, then open, each group by created_at descending
const statusOrder = (s) => (s === 'in_progress' ? 0 : s === 'open' ? 1 : 2)
```

### Credit Note / Refund Calculations
```typescript
computeCreditableAmount(total, creditNoteAmounts[])
computePaymentSummary(payments[]) → { totalPaid, totalRefunded, netPaid }
```

### Safe API Consumption (MANDATORY)
```typescript
// Every API response access:
res.data?.items ?? []
res.data?.total ?? 0
(value ?? 0).toLocaleString()

// Every useEffect with API call:
const controller = new AbortController()
// ... fetch with { signal: controller.signal }
return () => controller.abort()
```

### Invoice Template Styling
```typescript
resolveTemplateStyles(templateId, colours) → {
  primaryColour, accentColour, headerBgColour,
  isHeaderDark, logoPosition, layoutType
}
```

### Currency Formatting
```typescript
function formatNZD(amount) {
  return `NZD${Number(amount).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
```

### Branch Scoping
- `X-Branch-Id` header injected on every API request from localStorage
- `selectedBranchId` in BranchContext controls data filtering
- Branch selector in header (when branch_management module enabled)

---

## 10. Color Scheme and Typography

### Primary Colors (from landing page and app)
| Usage | Hex | Tailwind |
|-------|-----|----------|
| Primary brand / CTA | #2563EB | `blue-600` |
| Primary hover | #3B82F6 | `blue-500` |
| Header/footer bg | #0F172A | `slate-900` |
| Hero gradient end | #312E81 | `indigo-900` |
| Success/paid | #059669 | `emerald-600` |
| Warning/partial | #D97706 | `amber-600` |
| Error/overdue | #DC2626 | `red-600` |
| Info/issued | #2563EB | `blue-600` |
| Neutral/draft | #6B7280 | `gray-500` |
| Body text | #111827 | `gray-900` |
| Secondary text | #4B5563 | `gray-600` |
| Muted text | #9CA3AF | `gray-400` |
| Card borders | #E5E7EB | `gray-200` |
| Alt section bg | #F9FAFB | `gray-50` |
| Coming soon badge | #FEF3C7 / #92400E | `amber-100` / `amber-800` |

### CSS Variables (from TenantContext — org-customizable)
```css
--color-primary: #2563eb (default)
--color-secondary: #1e40af (default)
--sidebar-bg, --sidebar-text, --sidebar-border
--sidebar-active-bg, --sidebar-active-text, --sidebar-active-border
--content-bg
--input-border, --input-focus-border, --input-focus-ring, --input-radius
--transition-speed, --transition-fn
```

### Typography
- Default Tailwind font stack (system fonts)
- No custom fonts configured
- Form inputs: 42px height
- Headings: `font-bold` / `font-extrabold`
- Body: `text-sm` (14px) predominantly

---

## 11. API Base URL and Key Endpoints

**Base URL**: `/api/v1` (axios baseURL)
**V2 endpoints**: Use absolute paths `/api/v2/...`

### By Module

**Auth**: `/auth/login`, `/auth/register`, `/auth/token/refresh`, `/auth/logout`, `/auth/mfa/*`, `/auth/me`, `/auth/password-reset/*`

**Invoices**: `/invoices`, `/invoices/:id`, `/invoices/:id/issue`, `/invoices/:id/void`, `/invoices/:id/email`, `/invoices/:id/duplicate`, `/invoices/:id/pdf`, `/invoices/:id/share`, `/invoices/:id/send-reminder`, `/invoices/:id/attachments`, `/invoices/bulk-delete`

**Payments**: `/payments/cash`, `/payments/online-payments/status`, `/payments/online-payments/connect`

**Customers**: `/customers`, `/customers/:id`, `/customers/:id/reminders`, `/customers/:id/vehicle-dates`

**Vehicles**: `/vehicles`, `/vehicles/:id`

**Quotes**: `/quotes`, `/quotes/:id`, `/quotes/:id/convert`, `/quotes/:id/email`

**Job Cards**: `/job-cards`, `/job-cards/:id`, `/job-cards/:id/complete`, `/job-cards/:id/assign`, `/job-cards/:id/start-timer`, `/job-cards/:id/stop-timer`, `/job-cards/:id/attachments`

**Bookings**: `/bookings`, `/bookings/:id`

**Catalogue**: `/catalogue/items`, `/catalogue/labour-rates`

**Inventory**: `/inventory/stock-items`, `/inventory/suppliers`, `/inventory/import`

**Staff**: `/api/v2/staff`

**Time Tracking**: `/api/v2/time-entries`

**Expenses**: `/api/v2/expenses`

**Schedule**: `/api/v2/schedule`

**Recurring**: `/api/v2/recurring`

**Purchase Orders**: `/api/v2/purchase-orders`

**Compliance**: `/api/v2/compliance-docs`

**Franchise**: `/api/v2/franchise/*`

**Modules**: `/api/v2/modules`

**Org**: `/org/settings`, `/org/salespeople`, `/org/branches`

**Reports**: `/reports/revenue`, `/reports/profit-loss`, `/reports/balance-sheet`, `/reports/aged-receivables`, etc.

**Notifications**: `/notifications/preferences`, `/notifications/overdue-rules`

**SMS**: `/sms/conversations`, `/sms/send`

**Accounting**: `/accounting/accounts`, `/accounting/journals`

**Banking**: `/banking/accounts`, `/banking/transactions`, `/banking/reconciliation`

**Tax**: `/tax/gst-periods`, `/tax/wallets`

**Data**: `/data/import`, `/data/export`

**Dashboard**: `/dashboard/stats`

**Kiosk**: `/kiosk/check-in`

---

## 12. Third-Party Integrations (Frontend-Visible)

| Integration | Where Used | Purpose |
|-------------|-----------|---------|
| **Stripe** | SignupWizard (payment), OnlinePaymentsSettings, InvoicePaymentPage (public) | Subscription billing, online invoice payments |
| **Stripe Elements** | CardForm component | Credit card input UI |
| **CarJam** | VehicleLiveSearch component, Vehicle pages | NZ vehicle lookup by rego (make, model, VIN, WOF, rego expiry) |
| **Xero** | AccountingIntegrations settings page | Accounting sync, bank reconciliation |
| **WooCommerce** | Ecommerce settings pages | Product sync, SKU mapping |
| **Connexus SMS** | SMS chat page, notification settings | SMS sending/receiving |
| **Google OAuth** | Login page | Social login |
| **WebAuthn/Passkeys** | Login page, MFA settings | Passwordless authentication |
| **Firebase** | MFA verification | SMS-based MFA delivery |
| **WeasyPrint** | Invoice PDF generation (backend, triggered from frontend) | PDF rendering |

---

## 13. Uncertain / Flagged Items

These items may be admin-only or end-user facing — review manually:

1. **Settings page** (`/settings`) — Gated to `org_admin` role. Contains org branding, billing, integrations, security, modules. This is end-user facing for org admins but not for salesperson/branch_admin roles.
2. **Branch Transfers** (`/branch-transfers`) — Gated to `branch_management` module + `adminOnly`. Only org_admin can see.
3. **Staff Schedule** (`/staff-schedule`) — Same as above.
4. **Data Import/Export** (`/data`) — Visible to all roles in sidebar but may have role restrictions on certain operations.
5. **Onboarding Wizard** — Shown once after signup. Not a regular page.
6. **Setup Guide** — First-time setup flow. Not a regular page.

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| End-user pages/routes | ~60+ |
| Reusable components | 80+ |
| Data models/types | 15+ |
| Sidebar nav items | 35 |
| Module slugs | 27 |
| Forms | 10+ major forms |
| API endpoint groups | 20+ |
| Third-party integrations | 10 |
| User roles | 5 |
| Trade families | 6+ |

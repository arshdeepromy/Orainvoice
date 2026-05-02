# Mobile Context — Expo React Native App

This document contains everything needed to build and maintain the Expo React Native
mobile frontend for the OraInvoice / WorkshopPro NZ backend.

---

## Table of Contents

1. [OpenAPI / Route Catalogue](#1-openapi--route-catalogue)
2. [Auth Flow](#2-auth-flow)
3. [Data Models (TypeScript)](#3-data-models-typescript)
4. [Screen Inventory](#4-screen-inventory)
5. [Business Rules](#5-business-rules)
6. [Environment Config](#6-environment-config)

---

## 1. OpenAPI / Route Catalogue

All routes are served from the same base URL. Two API versions exist:

- **`/api/v1/`** — original endpoints (invoices, customers, vehicles, quotes, job-cards, bookings, payments, portal…)
- **`/api/v2/`** — newer endpoints (jobs, expenses, staff, time-entries, projects, purchase-orders, recurring, modules, flags…)

Every authenticated endpoint requires `Authorization: Bearer <access_token>`.  
Branch-scoped requests send `X-Branch-Id: <uuid>` (optional).

### 1.1 Auth (`/api/v1/auth/`)

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| POST | `/api/v1/auth/login` | `{email, password, remember_me?}` | `TokenResponse` or `MFARequiredResponse` | Core login |
| POST | `/api/v1/auth/login/google` | `{code, redirect_uri}` | `TokenResponse` | Google OAuth |
| POST | `/api/v1/auth/token/refresh` | `{refresh_token}` | `TokenResponse` | Renew access token |
| POST | `/api/v1/auth/logout` | — | `{message}` | Invalidate session |
| GET | `/api/v1/auth/me` | — | `UserProfileResponse` | Current user |
| PUT | `/api/v1/auth/me` | `{first_name?, last_name?}` | `UserProfileResponse` | Update profile |
| POST | `/api/v1/auth/change-password` | `{current_password, new_password}` | `{message}` | Change password |
| POST | `/api/v1/auth/password/reset-request` | `{email}` | `{message}` | Send reset email |
| POST | `/api/v1/auth/password/reset` | `{token, new_password}` | `{message}` | Complete reset |
| POST | `/api/v1/auth/mfa/verify` | `{mfa_token, code, method}` | `TokenResponse` | Complete MFA after login |
| POST | `/api/v1/auth/mfa/challenge/send` | `{mfa_token, method}` | `{message}` | Trigger SMS/email code |
| GET | `/api/v1/auth/mfa/methods` | — | `{methods: MFAMethodStatus[]}` | List enrolled methods |
| POST | `/api/v1/auth/passkey/login/options` | `{mfa_token}` | `{options}` | WebAuthn challenge |
| POST | `/api/v1/auth/passkey/login/verify` | `{mfa_token, credential_id, ...}` | `TokenResponse` | Passkey verify |
| POST | `/api/v1/auth/verify-email` | `{token, password}` | `{access_token, refresh_token, ...}` | Accept invitation |

### 1.2 Organisation

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/org/settings` | Branding, GST, invoice settings, trade family |
| PUT | `/api/v1/org/settings` | Update org settings (org_admin) |
| GET | `/api/v2/modules` | List modules with enabled status |
| GET | `/api/v2/flags` | Feature flags map |

### 1.3 Customers (`/api/v1/customers/`)

| Method | Path | Body / Query | Response |
|--------|------|-------------|----------|
| GET | `/api/v1/customers` | `?search=&page=&page_size=&branch_id=` | `CustomerListResponse` |
| POST | `/api/v1/customers` | `CustomerCreateRequest` | `CustomerResponse` |
| GET | `/api/v1/customers/{id}` | — | `CustomerResponse` |
| PUT | `/api/v1/customers/{id}` | `CustomerUpdateRequest` | `CustomerResponse` |
| DELETE | `/api/v1/customers/{id}` | — | `{message}` (GDPR anonymise) |
| POST | `/api/v1/customers/{id}/notify` | `{channel, message}` | `{message}` |
| POST | `/api/v1/customers/{id}/merge` | `{target_customer_id}` | `{message}` |
| GET | `/api/v1/customers/{id}/export` | — | JSON download |
| GET | `/api/v1/customers/{id}/reminders` | — | reminder config |
| PUT | `/api/v1/customers/{id}/reminders` | reminder config | `{message}` |
| PUT | `/api/v1/customers/{id}/vehicle-dates` | vehicle date object | `{message}` |

### 1.4 Invoices (`/api/v1/invoices/`)

| Method | Path | Body / Query | Response |
|--------|------|-------------|----------|
| GET | `/api/v1/invoices` | `?search=&status=&page=&page_size=&branch_id=` | `InvoiceListResponse` |
| POST | `/api/v1/invoices` | `InvoiceCreateRequest` | `InvoiceCreateResponse` |
| GET | `/api/v1/invoices/{id}` | — | `GetInvoiceResponse` |
| PUT | `/api/v1/invoices/{id}` | `UpdateInvoiceRequest` | `UpdateInvoiceResponse` |
| DELETE | `/api/v1/invoices/{id}` | — | `{message}` (draft only) |
| PUT | `/api/v1/invoices/{id}/issue` | — | `IssueInvoiceResponse` |
| PUT | `/api/v1/invoices/{id}/void` | `{reason}` | `VoidInvoiceResponse` |
| POST | `/api/v1/invoices/{id}/email` | `{recipient_email?}` | `InvoiceEmailResponse` |
| POST | `/api/v1/invoices/{id}/send-reminder` | `{channel}` | `SendReminderResponse` |
| POST | `/api/v1/invoices/{id}/duplicate` | — | `DuplicateInvoiceResponse` |
| GET | `/api/v1/invoices/{id}/pdf` | — | PDF blob |
| POST | `/api/v1/invoices/{id}/credit-note` | `CreditNoteCreateRequest` | `CreditNoteCreateResponse` |
| GET | `/api/v1/invoices/{id}/credit-notes` | — | `CreditNoteListResponse` |
| PUT | `/api/v1/invoices/{id}/notes` | `{notes_internal?, notes_customer?}` | `UpdateNotesResponse` |

### 1.5 Quotes (`/api/v1/quotes/` and `/api/v2/quotes/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/quotes` | List quotes (paginated) |
| POST | `/api/v1/quotes` | Create quote |
| GET | `/api/v1/quotes/{id}` | Get quote |
| PUT | `/api/v1/quotes/{id}` | Update quote |
| POST | `/api/v1/quotes/{id}/send` | Send to customer |
| POST | `/api/v1/quotes/{id}/convert` | Convert to invoice |
| DELETE | `/api/v1/quotes/{id}` | Delete draft |
| GET | `/api/v2/quotes` | v2 list (preferred) |
| POST | `/api/v2/quotes` | v2 create |
| GET | `/api/v2/quotes/{id}` | v2 detail |
| PUT | `/api/v2/quotes/{id}` | v2 update |
| PUT | `/api/v2/quotes/{id}/send` | v2 send |
| POST | `/api/v2/quotes/{id}/convert-to-invoice` | v2 convert |
| POST | `/api/v2/quotes/{id}/revise` | Create new revision |

### 1.6 Job Cards (`/api/v1/job-cards/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/job-cards` | List job cards |
| POST | `/api/v1/job-cards` | Create |
| GET | `/api/v1/job-cards/{id}` | Detail |
| PUT | `/api/v1/job-cards/{id}` | Update |
| DELETE | `/api/v1/job-cards/{id}` | Delete |
| POST | `/api/v1/job-cards/{id}/timer/start` | Start work timer |
| POST | `/api/v1/job-cards/{id}/timer/stop` | Stop work timer |
| POST | `/api/v1/job-cards/{id}/complete` | Mark complete |
| PUT | `/api/v1/job-cards/{id}/assign` | Assign staff member |

### 1.7 Jobs v2 (`/api/v2/jobs/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/jobs` | List jobs (`?status=&customer_id=&page=`) |
| POST | `/api/v2/jobs` | Create job |
| GET | `/api/v2/jobs/{id}` | Detail |
| PUT | `/api/v2/jobs/{id}` | Update |
| PUT | `/api/v2/jobs/{id}/status` | Change status (with valid transition check) |
| POST | `/api/v2/jobs/{id}/attachments` | Upload attachment |
| GET | `/api/v2/jobs/{id}/attachments` | List attachments |
| GET | `/api/v2/jobs/{id}/status-history` | Status change log |

### 1.8 Bookings (`/api/v2/bookings/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/bookings` | List (`?start=&end=&staff_id=`) |
| POST | `/api/v2/bookings` | Create |
| GET | `/api/v2/bookings/{id}` | Detail |
| PUT | `/api/v2/bookings/{id}` | Update |
| DELETE | `/api/v2/bookings/{id}` | Cancel |
| POST | `/api/v2/bookings/{id}/convert` | Convert to job or invoice |
| GET | `/api/v2/bookings/slots` | Available slots for a date |

### 1.9 Payments (`/api/v1/payments/`)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v1/payments/cash` | Record cash payment against invoice |
| GET | `/api/v1/payments/invoice/{id}/history` | Payment history for invoice |
| POST | `/api/v1/payments/stripe/create-link` | Generate Stripe payment link |

### 1.10 Vehicles (`/api/v1/vehicles/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/vehicles` | List vehicles for org |
| GET | `/api/v1/vehicles/{id}` | Vehicle detail |
| GET | `/api/v1/vehicles/lookup/{rego}` | CarJam lookup by rego |
| POST | `/api/v1/vehicles/lookup-with-fallback` | CarJam with manual entry fallback |
| POST | `/api/v1/vehicles/manual` | Manually create vehicle record |
| PUT | `/api/v1/vehicles/{id}` | Update vehicle |
| POST | `/api/v1/vehicles/{id}/link-customer` | Link vehicle to customer |

### 1.11 Expenses (`/api/v2/expenses/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/expenses` | List (`?job_id=&project_id=&page=`) |
| POST | `/api/v2/expenses` | Create |
| GET | `/api/v2/expenses/{id}` | Detail |
| PUT | `/api/v2/expenses/{id}` | Update |
| DELETE | `/api/v2/expenses/{id}` | Delete |
| POST | `/api/v2/expenses/bulk` | Bulk create |
| GET | `/api/v2/expenses/summary` | Summary by category/project |
| POST | `/api/v2/uploads/receipts` | Upload receipt image |
| GET | `/api/v2/expenses/mileage-preferences` | Get mileage settings |
| PUT | `/api/v2/expenses/mileage-preferences` | Update mileage rate |

### 1.12 Staff (`/api/v2/staff/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/staff` | List staff |
| POST | `/api/v2/staff` | Create |
| GET | `/api/v2/staff/{id}` | Detail |
| PUT | `/api/v2/staff/{id}` | Update |
| DELETE | `/api/v2/staff/{id}` | Delete |
| POST | `/api/v2/staff/{id}/activate` | Re-activate |

### 1.13 Time Tracking (`/api/v2/time-entries/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/time-entries/timesheet` | Timesheet view (`?date=&staff_id=`) |
| POST | `/api/v2/time-entries` | Add time entry |
| PUT | `/api/v2/time-entries/{id}` | Update entry |
| DELETE | `/api/v2/time-entries/{id}` | Delete entry |
| POST | `/api/v2/time-entries/clock-in` | Clock in (start timer) |
| POST | `/api/v2/time-entries/clock-out` | Clock out (stop timer) |
| POST | `/api/v2/time-entries/add-to-invoice` | Convert entries to invoice line items |

### 1.14 Projects (`/api/v2/projects/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/projects` | List |
| POST | `/api/v2/projects` | Create |
| GET | `/api/v2/projects/{id}` | Detail with budget/time summary |
| PUT | `/api/v2/projects/{id}` | Update |
| DELETE | `/api/v2/projects/{id}` | Delete |

### 1.15 Purchase Orders (`/api/v2/purchase-orders/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/purchase-orders` | List (`?status=&supplier_id=`) |
| POST | `/api/v2/purchase-orders` | Create |
| GET | `/api/v2/purchase-orders/{id}` | Detail |
| PUT | `/api/v2/purchase-orders/{id}` | Update |
| POST | `/api/v2/purchase-orders/{id}/send` | Send to supplier |
| POST | `/api/v2/purchase-orders/{id}/receive` | Mark goods received |

### 1.16 Recurring Invoices (`/api/v2/recurring/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v2/recurring` | List schedules |
| POST | `/api/v2/recurring` | Create schedule |
| GET | `/api/v2/recurring/{id}` | Detail |
| PUT | `/api/v2/recurring/{id}` | Update |
| DELETE | `/api/v2/recurring/{id}` | Cancel |
| POST | `/api/v2/recurring/{id}/pause` | Pause |
| POST | `/api/v2/recurring/{id}/resume` | Resume |
| GET | `/api/v2/recurring/dashboard` | Summary stats |

### 1.17 Inventory (`/api/v1/inventory/` and `/api/v2/`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/inventory/stock-items` | List stock items |
| POST | `/api/v1/inventory/stock-items` | Create stock item |
| GET | `/api/v1/inventory/stock-items/{id}` | Detail |
| PUT | `/api/v1/inventory/stock-items/{id}` | Update |
| POST | `/api/v1/inventory/stock-items/{id}/add-stock` | Add stock (purchase/receive) |
| GET | `/api/v2/suppliers` | List suppliers |
| POST | `/api/v2/suppliers` | Create supplier |
| GET | `/api/v2/stock-movements` | Movement log |
| POST | `/api/v2/stock-adjustments` | Adjust stock count |
| POST | `/api/v1/inventory/transfers` | Initiate branch transfer |

### 1.18 Assets, Compliance, Loyalty, Claims

| Module | Base Path | Key Methods |
|--------|-----------|------------|
| Assets | `/api/v2/assets` | GET list, POST create, GET/{id}, PUT/{id}, DELETE/{id} |
| Compliance | `/api/v2/compliance-docs` | GET/dashboard, GET/categories, POST upload, GET/{id}/download |
| Loyalty | `/api/v2/loyalty/config` | GET config, PUT config, GET tiers, POST tiers, GET analytics, GET customers/{id}/balance |
| Claims | `/api/v1/claims` | GET list, POST create, GET/{id}, PATCH/{id}/status, POST/{id}/resolve, POST/{id}/notes |

### 1.19 Reports

| Path | Notes |
|------|-------|
| GET `/api/v1/reports/revenue-summary?start_date=&end_date=` | Revenue by period |
| GET `/api/v1/reports/invoice-status?start_date=&end_date=` | Status breakdown |
| GET `/api/v1/reports/outstanding-invoices` | Overdue / outstanding |
| GET `/api/v1/reports/top-services?start_date=&end_date=` | Top revenue services |
| GET `/api/v1/reports/gst-return-summary?period_id=` | GST period breakdown |
| GET `/api/v1/reports/customer-statement?customer_id=&start_date=&end_date=` | Customer statement |

### 1.20 Dashboard

| Path | Notes |
|------|-------|
| GET `/api/v1/dashboard/branch-metrics` | KPIs for selected branch |
| GET `/api/v1/dashboard/widgets` | Widget data collection |
| GET `/api/v1/dashboard/todays-bookings` | Today's booking list |

### 1.21 Customer Portal (public — no auth header)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/portal/{token}` | Portal home — customer info + branding |
| GET | `/api/v1/portal/{token}/invoices` | Invoice list |
| GET | `/api/v1/portal/{token}/quotes` | Quote list |
| POST | `/api/v1/portal/{token}/quotes/{id}/accept` | Accept a quote |
| GET | `/api/v1/portal/{token}/vehicles` | Vehicle history |
| GET | `/api/v1/portal/{token}/assets` | Asset list |
| GET | `/api/v1/portal/{token}/bookings` | Booking list |
| POST | `/api/v1/portal/{token}/bookings` | Create booking |
| GET | `/api/v1/portal/{token}/bookings/slots` | Available slots |
| GET | `/api/v1/portal/{token}/loyalty` | Loyalty balance |
| POST | `/api/v1/portal/{token}/pay/{invoice_id}` | Initiate Stripe payment |

### 1.22 Public Invoice Payment (no auth)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/v1/public/pay/{token}` | Invoice data + Stripe client secret |
| POST | `/api/v1/public/pay/{token}/update-surcharge` | Recalculate surcharge for chosen method |
| POST | `/api/v1/public/pay/{token}/confirm` | Confirm payment intent |

### 1.23 Catalogue & Items

| Path | Notes |
|------|-------|
| GET `/api/v1/catalogue/items` | Search catalogue items (parts + labour) |
| GET `/api/v1/catalogue/parts` | Parts only |
| POST `/api/v1/catalogue/parts` | Create part |
| GET `/api/v2/products` | Product list (v2 POS) |
| GET `/api/v2/products/barcode/{barcode}` | Barcode lookup |

### 1.24 File Uploads

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v2/uploads/receipts` | Upload expense receipt (multipart/form-data) |
| POST | `/api/v2/uploads/attachments` | Upload job/invoice attachment |
| GET | `/api/v2/uploads/{file_key}` | Download / get signed URL |
| GET | `/api/v1/storage/files/{file_key}` | Alternate download endpoint |

---

## 2. Auth Flow

### 2.1 Overview

Authentication uses **short-lived JWTs + httpOnly refresh token cookies** (web) or **stored refresh tokens** (mobile).

For Expo React Native, store tokens in **SecureStore** (`expo-secure-store`), not AsyncStorage.

### 2.2 Login Flow

```
Step 1 — POST /api/v1/auth/login
  Body: { email, password, remember_me: true }

  Case A — Success:
    Response: { access_token, refresh_token, token_type: "bearer" }
    → Store access_token in memory (React state or Zustand)
    → Store refresh_token in SecureStore
    → Fetch GET /api/v1/auth/me to get name/role
    → Navigate to home screen

  Case B — MFA Required:
    Response: { mfa_required: true, mfa_token, mfa_methods: ["totp","sms"] }
    → Navigate to MfaScreen
    → (Optional) POST /api/v1/auth/mfa/challenge/send { mfa_token, method }
      to trigger SMS/email OTP delivery
    → POST /api/v1/auth/mfa/verify { mfa_token, code, method }
    → Returns TokenResponse → same as Case A success path

  Case C — Passkey (after MFA challenge):
    → POST /api/v1/auth/passkey/login/options { mfa_token }
    → Use native WebAuthn / Passkey API or platform authenticator
    → POST /api/v1/auth/passkey/login/verify { mfa_token, credential_id, ... }
    → Returns TokenResponse
```

### 2.3 Headers

Every authenticated request must include:

```
Authorization: Bearer <access_token>
Content-Type: application/json
X-Branch-Id: <uuid>          (optional — only when a branch is selected)
```

**Never send the refresh token in the Authorization header.** It is only sent to the refresh endpoint.

### 2.4 Token Refresh

Access token lifetime: **15 minutes** (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`).

```
When any API request returns 401:
  → POST /api/v1/auth/token/refresh
    Body: { refresh_token: <stored_refresh_token> }
  → On success: replace in-memory access_token, retry original request
  → On failure (401 from refresh endpoint): clear SecureStore, navigate to Login
```

Use a **singleton promise** (mutex) to deduplicate concurrent refresh requests — if 3 requests return 401 simultaneously, only one refresh call should be made and the others should wait for its result.

### 2.5 Session Persistence on App Launch

```
On app cold start:
  1. Read refresh_token from SecureStore
  2. If none → show Login screen
  3. If found → POST /api/v1/auth/token/refresh
     → Success: set access_token in memory, proceed to app
     → Failure: clear SecureStore, show Login screen
```

### 2.6 Logout

```
POST /api/v1/auth/logout  (sends current access_token)
→ Delete refresh_token from SecureStore
→ Clear in-memory access_token
→ Navigate to Login
```

### 2.7 Biometric Lock (mobile-specific)

After the user is authenticated, if biometric lock is enabled:

1. On app foreground after >5 min background: show `BiometricLockScreen`
2. Use `expo-local-authentication` to prompt Face ID / fingerprint
3. On success: restore session from SecureStore refresh token
4. On failure/cancel: require full login

### 2.8 Role-Based Access

| Role | App behaviour |
|------|--------------|
| `global_admin` | Redirect to admin dashboard; blocked from org screens |
| `org_admin` | Full access — sees Settings, can manage users/branches |
| `branch_admin` | Scoped to assigned branches; no Settings access |
| `salesperson` | Standard access; all module-gated screens |
| `kiosk` | Locked to Kiosk screen only |

Read role from `GET /api/v1/auth/me` → `role` field.

### 2.9 Module & Feature Flag Gating

After login, fetch and cache:

```
GET /api/v2/modules       → array of { slug, is_enabled }
GET /api/v2/flags         → map of { flagKey: boolean }
```

Gate screens with helper:
```typescript
function isModuleEnabled(modules: ModuleInfo[], slug: string): boolean {
  const m = modules.find(m => m.slug === slug)
  return m?.is_enabled ?? false
}
```

Screens that require a module should redirect to a "Feature Not Available" screen when the module is disabled.

---

## 3. Data Models (TypeScript)

### 3.1 Auth

```typescript
interface LoginRequest {
  email: string
  password: string
  remember_me?: boolean
}

interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
}

interface MFARequiredResponse {
  mfa_required: true
  mfa_token: string
  mfa_methods: string[]        // e.g. ['totp', 'sms']
  default_method?: string
}

interface UserProfile {
  id: string
  email: string
  first_name: string | null
  last_name: string | null
  role: 'global_admin' | 'org_admin' | 'branch_admin' | 'salesperson' | 'kiosk'
  mfa_methods: string[]
  has_password: boolean
}

interface MFAMethodStatus {
  method: string
  enabled: boolean
  verified_at: string | null
  phone_number: string | null    // masked e.g. "***1234"
  is_default: boolean
}
```

### 3.2 Organisation & Settings

```typescript
interface OrgSettings {
  name: string
  org_name?: string
  logo_url: string | null
  primary_colour: string         // hex e.g. '#2563eb'
  secondary_colour: string
  address: string | null
  phone: string | null
  email: string | null
  gst_number: string | null
  gst_percentage: number         // e.g. 15
  gst_inclusive: boolean
  invoice_prefix: string
  default_due_days: number
  payment_terms_text: string | null
  terms_and_conditions: string | null
  trade_family: string | null    // e.g. 'automotive-transport'
  trade_category: string | null  // e.g. 'general-automotive'
  sidebar_display_mode: 'icon_and_name' | 'icon_only' | 'name_only'
  address_country?: string | null
}

interface ModuleInfo {
  slug: string
  display_name: string
  description: string
  is_enabled: boolean
  is_core: boolean
  in_plan: boolean
  status: 'available' | 'coming_soon'
}
```

### 3.3 Customer

```typescript
interface Address {
  street?: string
  city?: string
  state?: string
  postal_code?: string
  country?: string
}

interface ContactPerson {
  salutation?: string
  first_name: string
  last_name: string
  email?: string
  work_phone?: string
  mobile_phone?: string
  designation?: string
  is_primary: boolean
}

interface CustomerCreateRequest {
  first_name: string               // required
  last_name?: string
  email?: string
  mobile_phone?: string
  customer_type?: 'individual' | 'business'
  salutation?: string
  company_name?: string
  display_name?: string
  work_phone?: string
  phone?: string
  currency?: string                // default 'NZD'
  language?: string                // default 'en'
  payment_terms?: string           // default 'due_on_receipt'
  enable_portal?: boolean
  enable_bank_payment?: boolean
  address?: string
  billing_address?: Address
  shipping_address?: Address
  contact_persons?: ContactPerson[]
  notes?: string
  remarks?: string
}

interface CustomerResponse {
  id: string
  org_id: string
  branch_id?: string
  first_name: string
  last_name?: string
  display_name?: string
  company_name?: string
  customer_type: string
  email?: string
  phone?: string
  mobile_phone?: string
  work_phone?: string
  address?: string
  billing_address?: Address
  currency: string
  payment_terms: string
  enable_portal: boolean
  portal_token?: string
  receivables: number
  unused_credits: number
  is_anonymised: boolean
  created_at: string
  updated_at: string
}

interface CustomerListItem {
  id: string
  display_name?: string
  first_name: string
  last_name?: string
  company_name?: string
  email?: string
  phone?: string
  work_phone?: string
  receivables: number
  unused_credits: number
  branch_id?: string
}

interface CustomerListResponse {
  customers: CustomerListItem[]
  total: int
}
```

### 3.4 Invoice

```typescript
type InvoiceStatus =
  | 'draft' | 'sent' | 'issued' | 'partially_paid'
  | 'paid' | 'overdue' | 'voided' | 'refunded' | 'partially_refunded'

type ItemType = 'service' | 'part' | 'labour'

interface LineItemCreate {
  item_type: ItemType
  description: string             // min 1, max 2000 chars
  quantity: number                // > 0
  unit_price?: number             // ≥ 0
  rate?: number                   // alias for unit_price
  hours?: number
  hourly_rate?: number
  discount_type?: 'percentage' | 'fixed'
  discount_value?: number         // ≥ 0
  is_gst_exempt?: boolean
  warranty_note?: string
  catalogue_item_id?: string
  stock_item_id?: string
  sort_order?: number
}

interface LineItemResponse {
  id: string
  item_type: string
  description: string
  quantity: number
  unit_price: number
  hours?: number
  hourly_rate?: number
  discount_type?: string
  discount_value?: number
  is_gst_exempt: boolean
  warranty_note?: string
  line_total: number
  sort_order: number
}

interface VehicleItem {
  id?: string
  rego?: string
  make?: string
  model?: string
  year?: number
  odometer?: number
}

interface InvoiceCreateRequest {
  customer_id: string
  vehicle_rego?: string
  vehicle_make?: string
  vehicle_model?: string
  vehicle_year?: number
  vehicle_odometer?: number
  global_vehicle_id?: string
  vehicles?: VehicleItem[]
  branch_id?: string
  status?: InvoiceStatus          // default 'draft'
  line_items?: LineItemCreate[]
  notes_internal?: string
  notes_customer?: string         // alias: customer_notes
  terms_and_conditions?: string
  issue_date?: string             // ISO date, defaults to today
  due_date?: string
  payment_terms?: string          // 'due_on_receipt' | 'net_15' | 'net_30' etc
  discount_type?: 'percentage' | 'fixed'
  discount_value?: number
  currency?: string               // default 'NZD'
}

interface PaymentSummary {
  id: string
  date?: string
  amount: number
  method: string                  // 'cash' | 'stripe' | 'bank_transfer' etc
  recorded_by: string
  note?: string
  is_refund: boolean
  refund_note?: string
}

interface CreditNoteSummary {
  id: string
  reference_number: string
  amount: number
  reason: string
  created_at?: string
}

interface InvoiceResponse {
  id: string
  org_id: string
  invoice_number?: string
  customer_id: string
  customer?: {
    id: string
    first_name: string
    last_name: string
    email?: string
    phone?: string
    company_name?: string
    display_name?: string
  }
  vehicle_rego?: string
  vehicle_make?: string
  vehicle_model?: string
  vehicle_year?: number
  vehicle_odometer?: number
  branch_id?: string
  status: InvoiceStatus
  issue_date?: string
  due_date?: string
  payment_terms?: string
  currency: string
  subtotal: number
  discount_amount: number
  discount_type?: string
  discount_value?: number
  gst_amount: number
  total: number
  amount_paid: number
  balance_due: number
  notes_internal?: string
  notes_customer?: string
  line_items: LineItemResponse[]
  payments: PaymentSummary[]
  credit_notes: CreditNoteSummary[]
  org_name?: string
  org_address?: string
  org_phone?: string
  org_email?: string
  org_logo_url?: string
  org_gst_number?: string
  payment_page_url?: string
  attachment_count: number
  created_at: string
  updated_at: string
}

interface InvoiceListItem {
  id: string
  invoice_number?: string
  customer_name?: string
  vehicle_rego?: string
  total: number
  status: InvoiceStatus
  issue_date?: string
  attachment_count: number
}

interface InvoiceListResponse {
  invoices: InvoiceListItem[]
  total: number
  limit: number
  offset: number
}
```

### 3.5 Quote

```typescript
type QuoteStatus = 'draft' | 'sent' | 'accepted' | 'declined' | 'expired' | 'converted'

interface QuoteCreateRequest {
  customer_id: string
  valid_until: string              // ISO date
  subject?: string
  line_items: LineItemCreate[]
  discount_type?: 'percentage' | 'fixed'
  discount_value?: number
  notes?: string
  terms?: string
  vehicle_rego?: string
  branch_id?: string
}

interface QuoteResponse {
  id: string
  quote_number?: string
  status: QuoteStatus
  customer_id: string
  customer?: CustomerSummary
  vehicle_rego?: string
  valid_until: string
  subject?: string
  line_items: LineItemResponse[]
  subtotal: number
  discount_amount: number
  gst_amount: number
  total: number
  notes?: string
  terms?: string
  converted_invoice_id?: string
  created_at: string
  updated_at: string
}
```

### 3.6 Job Card

```typescript
type JobCardStatus = 'open' | 'in_progress' | 'completed' | 'invoiced'

interface JobCardCreate {
  customer_id: string
  vehicle_rego?: string
  vehicle_make?: string
  vehicle_model?: string
  vehicle_year?: number
  description?: string
  notes?: string
  line_items?: JobCardLineItemCreate[]
  service_type_id?: string
  service_type_values?: Record<string, unknown>[]
}

interface JobCardLineItemCreate {
  item_type: ItemType
  description: string
  quantity: number
  unit_price: number
  is_gst_exempt?: boolean
  sort_order?: number
}

interface JobCardResponse {
  id: string
  org_id: string
  customer_id: string
  customer?: {
    first_name: string
    last_name: string
    email?: string
    phone?: string
  }
  vehicle_rego?: string
  status: JobCardStatus
  description?: string
  notes?: string
  assigned_to?: string
  assigned_to_name?: string
  job_card_number?: string
  line_items: JobCardLineItemResponse[]
  timer_start?: string
  timer_elapsed_seconds?: number
  created_at: string
  updated_at: string
}

interface JobCardLineItemResponse {
  id: string
  item_type: string
  description: string
  quantity: number
  unit_price: number
  is_completed: boolean
  line_total: number
  sort_order: number
}
```

### 3.7 Job (v2)

```typescript
type JobStatus = 'draft' | 'scheduled' | 'in_progress' | 'on_hold' | 'completed' | 'invoiced' | 'cancelled'

const VALID_JOB_TRANSITIONS: Record<JobStatus, JobStatus[]> = {
  draft: ['scheduled', 'cancelled'],
  scheduled: ['in_progress', 'cancelled'],
  in_progress: ['on_hold', 'completed', 'cancelled'],
  on_hold: ['in_progress', 'cancelled'],
  completed: ['invoiced', 'cancelled'],
  invoiced: ['cancelled'],
  cancelled: [],
}

interface JobCreate {
  title: string
  customer_id?: string
  project_id?: string
  template_id?: string
  description?: string
  priority?: 'low' | 'normal' | 'high' | 'urgent'
  site_address?: string
  scheduled_start?: string        // ISO datetime
  scheduled_end?: string
  checklist?: { text: string; done: boolean }[]
  internal_notes?: string
  customer_notes?: string
}

interface JobResponse {
  id: string
  title: string
  status: JobStatus
  customer_id?: string
  customer?: CustomerSummary
  project_id?: string
  description?: string
  priority: string
  site_address?: string
  scheduled_start?: string
  scheduled_end?: string
  checklist: { id: string; text: string; done: boolean }[]
  attachments: JobAttachment[]
  assigned_staff: { user_id: string; role: string }[]
  internal_notes?: string
  customer_notes?: string
  created_at: string
  updated_at: string
}

interface JobAttachment {
  id: string
  file_key: string
  file_name: string
  file_size: number
  content_type?: string
  uploaded_at: string
}
```

### 3.8 Booking

```typescript
type BookingStatus = 'pending' | 'confirmed' | 'completed' | 'cancelled'

interface BookingCreate {
  customer_name: string
  customer_email?: string
  customer_phone?: string
  staff_id?: string
  service_type?: string
  start_time: string              // ISO datetime
  end_time: string
  notes?: string
}

interface BookingResponse {
  id: string
  org_id: string
  customer_name: string
  customer_email?: string
  customer_phone?: string
  staff_id?: string
  service_type?: string
  start_time: string
  end_time: string
  status: BookingStatus
  notes?: string
  converted_job_id?: string
  converted_invoice_id?: string
  created_at: string
}

interface TimeSlot {
  start_time: string
  end_time: string
  available: boolean
}
```

### 3.9 Payment

```typescript
interface CashPaymentRequest {
  invoice_id: string
  amount: number                  // > 0
  notes?: string
}

interface PaymentResponse {
  id: string
  org_id: string
  invoice_id: string
  amount: number
  method: string
  recorded_by: string
  created_at: string
}
```

### 3.10 Expense

```typescript
interface ExpenseCreate {
  date: string                    // ISO date
  description: string
  amount: number                  // > 0
  tax_amount?: number
  category?: string
  reference_number?: string
  notes?: string
  receipt_file_key?: string       // from upload endpoint
  is_billable?: boolean
  is_pass_through?: boolean
  tax_inclusive?: boolean
  expense_type?: 'expense' | 'mileage'
  job_id?: string
  project_id?: string
  customer_id?: string
}

interface ExpenseResponse {
  id: string
  org_id: string
  date: string
  description: string
  amount: number
  tax_amount: number
  category?: string
  reference_number?: string
  receipt_file_key?: string
  is_billable: boolean
  is_invoiced: boolean
  expense_type: string
  created_at: string
  updated_at: string
}
```

### 3.11 Staff

```typescript
interface StaffMemberCreate {
  first_name: string
  last_name?: string
  email?: string
  phone?: string
  employee_id?: string
  position?: string
  shift_start?: string            // HH:MM format
  shift_end?: string
  role_type: 'employee' | 'contractor'
  hourly_rate?: number
  overtime_rate?: number
  availability_schedule?: Record<string, { start: string; end: string }>
  skills?: string[]
}

interface StaffMemberResponse {
  id: string
  org_id: string
  user_id?: string
  name: string
  first_name: string
  last_name?: string
  email?: string
  phone?: string
  employee_id?: string
  position?: string
  shift_start?: string
  shift_end?: string
  role_type: string
  hourly_rate?: number
  overtime_rate?: number
  is_active: boolean
  availability_schedule: Record<string, unknown>
  skills: string[]
}
```

### 3.12 Vehicle (automotive trade only)

```typescript
interface VehicleLookupResponse {
  id: string                      // Global vehicle UUID
  rego: string
  make?: string
  model?: string
  year?: number
  colour?: string
  body_type?: string
  fuel_type?: string
  engine_size?: string
  seats?: number
  wof_expiry?: string             // ISO date
  rego_expiry?: string
  odometer?: number
  source: 'cache' | 'carjam'
}

interface ManualVehicleCreate {
  rego: string
  make?: string
  model?: string
  year?: number
  colour?: string
  body_type?: string
  fuel_type?: string
  vin?: string
  chassis?: string
  engine_no?: string
  transmission?: string
  wof_expiry?: string
  rego_expiry?: string
  odometer?: number
}
```

### 3.13 Recurring Invoice

```typescript
type RecurringFrequency = 'weekly' | 'fortnightly' | 'monthly' | 'quarterly' | 'annually'

interface RecurringScheduleCreate {
  customer_id: string
  frequency: RecurringFrequency
  line_items: RecurringLineItem[]
  next_due_date: string           // ISO date
  auto_issue?: boolean
  notes?: string
}

interface RecurringLineItem {
  item_type: ItemType
  description: string
  quantity: number
  unit_price: number
  is_gst_exempt?: boolean
}

interface RecurringScheduleResponse {
  id: string
  customer_id: string
  frequency: string
  line_items: LineItemCreate[]
  auto_issue: boolean
  is_active: boolean
  next_due_date?: string
  last_generated_at?: string
  notes?: string
  created_at: string
}
```

### 3.14 Claim

```typescript
type ClaimType = 'warranty' | 'defect' | 'service_redo' | 'exchange' | 'refund_request'
type ClaimStatus = 'open' | 'investigating' | 'approved' | 'rejected' | 'resolved'
type ResolutionType = 'partial_refund' | 'full_refund' | 'credit_note' | 'redo_service' | 'exchange' | 'no_action'

interface ClaimCreateRequest {
  customer_id: string
  claim_type: ClaimType
  description: string
  invoice_id?: string
  job_card_id?: string
  line_item_ids?: string[]
  branch_id?: string
}

interface ClaimResponse {
  id: string
  reference?: string
  customer_id: string
  customer?: CustomerSummary
  claim_type: ClaimType
  status: ClaimStatus
  description: string
  invoice_id?: string
  job_card_id?: string
  resolution_type?: ResolutionType
  resolution_amount?: number
  resolution_notes?: string
  labour_cost: number
  parts_cost: number
  write_off_cost: number
  timeline: ClaimAction[]
  created_at: string
}

interface ClaimAction {
  id: string
  action_type: string
  from_status?: string
  to_status?: string
  notes?: string
  performed_by: string
  performed_by_name?: string
  performed_at: string
}
```

### 3.15 Portal

```typescript
interface PortalAccessResponse {
  customer: {
    id: string
    name: string
    email?: string
    phone?: string
  }
  branding: {
    org_name: string
    logo_url?: string
    primary_colour: string
    secondary_colour: string
  }
  stats: {
    outstanding_balance: number
    total_invoices: number
    total_paid: number
  }
  modules_enabled: {
    invoices: boolean
    quotes: boolean
    bookings: boolean
    vehicles: boolean
    assets: boolean
    loyalty: boolean
  }
}

// NOTE: The frontend web app uses a flat PortalInfo interface but
// the backend returns this nested structure. Use the nested version.
```

---

## 4. Screen Inventory

The following screens should be built in the Expo app. Module gates are noted — skip the screen (or show "Feature Not Available") if the module is disabled.

### 4.1 Auth Screens

| Screen | Route | Fetches | Actions |
|--------|-------|---------|---------|
| LoginScreen | `/login` | — | `POST /auth/login`, Google OAuth button, Passkey button |
| MfaScreen | `/mfa-verify` | — | `POST /auth/mfa/challenge/send`, `POST /auth/mfa/verify`, Passkey option |
| ForgotPasswordScreen | `/forgot-password` | — | `POST /auth/password/reset-request` |
| BiometricLockScreen | `/biometric-lock` | SecureStore refresh token | expo-local-authentication prompt, fallback to Login |

### 4.2 Dashboard

| Screen | Module | Fetches | Displays |
|--------|--------|---------|----------|
| DashboardScreen | None | `GET /dashboard/branch-metrics`, `GET /dashboard/widgets`, `GET /dashboard/todays-bookings` | Revenue KPIs (today / this week / this month), today's bookings list, overdue invoices count, cash-flow mini-chart |

### 4.3 Invoices

| Screen | Module | Fetches | Actions |
|--------|--------|---------|---------|
| InvoiceListScreen | None | `GET /invoices?page=&status=&search=` | Pull-to-refresh, search, filter by status, tap → detail, swipe → quick void/send |
| InvoiceDetailScreen | None | `GET /invoices/{id}` | View line items + payments, send email, record cash payment, download PDF, void, duplicate, generate Stripe link |
| InvoiceCreateScreen | None | `GET /customers` (picker), `GET /catalogue/items` (line item search), `GET /vehicles/lookup/{rego}` (automotive) | Create invoice with line items; submit → `POST /invoices` |
| InvoicePDFScreen | None | `GET /invoices/{id}/pdf` (blob) | Render PDF via `PDFViewer`, share/print |

### 4.4 Customers

| Screen | Module | Fetches | Actions |
|--------|--------|---------|---------|
| CustomerListScreen | None | `GET /customers?search=` | Search, tap → profile, swipe → notify |
| CustomerProfileScreen | None | `GET /customers/{id}`, `GET /invoices?customer_id=` | View history, edit, notify (email/sms), merge |
| CustomerCreateScreen | None | — | Create customer form → `POST /customers` |
| CustomerEditScreen | None | `GET /customers/{id}` | Edit → `PUT /customers/{id}` |

### 4.5 Jobs (v2 — module: `jobs`)

| Screen | Module | Fetches | Actions |
|--------|--------|---------|---------|
| JobListScreen | `jobs` | `GET /api/v2/jobs?status=&page=` | Filter status, search, pull-to-refresh |
| JobBoardScreen | `jobs` | `GET /api/v2/jobs` | Kanban columns; drag cards to change status |
| JobDetailScreen | `jobs` | `GET /api/v2/jobs/{id}` | View checklist, attachments, staff; change status `PUT /api/v2/jobs/{id}/status`; upload attachments |
| JobCardListScreen | `jobs` | `GET /job-cards?page=&status=` | List job cards; start/stop timer |
| JobCardCreateScreen | `jobs` | `GET /customers`, `GET /catalogue/items` | Create job card → `POST /job-cards` |
| JobCardDetailScreen | `jobs` | `GET /job-cards/{id}` | View items, edit, complete, convert to invoice |

### 4.6 Quotes (module: `quotes`)

| Screen | Module | Fetches | Actions |
|--------|--------|---------|---------|
| QuoteListScreen | `quotes` | `GET /api/v2/quotes` | Filter by status (draft/sent/accepted/declined/expired/converted), search |
| QuoteCreateScreen | `quotes` | `GET /customers`, `GET /catalogue/items` | Create with line items → `POST /api/v2/quotes` |
| QuoteDetailScreen | `quotes` | `GET /api/v2/quotes/{id}` | Send `PUT /{id}/send`, convert `POST /{id}/convert-to-invoice`, revise `POST /{id}/revise` |

### 4.7 Bookings (module: `bookings`)

| Screen | Module | Fetches | Actions |
|--------|--------|---------|---------|
| BookingCalendarScreen | `bookings` | `GET /api/v2/bookings?start=&end=` | Day/week calendar view, tap slot to create, tap booking to view |
| BookingCreateScreen | `bookings` | `GET /api/v2/bookings/slots?date=`, `GET /api/v2/staff` | Create booking; available slot picker → `POST /api/v2/bookings` |

### 4.8 Inventory (module: `inventory`)

| Screen | Module | Fetches | Actions |
|--------|--------|---------|---------|
| InventoryListScreen | `inventory` | `GET /api/v1/inventory/stock-items` | Search, filter by reorder needed |
| InventoryDetailScreen | `inventory` | `GET /api/v1/inventory/stock-items/{id}` | View stock levels, add stock `POST /{id}/add-stock`, view movement log |

### 4.9 Vehicles (module: `vehicles`, automotive only)

| Screen | Fetches | Actions |
|--------|---------|---------|
| VehicleListScreen | `GET /vehicles` | Search by rego, filter by expiry status |
| VehicleProfileScreen | `GET /vehicles/{id}` | View service history, edit dates |
| VehicleLookupModal | `GET /vehicles/lookup/{rego}` (CarJam) | Lookup → confirm → attach to invoice/job card |

### 4.10 Expenses (module: `expenses`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| ExpenseListScreen | `GET /api/v2/expenses` | Filter by date/category, search |
| ExpenseCreateScreen | `POST /api/v2/uploads/receipts`, `POST /api/v2/expenses` | Camera capture receipt, enter amount/category |

### 4.11 Staff (module: `staff`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| StaffListScreen | `GET /api/v2/staff` | Search, filter active/inactive |
| StaffDetailScreen | `GET /api/v2/staff/{id}` | View/edit profile, toggle active |

### 4.12 Time Tracking (module: `time_tracking`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| TimeTrackingScreen | `GET /api/v2/time-entries/timesheet`, `GET /api/v2/projects` | View daily/weekly, add entries, detect overlaps, convert to invoice |

### 4.13 Projects (module: `projects`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| ProjectListScreen | `GET /api/v2/projects` | Filter by status |
| ProjectDashboardScreen | `GET /api/v2/projects/{id}` | View budget vs actuals, linked invoices/expenses |

### 4.14 Reports

| Screen | Fetches | Displays |
|--------|---------|----------|
| ReportsMenuScreen | — | List available report types |
| ReportViewScreen | dynamic based on type | Revenue summary, invoice status, outstanding, top services, GST summary |

### 4.15 Purchase Orders (module: `purchase_orders`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| POListScreen | `GET /api/v2/purchase-orders` | Filter by status |
| PODetailScreen | `GET /api/v2/purchase-orders/{id}` | View line items, send, mark received |

### 4.16 Recurring Invoices (module: `recurring_invoices`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| RecurringListScreen | `GET /api/v2/recurring`, `GET /api/v2/recurring/dashboard` | Dashboard stats, list, pause/resume |
| RecurringDetailScreen | `GET /api/v2/recurring/{id}` | Edit schedule, cancel |

### 4.17 Accounting (module: `accounting`)

| Screen | Fetches | Displays |
|--------|---------|----------|
| ChartOfAccountsScreen | `GET /api/v1/ledger/accounts` | Account tree by type |
| JournalEntryListScreen | `GET /api/v1/ledger/journal-entries` | Journal list |
| JournalEntryDetailScreen | `GET /api/v1/ledger/journal-entries/{id}` | Debit/credit lines |
| BankAccountsScreen | `GET /api/v1/banking/accounts` | Bank accounts, sync button |
| BankTransactionsScreen | `GET /api/v1/banking/transactions?account_id=` | Transaction list, match to invoices |
| ReconciliationScreen | `GET /api/v1/banking/reconciliation` | Reconciliation summary |
| GstPeriodsScreen | `GET /api/v1/gst/periods` | GST period list |
| GstFilingDetailScreen | `GET /api/v1/gst/periods/{id}` | Period breakdown |
| TaxPositionScreen | `GET /api/v1/tax-wallets/position` | Net tax chart |

### 4.18 Compliance (module: `compliance_docs`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| ComplianceDashboardScreen | `GET /api/v2/compliance-docs/dashboard` | Summary cards, doc list with expiry badges |
| ComplianceUploadScreen | `POST /api/v2/uploads/attachments`, `POST /api/v2/compliance-docs` | Camera/file picker → upload |

### 4.19 Claims (module: `customer_claims`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| ClaimsListScreen | `GET /api/v1/claims` | Filter by status/type, search |
| ClaimDetailScreen | `GET /api/v1/claims/{id}` | View timeline, change status `PATCH /{id}/status`, resolve `POST /{id}/resolve` |
| ClaimCreateScreen | `GET /customers`, `GET /invoices?customer_id=` | Create claim → `POST /api/v1/claims` |

### 4.20 POS (module: `pos`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| POSScreen | `GET /api/v2/products`, `GET /api/v2/products/barcode/{code}` | Barcode scan, tap product, adjust qty, record payment `POST /api/v2/pos/transactions`, print receipt |

### 4.21 SMS (module: `sms`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| SMSComposeScreen | `GET /api/v1/customers/{id}` (contact lookup) | Compose + send SMS to customer |

### 4.22 Notifications

| Screen | Fetches | Actions |
|--------|---------|---------|
| NotificationPreferencesScreen | `GET /api/v1/notifications/preferences` | Toggle email/SMS for each event type |

### 4.23 Schedule (module: `scheduling`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| ScheduleCalendarScreen | `GET /api/v2/schedule?start=&end=&staff_id=` | Week view roster, assign entries |

### 4.24 Franchise (module: `franchise`)

| Screen | Fetches | Actions |
|--------|---------|---------|
| FranchiseDashboardScreen | `GET /api/v2/franchise/dashboard` | Per-location metrics |
| LocationDetailScreen | `GET /api/v2/franchise/locations/{id}` | Location detail, staff |
| StockTransferListScreen | `GET /api/v2/franchise/transfers` | Transfer list, create transfer |

### 4.25 Construction Modules

| Screen | Module | Fetches |
|--------|--------|---------|
| ProgressClaimListScreen | `progress_claims` | `GET /api/v2/progress-claims` |
| VariationListScreen | `variations` | `GET /api/v2/variations` |
| RetentionSummaryScreen | `retentions` | `GET /api/v2/retentions` |

### 4.26 More Menu

| Screen | Notes |
|--------|-------|
| MoreMenuScreen | Grid of tiles linking to all secondary screens. Module-gated tiles hidden when disabled. |

### 4.27 Settings

| Screen | Fetches | Actions |
|--------|---------|---------|
| SettingsScreen | `GET /org/settings`, `GET /auth/me` | Profile edit, change password, language, MFA settings, app info/version |

### 4.28 Customer Portal (public — no auth token)

| Screen | Fetches | Actions |
|--------|---------|---------|
| PortalHomeScreen | `GET /portal/{token}` | Show tabs for enabled sections |
| PortalInvoicesScreen | `GET /portal/{token}/invoices` | View invoice list, pay |
| PortalQuotesScreen | `GET /portal/{token}/quotes` | View quotes, accept a quote |
| PortalVehiclesScreen | `GET /portal/{token}/vehicles` | Service history |
| PortalBookingsScreen | `GET /portal/{token}/bookings`, `GET /portal/{token}/bookings/slots` | Create booking |
| PortalLoyaltyScreen | `GET /portal/{token}/loyalty` | Points balance + history |

### 4.29 Kiosk (kiosk role only)

| Screen | Route | Fetches | Actions |
|--------|-------|---------|---------|
| KioskScreen | `/kiosk` | — | Customer check-in form → `POST /kiosk/check-in` |

---

## 5. Business Rules

### 5.1 GST / Tax Calculation

The default GST rate is **15% (NZ)**. This is configurable per org in `gst_percentage`.

**Standard calculation (GST-exclusive):**
```
subtotal = Σ line_item.line_total
discount_amount = discount_type === 'percentage'
  ? subtotal * (discount_value / 100)
  : discount_value ?? 0
after_discount = subtotal - discount_amount
gst_amount = after_discount * (gst_percentage / 100)   // only taxable line items
total = after_discount + gst_amount
```

**GST-inclusive items** (`gst_inclusive: true` on line item):
```
exclusive_price = inclusive_price / (1 + gst_percentage / 100)
line_total = exclusive_price * quantity
```

**GST-exempt line items** (`is_gst_exempt: true`): contribute to `after_discount` but not `gst_amount`.

Always display amounts to **2 decimal places** using locale formatting (NZD: `$1,234.56`).

### 5.2 Invoice Status Flow

```
draft → issued      (user clicks "Issue")
      → voided      (can void a draft)

issued → partially_paid  (partial cash/stripe payment recorded)
       → paid            (full payment received)
       → overdue         (server cron — when due_date < today and balance_due > 0)
       → voided          (user voids an issued invoice)

partially_paid → paid    (remaining balance paid)
               → refunded / partially_refunded (via credit note or refund)

paid → refunded          (full refund)
     → partially_refunded (partial refund)

Voided and refunded are terminal — no further transitions.
```

UI action availability:
- **Send email**: when status is `draft`, `issued`, or `overdue`
- **Record payment**: when `balance_due > 0` and status not `voided`/`refunded`
- **Void**: when status is `draft`, `issued`, `overdue`, or `partially_paid`
- **Credit note / refund**: when status is `paid`, `partially_paid`
- **Edit (full)**: draft only — once issued, only `notes` and `payment_terms` are editable
- **Duplicate**: any status

### 5.3 Quote Status Flow

```
draft → sent      (user clicks "Send")
      → expired   (server cron when valid_until < today)
      → deleted

sent → accepted   (customer accepts via portal or staff clicks "Convert")
     → declined   (staff marks declined)
     → expired    (cron)

accepted → converted  (converted to invoice)
         
declined / expired → re-quoted (creates new draft)
```

Action availability:
- **Send**: draft only
- **Convert to invoice**: sent or accepted
- **Re-quote**: declined or expired
- **Delete**: draft only

### 5.4 Job Status Transitions

Valid transitions (enforce in UI — disable invalid buttons):

```
draft → scheduled | cancelled
scheduled → in_progress | cancelled
in_progress → on_hold | completed | cancelled
on_hold → in_progress | cancelled
completed → invoiced | cancelled
invoiced → cancelled
cancelled → (terminal)
```

### 5.5 Recurring Invoice Rules

- `next_due_date` is required; server generates invoices automatically on that date
- `auto_issue: true` → generated invoice is immediately set to `issued`
- `auto_issue: false` → generated as `draft` for manual review
- After generation, `next_due_date` advances by one `frequency` interval

### 5.6 Progress Claim Auto-Calculations

```typescript
revised_contract = contract_value + variations
this_period = work_completed_to_date - work_completed_previous
retention_withheld = (this_period + materials_on_site) * retention_rate / 100
amount_due = this_period + materials_on_site - retention_withheld
completion_pct = work_completed_to_date / revised_contract * 100

// Validation
if work_completed_to_date > revised_contract → error
if retention_rate < 0 || retention_rate > 100 → error
```

### 5.7 Automotive-Only Features

When `trade_family !== 'automotive-transport'`, hide these from the UI:

- Vehicles tab / nav item
- Vehicle rego field on invoices and job cards
- WOF / rego expiry fields on customer list
- CarJam lookup buttons
- Fleet report tab

Determine trade family from `GET /api/v1/org/settings` → `trade_family`.

### 5.8 Multi-Currency

If `gst_inclusive: false` (org default for NZ), `currency` defaults to `NZD`.

For multi-currency invoices:
- `exchange_rate_to_nzd` must be provided when `currency !== 'NZD'`
- `total_nzd = total * exchange_rate_to_nzd`
- Display in the invoice's own currency; show NZD equivalent in smaller text

Supported currencies: `NZD AUD USD GBP EUR JPY CAD SGD HKD CNY FJD WST TOP PGK`

### 5.9 Payment Terms Labels

| Value | Display |
|-------|---------|
| `due_on_receipt` | Due on Receipt |
| `net_7` | Net 7 Days |
| `net_15` | Net 15 Days |
| `net_30` | Net 30 Days |
| `net_45` | Net 45 Days |
| `net_60` | Net 60 Days |
| `net_90` | Net 90 Days |

### 5.10 Due Date Urgency Logic

Show coloured badges based on days until/since due:

```typescript
function getDueDateStatus(dueDate: string, status: InvoiceStatus) {
  if (['paid', 'voided', 'refunded'].includes(status)) return 'none'
  const days = differenceInDays(parseISO(dueDate), new Date())
  if (days < 0) return 'overdue'    // red
  if (days === 0) return 'today'    // amber
  if (days <= 7) return 'soon'      // amber
  return 'ok'                       // green
}
```

### 5.11 Quote Expiry Logic

```typescript
function getQuoteExpiryStatus(validUntil: string): 'expired' | 'today' | 'warning' | 'ok' {
  const days = differenceInDays(parseISO(validUntil), new Date())
  if (days < 0) return 'expired'
  if (days === 0) return 'today'
  if (days <= 7) return 'warning'
  return 'ok'
}
```

### 5.12 Vehicle Compliance Status (automotive)

```typescript
function getComplianceStatus(expiryDate: string | null): 'expired' | 'warning' | 'ok' | 'unknown' {
  if (!expiryDate) return 'unknown'
  const days = differenceInDays(parseISO(expiryDate), new Date())
  if (days < 0) return 'expired'    // red
  if (days <= 30) return 'warning'  // amber
  return 'ok'                       // green
}
```

### 5.13 Time Overlap Detection

When a user adds or edits a time entry, check for overlaps with existing entries on the same day for the same staff member:

```typescript
function hasOverlap(
  entries: TimeEntry[],
  candidate: { start_time: string; end_time: string },
  excludeId?: string
): boolean {
  return entries
    .filter(e => e.id !== excludeId)
    .some(e =>
      parseISO(candidate.start_time) < parseISO(e.end_time) &&
      parseISO(candidate.end_time) > parseISO(e.start_time)
    )
}
```

Highlight overlapping entries in red. Allow saving but show warning.

### 5.14 Module Gating UI Behaviour

- **Disabled module → screen shown**: render a "Feature Not Available" / "Upgrade your plan" screen
- **Disabled module → nav item**: hide it entirely from the tab bar and More menu
- **Loading modules**: show a spinner/skeleton before rendering any gated screen
- **Fetch on login**: load modules and flags once after successful auth, cache for session

### 5.15 Claim Status Transitions

```
open → investigating (staff starts investigation)
investigating → approved | rejected
approved → resolved
rejected → resolved
```

Resolution types available:
- `partial_refund` / `full_refund` — requires `resolution_amount`
- `credit_note` — creates credit on account
- `redo_service` — rebook the job
- `exchange` — return and replace stock
- `no_action` — claim closed without remedy

### 5.16 Validation Rules Summary

| Field | Rule |
|-------|------|
| Invoice line items | At least 1 line item to issue; each must have description ≥ 1 char |
| Invoice quantity | Must be > 0 |
| Invoice unit_price | Must be ≥ 0 |
| Due date | Must be ≥ issue date |
| Quote valid_until | Must be a future date when creating |
| Customer first_name | Required, 1–100 chars |
| Staff shift_start / shift_end | HH:MM format (regex: `^\d{2}:\d{2}$`) |
| Currency code | Exactly 3 uppercase chars |
| Staff role_type | Must be `employee` or `contractor` |
| Job status | Must follow VALID_JOB_TRANSITIONS map |
| Expense amount | Must be > 0 |
| Password | Min 8 chars; check HIBP via `POST /auth/password/check` before submitting |
| MFA code | Exactly 6 digits |
| Progress claim | Cumulative work ≤ revised contract value |

---

## 6. Environment Config

### 6.1 Expo App Environment Variables

Create a `.env` (or use `app.config.ts` with `extra` / `expo-constants`) for the mobile app:

```bash
# API base URL — point to the running backend
EXPO_PUBLIC_API_BASE_URL=https://your-domain.com

# Stripe publishable key — fetched from backend but can be pre-populated
# GET /api/v1/auth/stripe-publishable-key returns it dynamically
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...

# Google OAuth client ID (for Google Sign-In on mobile)
EXPO_PUBLIC_GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com

# App scheme for deep links / OAuth callbacks
EXPO_PUBLIC_APP_SCHEME=orainvoice

# App version (displayed in Settings screen)
EXPO_PUBLIC_APP_VERSION=1.0.0

# WebAuthn / Passkeys — RP ID must match the domain
EXPO_PUBLIC_WEBAUTHN_RP_ID=your-domain.com
```

### 6.2 API Client Setup (Expo)

```typescript
// api/client.ts
import axios from 'axios'
import * as SecureStore from 'expo-secure-store'

const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
})

// Inject access token on every request
apiClient.interceptors.request.use(async (config) => {
  const token = getAccessToken()    // in-memory store
  if (token) config.headers.Authorization = `Bearer ${token}`

  const branchId = await SecureStore.getItemAsync('active_branch_id')
  if (branchId) config.headers['X-Branch-Id'] = branchId

  return config
})

// Handle 401 with token refresh
let refreshPromise: Promise<string> | null = null

apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status !== 401) throw error

    if (!refreshPromise) {
      refreshPromise = doRefresh().finally(() => { refreshPromise = null })
    }

    const newToken = await refreshPromise
    error.config.headers.Authorization = `Bearer ${newToken}`
    return apiClient.request(error.config)
  }
)

async function doRefresh(): Promise<string> {
  const refreshToken = await SecureStore.getItemAsync('refresh_token')
  if (!refreshToken) throw new Error('No refresh token')

  const { data } = await axios.post(`${BASE_URL}/api/v1/auth/token/refresh`, {
    refresh_token: refreshToken,
  })

  setAccessToken(data.access_token)
  await SecureStore.setItemAsync('refresh_token', data.refresh_token)
  return data.access_token
}
```

### 6.3 SecureStore Keys

| Key | Contents |
|-----|---------|
| `refresh_token` | JWT refresh token string |
| `active_branch_id` | UUID of currently selected branch (optional) |
| `biometric_enabled` | `'true'` / `'false'` user preference |

Never store the access token in SecureStore — keep it in memory only (Zustand store or React context).

### 6.4 Backend Server Variables (for reference — not in mobile .env)

The backend is configured via these environment variables. You need to know them to understand what features are available:

| Variable | Default | Notes |
|----------|---------|-------|
| `ENVIRONMENT` | `production` | `development` enables debug docs, relaxed rate limits |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Standard refresh lifetime |
| `REFRESH_TOKEN_REMEMBER_DAYS` | `30` | "Remember me" refresh lifetime |
| `RATE_LIMIT_PER_USER_PER_MINUTE` | `100` | Per-user request rate limit |
| `RATE_LIMIT_AUTH_PER_IP_PER_MINUTE` | `10` | Auth endpoint rate limit (stricter) |
| `CARJAM_API_KEY` | — | Required for NZ vehicle lookup |
| `FIREBASE_PROJECT_ID` | — | Required for SMS MFA via Firebase |
| `STRIPE_PUBLISHABLE_KEY` | — | Fetched by mobile via `/api/v1/auth/stripe-publishable-key` |

### 6.5 Recommended Expo Dependencies

```json
{
  "dependencies": {
    "expo": "~52.x",
    "expo-secure-store": "~14.x",
    "expo-local-authentication": "~14.x",
    "expo-camera": "~15.x",
    "expo-document-picker": "~12.x",
    "expo-file-system": "~17.x",
    "expo-notifications": "~0.29.x",
    "expo-linking": "~7.x",
    "expo-constants": "~17.x",
    "@stripe/stripe-react-native": "^0.38.x",
    "axios": "^1.7.x",
    "zustand": "^5.x",
    "react-native-calendars": "^1.1306.x",
    "react-native-webview": "^13.x",
    "@gorhom/bottom-sheet": "^5.x",
    "date-fns": "^4.x"
  }
}
```

### 6.6 Deep Link Configuration

Register the app scheme for OAuth callbacks and push notification navigation:

```typescript
// app.config.ts
export default {
  scheme: process.env.EXPO_PUBLIC_APP_SCHEME ?? 'orainvoice',
  android: {
    intentFilters: [
      {
        action: 'VIEW',
        data: [{ scheme: 'orainvoice' }],
        category: ['BROWSABLE', 'DEFAULT'],
      },
    ],
  },
  ios: {
    bundleIdentifier: 'com.yourcompany.orainvoice',
    associatedDomains: [`applinks:${process.env.EXPO_PUBLIC_API_BASE_URL?.replace('https://', '')}`],
  },
}
```

Deep link routes to handle:

| URL Pattern | Screen |
|-------------|--------|
| `orainvoice://invoices/{id}` | InvoiceDetailScreen |
| `orainvoice://customers/{id}` | CustomerProfileScreen |
| `orainvoice://jobs/{id}` | JobDetailScreen |
| `orainvoice://bookings/{id}` | BookingDetailScreen |
| `orainvoice://portal/{token}` | PortalHomeScreen |

---

*Last updated: 2026-05-01*

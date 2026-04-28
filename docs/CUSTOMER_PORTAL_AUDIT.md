# Customer Portal — Full Gap & Issue Audit

**Date**: 2026-04-28  
**Investigator**: Claude (read-only, no code changed)  
**Scope**: Backend (`app/modules/portal/`), frontend (`frontend/src/pages/portal/`), mobile (`mobile/src/screens/`), middleware, schemas, routing, Stripe integration, security controls  
**Total Issues Found**: 23  

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Critical — Broken at Runtime](#critical--broken-at-runtime)
3. [High — Security Gaps](#high--security-gaps)
4. [Medium — Feature Gaps and Missing Flows](#medium--feature-gaps-and-missing-flows)
5. [Low — Code Quality and UX Gaps](#low--code-quality-and-ux-gaps)
6. [Summary Table](#summary-table)
7. [Recommended Fix Order](#recommended-fix-order)

---

## Executive Summary

The customer portal exists as a backend module with full routing and service logic, but the frontend and backend have drifted so far apart that **the portal is non-functional end-to-end**. The landing page shows blank/NaN data due to a complete API response shape mismatch. The vehicle history crashes. The bookings list crashes against a non-existent SQL column (same pattern as ISSUE-144). The payment flow is a stub. Stripe redirects post-payment to a 404.

Beyond correctness bugs, there are security gaps: no rate limiting on any portal endpoint, the `enable_portal` customer flag is never enforced, and an internal acceptance token is needlessly exposed in the quote list API response.

Feature completeness is also low: there is no mechanism to deliver the portal link to customers, no notifications when quotes are accepted, bookings are created but never confirmed, and mobile-generated portal share URLs are structurally wrong.

---

## Critical — Broken at Runtime

These issues cause crashes, blank data, or completely non-functional flows. All 6 are broken in production today.

---

### CP-001 — PortalPage API response shape mismatch — landing page is broken

**Files**:
- [`frontend/src/pages/portal/PortalPage.tsx`](../frontend/src/pages/portal/PortalPage.tsx) — `PortalInfo` interface (lines 16–33)
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalAccessResponse` (lines 58–68)
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `get_portal_access` (lines 121–151)

**Description**:

The frontend `PortalInfo` TypeScript interface expects a flat response object:

```ts
interface PortalInfo {
  customer_name: string        // does not exist in backend
  email: string
  phone: string
  org_name: string             // nested inside `branding` in backend
  logo_url: string | null      // nested inside `branding` in backend
  primary_color: string        // backend uses primary_colour (British spelling), nested
  outstanding_balance: number  // OK
  total_invoices: number       // backend field is `invoice_count`
  total_paid: number           // not in this endpoint at all
  powered_by?: ...             // nested inside `branding` in backend
  language?: string | null     // nested inside `branding` in backend
}
```

But `GET /api/v1/portal/{token}` returns `PortalAccessResponse`:

```json
{
  "customer": {
    "customer_id": "...",
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "...",
    "phone": "..."
  },
  "branding": {
    "org_name": "...",
    "logo_url": null,
    "primary_colour": "#2563eb",
    "secondary_colour": null,
    "powered_by": {...},
    "language": "en"
  },
  "outstanding_balance": "150.00",
  "invoice_count": 5
}
```

**Impact**:
- Welcome header renders: `Welcome, undefined undefined`
- "Total Invoices" card: `NaN` (reading `info.total_invoices` which is `undefined`)
- "Total Paid" card: `$0.00` (field does not exist in this response)
- Org name in header: `undefined`
- Primary colour branding never applies
- `powered_by` footer never renders (it's nested inside `branding`, not at root)

**Full field mismatch table**:

| Frontend expects | Backend returns | Status |
|---|---|---|
| `customer_name` | `customer.first_name + customer.last_name` | Mismatch — nested + split |
| `email` | `customer.email` | Mismatch — nested |
| `phone` | `customer.phone` | Mismatch — nested |
| `org_name` | `branding.org_name` | Mismatch — nested |
| `logo_url` | `branding.logo_url` | Mismatch — nested |
| `primary_color` | `branding.primary_colour` | Mismatch — nested + spelling |
| `outstanding_balance` | `outstanding_balance` | OK |
| `total_invoices` | `invoice_count` | Mismatch — renamed |
| `total_paid` | *(not present)* | Missing entirely |
| `powered_by` | `branding.powered_by` | Mismatch — nested |
| `language` | `branding.language` | Mismatch — nested |

---

### CP-002 — VehicleHistory crashes — wrong response shape and missing fields

**Files**:
- [`frontend/src/pages/portal/VehicleHistory.tsx`](../frontend/src/pages/portal/VehicleHistory.tsx) — lines 30–40, `PortalVehicle` interface
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalVehicleItem`, `PortalVehiclesResponse` (lines 136–151)

**Description**:

The component fetches and stores the response as if it were an array:

```tsx
// VehicleHistory.tsx line 39
const res = await apiClient.get<PortalVehicle[]>(`/portal/${token}/vehicles`)
setVehicles(res.data)   // res.data is an OBJECT, not an array
```

The backend returns `PortalVehiclesResponse = { branding: {...}, vehicles: [...] }`. Storing the whole object in `vehicles` state means `.map()` is called on an object — the component either crashes or renders nothing.

Additionally, the `PortalVehicle` TypeScript type defines fields that do not exist in `PortalVehicleItem`:

| Frontend `PortalVehicle` field | Backend `PortalVehicleItem` field | Status |
|---|---|---|
| `id: string` | *(not present — no vehicle ID in response)* | Missing |
| `rego: string` | `rego: str` | OK |
| `make: string` | `make: str \| None` | OK |
| `model: string` | `model: str \| None` | OK |
| `year: number \| null` | `year: int \| None` | OK |
| `colour: string \| null` | `colour: str \| None` | OK |
| `wof_expiry: string \| null` | *(not present)* | Missing |
| `rego_expiry: string \| null` | *(not present)* | Missing |
| `services: VehicleService[]` | `service_history: list[PortalServiceRecord]` | Mismatch — renamed |

The `VehicleCard` component shows WOF/Rego expiry badges that will never render (data is not in the API response). The service history array has a different key name.

---

### CP-003 — Portal bookings list crashes — `customer_id` column does not exist in bookings table

**Files**:
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `get_portal_bookings` (lines 553–577)
- [`app/modules/bookings_v2/models.py`](../app/modules/bookings_v2/models.py) — `Booking` model

**Description**:

`get_portal_bookings` executes this raw SQL:

```sql
SELECT id, service_type, start_time, end_time, status, notes, created_at
FROM bookings
WHERE customer_id = :cid AND org_id = :oid
ORDER BY start_time DESC
```

But the `bookings` table has **no `customer_id` column**. The model stores `customer_name: Mapped[str]` as a text field. This was confirmed during the ISSUE-144 investigation (the same missing column that breaks the dashboard widget).

Every request to `GET /portal/{token}/bookings` fires `asyncpg.UndefinedColumnError`, which poisons the PostgreSQL connection-level transaction. Any subsequent portal queries in the same session will fail with `InFailedSQLTransactionError`.

Note: `create_portal_booking` (line 602) correctly creates with `customer_name=f"{customer.first_name} {customer.last_name}"`, so the write path is fine — only the read path is broken.

---

### CP-004 — PaymentPage is a dead stub — never calls the payment API

**Files**:
- [`frontend/src/pages/portal/PaymentPage.tsx`](../frontend/src/pages/portal/PaymentPage.tsx)
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `create_portal_payment` (lines 320–393)
- [`app/modules/portal/router.py`](../app/modules/portal/router.py) — `portal_pay` (lines 127–151)

**Description**:

When a customer clicks "Pay Now" on an invoice in `InvoiceHistory`, they are navigated to `PaymentPage`. This component displays:

```
Online payments coming soon
Online payment processing is not yet available. Please contact us directly to arrange payment.
```

There is no call to `POST /portal/{token}/pay/{invoice_id}` in `PaymentPage.tsx`. The component renders a static warning and a "Back to invoices" button with no payment functionality.

Meanwhile, `create_portal_payment` in the backend is **fully implemented**: it resolves the customer, validates the invoice, calculates application fee, and creates a live Stripe Checkout session, returning `{ payment_url, invoice_id, amount }`.

The "Pay Now" button in `InvoiceHistory` correctly gates on `orgHasStripeConnect && inv.balance_due > 0 && PAYABLE_STATUSES.has(inv.status)`, so the logic to show the button is correct — but the destination page does nothing.

---

### CP-005 — Missing `/portal/:token/payment-success` route — Stripe redirects to 404

**Files**:
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — line 375
- [`frontend/src/App.tsx`](../frontend/src/App.tsx) — portal routing (line 517)

**Description**:

When creating a Stripe Checkout session, the backend sets:

```python
success_url = f"{portal_base}/portal/{token}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
cancel_url  = f"{portal_base}/portal/{token}/invoices"
```

After a successful Stripe payment, the customer is redirected to `/portal/{token}/payment-success`. But `App.tsx` only registers one portal route:

```tsx
<Route path="/portal/:token" element={<SafePage name="portal"><PortalPage /></SafePage>} />
```

There is no `/portal/:token/payment-success` route. The customer's browser lands on a 404 (or React Router fallback) after completing payment. There is also no backend confirmation step — the success URL is purely a frontend redirect with no server-side payment verification.

---

### CP-006 — `line_items_summary` field does not exist in backend schema

**Files**:
- [`frontend/src/pages/portal/InvoiceHistory.tsx`](../frontend/src/pages/portal/InvoiceHistory.tsx) — `PortalInvoice` interface (line 17), render (line 123)
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalInvoiceItem` (lines 88–105)

**Description**:

The `PortalInvoice` TypeScript interface declares `line_items_summary: string` and renders it in every invoice row:

```tsx
<p className="mt-1 text-sm text-gray-500 truncate">
  {inv.line_items_summary}
</p>
```

The backend `PortalInvoiceItem` schema has no `line_items_summary` field. The backend does return `vehicle_rego` (which could serve a similar summary purpose) and a `payments` array, but no pre-computed line item summary string.

Every invoice row shows `undefined` in the description position.

---

## High — Security Gaps

---

### CP-007 — `enable_portal` flag never enforced — any token holder can access portal

**Files**:
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `_resolve_token` (lines 89–113)
- [`app/modules/customers/models.py`](../app/modules/customers/models.py) — `enable_portal` field
- [`frontend/src/components/customers/CustomerEditModal.tsx`](../frontend/src/components/customers/CustomerEditModal.tsx) — line 367

**Description**:

The `Customer` model has `enable_portal: bool` (default `False`). The customer edit modal has a checkbox "Allow portal access for this customer". But `_resolve_token` — the single function called by every portal endpoint — only checks:

```python
.where(Customer.portal_token == token)
.where(Customer.is_anonymised.is_(False))
```

The `enable_portal` field is never queried. If a customer's portal access is disabled via the UI, they can still access the portal using their existing token URL.

Additionally, when a new customer is created with `enable_portal=False` (the default), a `portal_token` may still be assigned, and that token will still work if the customer obtains it.

---

### CP-008 — `acceptance_token` unnecessarily exposed in public GET quotes response

**Files**:
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalQuoteItem.acceptance_token` (line 207)
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `get_portal_quotes` (lines 401–451)

**Description**:

`PortalQuoteItem` serialises `acceptance_token: str | None` in the GET response. This token is an internal credential used to accept quotes via `QuoteService.accept_quote(acceptance_token)`. It is visible in every browser network request, stored in browser memory, and returned in every call to `GET /portal/{token}/quotes`.

The acceptance flow (`accept_portal_quote`) already validates ownership via the portal token + quote_id combination before looking up `acceptance_token`. Returning the raw `acceptance_token` to the customer's browser is unnecessary and increases attack surface. An intercepted GET response gives an attacker the token needed to directly call `QuoteService.accept_quote` bypassing the portal's ownership check.

---

### CP-009 — No rate limiting on any portal endpoint

**Files**:
- [`app/middleware/rate_limit.py`](../app/middleware/rate_limit.py) — `_apply_rate_limits` (lines 204–310)
- [`app/middleware/auth.py`](../app/middleware/auth.py) — `PUBLIC_PREFIXES` (lines 104–111)

**Description**:

The rate limiter applies limits in this priority order:

1. Auth endpoint IP rate limit (only applies to paths in `AUTH_ENDPOINT_PREFIXES`)
2. Per-user rate limit (requires `request.state.user_id`, which is `None` for portal)
3. Per-org rate limit (requires `request.state.org_id`, which is `None` for portal)

Portal paths (`/api/v1/portal/`, `/api/v2/portal/`) are in `PUBLIC_PREFIXES` so they bypass JWT auth — and they also skip the per-user and per-org rate limits since those require JWT claims. Portal paths are not in `AUTH_ENDPOINT_PREFIXES` so the IP rate limit does not apply either.

**Result**: All portal endpoints — including the token-resolution database query on every call — are completely unthrottled. Attack surface:
- Token enumeration: portal tokens are UUIDs (2^122 space) but with no throttle, high-volume guessing is feasible
- DoS via repeated portal access: each request hits the DB for token resolution + multiple aggregate queries
- Scraping customer data by holding a valid token and hammering all sub-endpoints

---

### CP-010 — Token expiry is not validated in the service layer — expired tokens can slip through

**Files**:
- [`app/middleware/auth.py`](../app/middleware/auth.py) — `_check_portal_token_expiry` (lines 293–342)
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `_resolve_token` (lines 89–113)

**Description**:

The auth middleware performs a portal token expiry check in `_check_portal_token_expiry` using its own separate `async_session_factory()` database session. However, `_resolve_token` in the service does **not** re-validate `portal_token_expires_at`.

If the middleware's expiry check raises any exception (network, DB, or otherwise), it is silently swallowed:

```python
except Exception:
    logger.warning("Failed to check portal token expiry for %s", token_str, exc_info=True)
return None  # ← allows request through
```

An expired token will then reach `_resolve_token` in the service, which queries only by `portal_token` and `is_anonymised` — no expiry check. The token is accepted as valid.

Defence in depth requires expiry validation at the service boundary.

---

### CP-011 — No Stripe Connect webhook — portal payments never update invoice status

**Files**:
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `create_portal_payment` (lines 378–393)
- [`app/integrations/stripe_connect.py`](../app/integrations/stripe_connect.py) — `create_payment_link` (lines 129–220)
- [`app/modules/payments/router.py`](../app/modules/payments/router.py) — `stripe_webhook_endpoint` (lines 1144–1214)

**Description**:

`create_payment_link` creates a Stripe Checkout Session **on the connected organisation's Stripe account** (the `Stripe-Account` header is set to `org.stripe_connect_account_id`). When the customer completes payment, Stripe fires `checkout.session.completed` on the **connected account**, not the platform account.

The platform webhook at `/api/v2/payments/stripe/webhook` uses the platform webhook signing secret (`get_stripe_webhook_secret()`). This webhook receives events for the **platform account only** — it never receives events from connected accounts unless a separate Connect webhook is configured in the Stripe Dashboard with its own endpoint secret.

There is no separate Stripe Connect webhook endpoint or listener in the codebase.

**Result**: When a customer pays via the portal:
1. Stripe processes the payment ✓
2. Customer is redirected to the (missing) success page ✗
3. `checkout.session.completed` fires on the connected account
4. No webhook endpoint receives it
5. `handle_stripe_webhook` is never called for this payment
6. The `Invoice` status stays as `issued`/`overdue`, never becomes `paid`
7. `amount_paid` and `balance_due` are never updated
8. The customer sees their invoice as still outstanding on next portal visit

---

## Medium — Feature Gaps and Missing Flows

---

### CP-012 — No portal link delivery mechanism — businesses cannot share the portal with customers

**Files**:
- [`app/modules/customers/router.py`](../app/modules/customers/router.py)
- [`app/modules/admin/router.py`](../app/modules/admin/router.py) — `regenerate_portal_token` (lines 4069–4140)
- [`frontend/src/components/customers/CustomerViewModal.tsx`](../frontend/src/components/customers/CustomerViewModal.tsx) — line 93

**Description**:

The only operations related to portal token management are:

1. `enable_portal` toggle in the customer edit modal (no token shown)
2. `POST /api/v1/admin/customers/{id}/regenerate-portal-token` — requires `global_admin` role; inaccessible to org staff

There is **no** endpoint to:
- Send the portal link via email to the customer
- Send the portal link via SMS
- Return the portal token/URL to org staff for copying
- Display the portal URL in any admin or org UI

`CustomerViewModal.tsx` line 93 only shows `Portal Access: Enabled / Disabled` — not the actual link URL. An org staff member who enables portal access for a customer has no way to give the customer the link, rendering the feature undeliverable.

---

### CP-013 — Quote acceptance sends no notification to the business

**Files**:
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `accept_portal_quote` (lines 454–487)
- [`app/modules/quotes_v2/service.py`](../app/modules/quotes_v2/service.py) — `accept_quote` (lines 170–190)

**Description**:

When a customer accepts a quote via `POST /portal/{token}/quotes/{quote_id}/accept`:

1. `accept_portal_quote` verifies ownership and calls `QuoteService.accept_quote(acceptance_token)`
2. `accept_quote` sets `quote.status = "accepted"` and `quote.accepted_at = datetime.now(timezone.utc)`
3. The function returns the updated quote

There is no:
- Email notification to the business owner
- In-app notification
- Webhook or event dispatch
- Celery task trigger

The business has no real-time signal that a customer accepted a quote. They must poll the quotes list to discover it.

---

### CP-014 — Portal bookings created as "pending" and never confirmed

**Files**:
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — `create_portal_booking` (lines 580–618)
- [`app/modules/bookings_v2/service.py`](../app/modules/bookings_v2/service.py) — `send_confirmation` (lines 195–204)

**Description**:

`create_portal_booking` calls `BookingService.create_booking()`, which creates a booking with `status="pending"` (the model default). `BookingService.send_confirmation()` exists and would change the status to `"confirmed"`, but it is never called from the portal service.

```python
# portal/service.py — create_portal_booking
booking = await svc.create_booking(org.id, booking_data, customer_id=customer.id)
# ← send_confirmation is never called here
return PortalBookingCreateResponse(
    booking_id=booking.id,
    status=booking.status,  # always "pending"
    ...
)
```

The customer receives a response with `status: "pending"`. The booking stays pending indefinitely. No confirmation email is sent, no staff notification is triggered, and the business cannot distinguish portal bookings from any other pending bookings.

---

### CP-015 — No booking cancellation endpoint in the portal

**Files**:
- [`app/modules/portal/router.py`](../app/modules/portal/router.py)
- [`frontend/src/pages/portal/BookingManager.tsx`](../frontend/src/pages/portal/BookingManager.tsx)

**Description**:

The portal router has no `DELETE` or `PATCH` endpoint for bookings. `BookingManager.tsx` shows existing bookings with a status badge but provides no cancel button. Customers who make a booking through the portal cannot cancel it through the portal — they must contact the business directly.

Existing endpoints:
- `GET  /portal/{token}/bookings` — list bookings (broken by CP-003)
- `POST /portal/{token}/bookings` — create booking
- `GET  /portal/{token}/bookings/slots` — get available slots

Missing:
- `DELETE /portal/{token}/bookings/{booking_id}` or `PATCH .../cancel`

---

### CP-016 — `total_paid` missing from portal landing page — always renders $0.00

**Files**:
- [`frontend/src/pages/portal/PortalPage.tsx`](../frontend/src/pages/portal/PortalPage.tsx) — line 97
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalAccessResponse` (lines 58–68)

**Description**:

`PortalPage` renders three summary cards on the landing page. The "Total Paid" card:

```tsx
<SummaryCard label="Total Paid" value={formatNZD(info.total_paid)} variant="success" />
```

`total_paid` is not in `PortalAccessResponse`. It only appears in `PortalInvoicesResponse` (the `/invoices` sub-request). The landing page makes only one API call (`GET /portal/{token}`) and does not call `/invoices` on load.

The "Total Paid" summary card always shows `$0.00` regardless of the customer's actual payment history. (Note: this is also masked by CP-001, since `info` itself is malformed.)

---

### CP-017 — Mobile "Share Portal Link" generates structurally wrong URLs

**Files**:
- [`mobile/src/screens/invoices/InvoiceDetailScreen.tsx`](../mobile/src/screens/invoices/InvoiceDetailScreen.tsx) — lines 391–406
- [`mobile/src/screens/quotes/QuoteDetailScreen.tsx`](../mobile/src/screens/quotes/QuoteDetailScreen.tsx) — lines 294–309

**Description**:

The mobile app provides a "Share Portal Link" button on both the invoice and quote detail screens. The generated URLs are:

```ts
// InvoiceDetailScreen.tsx line 392
const portalUrl = `${window.location.origin}/portal/invoices/${id}`

// QuoteDetailScreen.tsx line 295
const portalUrl = `${window.location.origin}/portal/quotes/${id}`
```

These URLs use the **document ID** (invoice or quote UUID) as the path segment after `/portal/`. The correct portal URL format is `/portal/{customer_portal_token}`.

The generated URLs:
- Do not exist (no matching route in `App.tsx`)
- Will always 404 for the customer
- Cannot identify a customer (document IDs are not customer tokens)
- Expose internal document IDs in shared links

The mobile app does not have access to the customer's portal token (it is not returned by invoice or quote API endpoints), so the correct URL cannot be constructed without an API change to return the portal token alongside invoice/quote details.

---

## Low — Code Quality and UX Gaps

---

### CP-018 — `PortalLayout.tsx` is dead code — never used in routing

**Files**:
- [`frontend/src/layouts/PortalLayout.tsx`](../frontend/src/layouts/PortalLayout.tsx)
- [`frontend/src/App.tsx`](../frontend/src/App.tsx) — line 517

**Description**:

`PortalLayout.tsx` is a complete layout component with:
- An org-branded header (logo or initial avatar, org name)
- `style={{ borderBottomColor: primaryColor }}`
- A main content area with `<Outlet />`
- A footer that hardcodes: `"Powered by WorkshopPro NZ"` (ignoring the configurable `PoweredByFooter` component)

It accepts `{ orgName, logoUrl, primaryColor }` props but is imported nowhere. `App.tsx` wraps the portal route in `SafePage` directly, not in `PortalLayout`. `PortalPage.tsx` renders its own inline header without using this component.

The hardcoded "WorkshopPro NZ" footer in the unused layout is also a white-label leak — it would expose the platform name even for white-labelled organisations.

---

### CP-019 — No pagination on any portal endpoint

**Files**:
- [`app/modules/portal/router.py`](../app/modules/portal/router.py) — all GET endpoints
- [`app/modules/portal/service.py`](../app/modules/portal/service.py) — all list functions

**Description**:

All portal list endpoints return every record for the customer with no pagination:

| Endpoint | Returns |
|---|---|
| `GET /portal/{token}/invoices` | All non-draft/voided invoices |
| `GET /portal/{token}/quotes` | All non-draft quotes |
| `GET /portal/{token}/vehicles` | All vehicles with full service history per vehicle |
| `GET /portal/{token}/assets` | All assets with full service history per asset |
| `GET /portal/{token}/bookings` | All bookings (descending) |
| `GET /portal/{token}/loyalty` | All loyalty transactions |

For an automotive workshop customer with 10+ years of history: potentially hundreds of invoices, each with a `payments` array loaded via `selectinload`, multiple vehicles with deep service histories. No `limit`, `offset`, or cursor parameter exists on any endpoint.

---

### CP-020 — `language` field received from API but never applied

**Files**:
- [`frontend/src/pages/portal/PortalPage.tsx`](../frontend/src/pages/portal/PortalPage.tsx) — line 32
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalBranding.language` (line 40)
- [`app/core/i18n.py`](../app/core/i18n.py) — portal translation keys (lines 192–196)

**Description**:

The backend returns `branding.language` (the org's locale code, e.g. `"mi"` for Māori). The `PortalInfo` TypeScript type includes `language?: string | null`. The i18n system has translation keys prefixed with `portal.*` for all portal UI strings.

However, `language` is never used in any frontend component:
- No `lang` attribute is set on `<html>` or any element
- No translation function is called
- All date formatters hardcode `'en-NZ'` locale
- All currency formatters hardcode `'en-NZ'` locale

The portal is displayed in English regardless of the organisation's configured locale.

---

### CP-021 — Booking form sends no `service_type` or `notes`

**Files**:
- [`frontend/src/pages/portal/BookingManager.tsx`](../frontend/src/pages/portal/BookingManager.tsx) — `handleBookSlot` (lines 77–93)
- [`app/modules/portal/schemas.py`](../app/modules/portal/schemas.py) — `PortalBookingCreateRequest` (lines 293–298)

**Description**:

When the customer clicks a time slot to book an appointment, `handleBookSlot` sends:

```ts
await apiClient.post(`/portal/${token}/bookings`, {
  start_time: slot.start_time,
  // service_type and notes are never included
})
```

`PortalBookingCreateRequest` supports `service_type: str | None` and `notes: str | None`, but the booking UI provides no input fields for these. Every booking arrives with both fields as `null`, making all bookings indistinguishable from one another — the business cannot see what the customer wants done.

---

### CP-022 — Invoice PDF not accessible from the portal

**Files**:
- [`app/core/i18n.py`](../app/core/i18n.py) — translation keys `portal.download_pdf`, `portal.view_invoice` (lines 193–196)
- [`frontend/src/pages/portal/InvoiceHistory.tsx`](../frontend/src/pages/portal/InvoiceHistory.tsx)

**Description**:

The i18n translation file defines these keys for every locale:
- `portal.download_pdf`
- `portal.view_invoice`

This implies PDF access was designed as a portal feature. However:
- `InvoiceHistory` has no download or preview button
- All existing PDF generation endpoints (`/api/v1/invoices/{id}/pdf`, etc.) require JWT authentication
- There is no public PDF endpoint accessible via portal token
- No PDF link is present in `PortalInvoiceItem` schema

Customers cannot download or view their invoice PDFs from the portal.

---

### CP-023 — Refunded invoice statuses not handled in frontend STATUS_CONFIG

**Files**:
- [`frontend/src/pages/portal/InvoiceHistory.tsx`](../frontend/src/pages/portal/InvoiceHistory.tsx) — `STATUS_CONFIG` (lines 35–41)
- [`app/modules/invoices/models.py`](../app/modules/invoices/models.py) — invoice status constraint (line 238)

**Description**:

The invoice `status` column allows: `draft`, `issued`, `partially_paid`, `paid`, `overdue`, `voided`, `refunded`, `partially_refunded`.

The portal service filters out only `draft` and `voided`, so `refunded` and `partially_refunded` invoices are returned to the portal. But `STATUS_CONFIG` in `InvoiceHistory.tsx` only defines:

```ts
const STATUS_CONFIG = {
  paid: ...,
  partially_paid: ...,
  issued: ...,
  overdue: ...,
  voided: ...,   // filtered out server-side anyway
}
```

`refunded` and `partially_refunded` fall through to:

```ts
const cfg = STATUS_CONFIG[inv.status] ?? { label: inv.status, variant: 'neutral' as const }
```

These statuses show as raw lowercase strings (`"refunded"`, `"partially_refunded"`) with a neutral badge — no user-friendly label, no colour coding, no explanation to the customer.

---

## Summary Table

| ID | Issue | Severity | Area | Backend | Frontend | Mobile |
|---|---|---|---|---|---|---|
| CP-001 | PortalPage API response shape mismatch | Critical | Data | ✓ | ✓ | |
| CP-002 | VehicleHistory crashes — wrong response type + missing fields | Critical | Data | ✓ | ✓ | |
| CP-003 | Bookings SQL references non-existent `customer_id` column | Critical | SQL | ✓ | | |
| CP-004 | PaymentPage is a dead stub — never calls payment API | Critical | Payment | | ✓ | |
| CP-005 | Missing `/portal/:token/payment-success` route | Critical | Routing | ✓ | ✓ | |
| CP-006 | `line_items_summary` field missing from backend schema | Critical | Data | ✓ | ✓ | |
| CP-007 | `enable_portal` flag never enforced in service | High | Security | ✓ | | |
| CP-008 | `acceptance_token` exposed in GET quotes response | High | Security | ✓ | | |
| CP-009 | No rate limiting on any portal endpoint | High | Security | ✓ | | |
| CP-010 | Token expiry not re-validated in service layer | High | Security | ✓ | | |
| CP-011 | No Stripe Connect webhook — paid invoices never update | High | Payment | ✓ | | |
| CP-012 | No portal link delivery mechanism | Medium | Feature | ✓ | ✓ | |
| CP-013 | Quote acceptance sends no notification | Medium | Feature | ✓ | | |
| CP-014 | Portal bookings stay pending forever | Medium | Feature | ✓ | | |
| CP-015 | No booking cancellation endpoint | Medium | Feature | ✓ | ✓ | |
| CP-016 | `total_paid` missing from portal landing page | Medium | Data | ✓ | ✓ | |
| CP-017 | Mobile "Share Portal Link" generates wrong URLs | Medium | Mobile | | | ✓ |
| CP-018 | `PortalLayout.tsx` is dead code | Low | Code quality | | ✓ | |
| CP-019 | No pagination on any portal endpoint | Low | Performance | ✓ | | |
| CP-020 | `language` field received but never applied | Low | i18n | | ✓ | |
| CP-021 | Booking form sends no `service_type` or `notes` | Low | UX | | ✓ | |
| CP-022 | Invoice PDF not accessible from portal | Low | Feature | ✓ | ✓ | |
| CP-023 | Refunded invoice statuses unhandled in frontend | Low | UX | | ✓ | |

---

## Recommended Fix Order

### Phase 1 — Make the portal functional (fix Criticals first)

1. **CP-001** — Align `PortalAccessResponse` with frontend `PortalInfo` shape (or update frontend to use nested structure). Add `total_paid` to the response.
2. **CP-006** — Add `line_items_summary` to `PortalInvoiceItem` (compute from `line_items` in service).
3. **CP-002** — Fix `VehicleHistory` to unpack `res.data.vehicles`, add `wof_expiry`/`rego_expiry` to backend schema if available, reconcile `services` vs `service_history` naming.
4. **CP-003** — Fix `get_portal_bookings` SQL to filter by `customer_name` (join approach or add `customer_id` FK to bookings table — the latter is the correct long-term fix).
5. **CP-004** — Implement `PaymentPage` to call `POST /portal/{token}/pay/{invoice_id}` and redirect to the returned `payment_url`.
6. **CP-005** — Add `/portal/:token/payment-success` route and component to show a "Payment received" confirmation.

### Phase 2 — Fix security gaps

7. **CP-009** — Add per-token rate limiting in the rate limiter (key: `rl:portal:{token_hash}`, e.g. 60 req/min).
8. **CP-007** — Add `enable_portal` check to `_resolve_token`.
9. **CP-010** — Add `portal_token_expires_at` check inside `_resolve_token`.
10. **CP-008** — Remove `acceptance_token` from `PortalQuoteItem` response.
11. **CP-011** — Register a Stripe Connect webhook endpoint and listener for `checkout.session.completed` events from connected accounts.

### Phase 3 — Restore missing features

12. **CP-012** — Add "Copy portal link" to `CustomerViewModal`; add `GET /customers/{id}/portal-link` endpoint for org staff; optionally add "Send portal link via email" action.
13. **CP-013** — Trigger notification (email or in-app) to org when quote is accepted.
14. **CP-014** — Call `send_confirmation()` after `create_booking()` in portal service; implement actual email dispatch.
15. **CP-015** — Add `PATCH /portal/{token}/bookings/{id}/cancel` endpoint and cancel button in `BookingManager`.
16. **CP-017** — Fix mobile "Share Portal Link" to use the customer's portal token (requires API to return portal token with invoice/quote details, or fetch it separately).
17. **CP-016** — Confirmed resolved by CP-001 fix if `total_paid` is added to `PortalAccessResponse`.

### Phase 4 — Polish and performance

18. **CP-021** — Add `service_type` dropdown and `notes` textarea to the new booking form.
19. **CP-022** — Add a public PDF endpoint gated by portal token; add download button to `InvoiceHistory`.
20. **CP-023** — Add `refunded` and `partially_refunded` entries to `STATUS_CONFIG` in `InvoiceHistory.tsx`.
21. **CP-020** — Apply `language` field from API response to page `lang` attribute and pass locale to date/currency formatters.
22. **CP-019** — Add `limit`/`offset` pagination to all portal list endpoints.
23. **CP-018** — Remove or wire up `PortalLayout.tsx` (remove the hardcoded "WorkshopPro NZ" text if kept).

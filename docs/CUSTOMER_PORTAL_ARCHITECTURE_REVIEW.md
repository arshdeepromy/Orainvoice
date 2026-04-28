# Customer Portal — Architecture & Feature Coverage Review

**Date**: 2026-04-28  
**Type**: Read-only investigation — no code changed  
**Scope**: Data model, multi-org identity, full feature coverage vs backend capabilities, requirements gap, security model  
**Related**: See also [`CUSTOMER_PORTAL_AUDIT.md`](./CUSTOMER_PORTAL_AUDIT.md) for the runtime bug and implementation audit (23 issues)

---

## Table of Contents

1. [The Multi-Org Identity Problem](#1-the-multi-org-identity-problem)
2. [How It Works Today — The Full Picture](#2-how-it-works-today--the-full-picture)
3. [What the Ideal Portal Looks Like](#3-what-the-ideal-portal-looks-like)
4. [Design Options for Multi-Org Support](#4-design-options-for-multi-org-support)
5. [Feature Coverage Gaps — Backend Has It, Portal Doesn't](#5-feature-coverage-gaps--backend-has-it-portal-doesnt)
6. [Requirements That Are Explicitly Stated but Not Implemented](#6-requirements-that-are-explicitly-stated-but-not-implemented)
7. [Security Model Gaps](#7-security-model-gaps)
8. [Operational Gaps for Org Admins](#8-operational-gaps-for-org-admins)
9. [Portal Token Lifecycle Gaps](#9-portal-token-lifecycle-gaps)
10. [Summary and Recommended Roadmap](#10-summary-and-recommended-roadmap)

---

## 1. The Multi-Org Identity Problem

This is the most fundamental architectural gap in the customer portal.

### What the data model actually does

The `customers` table is **100% org-scoped**. Every customer row has a mandatory `org_id` foreign key to `organisations`. The `portal_token` column is globally unique but it only ever resolves to **one customer row in one org**.

```
customers table:
┌─────────────────┬──────────────┬────────────┬─────────────────────────────┐
│ id              │ org_id       │ email      │ portal_token                │
├─────────────────┼──────────────┼────────────┼─────────────────────────────┤
│ uuid-cust-A     │ uuid-org-A   │ jane@x.com │ uuid-token-A (or NULL)      │
│ uuid-cust-B     │ uuid-org-B   │ jane@x.com │ uuid-token-B (or NULL)      │
└─────────────────┴──────────────┴────────────┴─────────────────────────────┘
```

"Jane Smith" who uses **Workshop A** and **Workshop B** (both running OraInvoice) has **two completely separate customer rows**. There is:

- No global customer identity table
- No cross-org linking by email or phone
- No concept of a unified customer who spans orgs
- No platform-level customer account

Searched the entire codebase: there is no `global_customers`, `customer_identities`, `cross_org_customer_links`, or any equivalent table.

### What a customer actually experiences today

1. Jane gets a job done at Workshop A. Staff enables portal for her and (if a global admin happens to run the token endpoint) she gets a link like `/portal/uuid-token-A`.
2. She visits Workshop B. They also create a customer record for her. She gets a completely separate link `/portal/uuid-token-B` (if that org ever generates one).
3. Each link shows only that one org's data in isolation.
4. Jane has to manage N separate bookmark links for N different workshops.
5. There is no way for Jane to know she has a relationship with Workshop B from within Workshop A's portal, or vice versa.
6. If she loses the link, she has to contact the business — there is no self-service token recovery (no "enter your email to get your portal link" flow).

### Why this matters

This is the core architectural question the user raised: **"ideally customer portal should allow customers to see all organisations where they have spent money and they have allowed the customer access to the portal."**

That requires a cross-org customer identity layer that does not currently exist.

---

## 2. How It Works Today — The Full Picture

### Portal token lifecycle (current state)

```
Customer created
      │
      ▼
portal_token = NULL  ← column is nullable=True, NO server_default in migration
enable_portal = false

      │  Org staff enables portal in customer edit modal
      ▼
enable_portal = true  (but portal_token still NULL — cannot access portal yet!)

      │  Global Admin (only) calls POST /admin/customers/{id}/regenerate-portal-token
      ▼
portal_token = new UUID  ←── expires in 90 days (platform-wide, not per-org)
portal_token_expires_at = now() + 90 days

      │  Token URL: /portal/{portal_token}
      ▼
Customer visits portal → sees only THIS org's data
```

**Three critical gaps in this flow:**
1. `portal_token` starts as NULL — the customer cannot access the portal even if `enable_portal=true` until a Global Admin manually generates it. Org staff cannot do this.
2. Token delivery is entirely manual — there is no email or SMS that sends the link to the customer.
3. Token TTL is 90 days, platform-wide. The spec (Req 49.1) requires it to be **configurable by the Org_Admin**. It is not.

### What `_resolve_token` does

Every portal endpoint calls `_resolve_token`:

```python
# app/modules/portal/service.py
stmt = (
    select(Customer)
    .where(Customer.portal_token == token)   # globally unique lookup
    .where(Customer.is_anonymised.is_(False))
    # ← NO enable_portal check
    # ← NO portal_token_expires_at check (that's in middleware, which can fail silently)
)
```

The result is a single `(customer, org)` pair. Everything the portal shows is then scoped to `customer.id` and `customer.org_id`. There is no mechanism to return data across multiple orgs.

---

## 3. What the Ideal Portal Looks Like

### The scenario the user described

A customer who has had work done at three workshops — all on OraInvoice — and each has enabled portal access for them should be able to:

1. Visit a single portal entry point (or receive a single unified link)
2. See a list of organisations they have a relationship with
3. Select an org context and see all their data for that org (invoices, quotes, vehicles, bookings, loyalty)
4. Switch between orgs without needing different links

### The current reality vs the ideal

| Aspect | Current | Ideal |
|---|---|---|
| Customer identity | Per-org row, no global identity | Global identity (email/phone) linked to N org relationships |
| Portal entry | N separate token URLs (one per org) | One entry point (email-based OTP or unified token) |
| Org visibility | Only the single org whose token was opened | List of all orgs with portal enabled for this customer |
| Data scope | One org at a time (hard-coded) | Switchable org context, or unified cross-org view |
| Token recovery | Contact the business | Self-service: enter email → get OTP → access all orgs |
| Token generation | Global Admin only, manual | Auto-generated on `enable_portal=true`, or on demand by org staff |

---

## 4. Design Options for Multi-Org Support

Listed from least to most architectural change required.

---

### Option A — Linked Portal Tokens (Minimal Change)

**Approach**: Keep the existing per-org token model but add a **cross-org directory page**. When a customer visits their Workshop A portal token, the portal makes a lookup by email across all orgs that have portal-enabled customers with that email, and shows a switcher.

**What changes:**
- New backend query: `SELECT org_id FROM customers WHERE email = :email AND enable_portal = true AND portal_token IS NOT NULL`
- Portal landing page adds an "Other organisations" section listing other orgs
- Clicking another org redirects to that org's portal URL (requires the customer to have received that link too)

**Pros**: Minimal schema change. Works within existing token model.  
**Cons**: Customer still needs all N links. The discovery only helps if they already have at least one valid link. Email is not verified — a customer could potentially discover other orgs' customer records for someone with the same email.

---

### Option B — Email-Based OTP Portal Login (Recommended)

**Approach**: Replace the opaque UUID token model with an email-based OTP flow. The customer enters their email address at a portal entry page, receives a time-limited OTP code, and then sees a unified view of **all orgs where they are a portal-enabled customer**.

**What changes:**

**New table: `portal_sessions`**
```sql
CREATE TABLE portal_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    otp_code    TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT now() + interval '10 minutes',
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**New table: `portal_org_access`** (the "relationship" table)
```sql
-- Links email addresses (customer identities) to orgs that have enabled portal for them
-- Populated when org staff enables portal for a customer
CREATE TABLE portal_org_access (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL,
    org_id          UUID NOT NULL REFERENCES organisations(id),
    customer_id     UUID NOT NULL REFERENCES customers(id),
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(email, org_id)
);
```

**Portal flow:**
```
/portal                         ← new landing page: "Enter your email"
    │
    ▼ POST /portal/request-otp  ← sends 6-digit OTP to email
    │
/portal/verify                  ← customer enters OTP
    │
    ▼ POST /portal/verify-otp   ← validates OTP, issues portal_session cookie (HttpOnly)
    │
/portal/dashboard               ← shows list of all orgs the customer has access to
    │
    ▼ customer selects Workshop A
    │
/portal/org/{org_id}/invoices   ← scoped to org, session proves identity
```

**Pros**: Proper identity model. Customer manages one credential (email). Self-service access recovery. Cross-org unified view is naturally possible.  
**Cons**: Requires email delivery working reliably. Breaking change to existing portal URL structure. Requires session management. More backend work.

**Backwards compatibility**: Keep existing `/portal/{uuid-token}` links working as a "deep link" that verifies via OTP if the session is not already established, or as a direct-access legacy path that still works but redirects to the dashboard showing all orgs.

---

### Option C — Unified Token Per Email (Middle Ground)

**Approach**: Generate one portal token per email address (not per customer-per-org). Store it in a new `portal_identities` table. When resolved, the token returns all orgs where that email is a portal-enabled customer.

**New table:**
```sql
CREATE TABLE portal_identities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    portal_token    UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT now() + interval '90 days',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`_resolve_token` returns a list of `(customer, org)` pairs instead of one. The portal shows an org picker on first load.

**Pros**: One link for the customer regardless of how many orgs. Simple to implement relative to Option B. No OTP flow needed.  
**Cons**: Token-in-URL security concerns remain. No self-service recovery. Token expiry still awkward (if one org generates the token, the TTL starts — other orgs joining later don't reset it).

---

### Recommendation

**Short term**: Implement Option A (cross-org email discovery within the existing token model) as an immediate improvement. This requires no schema migration and gives some multi-org visibility.

**Medium term**: Implement Option B (email OTP). This is the correct long-term architecture and aligns with how modern customer portals work (think: Xero's "My invoices", Trade Me's customer account). The portal entry point at `/portal` with email login is the industry-standard pattern.

---

## 5. Feature Coverage Gaps — Backend Has It, Portal Doesn't

The backend has fully-modelled data for these features. None of them are accessible from the portal.

---

### 5.1 Job Card / Job Status

**Module**: `app/modules/jobs_v2/`  
**Customer relevance**: HIGH — a customer drops their car off and wants to know: has work started, is it done, what was done?  
**What exists**: `Job` model with `customer_id`, `status` (pending/in_progress/completed/invoiced), `notes`, vehicle linking, status history audit trail  
**Portal gap**: No job status endpoint. No job history view. Customer calls the workshop instead.

**What a portal job view would show:**
- Active jobs: status, assigned staff, estimated completion
- Completed jobs: what was done, linked invoice, vehicle
- Status change history timeline

---

### 5.2 Claims and Returns

**Module**: `app/modules/claims/`  
**Customer relevance**: HIGH — if a customer has a warranty claim or return in progress, they want to track it  
**What exists**: `CustomerClaim` model with `customer_id`, `claim_type`, `status` (submitted/under_review/approved/rejected/resolved), `resolution_type`, `resolution_amount`, `resolution_notes`; `ClaimAction` for timeline events  
**Portal gap**: No claims endpoint in portal. Customer must phone the business to ask about their claim status.

**What a portal claims view would show:**
- Open claims with current status and last action
- Claim timeline (submitted → under review → approved)
- Resolution details once resolved

---

### 5.3 Projects

**Module**: `app/modules/projects/`  
**Customer relevance**: MEDIUM — relevant for trade/construction businesses doing multi-stage work  
**What exists**: `Project` model with `customer_id`, `status`, `description`, linked invoices and jobs  
**Portal gap**: No project endpoint. Customers with ongoing projects have no visibility.

---

### 5.4 Compliance Documents Linked to Invoices

**Module**: `app/modules/compliance_docs/`  
**Customer relevance**: MEDIUM — a customer may want to download safety certificates, inspection reports, compliance paperwork attached to their job  
**What exists**: `ComplianceDocument` model; documents can be linked to invoices  
**Portal gap**: **Explicitly required by Requirement 49.2**: "compliance documents linked to their invoices" — but completely absent from the portal implementation  
**Status**: This is a stated requirement, not just a nice-to-have.

---

### 5.5 Recurring Invoice Schedules

**Module**: `app/modules/recurring_invoices/`  
**Customer relevance**: MEDIUM — fleet customers on recurring contracts want to see their billing schedule  
**What exists**: `RecurringSchedule` with `customer_id`, `frequency`, `status`, `next_run_date`, `amount`  
**Portal gap**: No recurring schedule view. A fleet customer sees historical invoices but cannot see upcoming scheduled charges.

---

### 5.6 Invoice PDF Download

**Customer relevance**: HIGH — customers routinely need to download invoices for expense claims, insurance, records  
**What exists**: PDF generation endpoints at `/api/v1/invoices/{id}/pdf` — but they require JWT authentication  
**Portal gap**: No public PDF endpoint gated by portal token. The i18n system has `portal.download_pdf` as a translation key (indicating it was designed to exist). The invoice list shows no download button.

---

### 5.7 Progress Claims (Construction / Trade)

**Module**: `app/modules/progress_claims/`  
**Customer relevance**: MEDIUM for construction clients — progress claim approval is a formal customer-facing step  
**What exists**: `ProgressClaim` with `status` (draft/submitted/approved/rejected), `approved_at`, linked to `Project`  
**Portal gap**: Customers cannot review or approve progress claims online. Approval requires phone or email.

---

### 5.8 Partial Payment Control

**Customer relevance**: HIGH — a customer may want to pay a deposit or part-payment on a large invoice  
**What exists**: The backend `create_portal_payment` accepts an `amount` parameter for partial payments  
**Portal gap**: The `PaymentPage` component is a stub (bug CP-004) and even if it were implemented, the UI has no input for a custom amount — it would always pay the full balance. Partial payment is supported in the API but inaccessible from the UI.

---

### 5.9 Contact Details Self-Service Update

**Customer relevance**: MEDIUM — customers move, change phone numbers, want to update their email  
**What exists**: Customer update endpoint, but it requires JWT (org staff only)  
**Portal gap**: No self-service profile update in the portal. Customer must phone the business to update a phone number.

---

### 5.10 SMS Conversation History

**Module**: `app/modules/sms_chat/`  
**Customer relevance**: LOW-MEDIUM — some customers may want to review what was agreed in SMS  
**What exists**: `SmsMessage` with `direction` (inbound/outbound), linked to customer by phone  
**Portal gap**: No message history view in portal.

---

## 6. Requirements That Are Explicitly Stated but Not Implemented

These are verbatim from `Requirement 49` in the platform requirements spec.

| Req | Text | Status |
|---|---|---|
| 49.1 | Token expiry **configurable by the Org_Admin** (default 90 days) | ❌ TTL is platform-wide in `app/config.py`. No per-org setting. No Org_Admin UI to change it. |
| 49.2 | Display **compliance documents linked to invoices** | ❌ Completely absent from portal router, service, and frontend. |
| 49.2 | Display **all assets/vehicles with service history** | ⚠️ Partially implemented but broken (CP-002: VehicleHistory crashes). |
| 49.3 | Support **partial payments** if organisation allows them | ⚠️ Backend supports it; UI has no partial amount input and PaymentPage is a stub (CP-004). |
| 49.5 | Apply **organisation branding** (logo, colours) | ⚠️ Branding is returned from the API but not applied to the page — API response shape mismatch (CP-001) means colours never apply. |
| 49.6 | Support **the organisation's configured language**, displaying portal content in the appropriate language | ❌ Language field received but never applied. Portal is always English (CP-020). |

From `Requirement 4` (GDPR/Privacy):

| Req | Text | Status |
|---|---|---|
| 4.4 | **Cookie consent management on customer-facing pages** including customer portal | ❌ No cookie consent banner on the portal. |
| 4.4 | **DSAR (Data Subject Access Request) workflow** — customer can request data export or deletion | ❌ No self-service DSAR on portal. Org_Admin can anonymise but there is no customer-initiated flow. |

From `Requirement 38.6` / `35.6`:

| Req | Text | Status |
|---|---|---|
| 38.6 | Loyalty balance view on portal: **current points, tier, points to next tier, transaction history** | ⚠️ Partially implemented — loyalty endpoint exists and loyalty tab renders, but it only shows if org has loyalty configured; if not, returns `total_points: 0` with no explanation to customer. |

---

## 7. Security Model Gaps

Beyond what was documented in `CUSTOMER_PORTAL_AUDIT.md` (CP-007 through CP-011), the broader security model has these additional gaps.

---

### 7.1 Portal Token Exposed in Browser History and Logs

Portal token URLs take the form `/portal/550e8400-e29b-41d4-a716-446655440000`. The UUID is:
- Stored in browser history
- Stored in server access logs
- Visible in Referrer headers if the customer clicks an external link from the portal
- Shareable by accident (copy URL)

If the token is leaked, anyone with it gets full access to that customer's data. There is no way for the customer to revoke the token themselves — they must contact the business or a Global Admin to regenerate it.

**Better pattern**: Token in cookie (HttpOnly, Secure) with a short-lived session, not in the URL. Or: the UUID as a path param is acceptable only with OTP verification on first use.

---

### 7.2 No CSRF Protection on Portal POST Endpoints

Portal POST endpoints (`/portal/{token}/quotes/{id}/accept`, `/portal/{token}/bookings`, `/portal/{token}/pay/{id}`) have no CSRF protection. Since the token is in the URL (not a cookie), the standard cookie-based CSRF attack doesn't apply — but a malicious page can still craft a cross-origin POST to these endpoints if the token is known (e.g., from a phishing page that tricks the customer into clicking a link that they already have open).

---

### 7.3 No Portal Session Concept — No Logout

There is no concept of a portal session. Each request re-authenticates by token. This means:
- There is no logout mechanism
- A shared device (e.g., a workshop waiting room tablet) that a customer uses cannot be "signed out" of the portal — the URL in history gives permanent access until the token expires
- There is no activity timeout

---

### 7.4 No Audit Log for Portal Actions

Customer actions on the portal (accepting a quote, creating a booking, initiating a payment) are not logged in the `audit_log` table. If a quote is accepted via the portal and disputed later, there is no trail showing when and from what IP it was accepted.

---

### 7.5 Token is a UUID — Weaker Than Necessary

Portal tokens are UUID v4 (122 bits of randomness). This is technically sufficient against brute-force in practice, but:
- UUIDs are designed as identifiers, not secrets
- A URL-safe random string (e.g., `secrets.token_urlsafe(32)` — 256 bits) would be better practice
- UUID format leaks metadata (variant, version)

The admin `regenerate_portal_token` endpoint correctly uses `uuid.uuid4()` — changing to `secrets.token_urlsafe(32)` would be stronger.

---

## 8. Operational Gaps for Org Admins

These are features the org staff need to manage the portal effectively, none of which exist.

| Gap | Description |
|---|---|
| No global portal enable/disable | There is no org-level setting to disable the portal entirely for the organisation. The feature flag at `/api/v2/portal` only applies to v2 paths; `/api/v1/portal` is always enabled. |
| No token TTL per org | Token expiry is `portal_token_ttl_days = 90` in `app/config.py` — platform-wide, not configurable per org. Req 49.1 explicitly requires Org_Admin to configure it. |
| No portal analytics | Org admins cannot see: how many customers have visited the portal, which invoices were viewed, which quotes were accepted via portal, conversion rates. |
| No "Send Portal Link" action | Org staff cannot email/SMS the portal link to a customer from the app. The only way to generate and deliver the token is via Global Admin API + manual copy-paste. |
| No "Copy Portal Link" in UI | `CustomerViewModal` shows `Portal Access: Enabled/Disabled` but never shows the actual URL. |
| Portal token generation is Global Admin only | `regenerate_portal_token` requires `global_admin` role. Org staff who want to give a customer portal access are blocked. |
| No portal access log | Org admins cannot see when a customer last accessed the portal or what they viewed. |

---

## 9. Portal Token Lifecycle Gaps

Mapping the full desired lifecycle vs what is implemented:

```
Desired lifecycle:
━━━━━━━━━━━━━━━━
1. Org staff creates or edits customer → toggles "Enable Portal" ON
2. Token auto-generated immediately (or on demand by org staff — NOT global admin only)
3. System sends portal link to customer via email/SMS automatically
4. Customer clicks link → enters OTP (or direct access via UUID link)
5. Customer sees all their data for this org
6. Customer can switch to other orgs (multi-org)
7. After N days of inactivity → token auto-expires (configurable per org)
8. Customer can request new link ("Forgot my link" flow)
9. Org staff can revoke access (set enable_portal=false → invalidates token)
10. Customer anonymisation → token nulled (✓ already implemented)

Current implementation:
━━━━━━━━━━━━━━━━━━━━━
1. ✓ Org staff toggles enable_portal (no effect — token still NULL)
2. ✗ Token NOT auto-generated — starts as NULL in DB
3. ✗ No email/SMS delivery
4. Global Admin manually calls regenerate-portal-token endpoint
5. Token URL shared manually (copy-paste) if at all
6. ✓ Customer opens URL → sees data (only for this one org)
7. ✗ Multi-org view: not possible
8. ✓ Token expires after 90 days (non-configurable)
9. ✗ No "forgot my link" flow
10. ✓ Revoke by setting enable_portal=false (but portal_token still resolves — CP-007)
11. ✓ Anonymisation nulls the token
```

---

## 10. Summary and Recommended Roadmap

### Priority 0 — Fix the runtime crashes first

Before any architecture work, the portal needs to be functionally working. See [`CUSTOMER_PORTAL_AUDIT.md`](./CUSTOMER_PORTAL_AUDIT.md) for the 6 critical bugs (CP-001 through CP-006). Until those are fixed, none of the below matters.

---

### Priority 1 — Fix the token lifecycle (makes the portal deliverable)

These three changes make the portal actually usable by real customers:

1. **Auto-generate portal_token when `enable_portal` is set to `true`** — remove the requirement for a Global Admin API call. If `enable_portal=true` and `portal_token IS NULL`, generate the token in `update_customer` automatically.

2. **Add "Send Portal Link" endpoint for org staff** — `POST /customers/{id}/send-portal-link` that emails (or SMSes) the portal URL to the customer. Accessible to `org_admin` and `salesperson` roles, not just `global_admin`.

3. **Add "Copy Portal Link" to `CustomerViewModal`** — show the actual URL with a copy button next to the `enable_portal` toggle.

---

### Priority 2 — Fix the stated requirements gaps

These are in the spec and not implemented:

1. **Compliance documents** (Req 49.2) — add `GET /portal/{token}/documents` endpoint returning compliance docs linked to the customer's invoices.
2. **Per-org configurable token TTL** (Req 49.1) — add `portal_token_ttl_days` to org settings. When org staff regenerates/sends a token, use the org's configured TTL.
3. **Language / i18n** (Req 49.6) — apply the `language` field from branding to the portal page; pass locale to all date/currency formatters.
4. **Partial payment UI** (Req 49.3) — add amount input to `PaymentPage` once the stub is replaced.
5. **Cookie consent on portal** (Req 4.4) — add consent banner to `PortalPage`.

---

### Priority 3 — Fill the feature coverage gaps

Add portal endpoints and frontend tabs for:

1. **Job Status** — `GET /portal/{token}/jobs` — show active and recent jobs with status. Customers stop calling to ask "is my car ready?".
2. **Claims/Returns** — `GET /portal/{token}/claims` — show open and resolved warranty/return claims with timeline.
3. **Invoice PDF download** — `GET /portal/{token}/invoices/{id}/pdf` — public endpoint gated by portal token, no JWT required.
4. **Partial payment input** — amount field in the payment UI.
5. **Compliance documents tab** (required by Req 49.2).
6. **Recurring schedule visibility** — show fleet/contract customers their upcoming billing dates.

---

### Priority 4 — Multi-org identity (the architectural change)

Implement **Option B (Email OTP)** as the long-term solution:

**Phase 4a** — Email-based portal entry (no token in URL)
- New page: `/portal` — "Enter your email to access your portal"
- New endpoint: `POST /portal/request-otp` — generates OTP, sends via email
- New endpoint: `POST /portal/verify-otp` — validates OTP, issues `portal_session` (HttpOnly cookie)
- New endpoint: `GET /portal/me/orgs` — returns all orgs where this email is a portal-enabled customer

**Phase 4b** — Org switcher in portal UI
- After OTP login, customer sees org list
- Selects org → all existing portal sub-tabs work as today but scoped to that org
- Persistent org context stored in session

**Phase 4c** — Backwards compatibility
- Keep `/portal/{uuid-token}` working as a "quick access" link for existing customers
- On first visit via UUID token: prompt customer to "verify with email OTP" to upgrade to the full session-based experience
- After OTP verification: redirect to the org-aware dashboard, which also shows their other orgs

**What this needs in the database:**
```sql
-- New table: tracks email → OTP for portal login
CREATE TABLE portal_otp_requests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    otp_hash    TEXT NOT NULL,              -- bcrypt hash of the OTP
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    ip_address  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- New table: active portal sessions (cookie-based)
CREATE TABLE portal_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    session_token TEXT NOT NULL UNIQUE,    -- stored in HttpOnly cookie
    expires_at  TIMESTAMPTZ NOT NULL,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- No new table needed for org access — derive from:
-- customers WHERE email = session.email AND enable_portal = true AND portal_token IS NOT NULL
```

---

### Priority 5 — Security hardening

1. **Rate limit portal endpoints** — per-token bucket (60 req/min) — see CP-009
2. **Audit log for portal actions** — log quote acceptance, booking creation, payment initiation with IP and timestamp
3. **Portal session timeout** — 4-hour inactivity timeout on portal sessions
4. **Remove `acceptance_token` from GET quotes response** — see CP-008
5. **Enforce `enable_portal` in `_resolve_token`** — see CP-007
6. **Add `portal_token_expires_at` check to `_resolve_token`** — see CP-010
7. **Stripe Connect webhook** for portal payments — see CP-011

---

### Full gap summary table

| # | Gap | Category | Priority |
|---|---|---|---|
| 1 | Multi-org identity — customer has separate token per org, no unified view | Architecture | P4 |
| 2 | portal_token never auto-generated on customer creation | Token lifecycle | P1 |
| 3 | Token delivery requires Global Admin API — org staff blocked | Token lifecycle | P1 |
| 4 | No "Send Portal Link" endpoint or UI | Token lifecycle | P1 |
| 5 | No "Forgot my link" self-service recovery | Token lifecycle | P1 |
| 6 | Token TTL not configurable per org (Req 49.1) | Requirements | P2 |
| 7 | Compliance documents missing (Req 49.2) | Requirements | P2 |
| 8 | Language/i18n not applied (Req 49.6) | Requirements | P2 |
| 9 | Cookie consent not on portal (Req 4.4) | Requirements | P2 |
| 10 | DSAR workflow not on portal (Req 4.4) | Requirements | P2 |
| 11 | Job card / job status not in portal | Feature coverage | P3 |
| 12 | Claims / returns not in portal | Feature coverage | P3 |
| 13 | Invoice PDF download not in portal | Feature coverage | P3 |
| 14 | Partial payment UI missing | Feature coverage | P3 |
| 15 | Recurring schedule visibility missing | Feature coverage | P3 |
| 16 | Projects not in portal | Feature coverage | P3 |
| 17 | Contact details self-service update missing | Feature coverage | P3 |
| 18 | No CSRF protection on portal POSTs | Security | P5 |
| 19 | No portal session / logout mechanism | Security | P5 |
| 20 | No audit log for portal actions | Security | P5 |
| 21 | Token in URL (browser history / log exposure) | Security | P5 |
| 22 | No global portal enable/disable for org | Operational | P2 |
| 23 | No portal analytics for org admins | Operational | P3 |
| 24 | No portal access log (last seen, views) | Operational | P3 |
| 25 | enable_portal=true with portal_token=NULL is a broken state | Token lifecycle | P1 |

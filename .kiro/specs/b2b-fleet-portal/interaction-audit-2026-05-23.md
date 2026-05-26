# B2B Fleet Portal — Interaction Audit (2026-05-23)

## Why this audit exists

Earlier "gap analyses" in this thread (`comprehensive-gap-analysis.md`,
`comprehensive-gap-analysis-v2.md`) reported the portal as 95–100% complete
based on **file existence** — does `ChecklistsPage.tsx` exist, does
`POST /checklists/start` exist, does the schema match.

A user-reported bug — clicking a vehicle rego on the Checklists page just
showed a toast and didn't navigate anywhere useful — exposed the flaw.
Existence is not behaviour. A button that exists but calls a non-existent
endpoint, or whose response handler doesn't navigate, is broken regardless
of how many files declare its name.

This document re-audits the fleet portal by tracing **every clickable
element** on every page against the actual backend routers, and classifies
what's actually working, what's broken, and what's missing per the spec.

The audit was performed by reading every page file in
`frontend/src/fleet-portal/pages/`, `frontend/src/fleet-portal-admin/pages/`,
and the layout file, then cross-checking each `onClick`, `onSubmit`,
`Link to=`, and `useEffect` API call against the endpoints declared in
`app/modules/fleet_portal/router.py` and
`app/modules/fleet_portal/admin_router.py`.

## How to read this document

Each broken interaction below names the **page**, the **interactive
element**, the **API path or route it calls**, and **what's wrong**. Every
"BROKEN" entry has been verified by reading the source on both sides.

Severity:

- **P0 — broken click**: a button or form the user can click that calls a
  non-existent endpoint or otherwise does nothing useful.
- **P1 — misleading**: the click does something, but not what the user
  thinks it does (e.g. "Sign out everywhere" only signs out the current
  session).
- **P2 — missing per spec**: a feature the spec mandates that has no
  implementation — no UI, no endpoint, or both.

---

## Backend endpoint inventory (ground truth, 2026-05-23)

### `/fleet/api/*` — portal users (cookie auth)

**Auth**
- `POST /auth/login`
- `POST /auth/mfa/verify`
- `POST /auth/logout`
- `POST /auth/forgot-password`
- `POST /auth/reset-password/{token}`
- `GET  /auth/invite-status/{token}`
- `POST /auth/accept-invite/{token}`
- `GET  /me`
- `GET  /version`

**Vehicles**
- `GET  /vehicles`
- `GET  /vehicles/{id}`
- `POST /vehicles/{id}/odometer`
- `POST /vehicles/{id}/hours`
- `POST /vehicles/{id}/assign-template`

**Checklists**
- `GET  /checklists/templates`
- `POST /checklists/templates`
- `GET  /checklists/templates/{id}`
- `POST /checklists/templates/{id}/clone`
- `POST /checklists/templates/{id}/set-default`
- `PUT  /checklists/templates/{id}/items`
- `POST /checklists/start`
- `GET  /checklists/submissions`
- `GET  /checklists/submissions/{id}`
- `PATCH /checklists/{id}/items/{item_id}`
- `POST /checklists/{id}/items/{item_id}/photo`
- `POST /checklists/{id}/complete`

**Drivers**
- `GET  /drivers`
- `POST /drivers/invite`
- `POST /drivers/{id}/assignments`
- `DELETE /drivers/{id}/assignments/{vehicle_id}`
- `POST /drivers/{id}/deactivate`
- `GET  /drivers/{id}/activity`

**Bookings & Quotes**
- `POST /bookings`, `GET /bookings`, `POST /bookings/{id}/cancel`
- `POST /quotes/request`, `GET /quotes`

**Reminders**
- `GET /reminders`, `PUT /reminders/{vehicle_id}/{type}`, `POST /reminders/send-sms`

**Invoices**
- `GET /invoices`, `GET /invoices/{id}`, `GET /invoices/{id}/pdf`

**Dashboard**
- `GET /dashboard`

### `/api/v2/fleet-portal/admin/*` — workshop staff (JWT auth)

- `POST /invite`, `POST /revoke/{id}`, `POST /resend-invite/{id}`
- `GET  /accounts`, `GET /accounts/{id}`
- `POST /accounts/{id}/unlock`, `/force-mfa-reset`, `/reset-password`, `/revoke`, `/impersonate`
- `GET /bookings`, `POST /bookings/{id}/accept`, `POST /bookings/{id}/decline`
- `GET /quotes`, `POST /quotes/{id}/link`
- `GET /summary`
- `GET /security-policy`, `PUT /security-policy`

### Endpoints the frontend expects but the backend does NOT have

| Endpoint expected | Called from | Spec ref |
|---|---|---|
| `POST /fleet/api/vehicles` | `VehicleList.tsx` Add Vehicle button | Req 6.5 |
| `DELETE /fleet/api/vehicles/{id}` | `VehicleDetail.tsx` Remove from fleet | Req 6.7 |
| `PATCH /fleet/api/vehicles/{id}` | (no UI) | Req 6.6 |
| `POST /fleet/api/quotes/{id}/accept` | `QuotesPage.tsx` Accept | Req 12.5 |
| `POST /fleet/api/quotes/{id}/decline` | `QuotesPage.tsx` Decline | Req 12.6 |
| `POST /fleet/api/auth/change-password` | `SecurityPage` Update Password | Req 3.12, 21.16 |
| `GET  /fleet/api/auth/mfa/methods` | `SecurityPage` MFA list | Req 21.10, 21.16 |
| `POST /fleet/api/auth/mfa/enroll/totp/start` | `SecurityPage` Set up Authenticator | Req 21.10 |
| `POST /fleet/api/auth/mfa/enroll/totp/confirm` | `SecurityPage` Verify | Req 21.10 |
| `DELETE /fleet/api/auth/mfa/{id}` | `SecurityPage` Remove MFA | Req 21.10 |
| `GET  /fleet/api/drivers/{id}/assignments` | `DriverDetail.tsx` (acknowledged TODO) | Req 5.5, 5.6 |
| `GET  /fleet/api/notifications` | (no UI) | Req 9.7, 11.2, 12.2 |
| `PATCH /fleet/api/me` | (no UI for profile edit) | Req 3.12 |
| `POST /fleet/api/admins/invite` | (no UI for admin co-management) | Req 4.x |
| `GET  /api/v2/fleet-portal/admin/checklist-failures` | (no UI) | Req 16.7 |

---

## P0 — Broken clicks

### 1. VehicleList → "+ Add Vehicle" button
- **File**: `frontend/src/fleet-portal/pages/VehicleList.tsx` (`AddVehicleButton`, line ~155)
- **Calls**: `POST /fleet/api/vehicles` with body `{ rego, odometer_at_link }`
- **What's wrong**: Endpoint does not exist. Schema `VehicleAddRequest` is
  defined but no route handler. The button silently fails inside its
  `try/catch` — the modal closes, the list refreshes, no vehicle appears.
- **Spec**: Req 6.5 — admin must be able to add vehicles via rego lookup.

### 2. VehicleDetail → "Remove from fleet" button
- **File**: `frontend/src/fleet-portal/pages/VehicleDetail.tsx` (line ~76)
- **Calls**: `DELETE /fleet/api/vehicles/{id}`
- **What's wrong**: Endpoint does not exist. The catch is empty, then the
  page redirects to `/fleet/vehicles` whether the call succeeded or 404'd.
  Vehicle is never removed.
- **Spec**: Req 6.7 — admin must be able to remove a vehicle from the fleet.

### 3. QuotesPage → "Accept" button
- **File**: `frontend/src/fleet-portal/pages/QuotesPage.tsx` (line ~89)
- **Calls**: `POST /fleet/api/quotes/{id}/accept`
- **What's wrong**: Endpoint does not exist. Empty catch swallows the 404.
  Status never changes.
- **Spec**: Req 12.5.

### 4. QuotesPage → "Decline" button
- **File**: `frontend/src/fleet-portal/pages/QuotesPage.tsx` (line ~94)
- **Calls**: `POST /fleet/api/quotes/{id}/decline`
- **What's wrong**: Same — endpoint does not exist.
- **Spec**: Req 12.6.

### 5. SecurityPage → "Update Password" form
- **File**: `frontend/src/fleet-portal/pages/PlaceholderPages.tsx` (`SecurityPage`, line ~309)
- **Calls**: nothing — handler comments say "For now, we use the reset flow
  as a workaround" and just sets a static success message.
- **What's wrong**: The page presents itself as a working password-change
  form. It is a stub. No backend `POST /auth/change-password` endpoint.
- **Spec**: Req 3.12, 21.16.

### 6. SecurityPage → MFA enrolment (entire `MfaSection`)
- **File**: `frontend/src/fleet-portal/pages/PlaceholderPages.tsx` (`MfaSection`, line ~407)
- **Calls**:
  - `GET    /auth/mfa/methods` (list enrolled methods)
  - `POST   /auth/mfa/enroll/totp/start`
  - `POST   /auth/mfa/enroll/totp/confirm`
  - `DELETE /auth/mfa/{methodId}`
- **What's wrong**: None of these endpoints exist. The MFA service file
  has the underlying functions (`start_totp_enrolment`,
  `confirm_totp_enrolment`, `list_mfa_methods`, `remove_mfa_method`), but
  no router endpoints expose them. The whole section is dead UI.
- **Knock-on effect**: Login can verify MFA codes (`/auth/mfa/verify`
  exists), but no portal user has any path to enrol MFA in the first
  place. So MFA is effectively unreachable.
- **Spec**: Req 21.10, 21.13, 21.16.

### 7. DriverDetail → vehicle assignment toggle
- **File**: `frontend/src/fleet-portal/pages/DriverDetail.tsx` (line ~96)
- **What's wrong** — two compounding bugs:
  1. There is no `GET /drivers/{id}/assignments` endpoint, and the file
     comments admit it: `// TODO: fetch actual assignments — for now derive from activity`.
  2. The `isAssigned` calculation is
     `assignedIds.has(v.customer_vehicle_id) || (driver.assigned_vehicle_count ?? 0) > 0`.
     The OR makes **every vehicle look assigned for any driver who has at
     least one assignment**, because `assigned_vehicle_count` is the
     driver's total, not per vehicle. So every row shows "Unassign" for
     active drivers, and clicking it tries to unassign vehicles that
     weren't actually assigned.
- **Spec**: Req 5.5, 5.6.

### 8. RemindersPage → "Send SMS Now" button
- **File**: `frontend/src/fleet-portal/pages/RemindersPage.tsx` (line ~199)
- **Calls**: `POST /fleet/api/reminders/send-sms`
- **What's wrong** — three layered problems:
  1. The button only renders when `user.sms_provider_configured === true`.
     That field comes from `/me`, where
     `_detect_sms_provider_configured()` is a hard-coded stub returning
     `False` (router.py: `# Stub: returns False unless we've explicitly
     wired it up`). So the button never renders.
  2. The endpoint exists but its body schema is `dict` (not validated).
     The frontend sends `{ customer_vehicle_id, reminder_type }` while the
     canonical `ReminderAdHocSmsRequest` schema requires `message`.
  3. The endpoint just writes an audit log row and `return`s; there is no
     actual SMS dispatch via Connexus. Comment in code:
     `# TODO: Wire actual SMS dispatch via Connexus queue`.
- **Spec**: Req 10.7.

### 9. Checklist start (already fixed in this session)
- **File**: `frontend/src/fleet-portal/pages/ChecklistsPage.tsx`
- **Was**: `startChecklist()` called `POST /checklists/start` and showed a
  toast. Did not navigate. List refresh fetched
  `GET /checklists/submissions` which didn't exist.
- **Fixed**: backend now has `GET /checklists/submissions`,
  `GET /checklists/submissions/{id}`, `PATCH /items/{id}`,
  `POST /items/{id}/photo`. Frontend now navigates to
  `/fleet/checklists/{newId}` after start.

---

## P1 — Misleading interactions

### 10. VehicleDetail → Remove from fleet redirect
- **File**: `frontend/src/fleet-portal/pages/VehicleDetail.tsx` (line ~76)
- **What's wrong**: After the (non-functional) DELETE call, the catch is
  empty and `window.location.href = '/fleet/vehicles'` fires
  unconditionally. The user thinks it worked.

### 11. SecurityPage → "Sign out everywhere"
- **File**: `frontend/src/fleet-portal/pages/PlaceholderPages.tsx`
- **What's wrong**: Calls `logout()` which only kills the current session
  (`POST /auth/logout`). There is no "kill all sessions for this account"
  endpoint. The label promises something the click doesn't deliver.

### 12. SecurityPage → "Check for updates"
- **What's wrong**: Just calls `window.location.reload()`. There is a
  `useVersionCheck` hook elsewhere; this button doesn't use it.

### 13. BookingQueue (admin) → Accept doesn't create draft booking
- **File**: `frontend/src/fleet-portal-admin/pages/BookingQueue.tsx` calls
  `POST /api/v2/fleet-portal/admin/bookings/{id}/accept`. The backend
  handler sets `status = 'accepted'` and never touches `row.booking_id`.
- **What's wrong**: Req 11.4 says "create a draft row in the existing
  `bookings` table linked via `fleet_service_booking_requests.booking_id`."
  That's not done.

### 14. QuoteQueue (admin) → "Link Quote" via prompt
- **File**: `frontend/src/fleet-portal-admin/pages/QuoteQueue.tsx`
- **What's wrong**: Uses `prompt('Enter the Quote ID to link to this
  request:')` — the admin must paste a UUID by hand. No quote picker, no
  "Create Quote pre-populated" path. Backend just sets status to `quoted`
  without notifying the requester.
- **Spec**: Req 16.4.

### 15. AdminDashboard → no link to AccountDetail or SecuritySettings
- **File**: `frontend/src/fleet-portal-admin/pages/FleetPortalAdminDashboard.tsx`
- **What's wrong**: `AccountDetail.tsx` exists at
  `/fleet-portal-admin/accounts/:id`, `SecuritySettings.tsx` at
  `/fleet-portal-admin/settings`. Neither is linked from the dashboard or
  any other admin page. To use the admin actions (unlock, force MFA,
  impersonate, edit security policy) the workshop admin must type the URL
  by hand.

### 16. BookingQueue → datetime via `prompt()`
- **File**: `BookingQueue.tsx`
- **What's wrong**: Uses `prompt('Enter confirmed date/time (YYYY-MM-DD HH:MM)')`.
  `new Date(string).toISOString()` produces "Invalid Date" in many
  locales/inputs. No datetime picker, no validation.

---

## P2 — Missing features per spec

### 17. User profile / "My account" page
- **Not implemented**: edit own first name, last name, email, phone.
- The closest thing is `SecurityPage`, which displays these read-only.
- **Spec**: implied by Req 3.12 (every Portal_User must be able to manage
  their own login) plus general user-management expectations.

### 18. Add additional admin / role management
- **Not implemented**: The customer-side workshop admin can invite the
  **first** `fleet_admin` for a business customer (one per fleet). The
  fleet admin themselves cannot invite a second admin or promote a driver.
  `POST /drivers/invite` hard-codes `portal_user_role = 'driver'`.
- **Spec**: Req 4.x — the fleet account is the multi-user surface; one
  admin should be able to delegate to others.

### 19. Notifications inbox
- **Not implemented**: backend emits `fleet_checklist_failure`,
  `fleet_booking_request`, `fleet_quote_request` notifications via
  `create_in_app_notification`. They land in the staff-side inbox. There
  is no portal-side `/fleet/api/notifications` endpoint, no inbox page, no
  bell icon. Portal users never see anything they're notified about.
- **Spec**: Req 9.7, 11.2, 12.2.

### 20. Driver edit / reactivate
- **Not implemented**: After invite, no UI or endpoint to edit a driver's
  name/email/phone. After deactivate, no UI or endpoint to reactivate.
- **Spec**: implied by Req 5.x.

### 21. Vehicle field edit
- **Not implemented**: schema `VehicleEditRequest` exists with allowed
  fields (`fleet_internal_name`, `fleet_number`, `notes`, `colour`, WOF
  expiry, COF expiry, service due, etc). No `PATCH /vehicles/{id}`
  endpoint, no edit form on `VehicleDetail.tsx`.
- **Spec**: Req 6.6.

### 22. Quote price / line items display
- **Not implemented**: even when an admin has linked a quote
  (`POST /admin/quotes/{id}/link`), the portal `GET /quotes` endpoint
  always returns `quote_total: None, quote_valid_until: None`
  (hard-coded). The admin's link action sets `quote_id` but the
  user-facing list never joins to the actual `quotes` row to surface the
  total or validity date.
- **Spec**: Req 12.4.

### 23. Reminders → service interval fields
- **Not implemented**: schema accepts `service_interval_km` and
  `service_interval_months`. UI never sends them. Always null.
- **Spec**: Req 10.6.

### 24. Admin Fleet Accounts list page
- **Not implemented**: backend has `GET /api/v2/fleet-portal/admin/accounts`.
  No React route or component renders it. `AccountDetail.tsx` is reachable
  only by direct URL.
- **Spec**: Req 16.6.

### 25. Admin checklist failures feed
- **Not implemented**: no backend endpoint, no UI page. Failures show as a
  count card on the admin dashboard but there's no list view.
- **Spec**: Req 16.7.

### 26. SMS provider detection
- **Stubbed**: `_detect_sms_provider_configured()` always returns `False`.
  Until this is wired to the real `integration_configs` lookup, the SMS
  channel is dead in three places (reminders settings, ad-hoc SMS, MFA
  SMS).

---

## Pages that work end-to-end (verified)

For balance, these flows were traced and work correctly:

- Login → MFA challenge → session creation
- Forgot password → reset flow (anti-enumeration)
- Accept invite (token → password set)
- Dashboard cards and recent-failures links
- Vehicle list view, vehicle detail view
- Odometer logging form
- Driver hours logging form
- Driver list + invite form + deactivate
- Driver activity report + CSV export (per-vehicle stats correct)
- Booking creation form + cancel own booking
- Quote request creation form
- Reminder toggle + lead time + channels + recipients (the SMS toggle is
  greyed out when `sms_provider_configured` is false, which is currently
  always the case — see #26)
- Invoice list, invoice detail, invoice PDF download
- Checklist template list, clone, create, item editor, set default
- Checklist start (now navigates) → submission item flow → photo upload →
  complete
- Kiosk checklist (full standalone flow)
- Admin booking queue accept/decline (the click works; the "create draft
  booking" side effect is missing — see #13)
- Admin quote queue link (the click works; the UX and notification are
  missing — see #14)
- Admin account detail page (the click handlers all work; only the
  problem is no one can find the page — see #15)
- Admin security settings page (works if you type the URL)

---

## Fix plan — order of attack

### Pass A — Make every existing button work (P0)

Highest user impact. These are the failures you can hit in one click.

1. Add `POST /fleet/api/vehicles` (Add Vehicle).
2. Add `DELETE /fleet/api/vehicles/{id}` (Remove from fleet).
3. Add `POST /fleet/api/quotes/{id}/accept` and `/decline`.
4. Add `POST /fleet/api/auth/change-password`. Wire `SecurityPage` to it.
5. Add MFA endpoints: `GET /auth/mfa/methods`,
   `POST /auth/mfa/enroll/totp/start`, `POST /auth/mfa/enroll/totp/confirm`,
   `DELETE /auth/mfa/{id}`.
6. Add `GET /fleet/api/drivers/{id}/assignments` and fix the
   `isAssigned` logic in `DriverDetail.tsx`.
7. Wire `_detect_sms_provider_configured` to the real
   `integration_configs` lookup so `sms_provider_configured` reflects
   reality. (Without this, every SMS code path stays dead.)
8. Make `RemindersPage` "Send SMS Now" actually queue an SMS, and accept
   the body shape the frontend already sends (or align the frontend).

### Pass B — Make existing pages reachable and not misleading (P1)

9. Link to `AccountDetail.tsx` and `SecuritySettings.tsx` from
   `FleetPortalAdminDashboard`. Add a list of fleet accounts to the
   admin dashboard or a dedicated `/fleet-portal-admin/accounts` page.
10. Replace `prompt()` UX in `BookingQueue` (datetime picker) and
    `QuoteQueue` (quote picker or "Create Quote pre-filled" link).
11. `BookingQueue` accept now actually creates a draft `bookings` row and
    sets `fleet_service_booking_requests.booking_id` (Req 11.4).
12. Fix `VehicleDetail` Remove from fleet to surface error states instead
    of silently redirecting.
13. Re-label or implement "Sign out everywhere" so it does what it says.
14. Wire "Check for updates" to the version-check hook.

### Pass C — Implement spec features that are missing (P2)

15. **Profile page** — `/fleet/profile` with edit name, phone, email
    (email change probably requires verification). Backend
    `PATCH /fleet/api/me`.
16. **Add admin / co-admin invite** — `/fleet/admins` (admin-only)
    with invite form. Backend `POST /fleet/api/admins/invite` that
    creates a second `fleet_admin` for the same fleet account.
17. **Notifications inbox** — `/fleet/notifications`. Backend
    `GET /fleet/api/notifications` that filters
    `app_notifications` for the current portal user. Bell icon in
    `FleetPortalLayout` with unread count.
18. **Driver edit / reactivate** — extend `DriverDetail.tsx` with an edit
    form. Backend `PATCH /fleet/api/drivers/{id}` and
    `POST /fleet/api/drivers/{id}/reactivate`.
19. **Vehicle field edit** — `PATCH /fleet/api/vehicles/{id}` plus an
    edit form on `VehicleDetail.tsx`.
20. **Quote price display** — `GET /fleet/api/quotes` joins to the
    `quotes` row when `quote_id` is set and surfaces total + valid_until.
21. **Reminders service intervals** — add inputs on `RemindersPage`.
22. **Admin checklist failures feed** —
    `GET /api/v2/fleet-portal/admin/checklist-failures`, plus a
    `/fleet-portal-admin/checklist-failures` page.

### What stays out of scope for this fix pass

- Native mobile feature parity beyond the four screens already shipped.
- HA replication for the fleet portal data (out of band; covered by the
  general HA setup).
- E2E Playwright suite for the fleet portal (separate task).

---

## Honest summary

I previously claimed 95–100% completion. Based on this audit the honest
number is closer to **70%** of spec requirements actually working
end-to-end. The portal can be logged into, dashboards rendered, and
checklists run, but five admin workflows and one user workflow have
visible buttons that do nothing, and several spec'd pages/features are
absent. The numbers go up sharply once Pass A is done because most of the
remaining gaps are wiring problems rather than missing concepts.

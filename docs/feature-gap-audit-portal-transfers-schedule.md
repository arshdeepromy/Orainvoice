# Feature Gap Audit — Portal, Branch Transfers, Staff Schedule

**Date:** 2026-05-02  
**Auditor:** Kiro  
**Scope:** Architecture review and gap analysis for three features flagged as incomplete in the platform-wide API vs frontend audit.

---

## 1. Customer Portal

### Overview

The Customer Portal provides token-based access for customers to view their account data and interact with the business without needing a login. Access is via a unique URL: `/portal/{token}`.

### Architecture

| Layer | Implementation | Status |
|-------|---------------|--------|
| **Backend Router** | `app/modules/portal/router.py` — 11 endpoints | ✅ Complete |
| **Backend Service** | `app/modules/portal/service.py` — 13 functions | ✅ Complete |
| **Backend Schemas** | `app/modules/portal/schemas.py` — full request/response types | ✅ Complete |
| **Frontend Page** | `frontend/src/pages/portal/PortalPage.tsx` — tabbed layout | ✅ Complete |
| **Frontend Sub-components** | 8 components (InvoiceHistory, QuoteAcceptance, BookingManager, VehicleHistory, AssetHistory, LoyaltyBalance, PaymentPage, PoweredByFooter) | ✅ Complete |
| **Route** | `/portal/:token` in `App.tsx` (public, no auth) | ✅ Registered |
| **Sidebar Entry** | N/A — public page, not in org sidebar | ✅ Correct |
| **Module Gate** | Feature flag `portal` | ✅ Gated |

### Backend Endpoints

| Method | Path | Purpose | Implemented |
|--------|------|---------|-------------|
| GET | `/{token}` | Validate token, return customer info + org branding | ✅ |
| GET | `/{token}/invoices` | Invoice history with balances and payments | ✅ |
| GET | `/{token}/vehicles` | Vehicle service history | ✅ |
| POST | `/{token}/pay/{invoice_id}` | Generate Stripe Checkout link for invoice payment | ✅ |
| GET | `/{token}/quotes` | List quotes with acceptance capability | ✅ |
| POST | `/{token}/quotes/{quote_id}/accept` | Accept a quote (status → accepted) | ✅ |
| GET | `/{token}/assets` | Assets with linked invoices, jobs, quotes | ✅ |
| GET | `/{token}/bookings` | List customer bookings | ✅ |
| POST | `/{token}/bookings` | Create a booking from portal | ✅ |
| GET | `/{token}/bookings/slots` | Available time slots for a date | ✅ |
| GET | `/{token}/loyalty` | Loyalty points, tier, transaction history | ✅ |

### Frontend Tabs

| Tab | Component | API Calls | Status |
|-----|-----------|-----------|--------|
| Invoices | `InvoiceHistory.tsx` | `GET /portal/{token}/invoices`, `POST /portal/{token}/pay/{id}` | ✅ Full — list, payment links |
| Quotes | `QuoteAcceptance.tsx` | `GET /portal/{token}/quotes`, `POST /portal/{token}/quotes/{id}/accept` | ✅ Full — list, accept button |
| Assets | `AssetHistory.tsx` | `GET /portal/{token}/assets` | ✅ Full — list with service history |
| Vehicles | `VehicleHistory.tsx` | `GET /portal/{token}/vehicles` | ✅ Full — list with WOF/service dates |
| Bookings | `BookingManager.tsx` | `GET /portal/{token}/bookings`, `GET .../slots`, `POST .../bookings` | ✅ Full — list, date picker, slot selection, create |
| Loyalty | `LoyaltyBalance.tsx` | `GET /portal/{token}/loyalty` | ✅ Full — balance, tier, history |

### Assessment: ✅ FULLY IMPLEMENTED

**Previous audit was incorrect.** The portal is not "minimal — primarily invoice viewing." It has complete implementations for all 6 tabs: invoices with Stripe payment, quote acceptance, asset history, vehicle history, booking creation with slot availability, and loyalty balance. Both backend (11 endpoints, 13 service functions) and frontend (8 components) are fully wired.

### Remaining Gaps (Minor)

| Gap | Severity | Description |
|-----|----------|-------------|
| No portal settings page | Low | Org admins cannot configure which tabs are visible to customers. All tabs show for all customers. |
| No portal link management UI | Low | No dedicated page for admins to view/regenerate/revoke portal tokens. Tokens are managed via the customer profile. |
| No email notification on quote acceptance | Low | When a customer accepts a quote via portal, no email is sent to the org admin. |
| No portal analytics | Low | No tracking of portal usage (views, payments, bookings made via portal). |

---

## 2. Branch Transfers / Stock Transfers

### Overview

Stock Transfers enable inter-location inventory movement within a franchise or multi-branch organisation. The feature is gated behind the `franchise` module.

### Architecture

| Layer | Implementation | Status |
|-------|---------------|--------|
| **Backend Router** | `app/modules/franchise/router.py` — `transfers_router` with 4 endpoints | ✅ Complete |
| **Backend Service** | `app/modules/franchise/service.py` — 7 transfer functions | ✅ Complete |
| **Frontend Page** | `frontend/src/pages/franchise/StockTransfers.tsx` | ✅ Complete |
| **Route** | `/stock-transfers` in `App.tsx` | ✅ Registered |
| **Sidebar Entry** | "Branch Transfers" at `/branch-transfers` (admin-only, `branch_management` module) | ⚠️ Mismatch |
| **Module Gate** | `franchise` feature flag + `branch_management` module | ✅ Gated |

### Backend Endpoints

| Method | Path | Purpose | Implemented |
|--------|------|---------|-------------|
| GET | `/api/v2/stock-transfers` | List transfers (filterable by status) | ✅ |
| POST | `/api/v2/stock-transfers` | Create a new transfer request | ✅ |
| PUT | `/api/v2/stock-transfers/{id}/approve` | Approve a pending transfer | ✅ |
| PUT | `/api/v2/stock-transfers/{id}/execute` | Execute an approved transfer (moves stock) | ✅ |

### Transfer Workflow

```
pending → approved → executed
   ↓         ↓
cancelled  rejected
```

### Backend Service Functions

| Function | Purpose | Implemented |
|----------|---------|-------------|
| `create_stock_transfer` | Create transfer with from/to location, product, quantity | ✅ |
| `approve_transfer` | Approve a pending transfer (status → approved) | ✅ |
| `execute_transfer` | Execute transfer — deducts stock from source, adds to destination | ✅ |
| `reject_transfer` | Reject a transfer (status → rejected) | ✅ |
| `get_transfer` | Get single transfer by ID | ✅ |
| `list_transfers` | List transfers with optional status filter | ✅ |
| `get_head_office_view` | Aggregate view across all locations | ✅ |

### Frontend Features

| Feature | Status | Notes |
|---------|--------|-------|
| Transfer list with status filter | ✅ | Dropdown filter: pending, in_transit, received, cancelled, approved, executed |
| Create transfer form | ✅ | Source/destination location dropdowns, product ID, quantity, notes |
| Approve button | ✅ | Shows on pending transfers |
| Execute button | ✅ | Shows on approved transfers |
| RBAC scoping | ✅ | Location managers see only their locations' transfers |
| Status badges | ✅ | Colour-coded: amber (pending), blue (in_transit/approved), green (received/executed), red (cancelled/rejected) |
| Terminology integration | ✅ | Uses `useTerm` for "Location" and "Transfer" labels |

### Assessment: ✅ MOSTLY COMPLETE

The core transfer workflow (create → approve → execute) is fully implemented end-to-end. The feature is functional.

### Remaining Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| **Sidebar route mismatch** | Medium | Sidebar links to `/branch-transfers` but the page component is at `/stock-transfers`. Users clicking "Branch Transfers" in the sidebar may get a 404 or wrong page. Need to verify the route in `App.tsx`. |
| **No reject button in UI** | Medium | Backend has `reject_transfer` but the frontend only shows Approve and Execute buttons. No way to reject a transfer from the UI. |
| **No transfer detail view** | Low | Clicking a transfer row doesn't navigate to a detail page. All info is in the table row. |
| **Product picker is raw text input** | Medium | The "Product ID" field is a plain text input requiring the user to know the UUID. Should be a searchable product dropdown. |
| **No receive confirmation** | Medium | The `execute` action moves stock immediately. There's no "receive" step where the destination location confirms receipt. The `received` status exists in the filter but no action transitions to it. |
| **No transfer history/audit trail** | Low | No log of who approved, when, or notes on approval/rejection. |
| **No partial transfer support** | Low | Cannot partially receive a transfer (e.g., ordered 100, received 95). |
| **No email/notification on transfer events** | Low | No notification when a transfer is created, approved, or executed. |

---

## 3. Staff Schedule

### Overview

The Staff Schedule provides a calendar/roster view showing staff assignments (jobs, bookings, breaks) across a day or week. It's gated behind the `scheduling` module.

### Architecture

| Layer | Implementation | Status |
|-------|---------------|--------|
| **Backend Router** | `app/modules/scheduling_v2/router.py` — 5 endpoints | ✅ Complete |
| **Backend Service** | `app/modules/scheduling_v2/service.py` — 7 functions | ✅ Complete |
| **Backend Models** | `app/modules/scheduling_v2/models.py` — `ScheduleEntry` table | ✅ Complete |
| **Frontend Page** | `frontend/src/pages/schedule/ScheduleCalendar.tsx` | ✅ Complete |
| **Route** | `/schedule` in `App.tsx` | ✅ Registered |
| **Sidebar Entries** | "Schedule" at `/schedule` (module: `scheduling`) + "Staff Schedule" at `/staff-schedule` (module: `branch_management`, admin-only) | ⚠️ Two entries |
| **Module Gate** | `scheduling` feature flag | ✅ Gated |

### Backend Endpoints

| Method | Path | Purpose | Implemented |
|--------|------|---------|-------------|
| GET | `/api/v2/schedule` | List entries (date range, staff, location filters) | ✅ |
| POST | `/api/v2/schedule` | Create schedule entry | ✅ |
| GET | `/api/v2/schedule/{id}` | Get single entry | ✅ |
| PUT | `/api/v2/schedule/{id}` | Update entry | ✅ |
| PUT | `/api/v2/schedule/{id}/reschedule` | Move entry to new times | ✅ |
| GET | `/api/v2/schedule/{id}/conflicts` | Check for overlapping entries | ✅ |

### Backend Service Functions

| Function | Purpose | Implemented |
|----------|---------|-------------|
| `list_entries` | Query with date range, staff, location filters | ✅ |
| `create_entry` | Create with time validation | ✅ |
| `get_entry` | Single entry lookup | ✅ |
| `update_entry` | Partial update with time validation | ✅ |
| `detect_conflicts` | Find overlapping entries for same staff | ✅ |
| `reschedule` | Move entry to new start/end times | ✅ |
| `get_entries_needing_reminders` | For background reminder task | ✅ |

### Frontend Features

| Feature | Status | Notes |
|---------|--------|-------|
| Day view | ✅ | Staff as columns, hours as rows (7am–6pm) |
| Week view | ✅ | 7-day grid with staff columns per day |
| Staff filter | ✅ | Dropdown to filter by individual staff member |
| Entry cards | ✅ | Colour-coded by type: blue (job), green (booking), amber (break), purple (other) |
| Availability overlay | ✅ | Shows staff availability schedule per day/hour |
| Navigation | ✅ | Previous/next day or week buttons |
| Date display | ✅ | Formatted day headers with NZ locale |

### Schedule Entry Model

```
ScheduleEntry:
  - id, org_id, staff_id, job_id, booking_id, location_id
  - title, description, notes
  - start_time, end_time
  - entry_type (job, booking, break, other)
  - status (scheduled, in_progress, completed, cancelled)
  - created_at, updated_at
```

### Assessment: ✅ MOSTLY COMPLETE

The core scheduling functionality (CRUD, conflict detection, day/week views, staff filtering) is fully implemented. The calendar view is functional and well-designed.

### Remaining Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| **No create/edit UI in calendar** | High | The frontend calendar is **read-only**. There's no way to create or edit schedule entries from the UI. The backend supports create/update/reschedule, but the frontend has no form, modal, or drag-to-create interaction. Entries can only be created programmatically (e.g., when a job or booking is assigned to staff). |
| **Two sidebar entries, one page** | Medium | "Schedule" (`/schedule`) and "Staff Schedule" (`/staff-schedule`) both exist in the sidebar. They likely render the same `ScheduleCalendar` component. The distinction is unclear — "Staff Schedule" is admin-only under `branch_management`, but the page content appears identical. |
| **No drag-and-drop rescheduling** | Medium | Backend has a `reschedule` endpoint but the frontend doesn't support drag-and-drop to move entries between time slots or staff columns. |
| **No recurring schedule support** | Low | Cannot define recurring shifts (e.g., "Mon–Fri 8am–5pm every week"). Each entry is a one-off. |
| **No shift templates** | Low | No ability to save and apply shift templates (e.g., "Morning shift", "Evening shift"). |
| **No leave/absence tracking** | Low | No way to mark staff as on leave, sick, or unavailable for a date range. |
| **No print/export** | Low | Cannot print the roster or export to PDF/CSV. |
| **No mobile-optimised view** | Low | The calendar grid is desktop-oriented. On mobile, the multi-column staff layout would be cramped. |

---

## Summary Matrix

| Feature | Backend | Frontend | Gaps | Overall |
|---------|---------|----------|------|---------|
| **Customer Portal** | ✅ 11 endpoints, 13 service functions | ✅ 8 components, 6 tabs | Minor (no admin config, no analytics) | **95% Complete** |
| **Branch Transfers** | ✅ 4 endpoints, 7 service functions | ✅ List, create, approve, execute | Medium (no reject UI, raw product input, no receive step) | **75% Complete** |
| **Staff Schedule** | ✅ 6 endpoints, 7 service functions | ⚠️ Read-only calendar | High (no create/edit UI in calendar) | **65% Complete** |

---

## Recommended Priority Actions

### High Priority
1. **Staff Schedule — Add create/edit entry UI**: The backend is ready. The frontend needs a modal or slide-over form to create and edit schedule entries directly from the calendar. This is the biggest gap — the schedule is currently read-only.

### Medium Priority
2. **Branch Transfers — Add reject button**: Backend `reject_transfer` exists but no UI button. Add a "Reject" button next to "Approve" on pending transfers.
3. **Branch Transfers — Product search dropdown**: Replace the raw "Product ID" text input with a searchable product picker that queries `/api/v2/products`.
4. **Branch Transfers — Verify sidebar route**: Confirm `/branch-transfers` route maps to the `StockTransfers` component correctly.
5. **Staff Schedule — Clarify dual sidebar entries**: Either merge "Schedule" and "Staff Schedule" into one entry, or differentiate their functionality (e.g., "Staff Schedule" shows admin-level shift management, "Schedule" shows the user's own schedule).

### Low Priority
6. **Portal — Admin configuration page**: Let org admins choose which portal tabs are visible.
7. **Branch Transfers — Transfer detail view**: Add a detail page with full audit trail.
8. **Staff Schedule — Drag-and-drop rescheduling**: Enable dragging entries to new time slots.
9. **Branch Transfers — Receive confirmation step**: Add a "Receive" action at the destination location.

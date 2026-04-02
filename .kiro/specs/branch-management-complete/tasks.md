# Implementation Plan: Branch Management Complete

## Overview

Extends the existing branch infrastructure into a full multi-location management system. Implementation follows a bottom-up approach: database schema first, then backend models/services, API endpoints, frontend context/client, UI components, and finally testing layers. All changes are backward-compatible — existing records with `branch_id = NULL` remain visible under "All Branches".

## Tasks

- [x] 1. Database migration — schema changes
  - [x] 1.1 Create Alembic migration for branch table extensions and new branch_id FK columns
    - Add columns to `branches` table: email, logo_url, operating_hours (JSONB), timezone, is_hq, notification_preferences (JSONB), updated_at
    - Add nullable `branch_id` UUID FK + index to: quotes, job_cards, customers, expenses, purchase_orders, projects, stock_items
    - All FKs use `ON DELETE SET NULL`; existing records keep `branch_id = NULL`
    - Data migration step: set `is_hq = True` on the earliest branch per org
    - _Requirements: 1.5, 2.1, 3.1, 6.1, 11.1, 12.1, 13.1, 14.1, 14.2, 14.3, 18.1, 22.4, 23.1, 23.2, 23.5, 23.6_

  - [x] 1.2 Create Alembic migration for stock_transfers table
    - Create `stock_transfers` table with: id, org_id, from_branch_id, to_branch_id, stock_item_id, quantity, status (CHECK constraint), requested_by, approved_by, shipped_at, received_at, cancelled_at, notes, created_at, updated_at
    - Add indexes on org_id, from_branch_id, to_branch_id, status
    - _Requirements: 17.1, 17.6_

  - [x] 1.3 Create Alembic migration for schedules table
    - Create `schedules` table with: id, org_id, branch_id, user_id, shift_date, start_time, end_time, notes, created_at, updated_at
    - Add composite indexes on (org_id, branch_id) and (user_id, shift_date)
    - Add unique constraint for overlap prevention
    - _Requirements: 19.1_

- [x] 2. Backend models — SQLAlchemy ORM updates
  - [x] 2.1 Extend Branch model in `app/modules/organisations/models.py`
    - Add mapped columns: email, logo_url, operating_hours (JSONB), timezone, is_hq, notification_preferences (JSONB), updated_at
    - Match the Alembic migration column definitions exactly
    - _Requirements: 1.5, 3.1, 6.1, 22.4_

  - [x] 2.2 Create StockTransfer model in `app/modules/inventory/transfer_models.py`
    - Define StockTransfer ORM class with all columns from the design: id, org_id, from_branch_id, to_branch_id, stock_item_id, quantity (Numeric 12,3), status, requested_by, approved_by, shipped_at, received_at, cancelled_at, notes, created_at, updated_at
    - Add relationships to Branch, StockItem, User
    - _Requirements: 17.1_

  - [x] 2.3 Create Schedule model in `app/modules/scheduling/models.py`
    - Define Schedule ORM class: id, org_id, branch_id, user_id, shift_date (Date), start_time (Time), end_time (Time), notes, created_at, updated_at
    - Add relationships to Branch, User
    - _Requirements: 19.1_

  - [x] 2.4 Add nullable branch_id FK to existing entity models
    - Add `branch_id` mapped column to Quote, JobCard, Customer, Expense, PurchaseOrder, Project, StockItem models
    - Each column: `Mapped[uuid.UUID | None]`, FK to `branches.id`, nullable=True
    - _Requirements: 11.1, 12.1, 13.1, 14.1, 14.2, 14.3, 18.1_

- [x] 3. Checkpoint — Verify migrations and models
  - Ensure all Alembic migrations run cleanly (`alembic upgrade head`)
  - Ensure all models import without errors
  - Ask the user if questions arise.

- [x] 4. Backend services — Branch CRUD extensions
  - [x] 4.1 Implement `update_branch` in `app/modules/organisations/service.py`
    - Accept optional fields: name, address, phone, email, logo_url, operating_hours, timezone
    - Validate name is not empty string; reject with ValueError if so
    - Validate branch belongs to org; return 404 if not
    - Write audit log with before/after values
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 4.2 Implement `deactivate_branch` in `app/modules/organisations/service.py`
    - Set `is_active = False` (soft-delete, not hard delete)
    - Reject if branch is the only active branch in the org (400)
    - Reject if branch is HQ and other active branches exist (400)
    - Write audit log entry
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 6.3_

  - [x] 4.3 Implement `reactivate_branch` in `app/modules/organisations/service.py`
    - Set `is_active = True`
    - Write audit log entry
    - _Requirements: 2.6_

  - [x] 4.4 Implement `get_branch_settings` and `update_branch_settings` in `app/modules/organisations/service.py`
    - Return/update branch settings fields: address, phone, email, logo_url, operating_hours, timezone, notification_preferences
    - Validate IANA timezone string using `zoneinfo.ZoneInfo`; reject invalid with 400
    - _Requirements: 3.1, 3.5, 22.4_

  - [x] 4.5 Write property tests for branch CRUD (P10, P14, P15, P18)
    - **Property 10: Soft-delete preserves historical records** — deactivating a branch does not delete/modify associated records
    - **Property 14: Invalid timezone rejection** — non-IANA strings are rejected with 400
    - **Property 15: First branch is HQ** — first branch created has is_hq=True, subsequent have is_hq=False
    - **Property 18: Branch mutations write audit logs** — every update/deactivate/reactivate writes an audit log
    - **Validates: Requirements 2.1, 2.3, 2.5, 3.5, 6.1, 1.4**

- [x] 5. Backend services — Branch billing
  - [x] 5.1 Create `app/modules/billing/branch_billing.py` with billing functions
    - Implement `calculate_branch_cost(base_price, branch_count, interval, discount)` — pure function: base × count × interval_multiplier
    - Implement `preview_branch_addition(db, org_id)` — returns cost preview for adding one branch
    - Implement `sync_stripe_branch_quantity(db, org_id)` — updates Stripe subscription quantity to match active branch count
    - Implement `get_branch_cost_breakdown(db, org_id)` — returns per-branch cost breakdown
    - Handle proration for mid-cycle activations and deactivations
    - Wrap branch creation + Stripe update in a single transaction; rollback on Stripe failure
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.2, 5.3, 5.5, 6.2_

  - [x] 5.2 Write property tests for branch billing (P1, P2, P3, P4, P19)
    - **Property 1: Branch billing formula** — total = base × branches × interval_multiplier
    - **Property 2: Create+deactivate = net zero** — proration cancels out
    - **Property 3: Proration sum consistency** — sum of per-branch prorations = total proration
    - **Property 4: HQ deactivation protection** — HQ branch cannot be deactivated while others exist
    - **Property 19: Stripe failure rollback** — branch not persisted if Stripe fails
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6, 5.5, 6.3, 34.1, 34.2, 34.3, 34.4**

- [x] 6. Backend middleware — BranchContextMiddleware
  - [x] 6.1 Create `app/core/branch_context.py` with BranchContextMiddleware
    - Read `X-Branch-Id` header from request
    - Validate UUID format; return 403 "Invalid branch context" if invalid
    - Validate branch belongs to requesting user's org; return 403 if not
    - Set `request.state.branch_id` to validated UUID or None (if header absent = "All Branches")
    - Register middleware in `app/core/modules.py`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 6.2 Write property test for middleware (P8)
    - **Property 8: Branch context middleware ownership validation** — 403 for invalid UUID or wrong-org branch; None for absent header
    - **Validates: Requirements 9.3, 9.4, 9.5**

- [x] 7. Backend services — Branch-scoped data filtering
  - [x] 7.1 Update list/create service functions to accept optional `branch_id` filter
    - Modify list functions for: invoices, quotes, job_cards, customers, expenses, bookings, purchase_orders, projects
    - When `branch_id` is provided: filter `WHERE branch_id = :branch_id` (for customers also include `branch_id IS NULL` for shared customers)
    - When `branch_id` is None: return all records regardless of branch_id
    - Modify create functions: auto-set `branch_id` from `request.state.branch_id` when present
    - Validate that branch_id references an active branch on create; reject deactivated branches with 400
    - _Requirements: 10.1, 10.2, 10.3, 11.2, 11.3, 11.4, 12.2, 12.3, 12.4, 13.2, 13.3, 14.4, 14.5, 14.6, 23.3, 23.4, 2.2_

  - [x] 7.2 Write property tests for branch-scoped filtering (P6, P7, P9)
    - **Property 6: Branch-scoped data filtering** — query with branch B returns only records with branch_id=B (plus NULL for customers); query without filter returns all
    - **Property 7: New entity branch_id auto-assignment** — creating with branch context sets branch_id; without context sets NULL
    - **Property 9: Deactivated branch blocks new entity creation** — creating with deactivated branch_id is rejected
    - **Validates: Requirements 10.1, 10.2, 10.3, 11.2, 11.3, 11.4, 12.2, 12.3, 12.4, 13.2, 13.3, 14.4, 14.5, 14.6, 2.2**

- [x] 8. Checkpoint — Verify backend services and middleware
  - Ensure all service functions work with the new branch_id filtering
  - Ensure middleware correctly validates X-Branch-Id header
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Backend API endpoints — Branch CRUD and settings
  - [x] 9.1 Add branch CRUD endpoints to `app/modules/organisations/router.py`
    - PUT `/org/branches/{branch_id}` — update branch fields (org_admin)
    - DELETE `/org/branches/{branch_id}` — soft-delete/deactivate (org_admin)
    - POST `/org/branches/{branch_id}/reactivate` — reactivate (org_admin)
    - GET `/org/branches/{branch_id}/settings` — get branch settings (org_admin)
    - PUT `/org/branches/{branch_id}/settings` — update branch settings (org_admin)
    - Add Pydantic schemas: BranchUpdateRequest, BranchSettingsResponse, BranchSettingsUpdateRequest
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.5, 2.6, 3.1, 3.5_

  - [x] 9.2 Add branch billing endpoints to `app/modules/billing/router.py`
    - GET `/billing/branch-cost-preview` — preview cost of adding a branch (org_admin)
    - GET `/billing/branch-cost-breakdown` — per-branch cost breakdown (org_admin)
    - Add Pydantic schemas: BranchCostPreviewResponse, BranchCostBreakdownResponse
    - _Requirements: 4.5, 5.1, 5.2, 6.4_

- [x] 10. Backend API endpoints — Stock transfers
  - [x] 10.1 Create `app/modules/inventory/transfer_service.py` with transfer lifecycle functions
    - `create_transfer(db, org_id, from_branch_id, to_branch_id, stock_item_id, quantity, requested_by)` — validate branches differ, create with status "pending"
    - `approve_transfer(db, org_id, transfer_id, approved_by)` — pending → approved
    - `ship_transfer(db, org_id, transfer_id)` — approved → shipped, deduct quantity from source branch stock
    - `receive_transfer(db, org_id, transfer_id)` — shipped → received, add quantity to destination branch stock
    - `cancel_transfer(db, org_id, transfer_id)` — cancel from pending/approved/shipped; restore stock if shipped
    - All stock mutations in single transaction for consistency
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

  - [x] 10.2 Create `app/modules/inventory/transfer_router.py` with transfer endpoints
    - POST `/inventory/transfers` — create transfer (org_admin, salesperson)
    - GET `/inventory/transfers` — list transfers with branch filtering (org_admin, salesperson)
    - POST `/inventory/transfers/{id}/approve` — approve (org_admin)
    - POST `/inventory/transfers/{id}/ship` — mark shipped (org_admin, salesperson)
    - POST `/inventory/transfers/{id}/receive` — mark received (org_admin, salesperson)
    - POST `/inventory/transfers/{id}/cancel` — cancel (org_admin)
    - Add Pydantic schemas for request/response
    - Register router in `app/core/modules.py`
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

  - [x] 10.3 Write property tests for stock transfers (P5, P21)
    - **Property 5: Stock transfer quantity conservation** — ship decreases source by Q, receive increases dest by Q, cancel restores source
    - **Property 21: Transfer state machine validity** — only valid transitions: pending→approved→shipped→received; cancel from pending/approved/shipped
    - **Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 34.5**

- [x] 11. Backend API endpoints — Staff scheduling
  - [x] 11.1 Create `app/modules/scheduling/service.py` with schedule functions
    - `create_schedule_entry(db, org_id, branch_id, user_id, shift_date, start_time, end_time, notes)` — validate user assigned to branch, validate no overlap, create entry
    - `list_schedule_entries(db, org_id, branch_id=None, date_range=None)` — list with optional branch filter
    - `update_schedule_entry(db, org_id, entry_id, **fields)` — update with re-validation
    - `delete_schedule_entry(db, org_id, entry_id)` — delete entry
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

  - [x] 11.2 Create `app/modules/scheduling/router.py` with schedule endpoints
    - GET `/scheduling` — list schedule entries (org_admin, salesperson)
    - POST `/scheduling` — create entry (org_admin)
    - PUT `/scheduling/{id}` — update entry (org_admin)
    - DELETE `/scheduling/{id}` — delete entry (org_admin)
    - Add Pydantic schemas for request/response
    - Register router in `app/core/modules.py`
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

  - [x] 11.3 Write property tests for scheduling (P11, P12)
    - **Property 11: Schedule overlap rejection** — overlapping time ranges for same user/date rejected with 409
    - **Property 12: Schedule user-branch assignment validation** — user must be assigned to target branch
    - **Validates: Requirements 19.2, 19.5**

- [x] 12. Backend API endpoints — Branch dashboards and reports
  - [x] 12.1 Create `app/modules/organisations/dashboard_service.py` with dashboard functions
    - `get_branch_metrics(db, org_id, branch_id=None)` — revenue, invoice count/value, customer count, staff count, expense breakdown
    - `get_branch_comparison(db, org_id, branch_ids)` — side-by-side metrics for selected branches
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 16.1, 16.2, 16.3, 16.4_

  - [x] 12.2 Add dashboard endpoints to existing dashboard router
    - GET `/dashboard/branch-metrics` — branch-scoped metrics (org_admin, salesperson)
    - GET `/dashboard/branch-comparison` — compare multiple branches (org_admin)
    - _Requirements: 15.1, 15.2, 16.1, 16.2, 16.3_

  - [x] 12.3 Update existing report endpoints to accept optional `branch_id` parameter
    - Revenue report, GST return, outstanding invoices, customer statement — all accept optional branch_id
    - When branch_id provided, scope data to that branch; when absent, return org-wide data
    - _Requirements: 20.1, 20.2, 20.3, 20.4_

  - [x] 12.4 Write property test for aggregated metrics (P16)
    - **Property 16: Aggregated metrics equal sum of per-branch metrics** — org-wide totals = sum of individual branch metrics
    - **Validates: Requirements 15.1, 15.2**

- [x] 13. Backend API endpoints — Global admin branch views
  - [x] 13.1 Add global admin branch endpoints to `app/modules/admin/router.py`
    - GET `/admin/branches` — paginated branch list across all orgs (global_admin)
    - GET `/admin/branches/{id}` — branch detail with users + activity (global_admin)
    - GET `/admin/branch-summary` — platform-wide branch stats (global_admin)
    - GET `/admin/org-branch-revenue` — org table with branch counts + revenue (global_admin)
    - Add Pydantic schemas for response models
    - _Requirements: 7.1, 7.2, 7.3, 21.1, 21.2, 21.3, 21.4_

- [x] 14. Backend services — Branch notifications
  - [x] 14.1 Add branch notification triggers to `app/modules/notifications/service.py`
    - "New branch added" notification to all Org_Admin users on branch creation
    - "Branch deactivated" notification to all Org_Admin users on deactivation
    - "Billing updated" notification with new monthly total on cost changes
    - "Stock transfer request" notification to destination branch users on transfer creation
    - Respect per-branch `notification_preferences` JSON field
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

- [x] 15. Checkpoint — Verify all backend endpoints
  - Ensure all new routers are registered in `app/core/modules.py`
  - Ensure all endpoints return correct response shapes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Frontend — BranchContext provider and API client integration
  - [x] 16.1 Create `frontend/src/contexts/BranchContext.tsx` with BranchContext provider
    - Expose `selectedBranchId` (string | null), `branches` array, `selectBranch(id)`, `isLoading`
    - Read `selected_branch_id` from localStorage on mount
    - Validate stored branch_id against user's `branch_ids` array; reset to null if stale
    - Re-validate on every API response (check user's branch_ids)
    - Persist selection to localStorage on change
    - _Requirements: 8.5, 8.6, 24.1, 24.2, 24.3, 24.4_

  - [x] 16.2 Add X-Branch-Id request interceptor to `frontend/src/api/client.ts`
    - Add axios request interceptor: read `selected_branch_id` from localStorage
    - If value exists and is not "all", set `X-Branch-Id` header
    - If value is null or "all", omit the header
    - _Requirements: 9.1, 9.2_

  - [x] 16.3 Write property test for BranchContext (P17, P20)
    - **Property 17: Stale branch selection reset** — stored branch_id not in user's branch_ids resets to null
    - **Property 20: Branch selector shows exactly user's accessible branches** — selector lists user's branches + "All Branches"
    - **Validates: Requirements 24.2, 24.3, 8.2**

- [x] 17. Frontend — BranchSelector component
  - [x] 17.1 Create `frontend/src/components/branch/BranchSelector.tsx`
    - Dropdown in top navbar listing user's accessible branches + "All Branches" option
    - Pre-select single branch if user has only one; still allow "All Branches"
    - Call `selectBranch(id)` from BranchContext on selection change
    - Use safe API consumption patterns: `?? []` for arrays, `?? 0` for numbers
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 17.2 Integrate BranchSelector into the app layout/navbar
    - Add BranchSelector to the top navigation bar component
    - Wrap app with BranchContext provider
    - _Requirements: 8.1_

- [x] 18. Frontend — Branch CRUD UI enhancements
  - [x] 18.1 Enhance `frontend/src/pages/settings/BranchManagement.tsx`
    - Add "Deactivate" button per branch row with confirmation dialog; call DELETE endpoint
    - Add "Reactivate" button for inactive branches; call POST reactivate endpoint
    - Show error toast when deactivating the only active branch
    - Add billing confirmation dialog on "Add Branch" — show cost impact before creating
    - Call `GET /billing/branch-cost-preview` to populate confirmation dialog amount
    - On confirm: create branch; on cancel: do nothing; on Stripe failure: show error, no branch created
    - Use safe API patterns: `res.data?.branches ?? []`, `res.data?.amount ?? 0`
    - _Requirements: 1.1, 2.1, 2.4, 2.6, 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 18.2 Create `frontend/src/pages/settings/BranchSettings.tsx` for per-branch settings
    - Form for: address, phone, email, logo_url (upload), operating_hours (day-of-week editor), timezone (IANA dropdown)
    - Call GET/PUT `/org/branches/{id}/settings`
    - Validate timezone selection; show error on invalid
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 19. Frontend — Branch-scoped list pages and create forms
  - [x] 19.1 Add "Branch" column to all list pages
    - Update InvoiceList, QuoteList, JobCardList, CustomerList, ExpenseList, BookingList, POList, ProjectList
    - Add a "Branch" column showing branch name (from branch_id lookup)
    - No explicit branch filter needed in frontend — backend filters via X-Branch-Id header
    - _Requirements: 10.4, 10.5_

  - [x] 19.2 Update create forms to auto-set branch_id from BranchContext
    - Invoice, Quote, JobCard, Expense, Booking, PurchaseOrder, Project create forms: read `selectedBranchId` from BranchContext and include in POST payload
    - Customer create form: add "Branch" dropdown defaulting to current context + "Shared across branches" checkbox (sets branch_id to null)
    - _Requirements: 10.3, 11.4, 12.4, 13.4, 13.5, 14.6_

- [x] 20. Checkpoint — Verify frontend branch context and CRUD
  - Ensure BranchSelector renders in navbar and persists selection
  - Ensure X-Branch-Id header is sent on API requests
  - Ensure branch CRUD operations work end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 21. Frontend — Billing integration UI
  - [x] 21.1 Enhance `frontend/src/pages/settings/Billing.tsx` with per-branch cost breakdown
    - Add a "Branch Cost Breakdown" table showing each active branch name, cost, and HQ label
    - Call `GET /billing/branch-cost-breakdown` and render with safe patterns: `res.data?.branches ?? []`
    - Display total subscription amount as sum of per-branch costs
    - _Requirements: 4.5, 6.4_

- [x] 22. Frontend — Stock transfers UI
  - [x] 22.1 Create `frontend/src/pages/inventory/StockTransfers.tsx`
    - List all transfers with columns: date, from branch, to branch, product, quantity, status, requested by
    - "New Transfer" form: source branch, destination branch, product, quantity
    - Action buttons per row: Approve, Mark Shipped, Mark Received, Cancel (based on current status)
    - Use safe API patterns for all response data
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

  - [x] 22.2 Update per-branch stock level views
    - When branch selected: show stock for that branch only
    - When "All Branches": show aggregated stock with per-branch breakdown column
    - Reorder alerts scoped per branch
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5_

- [x] 23. Frontend — Staff scheduling UI
  - [x] 23.1 Create `frontend/src/pages/scheduling/StaffSchedule.tsx`
    - Calendar/table view of schedule entries filtered by branch context
    - "Add Shift" form: user (dropdown of branch-assigned users), date, start time, end time, notes
    - Show overlap error (409) as toast
    - When "All Branches": group entries by branch name
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

- [x] 24. Frontend — Branch dashboards and reports
  - [x] 24.1 Create/enhance dashboard page with branch-scoped metrics
    - When branch selected: show revenue, invoice count/value, customer count, staff count, expense breakdown for that branch
    - When "All Branches": show aggregated metrics with summary table (branch name, revenue, invoice count, customer count, staff count, expenses)
    - Include revenue chart (bar/line) with data points per branch
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [x] 24.2 Add "Compare Branches" view to dashboard
    - Toggle/tab to enter comparison mode
    - Select two or more branches for side-by-side comparison
    - Display comparison charts: revenue, invoice count, customer count, expense totals
    - Highlight highest/lowest performing branch per metric
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [x] 24.3 Update report UI pages to pass branch_id parameter
    - Revenue, GST Return, Outstanding Invoices, Customer Statement report pages
    - Auto-pass `branch_id` from BranchContext when a branch is selected
    - Omit `branch_id` when "All Branches" is selected
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6_

- [x] 25. Frontend — Global admin branch overview
  - [x] 25.1 Create `frontend/src/pages/admin/GlobalBranchOverview.tsx`
    - Paginated table of all branches across all orgs: org name, branch name, status, created date, settings summary
    - Filter by org name and branch status (active/inactive)
    - Click row to show detail panel: branch settings, assigned users, recent activity
    - Summary card: total active branches, total inactive, average branches per org
    - _Requirements: 21.1, 21.2, 21.3, 21.4_

  - [x] 25.2 Enhance `frontend/src/pages/dashboard/GlobalAdminDashboard.tsx` with branch revenue data
    - Add org table with columns: org name, active branch count, total monthly revenue, per-branch average revenue
    - Click org row to show branch list with individual revenue figures
    - Platform-wide summary: total active branches, total branch-related revenue, average branches per org
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 26. Frontend — Branch notifications display
  - [x] 26.1 Integrate branch notification types into existing notification UI
    - Display "New branch added", "Branch deactivated", "Billing updated", "Stock transfer request" notifications
    - Ensure notifications render correctly in the existing notification list/panel
    - _Requirements: 22.1, 22.2, 22.3, 22.5_

- [x] 27. Checkpoint — Verify all frontend pages
  - Ensure all new pages render without errors
  - Ensure branch context filtering works across all list pages
  - Ensure all tests pass, ask the user if questions arise.

- [x] 28. Backend — Booking operating hours validation and invoice branch logo
  - [x] 28.1 Update booking creation to validate against branch operating hours
    - When branch has `operating_hours` configured, validate new bookings fall within the branch's hours for that day
    - Reject bookings outside operating hours with 400
    - _Requirements: 3.4_

  - [x] 28.2 Update invoice PDF renderer to use branch logo
    - When branch has `logo_url`, use it instead of org logo on invoices for that branch
    - When branch has timezone, display timestamps in branch timezone on branch dashboard
    - _Requirements: 3.2, 3.3_

  - [x] 28.3 Write property test for booking operating hours (P13)
    - **Property 13: Booking operating hours validation** — bookings accepted only if entirely within branch operating hours for that day
    - **Validates: Requirements 3.4**

- [x] 29. Wire together — Route registration and navigation
  - [x] 29.1 Register all new backend routers in `app/core/modules.py`
    - Register transfer_router, scheduling router
    - Ensure all new endpoints are accessible
    - _Requirements: all endpoint requirements_

  - [x] 29.2 Add frontend routes and navigation links
    - Add routes for: BranchSettings, StockTransfers, StaffSchedule, GlobalBranchOverview
    - Add sidebar/navigation links for new pages
    - Ensure proper role-based visibility (org_admin vs salesperson vs global_admin)
    - _Requirements: all UI requirements_

- [x] 30. Checkpoint — Full integration verification
  - Ensure all backend endpoints respond correctly
  - Ensure all frontend pages load and interact with backend
  - Ensure branch context flows end-to-end (selector → header → middleware → filtered data)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 31. Property-based tests — remaining properties
  - [x] 31.1 Write property test P6: Branch-scoped data filtering
    - **Property 6: Branch-scoped data filtering** — query with branch B returns only matching records; query without filter returns all
    - **Validates: Requirements 10.1, 10.2, 11.2, 11.3, 12.2, 12.3, 13.2, 13.3, 14.4, 14.5, 23.3, 23.4**

  - [x] 31.2 Write property test P7: New entity branch_id auto-assignment
    - **Property 7: New entity branch_id auto-assignment** — creating with branch context sets branch_id; without sets NULL
    - **Validates: Requirements 10.3, 11.4, 12.4, 14.6**

  - [x] 31.3 Write property test P9: Deactivated branch blocks creation
    - **Property 9: Deactivated branch blocks new entity creation** — rejected with deactivated branch_id
    - **Validates: Requirements 2.2**

  - [x] 31.4 Write property test P16: Aggregated metrics equal sum
    - **Property 16: Aggregated metrics equal sum of per-branch metrics** — org-wide totals = sum of branch metrics
    - **Validates: Requirements 15.1, 15.2**

- [x] 32. API integration tests
  - [x] 32.1 Write API integration tests for branch CRUD endpoints
    - Test create, update, deactivate, reactivate endpoints
    - Test RBAC: org_admin full access, salesperson read-only, unauthorized 403
    - Test edge cases: empty name (400), last branch deactivation (400), HQ deactivation (400)
    - _Requirements: 33.1, 33.7_

  - [x] 32.2 Write API integration tests for X-Branch-Id header validation
    - Test valid branch header → filtered data
    - Test absent header → all branches data
    - Test invalid UUID → 403
    - Test wrong-org branch → 403
    - _Requirements: 33.3_

  - [x] 32.3 Write API integration tests for branch billing
    - Test Stripe subscription quantity updates on branch create/deactivate
    - Test proration calculations
    - Test cost preview and breakdown endpoints
    - _Requirements: 33.2_

  - [x] 32.4 Write API integration tests for stock transfer endpoints
    - Test full lifecycle: create → approve → ship → receive
    - Test cancellation at each stage
    - Verify stock level changes at each step
    - _Requirements: 33.4_

  - [x] 32.5 Write API integration tests for branch-scoped list endpoints
    - Test filtering for invoices, quotes, job_cards, customers, expenses, bookings, purchase_orders, projects
    - Test "All Branches" returns all records including NULL branch_id
    - _Requirements: 33.5_

  - [x] 32.6 Write API integration tests for branch-scoped report endpoints
    - Test revenue, GST, outstanding invoices, customer statement with branch_id parameter
    - _Requirements: 33.6_

- [x] 33. E2E browser tests (Playwright)
  - [x] 33.1 Write E2E tests for branch CRUD user flows
    - Add branch: navigate to Settings > Branches, fill form, create, verify in table
    - Edit branch: click Edit, modify name, update, verify
    - Deactivate: click Deactivate, confirm dialog, verify status
    - Reactivate: click Reactivate on inactive branch, verify status
    - Last branch deactivation error: attempt deactivate only branch, verify error
    - Assign users: click Assign Users, toggle checkboxes, verify persistence on reload
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6_

  - [x] 33.2 Write E2E tests for branch context switching
    - Select branch in selector, verify invoice list filters
    - Select "All Branches", verify all invoices shown
    - Select branch, navigate to different page, verify selection persists
    - Select branch, refresh browser, verify selection restored from localStorage
    - Single-branch user: verify pre-selected
    - Verify selector only shows user's accessible branches
    - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6_

  - [x] 33.3 Write E2E tests for branch billing user flows
    - Create branch: verify billing confirmation dialog with correct amount, confirm, verify created
    - Cancel billing dialog: verify no branch created
    - Billing page: verify per-branch cost breakdown table
    - Create branch then check billing: verify total increased
    - Deactivate branch then check billing: verify total decreased
    - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5_

  - [x] 33.4 Write E2E tests for branch-scoped data creation
    - Select Branch A, create invoice, verify branch_id = Branch A
    - Select Branch A, create quote, verify branch_id = Branch A
    - Select Branch A, create expense, verify branch_id = Branch A
    - Select Branch A, create customer, verify branch_id = Branch A
    - Create customer with "Shared across branches", verify branch_id = NULL
    - Select "All Branches", create invoice, verify branch_id = NULL
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6_

  - [x] 33.5 Write E2E tests for stock transfer user flows
    - Create transfer: fill form, submit, verify "Pending" status
    - Approve: click Approve, verify "Approved" status
    - Ship: click Mark Shipped, verify source stock decreased
    - Receive: click Mark Received, verify destination stock increased
    - Cancel shipped: click Cancel, verify source stock restored
    - Transfer history: verify all transfers listed correctly
    - _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6_

  - [x] 33.6 Write E2E tests for branch dashboard and reports
    - Select branch, view dashboard, verify scoped metrics
    - Select "All Branches", verify aggregated metrics
    - Compare Branches view: select two branches, verify comparison charts
    - Revenue report with branch filter
    - Outstanding invoices report with branch filter
    - GST return report with branch filter
    - _Requirements: 30.1, 30.2, 30.3, 30.4, 30.5, 30.6_

  - [x] 33.7 Write E2E tests for branch settings and notifications
    - Update operating hours, save, verify persistence
    - Upload branch logo, verify stored
    - Set timezone, verify dashboard timestamps
    - Create branch, verify "New branch added" notification
    - Deactivate branch, verify "Branch deactivated" notification
    - Create stock transfer, verify "Stock transfer request" notification
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5, 31.6_

  - [x] 33.8 Write E2E tests for global admin branch views
    - Login as Global_Admin, navigate to branch overview, verify multi-org table
    - Filter by org name, verify results
    - Filter by status, verify results
    - Click branch row, verify detail panel
    - Verify summary card totals
    - _Requirements: 32.1, 32.2, 32.3, 32.4, 32.5_

- [x] 34. Final checkpoint — Ensure all tests pass
  - Ensure all property-based tests pass
  - Ensure all API integration tests pass
  - Ensure all E2E browser tests pass
  - Ensure no regressions in existing test suite
  - Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at logical boundaries
- Property tests validate universal correctness properties from the design document
- All frontend code follows safe API consumption patterns (`.data?.property ?? fallback`)
- Database migrations are backward-compatible — existing records with `branch_id = NULL` remain accessible
- Backend uses Python (FastAPI + SQLAlchemy); Frontend uses TypeScript (React)

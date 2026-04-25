# Implementation Plan: Automotive Dashboard Widgets

## Overview

Transform the existing `OrgAdminDashboard` into a widget-based dashboard for automotive trade organisations. Implementation proceeds backend-first (database → models → schemas → service → router), then frontend (types → hook → components → integration). Each task builds on the previous, with checkpoints to validate incremental progress.

## Tasks

- [x] 1. Database migration for dashboard reminder tables
  - [x] 1.1 Create Alembic migration `0154_create_dashboard_reminder_tables.py` with two new tables
    - `dashboard_reminder_dismissals` table with columns: `id` (UUID PK), `org_id` (FK → organisations), `vehicle_id` (UUID FK), `reminder_type` (VARCHAR, "wof" or "service"), `action` (VARCHAR, "dismissed" or "reminder_sent"), `expiry_date` (DATE), `dismissed_by` (FK → users), `dismissed_at` (TIMESTAMP)
    - Add unique constraint on `(org_id, vehicle_id, reminder_type, expiry_date)`
    - `dashboard_reminder_config` table with columns: `id` (UUID PK), `org_id` (FK → organisations, UNIQUE), `wof_days` (INTEGER DEFAULT 30, CHECK 1–365), `service_days` (INTEGER DEFAULT 30, CHECK 1–365), `updated_by` (FK → users), `updated_at` (TIMESTAMP)
    - Use `IF NOT EXISTS` for idempotency per project conventions
    - _Requirements: 11.4, 11.5, 11.6, 11.7, 12.1, 12.4_

- [x] 2. Backend models and Pydantic schemas
  - [x] 2.1 Create SQLAlchemy models for `DashboardReminderDismissal` and `DashboardReminderConfig` in `app/modules/organisations/models.py`
    - Follow the data model definitions from the design document
    - _Requirements: 11.4, 11.5, 12.1, 12.4_

  - [x] 2.2 Create Pydantic schemas in `app/modules/organisations/schemas.py` for all widget data types
    - Add `RecentCustomerItem`, `TodayBookingItem`, `PublicHolidayItem`, `InventoryCategoryItem`, `CashFlowMonthItem`, `RecentClaimItem`, `ActiveStaffItem`, `ExpiryReminderItem`, `ReminderConfigResponse` response schemas
    - Add `WidgetDataSection[T]` generic wrapper and `DashboardWidgetsResponse` aggregated response
    - Add `ReminderDismissRequest` (vehicle_id, expiry_date, action) and `ReminderConfigUpdate` (wof_days: 1–365, service_days: 1–365) request schemas
    - _Requirements: 4.2, 5.2, 6.2, 7.2, 8.1, 9.2, 10.2, 11.2, 12.1, 12.6, 15.3_

- [x] 3. Backend dashboard service functions
  - [x] 3.1 Implement `get_recent_customers(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `invoices` JOIN `customers`, last 10 by `created_at DESC`, branch-scoped
    - Extract customer_name, invoice_date, vehicle_rego (nullable)
    - _Requirements: 4.1, 4.2, 4.5_

  - [x] 3.2 Implement `get_todays_bookings(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `bookings` where `start_time` is within current calendar date, branch-scoped
    - Sort by `start_time ASC`, return scheduled_time, customer_name, vehicle_rego
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 3.3 Implement `get_public_holidays(db, org_id)` in `dashboard_service.py`
    - Query `public_holidays` where `holiday_date >= today`, filtered by org's country (default "NZ")
    - Limit 5, sort by `holiday_date ASC`
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 3.4 Implement `get_inventory_overview(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `products` / `stock_items`, group by category (tyres, parts, fluids, other)
    - Count total items and items where `stock_quantity <= low_stock_threshold` per category
    - _Requirements: 7.1, 7.2_

  - [x] 3.5 Implement `get_cash_flow(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `invoices` and `expenses` grouped by month for last 6 months
    - Sum `subtotal` for revenue, sum `amount` for expenses per month
    - Return month label (e.g. "Jan 2025"), revenue, expenses
    - _Requirements: 8.1_

  - [x] 3.6 Implement `get_recent_claims(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `customer_claims` JOIN `customers`, last 10 by `created_at DESC`, branch-scoped
    - Return claim reference, customer_name, claim_date, status
    - _Requirements: 9.1, 9.2_

  - [x] 3.7 Implement `get_active_staff(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `time_entries` with `end_time IS NULL` for current date, branch-scoped
    - JOIN users to get staff name and clock_in_time
    - _Requirements: 10.1, 10.2_

  - [x] 3.8 Implement `get_expiry_reminders(db, org_id, branch_id)` in `dashboard_service.py`
    - Query `org_vehicles` + `global_vehicles` JOIN `customer_vehicles` JOIN `customers`
    - Filter where `wof_expiry` or `service_due_date` is within configured threshold days and in the future
    - Exclude vehicles with matching `dashboard_reminder_dismissals` records
    - Sort by expiry_date ASC
    - _Requirements: 11.1, 11.2, 11.3, 11.8_

  - [x] 3.9 Implement `get_reminder_config(db, org_id)` and `update_reminder_config(db, org_id, user_id, wof_days, service_days)` in `dashboard_service.py`
    - Get: return config row or default `{ wof_days: 30, service_days: 30 }`
    - Update: upsert config row with validation (1–365)
    - _Requirements: 12.1, 12.4, 12.5_

  - [x] 3.10 Implement `dismiss_reminder(db, org_id, user_id, vehicle_id, reminder_type, expiry_date, action)` in `dashboard_service.py`
    - Create `dashboard_reminder_dismissals` record
    - Idempotent: if dismissal already exists for (org_id, vehicle_id, reminder_type, expiry_date), return existing record
    - _Requirements: 11.4, 11.5, 11.6, 11.7_

  - [x] 3.11 Implement `get_all_widget_data(db, org_id, branch_id)` aggregator function in `dashboard_service.py`
    - Call all individual widget query functions
    - Catch exceptions per-widget: if one fails, return `{ items: [], total: 0 }` for that section, log error
    - Return `DashboardWidgetsResponse` shape
    - _Requirements: 15.5_

- [x] 4. Backend dashboard router endpoints
  - [x] 4.1 Add `GET /widgets` endpoint to `dashboard_router.py`
    - Call `get_all_widget_data()`, return `DashboardWidgetsResponse`
    - Require `org_admin` role, scope by org_id and branch_id from request state
    - _Requirements: 4.1, 5.1, 6.1, 7.1, 8.1, 9.1, 10.1, 11.1, 12.1, 15.3_

  - [x] 4.2 Add `POST /reminders/{reminder_type}/dismiss` endpoint to `dashboard_router.py`
    - Accept `ReminderDismissRequest` body, validate `reminder_type` is "wof" or "service"
    - Call `dismiss_reminder()` service function
    - Return 200 with dismissal record
    - _Requirements: 11.4, 11.5, 11.6, 11.7_

  - [x] 4.3 Add `GET /reminder-config` and `PUT /reminder-config` endpoints to `dashboard_router.py`
    - GET: return current config or defaults
    - PUT: accept `ReminderConfigUpdate`, validate, persist, return updated config
    - Require `org_admin` role
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6_

- [x] 5. Checkpoint — Backend complete
  - Run `alembic upgrade head` to verify migration applies cleanly
  - Run existing backend tests to ensure no regressions
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Backend property-based tests (Hypothesis)
  - [x] 6.1 Write property test for recent list bounded order
    - **Property 5: Recent List Endpoints Return Bounded Ordered Results**
    - Generate random invoice/claim lists, verify query returns ≤10 items in date-descending order
    - **Validates: Requirements 4.1, 9.1**

  - [x] 6.2 Write property test for today's bookings filter
    - **Property 6: Today's Bookings Filter**
    - Generate random booking sets with various dates, verify only today's bookings returned in ascending time order
    - **Validates: Requirements 5.1, 5.3**

  - [x] 6.3 Write property test for public holidays filter
    - **Property 7: Public Holidays Country and Date Filter**
    - Generate random holiday sets with various countries/dates, verify correct country filter, future-only, limit 5, ascending order
    - **Validates: Requirements 6.1, 6.3**

  - [x] 6.4 Write property test for inventory category grouping
    - **Property 8: Inventory Category Grouping Correctness**
    - Generate random product sets with categories and stock levels, verify total_count and low_stock_count per category
    - **Validates: Requirements 7.1, 7.2**

  - [x] 6.5 Write property test for cash flow monthly aggregation
    - **Property 9: Cash Flow Monthly Aggregation**
    - Generate random invoice/expense sets over 6 months, verify monthly revenue and expense sums
    - **Validates: Requirements 8.1**

  - [x] 6.6 Write property test for active staff filter
    - **Property 10: Active Staff Returns Only Clocked-In Staff**
    - Generate random time entries (open/closed), verify only staff with `end_time IS NULL` for today are returned
    - **Validates: Requirements 10.1**

  - [x] 6.7 Write property test for expiry reminders filter
    - **Property 11: Expiry Reminders Exclude Dismissed and Filter by Threshold**
    - Generate random vehicles + dismissals + threshold days, verify correct filtering
    - **Validates: Requirements 11.1, 11.8**

  - [x] 6.8 Write property test for reminder config validation range
    - **Property 12: Reminder Config Validation Range**
    - Generate random integers, verify acceptance only for 1–365 inclusive
    - **Validates: Requirements 12.6**

- [x] 7. Install frontend dependencies and create TypeScript types
  - [x] 7.1 Install `@dnd-kit/core`, `@dnd-kit/sortable`, and `recharts` as frontend dependencies
    - Run `npm install @dnd-kit/core @dnd-kit/sortable recharts` in the `frontend/` directory
    - _Requirements: 3.1, 8.1_

  - [x] 7.2 Create `frontend/src/pages/dashboard/widgets/types.ts` with all TypeScript interfaces
    - Define `RecentCustomer`, `TodayBooking`, `PublicHoliday`, `InventoryCategory`, `CashFlowMonth`, `RecentClaim`, `ActiveStaffMember`, `ExpiryReminder`, `ReminderConfig` interfaces
    - Define `WidgetDataSection<T>`, `DashboardWidgetData`, `WidgetDefinition`, `WidgetComponentProps`, `WidgetCardProps` interfaces
    - Field names must match backend Pydantic schemas exactly
    - _Requirements: 15.3_

- [x] 8. Frontend data hook and presentational components
  - [x] 8.1 Create `frontend/src/pages/dashboard/widgets/useDashboardWidgets.ts` hook
    - Fetch `GET /api/v1/dashboard/widgets` with typed generic `DashboardWidgetData`
    - Use `AbortController` cleanup in `useEffect`
    - Apply `?.` and `?? []` / `?? 0` on all response fields
    - Return `{ data, isLoading, error, refetch }`
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [x] 8.2 Create `frontend/src/pages/dashboard/widgets/WidgetCard.tsx` presentational component
    - Render card with `rounded-lg border border-gray-200 bg-white` styling
    - Header section with icon, title, and optional action link
    - Loading spinner overlay when `isLoading` is true
    - Error message display when `error` is set
    - Children slot for widget content
    - _Requirements: 14.1, 14.2, 14.3, 15.5_

- [x] 9. Frontend individual widget components
  - [x] 9.1 Create `RecentCustomersWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display 10 most recent customers with name, invoice date, vehicle rego (nullable)
    - Each entry clickable → navigate to customer profile
    - Empty state: "No recent customers"
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 9.2 Create `TodaysBookingsWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display today's bookings sorted by time ascending with time, customer name, vehicle rego
    - Each entry clickable → navigate to booking detail
    - Empty state: "No bookings for today"
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 9.3 Create `PublicHolidaysWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display next 5 upcoming holidays with name and date
    - Sorted by date ascending
    - Empty state: "No upcoming public holidays"
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 9.4 Create `InventoryOverviewWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display summary boxes per category (tyres, parts, fluids, other) with total count and low-stock count
    - Highlight low-stock count in amber/red warning colour
    - Each category clickable → navigate to inventory page filtered by category
    - Empty state: "No inventory items"
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.6_

  - [x] 9.5 Create `CashFlowChartWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Render bar chart using `recharts` with monthly revenue (green) and expenses (red) for last 6 months
    - X-axis: month names, Y-axis: NZD currency values
    - Tooltip on hover showing exact amounts
    - Empty state: "No financial data available"
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 9.6 Create `RecentClaimsWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display 10 most recent claims with reference, customer name, date, colour-coded status badge
    - Status colours: green (resolved), amber (investigating/approved), red (rejected), grey (open)
    - Each entry clickable → navigate to claim detail
    - Empty state: "No recent claims"
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6_

  - [x] 9.7 Create `ActiveStaffWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display list of clocked-in staff with name and clock-in time
    - Header summary showing total count of active staff
    - Empty state: "No staff currently clocked in"
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 9.8 Create `ExpiryRemindersWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display vehicles with upcoming WOF/service expiry: rego, make/model, expiry type, date, customer name
    - Sorted by expiry date ascending
    - "Mark Reminder Sent" button → POST dismiss with action "mark_sent", show "Sent" badge
    - "Dismiss" button → POST dismiss with action "dismiss", remove from list
    - Empty state: "No upcoming WOF or service expiries"
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.10_

  - [x] 9.9 Create `ReminderConfigWidget.tsx` in `frontend/src/pages/dashboard/widgets/`
    - Display current WOF and service reminder thresholds in days
    - Editable number inputs for each threshold
    - Save button → PUT `/dashboard/reminder-config`
    - Validate 1–365 range on client side before submit
    - Default to 30 days if no config exists
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [x] 10. Frontend WidgetGrid with drag-and-drop
  - [x] 10.1 Create `frontend/src/pages/dashboard/widgets/WidgetGrid.tsx`
    - Define `WIDGET_DEFINITIONS` array with all 9 widgets, their IDs, titles, icons, module gates, and default order
    - Filter visible widgets by module availability using `useModules().isEnabled()`
    - Read/write layout order from `localStorage` key `dashboard_layout_{userId}`
    - If no saved layout, use default order; if saved widget no longer available, remove from layout without gaps
    - Wrap each widget in `@dnd-kit/sortable` `SortableItem`
    - Apply CSS grid: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4`
    - Pass each widget its data slice from `useDashboardWidgets()` hook
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 13.1, 13.2, 13.3, 13.4_

- [x] 11. Integrate WidgetGrid into OrgAdminDashboard
  - [x] 11.1 Modify `frontend/src/pages/dashboard/OrgAdminDashboard.tsx`
    - Import `useTenant` and derive `isAutomotive` using `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'`
    - When `isAutomotive` is true, render `<WidgetGrid>` below the existing KPI cards and branch metrics
    - When `isAutomotive` is false, render only the existing generic dashboard content (no changes)
    - Pass `userId` and `branchId` props to `WidgetGrid`
    - Wrap module-gated widgets: `inventory` → InventoryOverview, `claims` → RecentClaims, `bookings` → TodaysBookings, `vehicles` → ExpiryReminders + ReminderConfig
    - Ungated widgets always visible: RecentCustomers, PublicHolidays, CashFlowChart, ActiveStaff
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 12. Checkpoint — Frontend integration complete
  - Run `npm run build` in `frontend/` to verify TypeScript compilation and build succeeds
  - Run `npm run test` in `frontend/` to verify no regressions in existing tests
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Frontend property-based tests (fast-check)
  - [x] 13.1 Write property test for trade family derivation
    - **Property 1: Trade Family Derivation**
    - File: `frontend/src/pages/dashboard/widgets/__tests__/tradeFamily.property.test.ts`
    - Generate random strings + null, verify `isAutomotive` is true iff `(tradeFamily ?? 'automotive-transport') === 'automotive-transport'`
    - **Validates: Requirements 1.1, 1.4**

  - [x] 13.2 Write property test for module gating widget visibility
    - **Property 2: Module Gating Determines Widget Visibility**
    - File: `frontend/src/pages/dashboard/widgets/__tests__/moduleGating.property.test.ts`
    - Generate random boolean combos for 4 module slugs, verify visible widget set matches expected union of ungated + enabled-gated widgets
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7**

  - [x] 13.3 Write property test for layout persistence round-trip
    - **Property 3: Layout Persistence Round-Trip**
    - File: `frontend/src/pages/dashboard/widgets/__tests__/layoutPersistence.property.test.ts`
    - Generate random widget ID arrays + user IDs, verify save then load returns identical order
    - **Validates: Requirements 3.2, 3.3**

  - [x] 13.4 Write property test for stale widget filtering
    - **Property 4: Stale Widget Filtering Preserves Available Widget Order**
    - File: `frontend/src/pages/dashboard/widgets/__tests__/layoutPersistence.property.test.ts`
    - Generate random saved orders + available sets, verify filtered result contains only available IDs in preserved relative order with new widgets appended
    - **Validates: Requirements 3.5**

  - [x] 13.5 Write property test for reminder config validation
    - **Property 12: Reminder Config Validation Range**
    - File: `frontend/src/pages/dashboard/widgets/__tests__/reminderConfig.property.test.ts`
    - Generate random integers, verify client-side validation accepts only 1–365 inclusive
    - **Validates: Requirements 12.6**

- [x] 14. Unit tests for widget components
  - [x] 14.1 Write unit tests for WidgetCard component
    - Test: renders header with icon, title, action link
    - Test: shows loading spinner when `isLoading=true`
    - Test: shows error message when `error` is set
    - File: `frontend/src/pages/dashboard/widgets/__tests__/WidgetCard.test.tsx`
    - _Requirements: 14.1, 14.2, 15.5_

  - [x] 14.2 Write unit tests for trade-family gating in OrgAdminDashboard
    - Test: renders WidgetGrid when `isAutomotive=true`
    - Test: hides WidgetGrid when `isAutomotive=false`
    - File: `frontend/src/pages/dashboard/__tests__/OrgAdminDashboard.test.tsx`
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 14.3 Write unit tests for empty states across all widgets
    - Test each widget renders correct empty state message when data array is empty
    - RecentCustomers: "No recent customers", TodaysBookings: "No bookings for today", PublicHolidays: "No upcoming public holidays", InventoryOverview: "No inventory items", CashFlowChart: "No financial data available", RecentClaims: "No recent claims", ActiveStaff: "No staff currently clocked in", ExpiryReminders: "No upcoming WOF or service expiries"
    - File: `frontend/src/pages/dashboard/widgets/__tests__/widgetEmptyStates.test.tsx`
    - _Requirements: 4.4, 5.5, 6.4, 7.6, 8.5, 9.6, 10.4, 11.10_

  - [x] 14.4 Write unit tests for claim status badge colours and inventory low-stock warning
    - Test: RecentClaimsWidget uses green for resolved, amber for investigating, red for rejected, grey for open
    - Test: InventoryOverviewWidget highlights low-stock count in warning colour
    - File: `frontend/src/pages/dashboard/widgets/__tests__/widgetStyling.test.tsx`
    - _Requirements: 9.3, 7.3, 14.4_

  - [x] 14.5 Write unit tests for default layout order and localStorage persistence
    - Test: WidgetGrid uses default order when no localStorage entry exists
    - Test: WidgetGrid reads saved order from localStorage on mount
    - File: `frontend/src/pages/dashboard/widgets/__tests__/WidgetGrid.test.tsx`
    - _Requirements: 3.2, 3.3, 3.4_

- [x] 15. Final checkpoint — All tests pass
  - Run `npm run test` in `frontend/` to verify all frontend tests pass
  - Run `pytest tests/test_dashboard_widgets.py -v` to verify all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Backend tasks (1–6) should be completed before frontend tasks (7–14)
- The migration number `0154` follows the current head at `0153`
- `fast-check` is already in `devDependencies`; `Hypothesis` is already in the project
- `@dnd-kit/core`, `@dnd-kit/sortable`, and `recharts` are new frontend dependencies (task 7.1)
- All frontend code must follow safe API consumption patterns (optional chaining, nullish coalescing, AbortController cleanup, typed generics)
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples, edge cases, and visual styling

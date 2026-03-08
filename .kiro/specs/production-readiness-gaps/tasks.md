# Implementation Plan: Production Readiness Gaps

## Overview

Replace all ~30 placeholder components in ModuleRouter.tsx with real, lazy-loaded React/TypeScript page components that consume existing backend APIs. Integrate FeatureFlagContext, ModuleContext, and TerminologyContext into every page. Add property-based tests (fast-check), unit tests, and integration tests. Ensure mobile/tablet responsiveness. Backend is 95% complete — work is primarily frontend.

## Tasks

- [x] 1. Shared infrastructure and cross-cutting foundations
  - [x] 1.1 Create `useModuleGuard` hook and `ModulePageWrapper` component
    - Implement `useModuleGuard(moduleSlug)` hook that checks `ModuleContext.enabledModules`, redirects to `/dashboard` with toast if disabled
    - Implement `ModulePageWrapper` combining module guard, `FeatureGate`, error boundary, and `Suspense`
    - Implement `ErrorBoundaryWithRetry` that catches `ChunkLoadError` and renders retry button
    - _Requirements: 17.1, 17.5, 17.6, 16.4_

  - [x] 1.2 Write property tests for module guard and terminology fallback
    - **Property 33: Module guard prevents rendering of disabled modules**
    - **Property 34: Terminology substitution with fallback**
    - **Validates: Requirements 17.1, 17.3, 17.4, 17.6**

  - [x] 1.3 Add responsive layout CSS utilities
    - Add media query breakpoints: phone (<767px), tablet (768-1024px), desktop (>1025px)
    - Add CSS utility classes for responsive grids, stacked layouts, and 44×44px minimum touch targets
    - Ensure all form inputs use correct mobile input types (`type="tel"`, `type="email"`, `inputmode="numeric"`)
    - _Requirements: 19.1, 19.2, 19.6, 19.7_

  - [x] 1.4 Write property test for form input mobile types
    - **Property 36: Form inputs use correct mobile input types**
    - **Validates: Requirements 19.7**

- [x] 2. Router placeholder replacement and dead-link elimination
  - [x] 2.1 Replace all placeholder components in ModuleRouter.tsx with `React.lazy` imports
    - Replace all ~30 module placeholders (KitchenPlaceholder, FranchisePlaceholder, ConstructionPlaceholder, FloorPlanPlaceholder, LoyaltyPlaceholder, etc.) with `React.lazy(() => import(...))` pointing to real page components
    - Replace core route placeholders (DashboardPlaceholder, InvoicesPlaceholder, CustomersPlaceholder, SettingsPlaceholder, ReportsPlaceholder, NotificationsPlaceholder, DataPlaceholder)
    - Wrap all lazy routes in `Suspense` with loading fallback and `ErrorBoundaryWithRetry`
    - Preserve existing `FlagGatedRoute` behaviour
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_

  - [x] 2.2 Write property tests for route resolution and disabled module redirect
    - **Property 31: All routes resolve to functional components**
    - **Property 32: Disabled module routes redirect to dashboard**
    - **Validates: Requirements 16.1, 16.3, 16.5, 16.6, 20.4**

  - [x] 2.3 Update sidebar navigation to hide disabled modules and flags
    - Ensure sidebar dynamically shows/hides menu items based on `ModuleContext` and `FeatureFlagContext`
    - Add "Feature not available" page for direct URL access to disabled modules
    - Ensure browser back button works correctly after redirect (no redirect loops)
    - Add development-mode console logging for remaining placeholders
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6_

  - [x] 2.4 Write property test for sidebar visibility
    - **Property 35: Sidebar visibility matches module and flag state**
    - **Validates: Requirements 20.3**

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Kitchen Display System frontend (CRITICAL)
  - [x] 4.1 Enhance KitchenDisplay.tsx with full functionality
    - Add WebSocket reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s) and "Connection Lost" banner
    - Add "Ready" column for prepared items with `PUT /api/v2/kitchen/orders/{id}/status` on tap
    - Add full-screen mode toggle with minimum 18px body / 24px heading text
    - Add station filtering via station selector calling `GET /api/v2/kitchen/orders` with station param
    - Add order urgency colour coding (white → amber at threshold → red at 2× threshold)
    - Integrate `TerminologyContext` and `FeatureFlagContext`
    - Optimise for landscape tablet with large touch targets
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 4.2 Write property tests for Kitchen Display
    - **Property 1: Kitchen order urgency level is deterministic**
    - **Property 2: Station filtering returns only matching orders**
    - **Property 3: WebSocket reconnection follows exponential backoff**
    - **Validates: Requirements 1.4, 1.6, 1.7**

- [x] 5. Franchise Management frontend (CRITICAL)
  - [x] 5.1 Enhance LocationList.tsx, FranchiseDashboard.tsx, and StockTransfers.tsx
    - Add location CRUD (add, edit, deactivate) to LocationList calling `GET/POST /api/v2/locations`
    - Add per-location performance comparison charts to FranchiseDashboard calling `GET /api/v2/franchise/dashboard`
    - Add stock transfer creation form and history list to StockTransfers calling `POST/GET /api/v2/stock-transfers`
    - Add RBAC-scoped data filtering for Location_Manager role
    - Add per-location filtering on all data views and combined org-level view for Org_Admin
    - Integrate `ModuleContext`, `FeatureFlagContext`, and `TerminologyContext`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 5.2 Write property test for RBAC location scoping
    - **Property 4: Location data is RBAC-scoped for Location_Manager**
    - **Validates: Requirements 2.6, 2.7**

- [x] 6. Construction frontend — Progress Claims (CRITICAL)
  - [x] 6.1 Enhance ProgressClaimList.tsx and add Progress Claim Form
    - Add Progress Claim List page calling `GET /api/v2/progress-claims`
    - Add Progress Claim Form page calling `POST /api/v2/progress-claims` with auto-calculated fields
    - Add real-time validation (cumulative cannot exceed revised contract value)
    - Add PDF generation button calling progress claim PDF endpoint
    - Add status change without full page reload
    - Integrate `TerminologyContext` for construction labels
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 6.2 Write property tests for Progress Claims
    - **Property 5: Progress claim calculations are correct**
    - **Property 6: Cumulative claimed cannot exceed revised contract value**
    - **Validates: Requirements 3.4, 3.5**

- [x] 7. Construction frontend — Variations (CRITICAL)
  - [x] 7.1 Enhance VariationList.tsx and VariationForm.tsx
    - Add variation register per project with cumulative impact display
    - Add PDF generation for variation orders
    - Prevent editing/deletion of approved variations with user guidance message
    - Display updated revised contract value after approval
    - Integrate `TerminologyContext`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 7.2 Write property tests for Variations
    - **Property 7: Approved variation updates revised contract value**
    - **Property 8: Approved variations are immutable**
    - **Validates: Requirements 4.4, 4.6**

- [x] 8. Construction frontend — Retentions (CRITICAL)
  - [x] 8.1 Enhance RetentionSummary.tsx with release workflow
    - Add per-project retention data display (total retained, released, outstanding, percentage)
    - Add retention release workflow calling `POST /api/v2/retentions/{id}/release`
    - Add validation (release cannot exceed outstanding balance)
    - Display retention alongside progress claim info on project dashboard
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 8.2 Write property test for Retentions
    - **Property 9: Retention release cannot exceed outstanding balance**
    - **Validates: Requirements 5.5**

- [x] 9. Webhook Management frontend (CRITICAL)
  - [x] 9.1 Enhance WebhookManagement.tsx with full CRUD and monitoring
    - Add webhook creation/editing form with HTTPS URL validation
    - Add "Test Webhook" button with response display modal calling `POST /api/v2/outbound-webhooks/{id}/test`
    - Add delivery log view per webhook calling `GET /api/v2/outbound-webhooks/{id}/deliveries`
    - Add visual status indicators (green/amber/red) based on delivery status and failure count
    - Add auto-disable warning with re-enable button
    - Integrate `FeatureFlagContext` and `ModuleContext`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 9.2 Write property tests for Webhooks
    - **Property 10: Webhook URL must be HTTPS**
    - **Property 11: Webhook health status indicator is deterministic**
    - **Validates: Requirements 6.3, 6.6, 6.7**

- [x] 10. Checkpoint — Ensure all critical priority tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Time Tracking V2 frontend (HIGH)
  - [x] 11.1 Enhance TimeSheet.tsx and HeaderTimer.tsx with V2 features
    - Add project/task selection before starting timer
    - Add task switching without stopping timer (automatic split entries)
    - Add project-based time reporting view (total hours, billable vs non-billable, cost analysis)
    - Add weekly timesheet grid (project × day with row/column totals)
    - Add "Convert to Invoice" action on billable entries (marks converted as "invoiced")
    - Add overlap validation in real-time
    - Add time entry panel on Job Detail page
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 11.2 Write property tests for Time Tracking
    - **Property 12: Time entry overlap detection**
    - **Property 13: Time entry aggregation is correct**
    - **Property 14: Invoiced time entries cannot be double-billed**
    - **Validates: Requirements 7.3, 7.4, 7.5, 7.6**

- [x] 12. Jobs V2 frontend (HIGH)
  - [x] 12.1 Enhance JobBoard.tsx, JobList.tsx, and JobDetail.tsx with V2 features
    - Add project hierarchy view with expandable/collapsible nodes
    - Add drag-and-drop Kanban with status transition validation
    - Add resource allocation timeline view with conflict highlighting
    - Add job profitability panel on Job Detail (revenue, costs, margin)
    - Add "Convert to Invoice" button on completed jobs
    - Add job template selection dropdown on creation
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 12.2 Write property tests for Jobs V2
    - **Property 15: Job status transitions are validated**
    - **Property 16: Job profitability calculation is correct**
    - **Validates: Requirements 8.3, 8.5**

- [x] 13. Enhanced Inventory frontend (HIGH)
  - [x] 13.1 Enhance inventory pages with pricing rules and advanced stock management
    - Add Pricing Rules management page calling pricing rules API
    - Add pricing rule creation form with overlap validation warning
    - Add advanced stock adjustment workflow with reasons and batch support
    - Add low-stock dashboard with one-click "Create Purchase Order" action
    - Add supplier catalogue integration view
    - Integrate barcode scanning via `barcodeScanner.ts` on stock take and product lookup
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [x] 13.2 Write property tests for Inventory
    - **Property 17: Pricing rule overlap detection**
    - **Property 18: Low stock threshold filtering**
    - **Validates: Requirements 9.4, 9.6**

- [x] 14. Loyalty Program frontend (HIGH)
  - [x] 14.1 Enhance LoyaltyConfig.tsx with full loyalty management
    - Add points earning/redemption rate configuration
    - Add membership tier management with ascending threshold validation
    - Add customer loyalty view on customer detail page (points, tier, history)
    - Add Loyalty Analytics dashboard (active members, points issued/redeemed, top customers)
    - Add manual points adjustment interface with required reason field
    - Integrate `ModuleContext` and `FeatureFlagContext`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 14.2 Write property tests for Loyalty
    - **Property 19: Loyalty tier thresholds are strictly ascending**
    - **Property 20: Loyalty points to next tier calculation**
    - **Property 21: Loyalty points adjustment requires reason**
    - **Validates: Requirements 10.3, 10.4, 10.6**

- [x] 15. Checkpoint — Ensure all high priority tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Feature Flag Management frontend (MEDIUM)
  - [x] 16.1 Build org-level feature flags page
    - Add feature flags page in org settings calling `GET /api/v2/flags`
    - Group flags by category with expandable sections and descriptions
    - Display inheritance source (trade category, plan tier, rollout) per flag
    - Add org-level toggle where `can_override === true`, disabled state otherwise
    - Add Global_Admin rollout monitoring view (adoption %, trends, error rates)
    - Integrate `FeatureFlagContext` and `ModuleContext`
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [x] 16.2 Write property tests for Feature Flags
    - **Property 22: Feature flag override respects can_override**
    - **Property 23: Feature flags grouped by category with required fields**
    - **Validates: Requirements 11.2, 11.3, 11.4**

- [x] 17. Module Management frontend (MEDIUM)
  - [x] 17.1 Build module configuration page
    - Add Module Configuration page in org settings with enable/disable toggles
    - Display dependency and dependent module lists per module
    - Add cascade disable confirmation dialog listing affected dependents
    - Add auto-enable dependencies notification
    - Add "coming soon" badge on non-selectable modules
    - Add visual dependency graph
    - Update `ModuleContext` on toggle for immediate route reflection
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [x] 17.2 Write property tests for Module Management
    - **Property 24: Module disable cascades to dependents**
    - **Property 25: Module enable auto-enables dependencies**
    - **Property 26: Coming soon modules are non-selectable**
    - **Validates: Requirements 12.3, 12.4, 12.5**

- [x] 18. Multi-Currency frontend (MEDIUM)
  - [x] 18.1 Build currency settings and exchange rate management pages
    - Add Currency Settings page showing base currency and enabled currencies
    - Add currency enablement from ISO 4217 list with search
    - Add exchange rate management with manual entry and rate source display
    - Add historical rate charts (7d, 30d, 90d, 1y)
    - Add rate provider configuration section
    - Add warning indicator and invoice creation block when rate is missing
    - Format all amounts per currency's ISO standard (decimal places, separator, symbol)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

  - [x] 18.2 Write property tests for Multi-Currency
    - **Property 27: Currency amount formatting follows ISO standard**
    - **Property 28: Missing exchange rate blocks invoice creation**
    - **Validates: Requirements 13.6, 13.7**

- [x] 19. Table Management frontend (MEDIUM)
  - [x] 19.1 Enhance FloorPlan.tsx and ReservationList.tsx
    - Add drag-and-drop floor plan editor (place, resize, move, label tables)
    - Add real-time table status colour coding (Available=green, Occupied=amber, Reserved=blue, Needs Cleaning=red)
    - Add POS integration on table tap (open/create order)
    - Add reservation timeline view and creation form
    - Add table merge/split functionality with visual feedback
    - Add calendar view for reservations with date/status filtering
    - Support touch gestures: pinch-to-zoom, tap, long-press
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [x] 19.2 Write property test for Table Management
    - **Property 29: Table status colour coding is deterministic**
    - **Validates: Requirements 14.2**

- [x] 20. Tipping Management frontend (MEDIUM)
  - [x] 20.1 Enhance TipPrompt.tsx and add tip management pages
    - Add Tip Distribution Rules page (equal split, percentage-based, role-based)
    - Add Staff Tip Allocation management page with distribution preview
    - Add Tip Analytics dashboard (daily/weekly/monthly totals, averages, trends)
    - Display tip info on POS transaction summary and invoice detail
    - Integrate `ModuleContext` and `TerminologyContext`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

  - [x] 20.2 Write property test for Tipping
    - **Property 30: Tip distribution allocation is correct**
    - **Validates: Requirements 15.3**

- [x] 21. Checkpoint — Ensure all medium priority tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 22. Integration tests
  - [x] 22.1 Write frontend integration tests with React Testing Library
    - Test ModuleRouter renders correct components for enabled modules
    - Test ModuleRouter redirects for disabled modules
    - Test FeatureFlagContext correctly gates sub-features
    - Test TerminologyContext correctly substitutes labels
    - _Requirements: 18.4_

  - [x] 22.2 Write backend integration tests for critical workflows
    - POS transaction flow: product selection → order → payment → inventory decrement → receipt
    - Job-to-invoice flow: job creation → time entry → expense → completion → invoice conversion
    - Construction flow: project → variation approval → progress claim → retention release
    - Multi-currency flow: currency enable → rate config → foreign invoice → payment with exchange difference
    - Onboarding flow: signup → setup wizard → first invoice with terminology
    - Franchise flow: location creation → stock transfer → per-location reporting → aggregate dashboard
    - _Requirements: 18.1, 18.2, 18.3, 18.5, 18.6_

- [x] 23. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use fast-check (TypeScript/frontend) and Hypothesis (Python/backend)
- All property tests run minimum 100 iterations
- Backend is 95% complete — no backend changes needed, work is frontend-only
- Existing patterns in KitchenDisplay.tsx, FranchiseDashboard.tsx, ProgressClaimList.tsx should be followed

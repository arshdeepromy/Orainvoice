# Implementation Plan: OraInvoice Mobile App

## Overview

This plan implements the OraInvoice Mobile App — a React + TypeScript + Vite + Tailwind CSS + Capacitor mobile-first web application served from a separate Docker container. Tasks are ordered by dependency: infrastructure first, then shared types, core framework, UI component library, auth screens, and progressively through all ~75 screens. Property-based tests are placed alongside the features they validate.

## Tasks

- [x] 1. Set up mobile app project structure and infrastructure
  - [x] 1.1 Create `mobile/` directory with `package.json`, `tsconfig.json`, `vite.config.ts`, `postcss.config.js`, `tailwind.config.js`, and `index.html`
    - `package.json` mirrors frontend dependencies plus Capacitor packages (`@capacitor/core`, `@capacitor/cli`, `@capacitor/camera`, `@capacitor/push-notifications`, `@capacitor/browser`, `@capacitor/share`, `@capacitor/preferences`, `@capacitor/app`, `@capacitor/haptics`, `@capacitor/network`, `capacitor-native-biometric`)
    - `vite.config.ts` with base path `/mobile/`, React plugin, path alias `@` → `./src`, and HMR config matching frontend pattern
    - `tailwind.config.js` scanning `./src/**/*.{ts,tsx}` with dark mode `class` strategy
    - `tsconfig.json` extending shared config with path aliases for `@/` and `@shared/`
    - _Requirements: 14.2, 14.5_
  - [x] 1.2 Create `mobile/Dockerfile` and update `docker-compose.yml` with mobile service and `mobile_dist` volume
    - Dockerfile: `node:20-alpine`, install deps, `vite build`, keep-alive CMD (same pattern as frontend)
    - Add `mobile` service to `docker-compose.yml` with `mobile_dist` volume mount
    - Add `mobile_dist` to nginx volumes as `/usr/share/nginx/mobile:ro`
    - _Requirements: 14.1_
  - [x] 1.3 Update `nginx/nginx.conf` with `/mobile/` and `/mobile/assets/` location blocks
    - `/mobile/assets/` with `expires 1y` and `Cache-Control: public, immutable`
    - `/mobile/` with `try_files $uri $uri/ /mobile/index.html` for SPA routing
    - _Requirements: 14.1, 14.4_
  - [x] 1.4 Create `mobile/capacitor.config.ts` with app ID, web dir, and plugin configuration
    - App ID: `nz.co.oraflows.invoice`, app name: `OraInvoice`, webDir: `dist`
    - Plugin configs for PushNotifications, Camera, BiometricAuth
    - _Requirements: 14.3_
  - [x] 1.5 Create `shared/types/` directory with barrel exports for all API type interfaces
    - Create `shared/types/index.ts`, `api.ts` (PaginatedResponse), `auth.ts`, `customer.ts`, `invoice.ts`, `quote.ts`, `job.ts`, `inventory.ts`, `staff.ts`, `expense.ts`, `booking.ts`, `vehicle.ts`, `accounting.ts`, `compliance.ts`, `module.ts`, `branch.ts`, `report.ts`, `notification.ts`
    - Update both `frontend/tsconfig.json` and `mobile/tsconfig.json` with `@shared/` path alias
    - _Requirements: 14.5_

- [x] 2. Implement core app shell, providers, and API client
  - [x] 2.1 Create `mobile/src/main.tsx` entry point and `mobile/src/index.css` with Tailwind imports and mobile base styles
    - Import Tailwind directives, set `html { touch-action: manipulation }`, safe area insets, 44px minimum touch targets
    - _Requirements: 1.3, 1.4_
  - [x] 2.2 Create `mobile/src/api/client.ts` — Axios API client with JWT Bearer injection, `X-Branch-Id` header, 401 refresh interceptor, and `withCredentials: true`
    - Base URL `/api/v1`, Content-Type JSON
    - Request interceptor: inject Bearer token from AuthContext, inject X-Branch-Id from BranchContext
    - Response interceptor: on 401, attempt token refresh, retry original request; on refresh failure, redirect to login
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_
  - [x] 2.3 Create context providers: `AuthContext.tsx`, `TenantContext.tsx`, `ModuleContext.tsx`, `BranchContext.tsx`, `ThemeContext.tsx` in `mobile/src/contexts/`
    - AuthContext: login, logout, MFA flow, token storage in memory, refresh via httpOnly cookie
    - TenantContext: org branding (logo, name) from tenant settings
    - ModuleContext: fetch enabled modules from `/api/v2/modules`, expose `isModuleEnabled(slug)` and `tradeFamily`
    - BranchContext: selected branch state, X-Branch-Id injection, branch selector visibility
    - ThemeContext: detect system dark/light mode via `prefers-color-scheme`, toggle dark class on root
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 1.5, 1.6, 44.1, 44.2, 44.3, 44.4_
  - [x] 2.4 Create `mobile/src/App.tsx` with provider hierarchy wrapping `<AppRoutes />`
    - Provider order: AuthProvider → TenantProvider → ModuleProvider → BranchProvider → ThemeProvider → OfflineProvider → BiometricProvider → MobileLayout → AppRoutes
    - _Requirements: 1.1, 1.7_
  - [x] 2.5 Create `mobile/src/hooks/useApiList.ts` — generic paginated list hook with search, filters, pull-refresh, load-more, and AbortController cleanup
    - Uses Safe API Pattern: `res.data?.items ?? []`, `res.data?.total ?? 0`
    - Typed generics on all API calls
    - AbortController in useEffect with cleanup on unmount
    - _Requirements: 13.1, 13.2, 13.3_
  - [x] 2.6 Create `mobile/src/hooks/useApiDetail.ts` — single resource fetch hook with AbortController cleanup and safe response handling
    - _Requirements: 13.1, 13.2, 13.3_

- [x] 3. Implement navigation system — TabNavigator, stack routes, module gating, and More menu
  - [x] 3.1 Create `mobile/src/components/layout/TabNavigator.tsx` — bottom tab bar with 5 tabs (Dashboard, Invoices, Customers, Jobs, More), 44px touch targets, active state styling
    - Tab config driven by `TabConfig[]` with module/trade-family/role filtering
    - _Requirements: 1.1, 1.2, 1.3, 5.2_
  - [x] 3.2 Create `mobile/src/navigation/TabConfig.ts` — tab definitions with module slugs, trade family gates, and role restrictions
    - Dashboard: always visible; Invoices: always visible; Customers: always visible; Jobs: `moduleSlug: 'jobs'`; More: always visible
    - _Requirements: 5.2, 5.3, 5.4, 5.5_
  - [x] 3.3 Create `mobile/src/navigation/StackRoutes.tsx` — React Router stack routes per tab with lazy-loaded screen components and scroll position preservation
    - Use `React.lazy()` for all screen imports
    - Preserve scroll position within tab stacks using `useLocation` state
    - _Requirements: 1.2, 1.8_
  - [x] 3.4 Create `mobile/src/components/common/ModuleGate.tsx` — wrapper component that shows/hides children based on enabled modules, trade family, and user role
    - Props: `moduleSlug`, `tradeFamily?`, `roles?`, `children`, `fallback?`
    - _Requirements: 5.2, 5.3, 5.4, 5.5_
  - [x] 3.5 Create `mobile/src/screens/more/MoreMenuScreen.tsx` — grid/list of module-gated navigation items for all features beyond the 4 main tabs
    - Items: Quotes, Inventory, Staff, Time Tracking, Expenses, Bookings, Vehicles, Accounting, Banking, Tax, Compliance, Reports, Notifications, POS, Construction, Franchise, Recurring, Purchase Orders, Projects, Schedule, SMS, Settings, Kiosk
    - Each item wrapped in ModuleGate
    - _Requirements: 5.2, 5.3, 5.4, 5.5_
  - [x] 3.6 Write property test for navigation visibility filtering
    - **Property 1: Navigation visibility respects module, trade family, and role filters**
    - Generate random combinations of enabled modules, trade families, and user roles; verify visible items match exactly the expected set
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5, 6.3, 28.2**

- [x] 4. Checkpoint — Verify infrastructure builds and navigation renders
  - Ensure `docker compose build mobile` succeeds, nginx serves `/mobile/`, tab navigator renders with module gating. Ensure all tests pass, ask the user if questions arise.

- [x] 5. Build mobile UI component library
  - [x] 5.1 Create `mobile/src/components/ui/MobileCard.tsx` — card container with shadow, rounded corners, dark mode support, and tap handler
    - _Requirements: 1.3, 1.5, 1.6_
  - [x] 5.2 Create `mobile/src/components/ui/MobileButton.tsx` — touch-optimised button with 44px min height, loading state, variant styles (primary, secondary, danger, ghost)
    - _Requirements: 1.3_
  - [x] 5.3 Create `mobile/src/components/ui/MobileInput.tsx` and `MobileSelect.tsx` — form input components with labels, error states, and 44px touch targets
    - _Requirements: 1.3_
  - [x] 5.4 Create `mobile/src/components/ui/MobileSearchBar.tsx` — search input with debounced onChange, clear button, and search icon
    - _Requirements: 7.2, 8.1, 9.1_
  - [x] 5.5 Create `mobile/src/components/ui/MobileList.tsx` and `MobileListItem.tsx` — generic paginated list with empty state, loading skeleton, and load-more trigger
    - Props match `MobileListProps<T>` interface from design
    - _Requirements: 7.1, 8.1_
  - [x] 5.6 Create `mobile/src/components/ui/MobileForm.tsx` and `MobileFormField.tsx` — form wrapper with validation, required field highlighting, and submit handler
    - _Requirements: 7.5, 8.3_
  - [x] 5.7 Create `mobile/src/components/ui/MobileModal.tsx` — bottom sheet / modal with backdrop, close button, and swipe-to-dismiss
    - _Requirements: 1.3_
  - [x] 5.8 Create `mobile/src/components/ui/MobileBadge.tsx`, `MobileSpinner.tsx`, `MobileToast.tsx`, `MobileEmptyState.tsx` — utility UI components
    - MobileBadge: status badges (paid, overdue, draft, etc.)
    - MobileSpinner: loading indicator
    - MobileToast: success/error/info toast notifications
    - MobileEmptyState: empty list placeholder with icon and message
    - _Requirements: 1.3, 1.5, 1.6_
  - [x] 5.9 Create `mobile/src/components/ui/index.ts` — barrel export for all UI components
    - _Requirements: 14.2_

- [x] 6. Build gesture components — SwipeAction, PullRefresh, DragDrop
  - [x] 6.1 Create `mobile/src/components/gestures/SwipeAction.tsx` — horizontal swipe on list items revealing left/right action buttons with configurable threshold (default 80px)
    - Touch event handlers: `onTouchStart`, `onTouchMove`, `onTouchEnd`
    - Snap-back animation when below threshold
    - _Requirements: 7.6, 8.6_
  - [x] 6.2 Create `mobile/src/components/gestures/PullRefresh.tsx` — pull-to-refresh wrapper with spinner, configurable threshold (default 60px), and `onRefresh` callback
    - _Requirements: 6.2, 7.3, 8.8_
  - [x] 6.3 Create `mobile/src/components/gestures/DragDrop.tsx` — drag-and-drop for kanban board columns with touch support
    - _Requirements: 10.6_
  - [x] 6.4 Create `mobile/src/hooks/useSwipeActions.ts` and `mobile/src/hooks/usePullRefresh.ts` — gesture state hooks
    - _Requirements: 7.6, 6.2_

- [x] 7. Build layout components — AppHeader, MobileLayout, BranchBadge, OfflineIndicator
  - [x] 7.1 Create `mobile/src/components/layout/AppHeader.tsx` — app header with org branding (logo + name), branch badge, and offline indicator
    - _Requirements: 1.7, 44.5, 30.1_
  - [x] 7.2 Create `mobile/src/components/layout/MobileLayout.tsx` — root layout wrapping AppHeader + content area + TabNavigator, responsive 320px–430px
    - _Requirements: 1.4_
  - [x] 7.3 Create `mobile/src/components/layout/BranchBadge.tsx` — displays active branch name, tappable to open branch selector
    - _Requirements: 44.1, 44.5_
  - [x] 7.4 Create `mobile/src/components/layout/OfflineIndicator.tsx` — banner shown when device is offline
    - _Requirements: 30.1_

- [x] 8. Implement auth screens — Login, MFA, ForgotPassword, BiometricLock
  - [x] 8.1 Create `mobile/src/screens/auth/LoginScreen.tsx` — email + password fields, "Remember Me" toggle, Google Sign-In button, "Forgot Password" link, form validation
    - On submit: call `/api/v1/auth/login`, store JWT in memory, refresh token as httpOnly cookie
    - On invalid credentials: display backend error message
    - _Requirements: 2.1, 2.2, 2.3, 2.8_
  - [x] 8.2 Create `mobile/src/screens/auth/MfaScreen.tsx` — MFA method selection (TOTP, SMS, backup codes), code input, submit, error handling, Firebase MFA support
    - Navigate here when backend returns MFA challenge after login
    - On valid code: complete auth, navigate to Dashboard
    - On invalid code: display error, allow retry
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [x] 8.3 Create `mobile/src/screens/auth/ForgotPasswordScreen.tsx` — email input, submit, confirmation message
    - _Requirements: 2.6, 2.7_
  - [x] 8.4 Create `mobile/src/screens/auth/BiometricLockScreen.tsx` — biometric prompt on app open, 3-failure fallback to password login
    - _Requirements: 4.2, 4.3_
  - [x] 8.5 Create `mobile/src/contexts/BiometricContext.tsx` — biometric enable/disable state, device capability detection, verification flow
    - Uses `capacitor-native-biometric` plugin
    - Hide biometric option if device doesn't support it
    - _Requirements: 4.1, 4.4, 4.5_
  - [x] 8.6 Write unit tests for LoginScreen, MfaScreen, and BiometricLockScreen
    - Test form validation, error display, navigation flows
    - _Requirements: 2.1, 2.3, 3.4, 4.3_

- [x] 9. Implement Dashboard screen
  - [x] 9.1 Create `mobile/src/screens/dashboard/DashboardScreen.tsx` — role-based summary cards (revenue, outstanding invoices, jobs in progress, upcoming bookings), quick action buttons, pull-to-refresh
    - Summary cards tappable → navigate to corresponding list screen
    - Quick actions filtered by ModuleGate: New Invoice, New Quote, New Job Card, New Customer
    - Clock in/out button when time_tracking module enabled
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 19.1_
  - [x] 9.2 Write unit tests for DashboardScreen
    - Test summary card rendering, quick action filtering, pull-to-refresh
    - _Requirements: 6.1, 6.3_

- [x] 10. Implement Customer screens — list, profile, create
  - [x] 10.1 Create `mobile/src/screens/customers/CustomerListScreen.tsx` — searchable paginated list with name, phone, email; swipe actions (Call, Email, SMS); pull-to-refresh
    - Uses `useApiList<Customer>` hook with endpoint `/api/v1/customers`
    - SwipeAction with Call (tel: link), Email (mailto: link), SMS (sms: link) via Capacitor
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7, 7.8, 7.9_
  - [x] 10.2 Create `mobile/src/screens/customers/CustomerProfileScreen.tsx` — full contact details, linked invoices, quotes, and job history tabs
    - Uses `useApiDetail<Customer>` hook
    - _Requirements: 7.4_
  - [x] 10.3 Create `mobile/src/screens/customers/CustomerCreateScreen.tsx` — creation form with first name required, all other fields optional
    - POST to `/api/v1/customers`, navigate to profile on success
    - _Requirements: 7.5_
  - [x] 10.4 Write unit tests for CustomerListScreen swipe actions and CustomerCreateScreen validation
    - _Requirements: 7.5, 7.6_

- [x] 11. Implement Invoice screens — list, detail, create, PDF viewer
  - [x] 11.1 Create `mobile/src/screens/invoices/InvoiceListScreen.tsx` — searchable paginated list with invoice number, customer, amount, status, date; swipe actions (Send, Record Payment); pull-to-refresh
    - Uses `useApiList<Invoice>` hook with endpoint `/api/v1/invoices`
    - _Requirements: 8.1, 8.6, 8.8_
  - [x] 11.2 Create `mobile/src/screens/invoices/InvoiceDetailScreen.tsx` — full invoice with line items, totals, tax, payment history; Send, Record Payment, Preview PDF buttons
    - _Requirements: 8.2, 8.4, 8.5, 8.7_
  - [x] 11.3 Create `mobile/src/screens/invoices/InvoiceCreateScreen.tsx` — form with customer picker, line item editor, tax calculation, discount fields, running total
    - Uses CustomerPicker and LineItemEditor common components
    - _Requirements: 8.3, 15.1, 15.2, 15.3, 15.4, 15.5_
  - [x] 11.4 Create `mobile/src/components/common/PDFViewer.tsx` — full-screen PDF viewer component
    - _Requirements: 8.7_
  - [x] 11.5 Create `mobile/src/screens/invoices/InvoicePDFScreen.tsx` — screen wrapper for PDFViewer showing invoice PDF
    - _Requirements: 8.7_
  - [x] 11.6 Write unit tests for InvoiceListScreen and InvoiceDetailScreen
    - Test list rendering, swipe actions, detail display, payment recording
    - _Requirements: 8.1, 8.2_

- [x] 12. Implement shared form components — LineItemEditor, CustomerPicker, ItemPicker
  - [x] 12.1 Create `mobile/src/components/common/LineItemEditor.tsx` — add/edit/remove line items with description, quantity, unit price, tax rate; real-time subtotal/tax/total calculation
    - Running total display at bottom of form
    - "Add Item" button opens ItemPicker
    - _Requirements: 15.1, 15.2, 15.5, 16.1, 16.2_
  - [x] 12.2 Create `mobile/src/components/common/CustomerPicker.tsx` — searchable customer selection modal
    - _Requirements: 8.3, 9.3_
  - [x] 12.3 Create `mobile/src/components/common/ItemPicker.tsx` — searchable inventory item selection that pre-fills line item description and unit price
    - _Requirements: 15.3, 15.4, 16.3_
  - [x] 12.4 Write property test for line item total calculation
    - **Property 2: Line item total calculation is mathematically correct**
    - Generate random sets of line items with quantity >= 0, unit_price >= 0, tax_rate 0–1; verify subtotal = sum(qty * price), tax = sum(qty * price * tax_rate), total = subtotal + tax - discount
    - **Validates: Requirements 15.2, 16.2**

- [x] 13. Checkpoint — Verify auth flow, dashboard, customers, invoices, and line item editor work end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Implement Quote screens — list, detail, create
  - [x] 14.1 Create `mobile/src/screens/quotes/QuoteListScreen.tsx` — searchable paginated list with quote number, customer, amount, status; pull-to-refresh; wrapped in ModuleGate for quotes module
    - Uses `useApiList<Quote>` hook
    - _Requirements: 9.1, 9.6_
  - [x] 14.2 Create `mobile/src/screens/quotes/QuoteDetailScreen.tsx` — full quote with line items, totals; Send and Convert to Invoice buttons
    - Convert to Invoice: POST to create invoice pre-populated with quote data
    - _Requirements: 9.2, 9.4, 9.5_
  - [x] 14.3 Create `mobile/src/screens/quotes/QuoteCreateScreen.tsx` — form with customer picker, line item editor (reuses LineItemEditor), tax, discount fields
    - _Requirements: 9.3, 16.1, 16.2, 16.3_
  - [x] 14.4 Write unit tests for QuoteDetailScreen Convert to Invoice flow
    - _Requirements: 9.5_

- [x] 15. Implement Job screens — list, board, detail
  - [x] 15.1 Create `mobile/src/screens/jobs/JobListScreen.tsx` — list view with status filters, toggle to board view; pull-to-refresh; wrapped in ModuleGate for jobs module
    - _Requirements: 10.1, 10.5_
  - [x] 15.2 Create `mobile/src/screens/jobs/JobBoardScreen.tsx` — kanban board with drag-drop columns (using DragDrop gesture component), status update on column change
    - _Requirements: 10.1, 10.6_
  - [x] 15.3 Create `mobile/src/screens/jobs/JobDetailScreen.tsx` — description, status, assigned staff, time entries, linked invoices; status change dropdown; timer button for time tracking
    - _Requirements: 10.2, 10.3, 10.4_
  - [x] 15.4 Create `mobile/src/hooks/useTimer.ts` — job time tracking timer hook with start/stop, elapsed time display, and API integration
    - _Requirements: 10.4_
  - [x] 15.5 Write unit tests for JobBoardScreen drag-drop status update and JobDetailScreen timer
    - _Requirements: 10.3, 10.4, 10.6_

- [x] 16. Implement Job Card screens (automotive) — list, detail, create
  - [x] 16.1 Create `mobile/src/screens/jobs/JobCardListScreen.tsx` — searchable list with job card number, customer, vehicle registration, status; pull-to-refresh; wrapped in ModuleGate for jobs module + automotive-transport trade family
    - _Requirements: 11.1, 11.4_
  - [x] 16.2 Create `mobile/src/screens/jobs/JobCardDetailScreen.tsx` — vehicle info, service items, parts, labour, status
    - _Requirements: 11.2_
  - [x] 16.3 Create job card creation form accessible from "New Job Card" — customer selection, vehicle selection, service description fields
    - _Requirements: 11.3_
  - [x] 16.4 Write unit tests for JobCardListScreen trade family gating
    - _Requirements: 11.1, 5.4_

- [x] 17. Implement API client branch header injection and property test
  - [x] 17.1 Verify and refine `mobile/src/api/client.ts` branch header interceptor — inject `X-Branch-Id` when branch selected, omit when "All Branches" (null)
    - _Requirements: 13.4, 44.2, 44.3_
  - [x] 17.2 Write property test for branch header injection
    - **Property 3: Branch header injection matches selected branch**
    - Generate random branch IDs (including null); verify X-Branch-Id header presence/absence matches selection
    - **Validates: Requirements 13.4, 44.2, 44.3**
  - [x] 17.3 Write property test for safe API response handling
    - **Property 4: Safe API response handling never throws on malformed responses**
    - Generate random malformed API responses (missing fields, null values, empty objects, unexpected types); verify useApiList and useApiDetail hooks return safe defaults without throwing
    - **Validates: Requirements 13.1**

- [x] 18. Implement Push Notifications and Deep Linking
  - [x] 18.1 Create `mobile/src/hooks/usePushNotifications.ts` — FCM registration via Capacitor, permission request, token submission to backend
    - _Requirements: 12.1, 12.2, 12.4_
  - [x] 18.2 Create `mobile/src/hooks/useDeepLink.ts` — deep link URL handler that resolves patterns (`/invoices/:id`, `/jobs/:id`, `/customers/:id`, `/compliance`) to screen navigation
    - _Requirements: 42.1, 42.2, 42.3, 42.4, 42.5_
  - [x] 18.3 Create `mobile/src/navigation/DeepLinkConfig.ts` — registered deep link URL patterns with param extractors
    - _Requirements: 42.1, 42.2, 42.3, 42.4_
  - [x] 18.4 Wire push notification tap handler to deep link navigation — tapping a notification opens the relevant screen
    - _Requirements: 12.3_
  - [x] 18.5 Write property test for deep link URL routing
    - **Property 8: Deep link URL routing resolves to the correct screen**
    - Generate random valid deep link URLs matching registered patterns and random invalid URLs; verify correct screen resolution and parameter extraction; verify invalid URLs resolve to fallback
    - **Validates: Requirements 39.2, 42.1, 42.2, 42.3, 42.4**

- [x] 19. Checkpoint — Verify quotes, jobs, job cards, push notifications, and deep linking
  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Implement Inventory screens — list, detail
  - [x] 20.1 Create `mobile/src/screens/inventory/InventoryListScreen.tsx` — searchable list with name, SKU, stock level, price; pull-to-refresh; wrapped in ModuleGate for inventory module
    - Search filters by item name or SKU
    - _Requirements: 17.1, 17.2, 17.4_
  - [x] 20.2 Create `mobile/src/screens/inventory/InventoryDetailScreen.tsx` — full description, stock levels per branch, pricing, supplier information
    - _Requirements: 17.3_

- [x] 21. Implement Staff screens — list, detail
  - [x] 21.1 Create `mobile/src/screens/staff/StaffListScreen.tsx` — list with name, role, contact details; swipe actions (Call, Email); wrapped in ModuleGate for staff module
    - _Requirements: 18.1, 18.3_
  - [x] 21.2 Create `mobile/src/screens/staff/StaffDetailScreen.tsx` — full profile, assigned branches, role information
    - _Requirements: 18.2_

- [x] 22. Implement Time Tracking screen
  - [x] 22.1 Create `mobile/src/screens/time-tracking/TimeTrackingScreen.tsx` — clock in/out button, running timer display, daily/weekly timesheet view with total hours; pull-to-refresh; wrapped in ModuleGate for time_tracking module
    - Clock In: POST to backend, start timer display
    - Clock Out: POST to backend, stop timer
    - Timesheet: paginated list of time entries
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

- [x] 23. Implement Expense screens — list, create with camera
  - [x] 23.1 Create `mobile/src/screens/expenses/ExpenseListScreen.tsx` — list with date, description, amount, category; pull-to-refresh; wrapped in ModuleGate for expenses module
    - _Requirements: 20.1, 20.6_
  - [x] 23.2 Create `mobile/src/screens/expenses/ExpenseCreateScreen.tsx` — form with description, amount, category, date, receipt photo (camera capture or gallery selection)
    - _Requirements: 20.2, 20.3, 20.4, 20.5_
  - [x] 23.3 Create `mobile/src/hooks/useCamera.ts` — Capacitor camera wrapper for photo capture and gallery selection, with permission handling
    - _Requirements: 43.1, 43.2, 43.3, 43.4, 43.5_
  - [x] 23.4 Create `mobile/src/components/common/CameraCapture.tsx` — camera UI component with capture, preview, retake/confirm, and 2MB compression
    - _Requirements: 43.4, 43.5_

- [x] 24. Implement Booking screens — calendar, create
  - [x] 24.1 Create `mobile/src/screens/bookings/BookingCalendarScreen.tsx` — calendar view with bookings (time, customer, service type); tap date to show day list; pull-to-refresh; wrapped in ModuleGate for bookings module
    - _Requirements: 21.1, 21.2, 21.5_
  - [x] 24.2 Create `mobile/src/screens/bookings/BookingCreateScreen.tsx` — form with customer selection, date, time, duration, service type
    - _Requirements: 21.3_
  - [x] 24.3 Create `mobile/src/components/common/DateRangePicker.tsx` — date range selection component for reports and calendar filters
    - _Requirements: 28.4_

- [x] 25. Implement Vehicle screens (automotive) — list, profile
  - [x] 25.1 Create `mobile/src/screens/vehicles/VehicleListScreen.tsx` — searchable list with registration, make, model, owner; pull-to-refresh; wrapped in ModuleGate for vehicles module + automotive-transport trade family
    - Search by registration, make, or model
    - _Requirements: 22.1, 22.3, 22.4_
  - [x] 25.2 Create `mobile/src/screens/vehicles/VehicleProfileScreen.tsx` — full vehicle details, owner information, service history
    - _Requirements: 22.2_

- [x] 26. Checkpoint — Verify all Phase 2 screens (inventory, staff, time tracking, expenses, bookings, vehicles)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 27. Implement Accounting screens — Chart of Accounts, Journal Entries
  - [x] 27.1 Create `mobile/src/screens/accounting/ChartOfAccountsScreen.tsx` — hierarchical list with account code, name, type, balance; tap to view account detail with recent journal entries; pull-to-refresh; wrapped in ModuleGate for accounting module
    - _Requirements: 23.1, 23.2, 23.3_
  - [x] 27.2 Create `mobile/src/screens/accounting/JournalEntryListScreen.tsx` — paginated list with date, description, amount; pull-to-refresh
    - _Requirements: 24.1, 24.3_
  - [x] 27.3 Create `mobile/src/screens/accounting/JournalEntryDetailScreen.tsx` — all debit and credit lines for a journal entry
    - _Requirements: 24.2_

- [x] 28. Implement Banking screens — accounts, transactions, reconciliation
  - [x] 28.1 Create `mobile/src/screens/accounting/BankAccountsScreen.tsx` — list with account name, institution, balance; pull-to-refresh; wrapped in ModuleGate for accounting module
    - _Requirements: 25.1, 25.4_
  - [x] 28.2 Create `mobile/src/screens/accounting/BankTransactionsScreen.tsx` — paginated transaction list for a bank account; pull-to-refresh
    - _Requirements: 25.2, 25.4_
  - [x] 28.3 Create `mobile/src/screens/accounting/ReconciliationScreen.tsx` — reconciliation dashboard with unreconciled counts and amounts per bank account
    - _Requirements: 25.3_

- [x] 29. Implement Tax and GST screens
  - [x] 29.1 Create `mobile/src/screens/accounting/GstPeriodsScreen.tsx` — list with period dates, status, GST amounts; pull-to-refresh; wrapped in ModuleGate for accounting module
    - _Requirements: 26.1, 26.4_
  - [x] 29.2 Create `mobile/src/screens/accounting/GstFilingDetailScreen.tsx` — GST collected vs GST paid breakdown
    - _Requirements: 26.2_
  - [x] 29.3 Create `mobile/src/screens/accounting/TaxPositionScreen.tsx` — current tax liability or refund position summary
    - _Requirements: 26.3_

- [x] 30. Implement Compliance screens — dashboard, upload
  - [x] 30.1 Create `mobile/src/screens/compliance/ComplianceDashboardScreen.tsx` — document categories, counts, expiry status; document list with name, type, expiry date, status (valid/expiring/expired); 30-day expiry badge; pull-to-refresh; wrapped in ModuleGate for compliance_docs module
    - _Requirements: 27.1, 27.4, 27.6, 27.7_
  - [x] 30.2 Create `mobile/src/screens/compliance/ComplianceUploadScreen.tsx` — camera capture or file selection, form for document type, description, expiry date, upload to backend
    - Uses CameraCapture component
    - _Requirements: 27.2, 27.3_
  - [x] 30.3 Add document preview on tap in compliance dashboard
    - _Requirements: 27.5_

- [x] 31. Implement Reports screens — menu, report viewer
  - [x] 31.1 Create `mobile/src/screens/reports/ReportsMenuScreen.tsx` — list of report types (Revenue, Job, Fleet, Inventory, Customer Statement, Outstanding Invoices, P&L, Balance Sheet, Aged Receivables) filtered by ModuleGate
    - Fleet report only visible for automotive trade family
    - _Requirements: 28.1, 28.2_
  - [x] 31.2 Create `mobile/src/screens/reports/ReportViewScreen.tsx` — mobile-optimised report display with summary cards, scrollable data tables, date range filter, pull-to-refresh
    - _Requirements: 28.3, 28.4, 28.5_

- [x] 32. Implement Notification Preferences screen
  - [x] 32.1 Create `mobile/src/screens/notifications/NotificationPreferencesScreen.tsx` — list of notification categories with toggles (invoice payments, job updates, expiry reminders, booking confirmations); overdue invoice reminder rules; pull-to-refresh
    - Toggle updates preference via backend API
    - _Requirements: 29.1, 29.2, 29.3, 29.4_

- [x] 33. Checkpoint — Verify all Phase 3 screens (accounting, banking, tax, compliance, reports, notifications)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 34. Implement Offline Mode — context, queue, sync, persistence
  - [x] 34.1 Create `mobile/src/contexts/OfflineContext.tsx` — network status monitoring via `@capacitor/network`, online/offline state, offline indicator trigger
    - _Requirements: 30.1, 30.2_
  - [x] 34.2 Create `mobile/src/hooks/useOfflineQueue.ts` — offline mutation queue: store mutations with timestamp, endpoint, method, body, entity type; persist to `@capacitor/preferences`; replay in chronological order on reconnect; conflict handling; retry with exponential backoff (max 3 retries)
    - _Requirements: 30.3, 30.4, 30.5, 30.6, 30.7_
  - [x] 34.3 Wire offline queue into API client — intercept write requests when offline, queue them, show "Saved offline" toast; on reconnect, replay queue and show sync confirmation with count
    - _Requirements: 30.3, 30.4, 30.6_
  - [x] 34.4 Write property test for offline queue mutation storage
    - **Property 5: Offline queue stores all mutations with correct metadata**
    - Generate random mutations (create/update/delete) with random endpoints, methods, bodies, entity types; verify queue contains entries with correct metadata and monotonically non-decreasing timestamps
    - **Validates: Requirements 30.3**
  - [x] 34.5 Write property test for offline queue replay ordering
    - **Property 6: Offline queue replays mutations in chronological order**
    - Generate random sequences of mutations with arbitrary timestamps; verify replay order is strictly non-decreasing by timestamp
    - **Validates: Requirements 30.4**
  - [x] 34.6 Write property test for offline queue persistence round-trip
    - **Property 7: Offline queue persistence round-trip preserves all mutations**
    - Generate random queue states with zero or more mutations; serialize to local storage and deserialize; verify deep equality of original and restored queue
    - **Validates: Requirements 30.7**

- [x] 35. Implement POS screen
  - [x] 35.1 Create `mobile/src/screens/pos/POSScreen.tsx` — product grid, cart with quantity editing, real-time total calculation, Pay button (creates invoice + records payment); cash/card/other payment methods; wrapped in ModuleGate for pos module
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5_

- [x] 36. Implement Construction screens — progress claims, variations, retentions
  - [x] 36.1 Create `mobile/src/screens/construction/ProgressClaimListScreen.tsx` — list with claim number, project, amount, status; pull-to-refresh; wrapped in ModuleGate for progress_claims module
    - _Requirements: 32.1, 32.5_
  - [x] 36.2 Create `mobile/src/screens/construction/VariationListScreen.tsx` — list with variation number, description, amount, status; pull-to-refresh; wrapped in ModuleGate for variations module
    - _Requirements: 32.2, 32.5_
  - [x] 36.3 Create `mobile/src/screens/construction/RetentionSummaryScreen.tsx` — total retained amounts and release schedules; wrapped in ModuleGate for retentions module
    - _Requirements: 32.3_
  - [x] 36.4 Create `mobile/src/screens/construction/ConstructionDetailScreen.tsx` — detail view for progress claims and variations with full breakdown and approval status
    - _Requirements: 32.4_

- [x] 37. Implement Franchise screens — dashboard, location detail, stock transfers
  - [x] 37.1 Create `mobile/src/screens/franchise/FranchiseDashboardScreen.tsx` — location summary cards; pull-to-refresh; wrapped in ModuleGate for franchise module
    - _Requirements: 33.1, 33.4_
  - [x] 37.2 Create `mobile/src/screens/franchise/LocationDetailScreen.tsx` — performance metrics and staff for a location
    - _Requirements: 33.2_
  - [x] 37.3 Create `mobile/src/screens/franchise/StockTransferListScreen.tsx` — list with transfer number, source, destination, status, item count
    - _Requirements: 33.3_

- [x] 38. Implement Recurring Invoices screens — list, detail
  - [x] 38.1 Create `mobile/src/screens/recurring/RecurringListScreen.tsx` — list with customer name, amount, frequency, next run date; pull-to-refresh; wrapped in ModuleGate for recurring_invoices module
    - _Requirements: 34.1, 34.3_
  - [x] 38.2 Create `mobile/src/screens/recurring/RecurringDetailScreen.tsx` — template configuration and generation history
    - _Requirements: 34.2_

- [x] 39. Implement Purchase Order screens — list, detail
  - [x] 39.1 Create `mobile/src/screens/purchase-orders/POListScreen.tsx` — paginated list with PO number, supplier, amount, status; pull-to-refresh; wrapped in ModuleGate for purchase_orders module
    - _Requirements: 35.1, 35.3_
  - [x] 39.2 Create `mobile/src/screens/purchase-orders/PODetailScreen.tsx` — line items, supplier details, delivery status
    - _Requirements: 35.2_

- [x] 40. Implement Project screens — list, dashboard
  - [x] 40.1 Create `mobile/src/screens/projects/ProjectListScreen.tsx` — list with project name, status, budget utilisation; pull-to-refresh; wrapped in ModuleGate for projects module
    - _Requirements: 36.1, 36.3_
  - [x] 40.2 Create `mobile/src/screens/projects/ProjectDashboardScreen.tsx` — tasks, budget breakdown, linked invoices, time entries
    - _Requirements: 36.2_

- [x] 41. Implement Schedule screen
  - [x] 41.1 Create `mobile/src/screens/schedule/ScheduleCalendarScreen.tsx` — calendar view with events, appointments, staff assignments; tap event for detail; "New Event" form with date, time, staff, description; pull-to-refresh; wrapped in ModuleGate for scheduling module
    - _Requirements: 37.1, 37.2, 37.3, 37.4_

- [x] 42. Implement SMS Compose screen
  - [x] 42.1 Create `mobile/src/screens/sms/SMSComposeScreen.tsx` — message composition with pre-filled customer phone, send via backend Connexus endpoint, delivery confirmation, error handling; wrapped in ModuleGate for sms module
    - SMS option accessible from customer profile and invoice detail screens
    - _Requirements: 38.1, 38.2, 38.3, 38.4_

- [x] 43. Implement Settings screen
  - [x] 43.1 Create `mobile/src/screens/settings/SettingsScreen.tsx` — sections for Profile, Organisation, Notifications, Branding, Online Payments; save button with API update and success confirmation; biometric enable/disable toggle; wrapped in ModuleGate with org_admin/global_admin role restriction
    - _Requirements: 41.1, 41.2, 41.3, 41.4, 4.1, 4.4_

- [x] 44. Implement Kiosk screen
  - [x] 44.1 Create `mobile/src/screens/kiosk/KioskScreen.tsx` — kiosk-mode display for kiosk role users; hide TabNavigator, restrict navigation; optimise layout for tablet (768px+)
    - _Requirements: 40.1, 40.2, 40.3_

- [x] 45. Implement Customer Portal Deep Links and Share
  - [x] 45.1 Add "Share Portal Link" button to InvoiceDetailScreen and QuoteDetailScreen — generate portal URL, open native share sheet via `@capacitor/share`
    - _Requirements: 39.1_
  - [x] 45.2 Wire deep link receiver in App.tsx — handle incoming deep links, redirect to login if unauthenticated then navigate to target screen after auth
    - _Requirements: 39.2, 42.5_

- [x] 46. Implement Branch Context UI
  - [x] 46.1 Add branch selector to AppHeader — dropdown showing available branches and "All Branches" option; visible when branch_management module enabled and user is not branch_admin; lock to assigned branch for branch_admin role
    - _Requirements: 44.1, 44.2, 44.3, 44.4, 44.5_

- [x] 47. Checkpoint — Verify all Phase 4 screens (offline, POS, construction, franchise, recurring, POs, projects, schedule, SMS, settings, kiosk, deep links, branch context)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 48. Final integration and wiring
  - [x] 48.1 Wire all screen routes into StackRoutes.tsx — ensure every screen is reachable from navigation, all lazy imports resolve, and module gating is applied at the route level
    - _Requirements: 1.1, 1.2, 5.2, 5.3_
  - [x] 48.2 Verify all screens use Safe API Pattern — audit every API call for optional chaining (`?.`), nullish coalescing (`?? []`, `?? 0`), typed generics (no `as any`), and AbortController cleanup
    - _Requirements: 13.1, 13.2, 13.3_
  - [x] 48.3 Verify dark mode renders correctly across all screens — ensure ThemeContext toggles dark class and all components use Tailwind dark: variants
    - _Requirements: 1.5, 1.6_
  - [x] 48.4 Verify responsive layout at 320px, 375px, and 430px viewport widths — ensure no horizontal overflow, touch targets meet 44px minimum
    - _Requirements: 1.3, 1.4_
  - [x] 48.5 Write integration tests for end-to-end navigation flows
    - Test tab switching, stack navigation, deep link resolution, module gating
    - _Requirements: 1.1, 1.2, 1.8, 42.1_

- [x] 49. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at logical boundaries
- Property tests validate the 8 universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All screens use the same mobile UI component library (task 5) and gesture components (task 6)
- The shared types directory (task 1.5) eliminates type drift between frontend and mobile
- Capacitor native features (camera, biometrics, push, share) are abstracted behind hooks for testability
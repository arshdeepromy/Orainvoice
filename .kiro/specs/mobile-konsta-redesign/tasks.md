# Implementation Plan: Mobile Konsta UI Redesign

## Overview

This plan migrates the OraInvoice mobile app frontend from custom Tailwind styling to Konsta UI v5 components, delivering native-feeling iOS and Material Design interfaces. The migration is structured in 13 phases: infrastructure setup, navigation shell, auth screens, core screens, five batches of module screens, native plugins, property-based tests, and build verification. All business logic, contexts, API contracts, and module gating are preserved unchanged.

**Language:** TypeScript (React 19 + Vite 8 + Tailwind CSS 4)
**UI Library:** Konsta UI v5
**Testing:** Vitest + React Testing Library + fast-check v4

## Tasks

- [ ] 1. Phase 1 — Infrastructure Setup
  - [ ] 1.1 Install Konsta UI v5 and configure Tailwind CSS 4
    - Run `npm install konsta` in `mobile/`
    - Update `mobile/tailwind.config.js` to use `konsta/config` wrapper with content paths `['./index.html', './src/**/*.{js,ts,jsx,tsx}']`
    - Extend Tailwind theme with `primary: 'var(--color-primary, #2563EB)'` and `secondary: 'var(--color-secondary, #1E40AF)'`
    - Ensure `darkMode: 'class'` is set
    - Verify PostCSS config uses `@tailwindcss/postcss` (already in devDependencies)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ] 1.2 Wrap App root with KonstaApp component
    - Modify `mobile/src/App.tsx` to import `App as KonstaApp` from `konsta/react`
    - Detect platform via `Capacitor.getPlatform()` — use `'ios'` theme for iOS, `'material'` for Android/web
    - Wrap KonstaApp **outside** all existing context providers with `safeAreas` prop enabled
    - Preserve the existing provider hierarchy: Auth → Tenant → Module → Branch → Theme → Offline → Biometric
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ] 1.3 Create useHaptics hook
    - Create `mobile/src/hooks/useHaptics.ts`
    - Implement `light()`, `medium()`, `heavy()`, `selection()` methods wrapping `@capacitor/haptics`
    - Guard with `isNativePlatform()` check — no-op silently on web
    - Wrap all calls in try/catch to prevent errors on unsupported devices
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ] 1.4 Create useGeolocation hook
    - Create `mobile/src/hooks/useGeolocation.ts`
    - Implement `getCurrentPosition()` returning `{ lat, lng } | null`
    - Use `enableHighAccuracy: false`, `timeout: 5000`
    - Guard with platform detection, return null silently on failure or permission denial
    - _Requirements: 51.1, 51.2, 51.4_

  - [ ] 1.5 Create StatusBadge component
    - Create `mobile/src/components/konsta/StatusBadge.tsx`
    - Use existing `STATUS_CONFIG` map from `utils/statusConfig.ts`
    - Render as a Konsta UI `Chip` with correct label, text colour, and background colour
    - Support `sm` and `md` sizes
    - _Requirements: 10.3, 56.2_

  - [ ] 1.6 Create HapticButton component
    - Create `mobile/src/components/konsta/HapticButton.tsx`
    - Wrap Konsta UI `Button` and trigger appropriate haptic impact on press via `useHaptics`
    - Accept `hapticStyle` prop: `'light' | 'medium' | 'heavy' | 'selection'`
    - _Requirements: 9.1, 9.2, 9.3_

- [ ] 2. Phase 1 Checkpoint
  - Ensure `npm run build` succeeds in `mobile/`
  - Ensure all existing tests still pass with `npm run test`
  - Verify KonstaApp wraps the app root correctly
  - Ask the user if questions arise.

- [ ] 3. Phase 2 — Navigation Shell
  - [ ] 3.1 Create KonstaShell layout component
    - Create `mobile/src/components/konsta/KonstaShell.tsx`
    - Replace `MobileLayout` as the layout wrapper
    - On auth routes (`/login`, `/login/mfa`, `/forgot-password`, `/signup`, `/reset-password`, `/verify-email`): render children only (no navbar, no tabbar)
    - On authenticated routes: render KonstaNavbar + scrollable content + KonstaTabbar
    - On kiosk role: render content only (no tabbar)
    - _Requirements: 6.1, 4.1, 4.8_

  - [ ] 3.2 Create KonstaTabbar bottom tab bar
    - Create `mobile/src/components/konsta/KonstaTabbar.tsx`
    - Render Konsta UI `Tabbar` with `TabbarLink` for 5 tabs: Home, Invoices, Customers, dynamic 4th tab, More
    - Implement dynamic 4th tab resolution: Jobs (if `jobs` enabled) → Quotes (if `quotes` enabled) → Bookings (if `bookings` enabled) → Reports (fallback)
    - Read module state from `useModules().isEnabled(slug)`
    - Use Ionicons for tab icons, `active` prop for current tab
    - Respect safe area insets via KonstaApp `safeAreas`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ] 3.3 Create KonstaNavbar screen header
    - Create `mobile/src/components/konsta/KonstaNavbar.tsx`
    - Accept `title`, `subtitle`, `showBack`, `onBack`, `rightActions` props
    - Root screens: title centered, no back button
    - Detail screens: back button on left, title centered
    - Right slot: screen-specific action buttons (search, filter, overflow menu)
    - When `branch_management` module enabled: show tappable branch selector pill as subtitle
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 3.4 Create MoreDrawer sheet component
    - Create `mobile/src/components/konsta/MoreDrawer.tsx`
    - Create `mobile/src/navigation/MoreMenuConfig.ts` with all navigation items and their module/trade/role gates
    - Use Konsta UI `Sheet` component opened when More tab is tapped
    - Filter items using identical logic to existing sidebar: `module enabled + feature flag + trade family + user role`
    - Group items by category with `BlockTitle` section headers: Sales, Operations, People, Industry, Assets & Compliance, Communications, Finance, Other, Account
    - Render each item as Konsta `ListItem` with leading icon, title, optional badge, and chevron
    - Navigate to route and close drawer on item tap
    - Hide items when module disabled, trade family doesn't match, or role is insufficient
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8_

  - [ ] 3.5 Create KonstaFAB floating action button
    - Create `mobile/src/components/konsta/KonstaFAB.tsx`
    - Position bottom-right, above the Tabbar
    - Style with primary brand colour from TenantContext
    - Trigger light haptic on tap
    - Accept `label`, `onClick`, `icon` props
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ] 3.6 Create BranchPickerSheet component
    - Create `mobile/src/components/konsta/BranchPickerSheet.tsx`
    - Konsta `Sheet` listing available branches as `ListItem` with radio selection
    - Update localStorage and trigger BranchContext refresh on selection
    - _Requirements: 6.5_

  - [ ] 3.7 Wire KonstaShell into App.tsx and update routing
    - Replace `MobileLayout` with `KonstaShell` in `App.tsx`
    - Update `AppRoutes.tsx` to work with the new shell (auth routes without shell, app routes with shell)
    - Extend `TabConfig.ts` with dynamic 4th tab logic
    - _Requirements: 2.5, 3.6, 4.1_

  - [ ]* 3.8 Write unit tests for KonstaTabbar and MoreDrawer
    - Test KonstaTabbar renders 5 tabs with correct dynamic 4th tab for various module combinations
    - Test MoreDrawer filters items correctly by module, trade family, and role
    - Test MoreDrawer groups items by category
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 4.7, 5.2, 5.4, 5.5, 5.6_

- [ ] 4. Phase 2 Checkpoint
  - Ensure all tests pass and build succeeds
  - Verify bottom tab bar renders with correct tabs
  - Verify More drawer opens and shows filtered navigation items
  - Ask the user if questions arise.

- [ ] 5. Phase 3 — Auth Screens
  - [ ] 5.1 Redesign Login screen with Konsta UI
    - Restyle `mobile/src/screens/auth/LoginScreen.tsx` using Konsta `Page`, `Block`, `List`, `ListInput`, `Button`
    - Hero gradient header (slate-900 → indigo-900) with OraInvoice logo
    - Email and password inputs as Konsta `ListInput`
    - Full-width primary "Sign In" button
    - Secondary buttons: "Continue with Google", "Sign in with Passkey"
    - Footer links: "Forgot password?", "Create account"
    - Support dark and light mode
    - Preserve existing `POST /auth/login` flow unchanged
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_

  - [ ] 5.2 Redesign MFA Verification screen
    - Restyle MFA screen at `/login/mfa` using Konsta `Page`, `Block`, `ListInput`, `Segmented`, `SegmentedButton`, `Button`
    - 6-digit numeric code input with autoFocus
    - Segmented control for method selection (TOTP, SMS, Email, Passkey, Backup)
    - "Verify" primary button and "Try another method" link
    - Preserve `POST /auth/mfa/verify` flow unchanged
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ] 5.3 Redesign Signup Wizard
    - Restyle signup at `/signup` as multi-step Konsta page with progress dots
    - Step 1: Account (name, email, password, business name)
    - Step 2: Plan selection (Mech Pro Plan $60 NZD/month)
    - Step 3: Stripe Elements card form in Konsta `Block`
    - Step 4: Confirmation
    - Preserve `POST /auth/register` flow unchanged
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [ ] 5.4 Redesign Password Reset and Email Verification screens
    - Restyle `/forgot-password` as single-form Konsta page with email input and submit button
    - Restyle `/reset-password` as single-form Konsta page with new password input
    - Restyle `/verify-email` as status page with auto-verify
    - Preserve all API calls unchanged
    - _Requirements: 14.1, 14.2, 14.3_

  - [ ] 5.5 Redesign Landing Page (mobile-optimized)
    - Restyle `/` with hero gradient, headline, CTA buttons (Sign Up, Login)
    - Feature cards in vertical stack layout
    - Pricing card and footer
    - _Requirements: 15.1, 15.2, 15.3_

  - [ ] 5.6 Redesign Public Invoice Payment page
    - Restyle `/pay/:token` with invoice summary card (org logo, invoice number, customer, collapsed line items, total)
    - Stripe Elements card form in Konsta `Block`
    - "Pay NZD X,XXX.XX" primary button with formatted total
    - Preserve `GET /public/invoice/:token` and Stripe Elements unchanged
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

- [ ] 6. Phase 3 Checkpoint
  - Ensure all auth screens render correctly
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.


- [ ] 7. Phase 4 — Core Screens (Dashboard, Invoices, Customers)
  - [ ] 7.1 Redesign Dashboard screen
    - Restyle `/dashboard` using Konsta `Page`, `Card`, `Chip`, `List`, `BlockTitle`
    - Greeting "Hello, {first_name}" with branch selector subtitle
    - Stat cards in 2-column grid: Revenue (this month), Outstanding receivables, Overdue count (red badge if > 0), Active jobs (only if `jobs` module enabled)
    - Scrollable horizontal quick action `Chip` buttons: New Invoice, New Customer, New Quote (if `quotes`), New Job (if `jobs`), New Booking (if `bookings`)
    - "Recent Invoices" section with last 5 invoices as Konsta `List`
    - "Needs Attention" section with overdue invoices and red status indicators
    - Compliance alert card (if `compliance_docs` module + expiring docs) with yellow card and count
    - Implement Pull_To_Refresh using Konsta `Page` `ptr` prop
    - Call `GET /dashboard/stats` and `GET /invoices?status=overdue` with safe API consumption
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 8.1, 8.2, 8.3_

  - [ ] 7.2 Redesign Invoice List screen
    - Restyle `/invoices` as full-screen list (replacing desktop split-pane)
    - Konsta `Searchbar` with status filter chips (All, Draft, Issued, Partially Paid, Paid, Overdue, Voided, Refunded, Partially Refunded)
    - Each invoice as Konsta `ListItem`: customer name (bold), invoice number (muted), NZD total (right-aligned, large), status badge (StatusBadge component), due date, Stripe icon if applicable, paperclip if `attachment_count > 0`
    - Swipe-left actions: Mark Sent, Email, Void
    - Swipe-right actions: Record Payment, Duplicate
    - Infinite scroll pagination (25 per page) using `offset` and `limit`
    - FAB for "+ New Invoice" navigating to `/invoices/new`
    - Pull_To_Refresh
    - Call `GET /invoices` with safe API consumption: `res.data?.items ?? []`, `res.data?.total ?? 0`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9, 18.10, 7.1, 8.1_

  - [ ] 7.3 Redesign Invoice Detail screen
    - Restyle `/invoices/:id` with Konsta `Page`, `Navbar`, `Card`, `Block`, `List`, `Sheet`
    - Header: invoice number, back button, overflow menu (•••)
    - Hero card: customer name, vehicle (if any), status badge, total NZD, balance due
    - Sections: Vehicles (if vehicles module), Line items (collapsible), Totals (subtotal, discount, GST, shipping, adjustment, total — exact existing calculation logic), Payments, Credit notes, Attachments (thumbnail row + Camera button), Notes
    - Bottom sheet action menu: Email, Mark Sent, Void, Duplicate, Download PDF, Print, Print POS Receipt, Record Payment, Create Credit Note, Process Refund, Share Link, Send Reminder, Delete
    - Use Konsta `Sheet` for modal forms (record payment, void reason, credit note, refund)
    - Preserve `computeCreditableAmount()` and `computePaymentSummary()` helper logic exactly
    - Call `GET /invoices/:id` and all action endpoints unchanged
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 56.1, 56.5_

  - [ ] 7.4 Redesign Invoice Create/Edit screen
    - Restyle `/invoices/new` and `/invoices/:id/edit` as multi-step form with Konsta `Block` per step
    - Step 1 (Customer & Vehicle): customer selector with searchable list, vehicle selector with multi-select chip pills (only if `vehicles` module + automotive-transport trade)
    - Step 2 (Dates & Meta): issue date, due date, payment terms dropdown, salesperson select, subject, order number, GST number (read-only)
    - Step 3 (Line Items): Konsta `Card` per line item with description, qty, rate, tax mode, discount, computed amount; buttons for "Add from Catalogue", "Add from Inventory" (if `inventory`), "Add Labour", "Add Empty Line"
    - Step 4 (Adjustments): discount (% or $ toggle), shipping charges, adjustment
    - Step 5 (Notes & Attachments): customer notes, internal notes, terms, attachments with file upload and Camera button (max 5 files, 20MB each)
    - Step 6 (Review & Save): summary card with "Save as Draft", "Save & Send", "Mark Paid & Email", "Make Recurring" toggle, payment method selector
    - Compute line item totals using exact existing calculation logic
    - Use `formatNZD()` for all currency display
    - Call all API endpoints unchanged: `POST /invoices`, `PUT /invoices/:id`, `GET /catalogue/items`, etc.
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 20.10, 56.1, 56.4_

  - [ ] 7.5 Redesign Customer List screen
    - Restyle `/customers` with sticky Konsta `Searchbar`
    - Each customer as Konsta `ListItem`: display_name or `${first_name} ${last_name}` as title, company_name or phone as subtitle, receivables badge (red if > 0) on right
    - Infinite scroll pagination
    - FAB for "+ New Customer"
    - Tap row navigates to `/customers/:id`
    - Call `GET /customers` with safe API consumption
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 7.1_

  - [ ] 7.6 Redesign Customer Create screen
    - Restyle `/customers/new` as single-page Konsta form
    - Fields: First Name (required), Last Name, Company Name, Email, Phone, Mobile Phone, Work Phone, Address (textarea)
    - "Save" and "Save & Add Another" buttons
    - Validate First Name before submission
    - Call `POST /customers` unchanged
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5_

  - [ ] 7.7 Redesign Customer Profile screen
    - Restyle `/customers/:id` with header card (avatar initials, name, company, contact buttons: call via `tel:`, email via `mailto:`, SMS via `sms:`)
    - Tabs using Konsta `Segmented`: Profile, Invoices, Vehicles (if `vehicles` + automotive trade), Reminders, History
    - Profile tab: read-only fields with "Edit" button opening modal form
    - Invoices tab: list of customer's invoices with status and total
    - Vehicles tab: linked vehicles (only if `vehicles` module + automotive-transport trade)
    - Reminders tab: WOF/service reminder configuration
    - Call `GET /customers/:id`, `GET /invoices?customer_id=:id`, `GET /vehicles?customer_id=:id` with safe API consumption
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7_

  - [ ]* 7.8 Write unit tests for Dashboard, Invoice List, and Customer List screens
    - Smoke test: each screen renders without crashing with mocked API data
    - Test Pull_To_Refresh triggers API refetch
    - Test FAB appears on list screens and navigates to create form
    - Test status badges render correct colours
    - _Requirements: 17.1, 18.1, 21.1, 8.1, 7.1_

- [ ] 8. Phase 4 Checkpoint
  - Ensure all core screens render correctly
  - Ensure all tests pass and build succeeds
  - Verify invoice calculations match existing logic exactly
  - Ask the user if questions arise.

- [ ] 9. Phase 5 — Module Screens Batch 1 (Quotes, Job Cards, Vehicles, Bookings)
  - [ ] 9.1 Redesign Quote List screen
    - Restyle `/quotes` with status filters (Draft, Sent, Accepted, Declined, Expired), FAB for "+ New Quote", Pull_To_Refresh
    - Wrap in `ModuleGate` for `quotes` module
    - Call `GET /quotes` with safe API consumption
    - _Requirements: 24.1, 24.5, 55.1_

  - [ ] 9.2 Redesign Quote Create screen
    - Restyle `/quotes/new` as stepper: Step 1 (Customer), Step 2 (Line items), Step 3 (Discount, terms, notes, expiry date), Step 4 (Save/Send)
    - Wrap in `ModuleGate` for `quotes` module
    - Call `POST /quotes` unchanged
    - _Requirements: 24.2, 24.5_

  - [ ] 9.3 Redesign Quote Detail screen
    - Restyle `/quotes/:id` with hero card (customer, total, status), line items list, bottom action sheet (Send, Convert to Invoice, Edit, Duplicate)
    - Wrap in `ModuleGate` for `quotes` module
    - Call `GET /quotes/:id`, `POST /quotes/:id/convert`, `POST /quotes/:id/email` unchanged
    - _Requirements: 24.3, 24.4, 24.5_

  - [ ] 9.4 Redesign Job Card List screen
    - Restyle `/job-cards` with sorting: in_progress first, open second, completed/invoiced last (preserve `statusOrder` logic), then by `created_at` descending
    - Each job card: status colour pill, customer name, vehicle rego as subtitle, assigned-to avatar on right
    - Status filter and "assigned to me" toggle
    - FAB for "+ New Job Card"
    - Wrap in `ModuleGate` for `jobs` module
    - Call `GET /job-cards` with safe API consumption
    - _Requirements: 25.1, 25.2, 25.3, 25.4, 55.1, 56.3_

  - [ ] 9.5 Redesign Job Card Create screen
    - Restyle `/job-cards/new` as stepper: Step 1 (Customer & Vehicle), Step 2 (Description, service type, assigned staff), Step 3 (Parts from inventory if `inventory` enabled), Step 4 (Labour entries from labour rates), Step 5 (Save)
    - Wrap in `ModuleGate` for `jobs` module
    - Call `POST /job-cards` unchanged
    - _Requirements: 26.1, 26.2, 26.3_

  - [ ] 9.6 Redesign Job Card Detail screen
    - Restyle `/job-cards/:id` with hero section (customer, vehicle, status, assigned staff)
    - Sections: Parts, Labour, Notes, Attachments (with Camera button for photos), Status History
    - Bottom actions: Edit, Add Parts, Add Labour, Upload Attachment, Complete Job (creates invoice), Reassign
    - Wrap in `ModuleGate` for `jobs` module
    - Call `GET /job-cards/:id`, `PUT /job-cards/:id`, `POST /job-cards/:id/complete`, `POST /job-cards/:id/attachments` unchanged
    - _Requirements: 27.1, 27.2, 27.3, 27.4_

  - [ ] 9.7 Redesign Active Jobs Board (timer screen)
    - Restyle `/jobs` as card-based view of in-progress and open jobs
    - Each card: customer, vehicle, live timer (HH:MM:SS updating every second) if started
    - Buttons per card: Start Timer / Stop Timer (toggle), Assign to Me, Take Over, Confirm Done
    - On Start Timer: call `POST /job-cards/:id/start-timer` and optionally request GPS via `useGeolocation` (silent, non-blocking)
    - On Stop Timer: call `POST /job-cards/:id/stop-timer`
    - Trigger haptics on timer start and stop
    - If geolocation unavailable or denied, continue without location silently
    - _Requirements: 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7, 51.1, 51.4_

  - [ ] 9.8 Redesign Vehicle List screen
    - Restyle `/vehicles` with searchbar (search by rego)
    - List items: rego (large, monospace), make/model/year, owner name, WOF expiry pill (red if expired, amber if <30 days)
    - Wrap in `ModuleGate` for `vehicles` module AND trade family check for `automotive-transport`
    - Call `GET /vehicles` with safe API consumption
    - _Requirements: 29.1, 29.4, 55.5_

  - [ ] 9.9 Redesign Vehicle Profile screen
    - Restyle `/vehicles/:id` with hero (large rego, make/model/year/colour)
    - Stats: WOF expiry, rego expiry, odometer, service due date
    - Sections: Service History (linked invoices/jobs), Linked Customer
    - "Edit" button for dates
    - Wrap in `ModuleGate` for `vehicles` module AND trade family check
    - Call `GET /vehicles/:id` with safe API consumption
    - _Requirements: 29.2, 29.3, 29.4_

  - [ ] 9.10 Redesign Booking Calendar screen
    - Restyle `/bookings` with calendar view and list of bookings for selected date below
    - FAB for "+ New Booking"
    - Tap booking opens edit sheet
    - "Create Job from Booking" action in booking detail sheet
    - Long-press menu with date picker for rescheduling (replacing desktop drag-and-drop)
    - Wrap in `ModuleGate` for `bookings` module
    - Call `GET /bookings`, `POST /bookings`, `PUT /bookings/:id`, `DELETE /bookings/:id` unchanged
    - _Requirements: 30.1, 30.2, 30.3, 30.4, 30.5, 30.6_

  - [ ]* 9.11 Write unit tests for Quote, Job Card, Vehicle, and Booking screens
    - Smoke test each screen renders with mocked data
    - Test module gating hides screens when module disabled
    - Test job card sorting order
    - Test timer start/stop flow
    - _Requirements: 24.1, 25.1, 29.1, 30.1, 55.1_

- [ ] 10. Phase 5 Checkpoint
  - Ensure all module screens batch 1 render correctly
  - Ensure module gating works for quotes, jobs, vehicles, bookings
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.


- [ ] 11. Phase 6 — Module Screens Batch 2 (Inventory, Catalogue, Staff, Projects)
  - [ ] 11.1 Redesign Inventory screen
    - Restyle `/inventory` with Konsta tabs: Stock Levels, Usage History, Update Log, Reorder Alerts, Suppliers
    - Stock Levels tab: searchable list with item name, available qty, sell price, brand as subtitle
    - Tap stock item opens detail sheet with all StockItem fields and "Adjust Stock" action
    - Reorder Alerts tab: red-bordered cards
    - Wrap in `ModuleGate` for `inventory` module
    - Call `GET /inventory/stock-items`, `POST /inventory/stock-items/:id/adjust`, `GET /inventory/suppliers` with safe API consumption
    - _Requirements: 31.1, 31.2, 31.3, 31.4, 31.5, 55.1_

  - [ ] 11.2 Redesign Catalogue Items screen
    - Restyle `/items` with tabs: Items, Labour Rates, Service Types
    - Each CatalogueItem: name, default_price, GST applicable badge
    - Tap item opens edit sheet
    - FAB for "+ Add Item"
    - Wrap in `ModuleGate` for `inventory` module
    - Call `GET /catalogue/items`, `POST /catalogue/items`, `PUT /catalogue/items/:id`, `GET /catalogue/labour-rates` unchanged
    - _Requirements: 32.1, 32.2, 32.3, 32.4, 32.5, 55.1_

  - [ ] 11.3 Redesign Staff screen
    - Restyle `/staff` as list with staff name, role badges (Konsta `Chip`), branch, and status
    - Tap staff member opens edit sheet
    - Wrap in `ModuleGate` for `staff` module
    - Call `GET /api/v2/staff`, `POST /api/v2/staff`, `PUT /api/v2/staff/:id` with safe API consumption
    - _Requirements: 33.1, 33.2, 33.3, 55.1_

  - [ ] 11.4 Redesign Projects screen
    - Restyle `/projects` as list with project name, status, budget, and progress bar (Konsta `Progressbar`)
    - Restyle `/projects/:id` as project dashboard with financials, tasks, and progress
    - Wrap in `ModuleGate` for `projects` module
    - Call `GET /projects`, `GET /projects/:id` with safe API consumption
    - _Requirements: 34.1, 34.2, 34.3, 55.1_

  - [ ]* 11.5 Write unit tests for Inventory, Catalogue, Staff, and Projects screens
    - Smoke test each screen renders with mocked data
    - Test module gating hides screens when module disabled
    - Test inventory stock adjustment flow
    - _Requirements: 31.1, 32.1, 33.1, 34.1, 55.1_

- [ ] 12. Phase 6 Checkpoint
  - Ensure all module screens batch 2 render correctly
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.

- [ ] 13. Phase 7 — Module Screens Batch 3 (Expenses, Time Tracking, Schedule, POS)
  - [ ] 13.1 Redesign Expenses screen
    - Restyle `/expenses` as list with date, category, amount, and receipt indicator
    - Creation form with Camera button for receipt capture using `@capacitor/camera`
    - Category picker in expense form
    - FAB for "+ New Expense"
    - Wrap in `ModuleGate` for `expenses` module
    - Call `GET /api/v2/expenses`, `POST /api/v2/expenses` with safe API consumption
    - _Requirements: 35.1, 35.2, 35.3, 35.4, 35.5, 50.2, 55.1_

  - [ ] 13.2 Redesign Time Tracking screen
    - Restyle `/time-tracking` with prominent clock-in/clock-out buttons, today's entries list, and manual entry form
    - Wrap in `ModuleGate` for `time_tracking` module
    - Call `GET /api/v2/time-entries`, `POST /api/v2/time-entries` with safe API consumption
    - _Requirements: 36.1, 36.2, 55.1_

  - [ ] 13.3 Redesign Schedule screen
    - Restyle `/schedule` as calendar view of staff/bay schedules
    - Support creating and editing schedule entries
    - Wrap in `ModuleGate` for `scheduling` module
    - Call `GET /api/v2/schedule`, `POST /api/v2/schedule` with safe API consumption
    - _Requirements: 37.1, 37.2, 37.3, 55.1_

  - [ ] 13.4 Redesign POS screen
    - Restyle `/pos` as full-screen mobile POS layout
    - Product grid: 2-column Konsta `Card` grid populated from catalogue items
    - Order panel: bottom sheet (drag up to expand) with selected items, quantities, running total
    - Payment sheet: final step with payment method selection
    - Wrap in `ModuleGate` for `pos` module
    - Call `GET /catalogue/items` for products and `POST /invoices` + `POST /payments/cash` for order completion unchanged
    - _Requirements: 38.1, 38.2, 38.3, 38.4, 38.5, 55.1_

  - [ ]* 13.5 Write unit tests for Expenses, Time Tracking, Schedule, and POS screens
    - Smoke test each screen renders with mocked data
    - Test module gating hides screens when module disabled
    - Test camera integration falls back to file input on web
    - _Requirements: 35.1, 36.1, 37.1, 38.1, 55.1_

- [ ] 14. Phase 7 Checkpoint
  - Ensure all module screens batch 3 render correctly
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.

- [ ] 15. Phase 8 — Module Screens Batch 4 (Recurring, Purchase Orders, Construction, Hospitality)
  - [ ] 15.1 Redesign Recurring Invoices screen
    - Restyle `/recurring` as list with frequency badge per template
    - Swipe actions for pause and resume
    - Wrap in `ModuleGate` for `recurring_invoices` module
    - Call `GET /api/v2/recurring`, `POST /api/v2/recurring` with safe API consumption
    - _Requirements: 39.1, 39.2, 39.3, 55.1_

  - [ ] 15.2 Redesign Purchase Orders screen
    - Restyle `/purchase-orders` as list with supplier, status, and total
    - Detail view `/purchase-orders/:id` with line items and "Receive Stock" action
    - Wrap in `ModuleGate` for `purchase_orders` module
    - Call `GET /api/v2/purchase-orders`, `GET /api/v2/purchase-orders/:id`, `PUT /api/v2/purchase-orders/:id` with safe API consumption
    - _Requirements: 40.1, 40.2, 40.3, 55.1_

  - [ ] 15.3 Redesign Construction screens (Progress Claims, Variations, Retentions)
    - Restyle `/progress-claims` as claim list with create form — gate by `progress_claims` module + `building-construction` trade
    - Restyle `/variations` as variation list with cost impact display — gate by `variations` module + `building-construction` trade
    - Restyle `/retentions` as retention summary by project with release action — gate by `retentions` module + `building-construction` trade
    - Call `GET /progress-claims`, `GET /variations`, `GET /retentions` with safe API consumption
    - _Requirements: 41.1, 41.2, 41.3, 41.4, 55.1, 55.5_

  - [ ] 15.4 Redesign Hospitality screens (Floor Plan, Kitchen Display)
    - Restyle `/floor-plan` as visual table layout (SVG/canvas) where tapping a table seats a customer — gate by `tables` module + `food-hospitality` trade
    - Restyle `/kitchen` as full-screen kitchen display with large order cards, tap-to-mark-ready, auto-refresh every 5 seconds — gate by `kitchen_display` module + `food-hospitality` trade
    - Call `GET /tables`, `POST /reservations`, `GET /kitchen/orders`, `PUT /kitchen/orders/:id` with safe API consumption
    - _Requirements: 42.1, 42.2, 42.3, 55.1, 55.5_

  - [ ]* 15.5 Write unit tests for Recurring, Purchase Orders, Construction, and Hospitality screens
    - Smoke test each screen renders with mocked data
    - Test module gating and trade family gating
    - Test kitchen display auto-refresh
    - _Requirements: 39.1, 40.1, 41.1, 42.1, 55.1, 55.5_

- [ ] 16. Phase 8 Checkpoint
  - Ensure all module screens batch 4 render correctly
  - Ensure trade family gating works for construction and hospitality screens
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.

- [ ] 17. Phase 9 — Module Screens Batch 5 (Assets, Compliance, SMS, Reports, Notifications)
  - [ ] 17.1 Redesign Assets screen
    - Restyle `/assets` as asset list with name, category, value, and depreciation info
    - Detail view `/assets/:id` with depreciation schedule and maintenance log
    - Wrap in `ModuleGate` for `assets` module
    - Call `GET /assets`, `GET /assets/:id` with safe API consumption
    - _Requirements: 43.1, 43.2, 43.3, 55.1_

  - [ ] 17.2 Redesign Compliance Documents screen
    - Restyle `/compliance` with document list showing expiry pills (green=valid, amber=expiring, red=expired)
    - Summary cards at top with counts by status (valid, expiring, expired)
    - Upload via Camera (`@capacitor/camera`) or file picker
    - Wrap in `ModuleGate` for `compliance_docs` module
    - Call `GET /api/v2/compliance-docs`, `POST /api/v2/compliance-docs`, `DELETE /api/v2/compliance-docs/:id` with safe API consumption
    - _Requirements: 44.1, 44.2, 44.3, 44.4, 50.2, 55.1_

  - [ ] 17.3 Redesign SMS Chat screen
    - Restyle `/sms` with conversation list using Konsta UI `Messages` component
    - Conversation thread view with send composer using Konsta `Messagebar`
    - Wrap in `ModuleGate` for `sms` module
    - Call `GET /sms/conversations`, `POST /sms/send` with safe API consumption
    - _Requirements: 45.1, 45.2, 45.3, 55.1_

  - [ ] 17.4 Redesign Reports screen
    - Restyle `/reports` as report hub with category cards (Sales, Finance, Operations, Industry)
    - Select report → date range picker (Konsta `Sheet`) → run → display chart/table
    - Export buttons for PDF and CSV
    - Call appropriate `/reports/*` endpoints with safe API consumption
    - _Requirements: 46.1, 46.2, 46.3, 46.4_

  - [ ] 17.5 Redesign Notifications screen
    - Restyle `/notifications` with preferences list using Konsta `Toggle` components
    - Overdue rules configuration
    - Reminder templates editor
    - Call `GET /notifications/preferences`, `PUT /notifications/preferences`, `GET /notifications/overdue-rules`, `PUT /notifications/overdue-rules` with safe API consumption
    - _Requirements: 47.1, 47.2, 47.3, 47.4_

  - [ ]* 17.6 Write unit tests for Assets, Compliance, SMS, Reports, and Notifications screens
    - Smoke test each screen renders with mocked data
    - Test compliance expiry pill colours
    - Test module gating
    - _Requirements: 43.1, 44.1, 45.1, 46.1, 47.1, 55.1_

- [ ] 18. Phase 9 Checkpoint
  - Ensure all module screens batch 5 render correctly
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.


- [ ] 19. Phase 10 — Module Screens Batch 6 (Portal, Kiosk)
  - [ ] 19.1 Redesign Customer Portal screen
    - Restyle `/portal` with existing customer self-service functionality using Konsta UI components
    - Preserve all portal logic (view invoices, pay online, accept quotes, book appointments) unchanged
    - _Requirements: 48.1, 48.2_

  - [ ] 19.2 Redesign Kiosk screen
    - Restyle `/kiosk` as large-button check-in screen designed for tablet but functional on phone
    - When user role is `kiosk`, show Kiosk screen instead of standard tabs (handled by KonstaShell)
    - Call `POST /kiosk/check-in` unchanged
    - _Requirements: 49.1, 49.2, 49.3_

  - [ ]* 19.3 Write unit tests for Portal and Kiosk screens
    - Smoke test each screen renders with mocked data
    - Test kiosk role hides standard tabs
    - _Requirements: 48.1, 49.1, 49.2_

- [ ] 20. Phase 10 Checkpoint
  - Ensure Portal and Kiosk screens render correctly
  - Ensure all tests pass and build succeeds
  - Ask the user if questions arise.

- [ ] 21. Phase 11 — Native Capacitor Plugins
  - [ ] 21.1 Install missing Capacitor plugin dependencies
    - Verify `@capacitor/camera`, `@capacitor/geolocation`, `@capacitor/push-notifications`, `@capacitor/preferences`, `@capacitor/network`, `@capacitor/haptics` are installed (check package.json — most already present)
    - Install `@capacitor/status-bar` and `@capacitor/splash-screen` if not present
    - Run `npx cap sync` to sync native project configurations
    - _Requirements: 59.1, 59.2, 59.3, 59.4, 59.5, 59.6, 59.7, 59.8, 59.9_

  - [ ] 21.2 Wire Camera plugin into attachment screens
    - Integrate `@capacitor/camera` with `CameraResultType.Uri`, `CameraSource.Prompt`, quality 85
    - Wire into: invoice attachments (create step 5 and detail screen), job card attachments, compliance document upload, expense receipt capture
    - Upload captured photo as multipart to existing attachments endpoint
    - Fall back to standard `<input type="file">` on web browser (not native)
    - Guard with `isNativePlatform()` check
    - _Requirements: 50.1, 50.2, 50.3, 50.4, 50.5_

  - [ ] 21.3 Wire Geolocation plugin into job timer
    - Integrate `@capacitor/geolocation` into Active Jobs Board timer start
    - Use `enableHighAccuracy: false`, `timeout: 5000`
    - Include coordinates in start-timer request if backend accepts them
    - Continue silently if geolocation fails, permission denied, or backend doesn't accept geo data
    - _Requirements: 51.1, 51.2, 51.3, 51.4_

  - [ ] 21.4 Wire Push Notifications plugin
    - Integrate `@capacitor/push-notifications` to request permissions and register on login
    - POST device token to `POST /notifications/devices/register` with `{ token, platform }`
    - Show Konsta UI Toast on foreground notification received
    - Deep-link to relevant screen on notification tap based on `notification.data.route`
    - Handle notifications for: invoice paid, invoice overdue, job assigned, booking reminder, compliance expiring, new SMS
    - Continue without push if permission denied
    - _Requirements: 52.1, 52.2, 52.3, 52.4, 52.5, 52.6_

  - [ ] 21.5 Wire Network awareness
    - Integrate `@capacitor/network` to monitor connectivity status
    - Show red offline banner at top of app when offline
    - Hide banner when back online
    - No offline mutation queuing (out of scope)
    - _Requirements: 53.1, 53.2, 53.3, 53.4_

  - [ ] 21.6 Configure Status Bar and Splash Screen
    - Configure `@capacitor/splash-screen` with org logo and primary brand colour background
    - Configure `@capacitor/status-bar` for dark text on light backgrounds, light text on dark backgrounds (slate-900 hero screens)
    - Adapt status bar style per screen context
    - _Requirements: 54.1, 54.2, 54.3_

  - [ ] 21.7 Update native platform permissions
    - iOS Info.plist: add `NSCameraUsageDescription`, `NSPhotoLibraryUsageDescription`, `NSLocationWhenInUseUsageDescription` with appropriate descriptions
    - Android AndroidManifest.xml: add `android.permission.CAMERA`, `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`
    - Ensure all Capacitor plugin calls are guarded with platform detection
    - _Requirements: 50.6, 50.7, 51.5, 51.6, 61.1, 61.2, 61.3, 61.4_

  - [ ]* 21.8 Write unit tests for native plugin hooks
    - Test `useHaptics` no-ops on web without error
    - Test `useGeolocation` returns null on failure
    - Test camera falls back to file input on web
    - Test push notification registration flow with mocked plugin
    - _Requirements: 9.5, 51.4, 50.5, 52.6_

- [ ] 22. Phase 11 Checkpoint
  - Ensure all native plugins are wired correctly
  - Ensure all tests pass and build succeeds
  - Verify Camera, Geolocation, Push, Haptics, Network, Status Bar, Splash Screen integrations
  - Ask the user if questions arise.

- [ ] 23. Phase 12 — Property-Based Tests
  - [ ]* 23.1 Write property test for tab bar resolution (Property 1)
    - **Property 1: Tab bar always shows core tabs and resolves dynamic 4th tab**
    - Create `mobile/src/components/konsta/__tests__/KonstaTabbar.property.test.ts`
    - Generate random sets of module slugs (including empty set)
    - Assert: Home, Invoices, Customers, More always present (4 core tabs)
    - Assert: 4th tab is Jobs if `jobs` enabled, else Quotes if `quotes` enabled, else Bookings if `bookings` enabled, else Reports
    - Assert: exactly 5 tabs returned
    - Minimum 100 iterations
    - **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 4.7**

  - [ ]* 23.2 Write property test for navigation item filtering (Property 2)
    - **Property 2: Navigation item filtering matches sidebar logic**
    - Create `mobile/src/navigation/__tests__/TabConfig.property.test.ts`
    - Generate random combinations of enabled module slugs, trade family (including null), user role, and navigation items
    - Assert: only items where moduleSlug is null or in enabled set, AND tradeFamily is null or matches, AND allowedRoles is empty or contains user role
    - Assert: no other items included or excluded
    - Minimum 100 iterations
    - **Validates: Requirements 5.2, 5.4, 5.5, 5.6, 55.2, 55.4, 55.5**

  - [ ]* 23.3 Write property test for invoice calculation correctness (Property 3)
    - **Property 3: Invoice calculation correctness**
    - Create `mobile/src/utils/__tests__/invoiceCalc.property.test.ts`
    - Generate random line items (non-negative qty, non-negative unit_price, tax_rate in [0,1], gst_inclusive boolean), discount type and value, shipping, adjustment
    - Assert: `total = (subtotal - discountAmount) + taxAmount + shippingCharges + adjustment`
    - Assert: rounding to 2 decimal places for tax calculations
    - Minimum 100 iterations
    - **Validates: Requirements 20.8, 56.1**

  - [ ]* 23.4 Write property test for job card sorting invariant (Property 4)
    - **Property 4: Job card sorting invariant**
    - Create `mobile/src/utils/__tests__/jobSort.property.test.ts`
    - Generate random lists of job cards with status in {open, in_progress, completed, invoiced} and created_at timestamps
    - Assert: all `in_progress` before all `open`, all `open` before `completed`/`invoiced`
    - Assert: within each status group, ordered by `created_at` descending
    - Minimum 100 iterations
    - **Validates: Requirements 25.1, 56.3**

  - [ ]* 23.5 Write property test for currency formatting (Property 5)
    - **Property 5: Currency formatting correctness**
    - Create `mobile/src/utils/__tests__/formatNZD.property.test.ts`
    - Generate random numbers (0, negatives, large numbers up to 1e12), null, undefined
    - Assert: output starts with `"NZD"`, has exactly 2 decimal places
    - Assert: `formatNZD(null)` and `formatNZD(undefined)` return `"NZD0.00"`
    - Minimum 100 iterations
    - **Validates: Requirements 56.4**

  - [ ]* 23.6 Write property test for status colour mapping completeness (Property 6)
    - **Property 6: Status colour mapping completeness**
    - Create `mobile/src/utils/__tests__/statusConfig.property.test.ts`
    - Generate random valid status keys from {draft, issued, partially_paid, paid, overdue, voided, refunded, partially_refunded}
    - Assert: `STATUS_CONFIG[status]` returns object with non-empty `label`, non-empty `color` containing Tailwind text colour class, non-empty `bg` containing Tailwind background colour class
    - Minimum 100 iterations
    - **Validates: Requirements 10.3, 56.2**

- [ ] 24. Phase 12 Checkpoint
  - Ensure all property-based tests pass
  - Ensure all unit tests pass
  - Ask the user if questions arise.

- [ ] 25. Phase 13 — Build Verification and Acceptance
  - [ ] 25.1 Verify theme system and brand colour propagation
    - Confirm TenantContext CSS variables (`--color-primary`, `--color-secondary`, etc.) apply to Konsta UI components
    - Confirm default primary colour `#2563EB` is used when no org override is set
    - Confirm dark mode works via `dark:` Tailwind variants toggled by ThemeContext
    - Confirm org colour changes reflect across all themed components without restart
    - _Requirements: 10.1, 10.2, 10.4, 10.5_

  - [ ] 25.2 Verify module gating preservation
    - Confirm `ModuleGate` wraps screen content (not routes) for all module-gated screens
    - Confirm all 27 module slugs are honoured
    - Confirm trade family gating: vehicles → `automotive-transport`, construction → `building-construction`, hospitality → `food-hospitality`
    - Confirm disabled modules hide all gated UI elements (navigation items, screens, form sections)
    - _Requirements: 55.1, 55.2, 55.3, 55.4, 55.5_

  - [ ] 25.3 Verify business logic preservation
    - Confirm invoice calculation logic matches exactly (subtotal, discount, GST, shipping, adjustment, total)
    - Confirm `STATUS_CONFIG` colour map is correct for all 8 statuses
    - Confirm job card sorting preserves `statusOrder` logic
    - Confirm `formatNZD()` formatting is correct
    - Confirm `computeCreditableAmount()` and `computePaymentSummary()` are preserved
    - Confirm safe API consumption patterns on every API call
    - _Requirements: 56.1, 56.2, 56.3, 56.4, 56.5, 56.6, 56.7, 57.1, 57.2, 57.3, 57.4, 57.5, 57.6_

  - [ ] 25.4 Verify exclusions are respected
    - Confirm no global admin screens are included
    - Confirm no org admin settings screens are included
    - Confirm no `/settings` hub, onboarding wizard, branch transfers, staff schedule, franchise admin, data import/export, accounting/banking/tax editors are included
    - _Requirements: 58.1, 58.2, 58.3, 58.4, 58.5, 58.6, 58.7, 58.8, 58.9, 58.10_

  - [ ] 25.5 Verify touch targets and accessibility
    - Confirm all interactive elements have minimum 44×44 CSS pixel touch targets
    - Confirm safe area insets are respected
    - Confirm minimum font sizes (12px secondary, 14px+ primary)
    - Confirm viewport range 320px–430px is supported
    - Confirm dark mode works on all components
    - _Requirements: 60.1, 60.2, 60.3, 60.4, 60.5, 60.6_

  - [ ] 25.6 Final build and test verification
    - Run `npm run build` in `mobile/` — must succeed with zero errors
    - Run `npm run test` in `mobile/` — all tests must pass
    - Verify all 62 requirements are covered by implementation tasks
    - _Requirements: 62.1, 62.2, 62.3, 62.4, 62.5, 62.6, 62.7, 62.8, 62.9, 62.10, 62.11, 62.12, 62.13, 62.14, 62.15, 62.16, 62.17, 62.18, 62.19_

- [ ] 26. Final Checkpoint — Ensure all tests pass
  - Ensure all unit tests, property tests, and build pass
  - Verify the complete Konsta UI redesign is functional
  - Ask the user if questions arise.

- [ ] 27. Git push all changes to repository
  - [ ] 27.1 Stage all changed and new files
  - [ ] 27.2 Commit with descriptive message summarising the Konsta UI redesign changes
  - [ ] 27.3 Push to remote repository

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each phase
- Property tests validate the 6 universal correctness properties from the design document
- Unit tests validate specific examples, edge cases, and screen rendering
- All API endpoints, business logic, contexts, and module gating are preserved unchanged
- The implementation language is TypeScript throughout (React 19 + Vite 8 + Tailwind CSS 4 + Konsta UI v5)
- Use v2 API endpoints where available (time entries, expenses, staff, schedule, purchase orders, recurring, compliance docs)
- Use `offset` (not `skip`) and `limit` for all pagination parameters
- All Capacitor plugin calls must be guarded with `isNativePlatform()` platform detection

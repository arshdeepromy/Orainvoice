# Requirements Document

## Introduction

This document specifies the requirements for redesigning the OraInvoice mobile app (Capacitor) frontend using Konsta UI v5 with Tailwind CSS 4. The redesign replaces the existing basic Tailwind styling with native-feeling iOS and Material Design components while preserving all business logic, module gating, calculations, contexts, and data flows exactly as they are. This is a frontend-only redesign — no backend changes, no API contract changes, no auth flow changes.

## Glossary

- **Mobile_App**: The OraInvoice Capacitor-based mobile application for iOS and Android
- **Konsta_UI**: A mobile UI component library (v5) providing iOS and Material Design styled React components
- **Tailwind_CSS_4**: The utility-first CSS framework (version 4) used for styling
- **Capacitor**: The native bridge framework (v7) enabling access to device APIs (camera, geolocation, push notifications, haptics, etc.)
- **Module_Gate**: The system that conditionally shows/hides features based on which modules are enabled for an organisation
- **Trade_Family**: The business type classification (automotive-transport, building-construction, food-hospitality, etc.) that gates trade-specific features
- **Bottom_Tab_Bar**: The 5-tab navigation bar fixed at the bottom of the screen
- **More_Drawer**: The sheet/panel opened by the "More" tab containing all module-gated navigation items
- **FAB**: Floating Action Button positioned bottom-right on list screens for primary creation actions
- **Pull_To_Refresh**: The gesture-triggered data refresh on list screens
- **Safe_API_Consumption**: The mandatory pattern of using optional chaining and nullish coalescing on all API response data
- **KonstaApp_Wrapper**: The root `<App>` component from Konsta UI that provides platform-aware theming
- **Status_Config**: The colour mapping object for invoice/job statuses
- **TenantContext**: The React context providing org-customizable brand colours and settings
- **ModuleContext**: The React context providing module enabled/disabled state per organisation
- **BranchContext**: The React context managing branch selection and X-Branch-Id header injection
- **AuthContext**: The React context managing JWT auth, refresh tokens, MFA, and user session

---

## Requirements

### Requirement 1: Konsta UI v5 and Tailwind CSS 4 Installation

**User Story:** As a developer, I want Konsta UI v5 and Tailwind CSS 4 properly installed and configured, so that all mobile components render with native iOS and Material Design styling.

#### Acceptance Criteria

1. THE Mobile_App SHALL include `konsta` (v5) as a production dependency
2. THE Mobile_App SHALL use Tailwind CSS version 4 with `@tailwindcss/postcss` as a dev dependency
3. THE Mobile_App SHALL configure `tailwind.config.js` using `konsta/config` wrapper with content paths covering `./index.html` and `./src/**/*.{js,ts,jsx,tsx}`
4. THE Mobile_App SHALL extend the Tailwind theme with `primary` mapped to `var(--color-primary, #2563EB)` and `secondary` mapped to `var(--color-secondary, #1E40AF)`
5. THE Mobile_App SHALL set `darkMode: 'class'` in the Tailwind configuration

### Requirement 2: KonstaApp Root Wrapper

**User Story:** As a user, I want the app to automatically render iOS-style components on iPhone and Material Design on Android, so that the app feels native on my device.

#### Acceptance Criteria

1. THE Mobile_App SHALL wrap the entire application in a KonstaApp_Wrapper component at the root level
2. WHEN the platform is iOS, THE KonstaApp_Wrapper SHALL use theme `'ios'`
3. WHEN the platform is Android or web, THE KonstaApp_Wrapper SHALL use theme `'material'`
4. THE KonstaApp_Wrapper SHALL enable the `safeAreas` prop to respect device safe area insets
5. THE KonstaApp_Wrapper SHALL be placed outside all existing context providers (AuthContext, TenantContext, ModuleContext, BranchContext, ThemeContext, OfflineContext, BiometricContext) so that providers remain unchanged

### Requirement 3: Context Preservation

**User Story:** As a developer, I want all existing React contexts preserved without modification, so that business logic, auth, module gating, and branch scoping continue to function identically.

#### Acceptance Criteria

1. THE Mobile_App SHALL preserve AuthContext with JWT in-memory storage, httpOnly cookie refresh tokens, 401 mutex refresh, MFA, passkeys, and Google OAuth unchanged
2. THE Mobile_App SHALL preserve TenantContext with org-customizable CSS variables (`--color-primary`, `--color-secondary`, `--sidebar-bg`, etc.) unchanged
3. THE Mobile_App SHALL preserve ModuleContext with `useModules().isEnabled(slug)` unchanged
4. THE Mobile_App SHALL preserve BranchContext with `X-Branch-Id` header injection from localStorage unchanged
5. THE Mobile_App SHALL preserve ThemeContext, OfflineContext, and BiometricContext unchanged
6. THE Mobile_App SHALL maintain the existing provider hierarchy order: Auth → Tenant → Module → Branch → Theme → Offline → Biometric

### Requirement 4: Bottom Tab Bar Navigation

**User Story:** As a user, I want a bottom tab bar with my most-used features always accessible, so that I can quickly navigate between core sections.

#### Acceptance Criteria

1. THE Mobile_App SHALL render a Bottom_Tab_Bar with exactly 5 tabs using Konsta UI Tabbar and TabbarLink components
2. THE Bottom_Tab_Bar SHALL display tabs in this order: Home (dashboard), Invoices, Customers, Jobs, More
3. THE Bottom_Tab_Bar SHALL always display the Home, Invoices, Customers, and More tabs regardless of module state
4. WHEN the `jobs` module is enabled, THE Bottom_Tab_Bar SHALL display the Jobs tab with a construct-outline icon
5. WHEN the `jobs` module is disabled AND the `quotes` module is enabled, THE Bottom_Tab_Bar SHALL replace the Jobs tab with a Quotes tab
6. WHEN the `jobs` module is disabled AND the `quotes` module is disabled AND the `bookings` module is enabled, THE Bottom_Tab_Bar SHALL replace the Jobs tab with a Bookings tab
7. WHEN the `jobs` module, `quotes` module, and `bookings` module are all disabled, THE Bottom_Tab_Bar SHALL replace the Jobs tab with a Reports tab
8. THE Bottom_Tab_Bar SHALL respect device safe area insets at the bottom

### Requirement 5: More Drawer Navigation

**User Story:** As a user, I want the More tab to show all my enabled features organized by category, so that I can access any part of the app.

#### Acceptance Criteria

1. WHEN the user taps the More tab, THE Mobile_App SHALL open a Konsta UI Sheet or Panel component
2. THE More_Drawer SHALL filter navigation items using the identical logic as the existing sidebar: `module enabled + feature flag + trade family + user role`
3. THE More_Drawer SHALL group items by category with section headers: Sales, Operations, People, Industry-specific, Assets & Compliance, Communications, Finance, Other, Account
4. WHEN a module is disabled for the organisation, THE More_Drawer SHALL hide all navigation items gated by that module
5. WHEN the trade family does not match an item's required trade family, THE More_Drawer SHALL hide that item
6. WHEN the user role is not `org_admin`, THE More_Drawer SHALL hide items marked `adminOnly`
7. THE More_Drawer SHALL render each item as a Konsta UI ListItem with leading icon, title, optional badge, and chevron
8. WHEN the user taps a navigation item, THE More_Drawer SHALL navigate to the corresponding route and close the drawer

### Requirement 6: Navbar Header

**User Story:** As a user, I want a consistent header bar on every screen with contextual actions, so that I can navigate back and perform screen-specific actions.

#### Acceptance Criteria

1. THE Mobile_App SHALL render a Konsta UI Navbar on every screen
2. WHEN on a detail or nested screen, THE Navbar SHALL display a back button on the left
3. WHEN on a root-level screen, THE Navbar SHALL display the page title centred
4. THE Navbar SHALL display page-specific action buttons on the right (search, filter, add, overflow menu)
5. WHEN the `branch_management` module is enabled, THE Navbar SHALL display a branch selector pill as a subtitle that opens a branch picker sheet on tap

### Requirement 7: Floating Action Button

**User Story:** As a user, I want a prominent button on list screens to quickly create new items, so that I can perform primary actions with one tap.

#### Acceptance Criteria

1. WHEN on a list screen that supports creation (invoices, customers, job cards, quotes, bookings, expenses, purchase orders, recurring invoices, assets, catalogue items), THE Mobile_App SHALL display a FAB in the bottom-right corner
2. WHEN the user taps the FAB, THE Mobile_App SHALL navigate to the creation form for that screen's entity
3. THE FAB SHALL be styled with the primary brand colour and positioned above the Bottom_Tab_Bar

### Requirement 8: Pull-to-Refresh

**User Story:** As a user, I want to pull down on any list to refresh the data, so that I always see the latest information.

#### Acceptance Criteria

1. THE Mobile_App SHALL implement Pull_To_Refresh on every list screen
2. WHEN the user pulls down on a list screen, THE Mobile_App SHALL re-fetch data from the corresponding API endpoint
3. WHILE a refresh is in progress, THE Mobile_App SHALL display a loading indicator

### Requirement 9: Haptic Feedback

**User Story:** As a user, I want tactile feedback on interactions, so that the app feels responsive and native.

#### Acceptance Criteria

1. WHEN the user taps a primary action button, THE Mobile_App SHALL trigger a light impact haptic via `@capacitor/haptics`
2. WHEN the user toggles a switch or changes a status, THE Mobile_App SHALL trigger a medium impact haptic
3. WHEN the user confirms a destructive action (delete, void), THE Mobile_App SHALL trigger a heavy impact haptic
4. WHEN the user performs a swipe action on a list item, THE Mobile_App SHALL trigger a selection haptic
5. IF the device does not support haptics or the app is running in a web browser, THEN THE Mobile_App SHALL skip haptic calls without error


### Requirement 10: Theme System with Org-Customizable Brand Colours

**User Story:** As an organisation owner, I want my brand colours to apply throughout the mobile app, so that the app reflects my business identity.

#### Acceptance Criteria

1. THE Mobile_App SHALL read CSS variables from TenantContext (`--color-primary`, `--color-secondary`, `--sidebar-bg`, `--sidebar-text`, `--content-bg`, etc.) and apply them to Konsta UI components
2. THE Mobile_App SHALL use `#2563EB` (blue-600) as the default primary colour when no org override is set
3. THE Mobile_App SHALL use the status colour map for invoice and job statuses: draft=gray-500, issued=blue-600, partially_paid=amber-600, paid=emerald-600, overdue=red-600, voided=gray-400, refunded=orange-600, partially_refunded=orange-600
4. THE Mobile_App SHALL support dark mode via the `dark:` Tailwind variant class toggled by ThemeContext
5. WHEN the org changes their primary colour via TenantContext, THE Mobile_App SHALL reflect the new colour across all themed components without requiring a restart

### Requirement 11: Login Screen

**User Story:** As a user, I want a polished login screen with all authentication options, so that I can sign in securely using my preferred method.

#### Acceptance Criteria

1. THE Mobile_App SHALL render the login screen at route `/login` with a hero header using gradient from slate-900 to indigo-900
2. THE Mobile_App SHALL display the OraInvoice logo in the hero section
3. THE Mobile_App SHALL render email and password inputs using Konsta UI ListInput components
4. THE Mobile_App SHALL render a full-width primary "Sign In" button
5. THE Mobile_App SHALL render secondary buttons for "Continue with Google" and "Sign in with Passkey"
6. THE Mobile_App SHALL render footer links for "Forgot password?" and "Create account"
7. WHEN the user submits credentials, THE Mobile_App SHALL POST to `/auth/login` with the existing auth flow unchanged
8. THE Mobile_App SHALL support both dark and light mode on the login screen

### Requirement 12: MFA Verification Screen

**User Story:** As a user with MFA enabled, I want to verify my identity with my chosen method, so that my account remains secure.

#### Acceptance Criteria

1. THE Mobile_App SHALL render the MFA screen at route `/login/mfa` with a Konsta UI Page and Block for instructions
2. THE Mobile_App SHALL render a 6-digit code input with numeric keyboard and autoFocus
3. THE Mobile_App SHALL render a segmented control for method selection (TOTP, SMS, Email, Passkey, Backup)
4. THE Mobile_App SHALL render a "Verify" primary button and a "Try another method" link
5. WHEN the user submits the code, THE Mobile_App SHALL POST to `/auth/mfa/verify` unchanged

### Requirement 13: Signup Wizard

**User Story:** As a new user, I want a guided signup flow, so that I can create my account and subscribe in a few steps.

#### Acceptance Criteria

1. THE Mobile_App SHALL render the signup wizard at route `/signup` as a multi-step Konsta UI page with progress dots
2. THE Mobile_App SHALL include Step 1 (Account: name, email, password, business name), Step 2 (Plan selection: Mech Pro Plan $60 NZD/month), Step 3 (Stripe Elements card form), Step 4 (Confirmation)
3. WHEN the user completes all steps, THE Mobile_App SHALL POST to `/auth/register` with the existing registration flow unchanged
4. THE Mobile_App SHALL embed Stripe Elements in a Konsta UI Block for payment input

### Requirement 14: Password Reset and Email Verification

**User Story:** As a user, I want to reset my password and verify my email from mobile, so that I can recover access and complete registration.

#### Acceptance Criteria

1. THE Mobile_App SHALL render `/forgot-password` as a single-form Konsta UI page with email input and primary submit button, POSTing to `/auth/password-reset/request`
2. THE Mobile_App SHALL render `/reset-password` as a single-form Konsta UI page with new password input, POSTing to `/auth/password-reset/complete`
3. THE Mobile_App SHALL render `/verify-email` as a status page that auto-verifies via token, POSTing to `/auth/verify-email`

### Requirement 15: Landing Page (Mobile-Optimized)

**User Story:** As a visitor, I want a mobile-optimized marketing page, so that I can learn about OraInvoice and sign up from my phone.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/` as a mobile-optimized landing page with hero gradient, headline, and CTA buttons (Sign Up, Login)
2. THE Mobile_App SHALL display feature cards in a vertical stack layout
3. THE Mobile_App SHALL display a pricing card and footer

### Requirement 16: Public Invoice Payment Page

**User Story:** As a customer, I want to pay an invoice from a shared link on my phone, so that I can settle my bill quickly.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/pay/:token` with an invoice summary card (org logo, invoice number, customer, collapsed line items, total)
2. THE Mobile_App SHALL embed Stripe Elements card form in a Konsta UI Block
3. THE Mobile_App SHALL render a "Pay NZD X,XXX.XX" primary button with the formatted total
4. THE Mobile_App SHALL call `GET /public/invoice/:token` for invoice data and use Stripe Elements for payment unchanged

### Requirement 17: Dashboard Screen

**User Story:** As a user, I want a dashboard showing my key business metrics and recent activity, so that I can monitor my business at a glance.

#### Acceptance Criteria

1. THE Mobile_App SHALL render the dashboard at route `/dashboard` with a greeting "Hello, {first_name}" and branch selector subtitle
2. THE Mobile_App SHALL display stat cards in a 2-column grid using Konsta UI Card components: Revenue (this month), Outstanding receivables, Overdue count (red badge if > 0), Active jobs (only if `jobs` module enabled)
3. THE Mobile_App SHALL display a scrollable horizontal row of quick action Chip buttons: New Invoice, New Customer, New Quote (if `quotes` enabled), New Job (if `jobs` enabled), New Booking (if `bookings` enabled)
4. THE Mobile_App SHALL display a "Recent Invoices" section with the last 5 invoices as a Konsta UI List, tappable to navigate
5. THE Mobile_App SHALL display a "Needs Attention" section listing overdue invoices with red status indicators
6. WHEN the `compliance_docs` module is enabled AND documents are expiring, THE Mobile_App SHALL display a yellow compliance alert card with count
7. THE Mobile_App SHALL call `GET /dashboard/stats` and `GET /invoices?status=overdue` with safe API consumption patterns
8. THE Mobile_App SHALL support Pull_To_Refresh on the dashboard

### Requirement 18: Invoice List Screen

**User Story:** As a user, I want to browse, search, and filter my invoices in a mobile-optimized list, so that I can find and manage invoices quickly.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/invoices` as a full-screen list (replacing the desktop split-pane pattern)
2. THE Mobile_App SHALL render a Konsta UI Searchbar with status filter chips below (All, Draft, Issued, Partially Paid, Paid, Overdue, Voided, Refunded, Partially Refunded)
3. THE Mobile_App SHALL render each invoice as a Konsta UI ListItem showing: customer name (bold), invoice number (muted), NZD total (right-aligned, large), status badge (coloured chip), due date, Stripe icon if applicable, paperclip icon if `attachment_count > 0`
4. THE Mobile_App SHALL support swipe-left actions on list items: Mark Sent, Email, Void
5. THE Mobile_App SHALL support swipe-right actions on list items: Record Payment, Duplicate
6. THE Mobile_App SHALL implement infinite scroll pagination (25 per page) using `offset` and `limit` parameters
7. WHEN the user taps an invoice row, THE Mobile_App SHALL navigate to `/invoices/:id` detail screen
8. THE Mobile_App SHALL display a FAB for "+ New Invoice" navigating to `/invoices/new`
9. THE Mobile_App SHALL support Pull_To_Refresh
10. THE Mobile_App SHALL call `GET /invoices` with safe API consumption: `res.data?.items ?? []`, `res.data?.total ?? 0`

### Requirement 19: Invoice Detail Screen

**User Story:** As a user, I want to view full invoice details with all actions available, so that I can manage invoices without switching to desktop.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/invoices/:id` with a header showing invoice number, back button, and overflow menu (•••)
2. THE Mobile_App SHALL display a hero card with customer name, vehicle (if any), status badge, total NZD, and balance due
3. THE Mobile_App SHALL display sections for: Vehicles (if vehicles module enabled), Line items (collapsible), Totals (subtotal, discount, GST, shipping, adjustment, total using exact existing calculation logic), Payments, Credit notes, Attachments (with thumbnail row and Camera button for new), Notes
4. THE Mobile_App SHALL provide a bottom sheet action menu with: Email, Mark Sent, Void, Duplicate, Download PDF, Print, Print POS Receipt, Record Payment, Create Credit Note, Process Refund, Share Link, Send Reminder, Delete
5. THE Mobile_App SHALL use Konsta UI Sheet for modal forms (record payment, void reason, credit note, refund)
6. THE Mobile_App SHALL call `GET /invoices/:id` and all action endpoints unchanged
7. THE Mobile_App SHALL preserve `computeCreditableAmount()` and `computePaymentSummary()` helper logic exactly


### Requirement 20: Invoice Create/Edit Screen

**User Story:** As a user, I want to create and edit invoices on mobile with all fields and line item options, so that I can invoice customers from the field.

#### Acceptance Criteria

1. THE Mobile_App SHALL render routes `/invoices/new` and `/invoices/:id/edit` as a multi-step form with Konsta UI Blocks per step
2. THE Mobile_App SHALL include Step 1 (Customer & Vehicle): customer selector with searchable list, vehicle selector with multi-select chip pills (only if `vehicles` module + automotive-transport trade)
3. THE Mobile_App SHALL include Step 2 (Dates & Meta): issue date, due date, payment terms dropdown, salesperson select, subject, order number, GST number (read-only from org)
4. THE Mobile_App SHALL include Step 3 (Line Items): list of line items as Konsta UI Cards, each with description, qty, rate, tax mode (inclusive/exclusive/exempt), discount, computed amount; buttons for "Add from Catalogue", "Add from Inventory" (if `inventory` module), "Add Labour", "Add Empty Line"
5. THE Mobile_App SHALL include Step 4 (Adjustments): discount (% or $ toggle), shipping charges, adjustment
6. THE Mobile_App SHALL include Step 5 (Notes & Attachments): customer notes, internal notes, terms, attachments with file upload and Camera button (max 5 files, 20MB each)
7. THE Mobile_App SHALL include Step 6 (Review & Save): summary card with buttons "Save as Draft", "Save & Send", "Mark Paid & Email" (if balance zero), "Make Recurring" toggle, payment method selector
8. THE Mobile_App SHALL compute line item totals, subtotal, discount, GST, and total using the exact existing calculation logic (subtotal = sum of line amounts; discount = percentage or fixed; GST handles inclusive/exclusive/exempt per line; total = afterDiscount + taxAmount + shipping + adjustment)
9. THE Mobile_App SHALL call `POST /invoices`, `PUT /invoices/:id`, `GET /catalogue/items`, `GET /org/salespeople`, `GET /inventory/stock-items`, `GET /catalogue/labour-rates`, `POST /invoices/:id/attachments` unchanged
10. THE Mobile_App SHALL use `formatNZD()` for all currency display: `NZD${Number(amount ?? 0).toLocaleString('en-NZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

### Requirement 21: Customer List Screen

**User Story:** As a user, I want to browse and search my customers on mobile, so that I can find customer information in the field.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/customers` with a sticky Konsta UI Searchbar
2. THE Mobile_App SHALL render each customer as a Konsta UI ListItem with: display_name or `${first_name} ${last_name}` as title, company_name or phone as subtitle, receivables badge (red if > 0) on the right
3. THE Mobile_App SHALL implement infinite scroll pagination
4. THE Mobile_App SHALL display a FAB for "+ New Customer"
5. WHEN the user taps a customer row, THE Mobile_App SHALL navigate to `/customers/:id`
6. THE Mobile_App SHALL call `GET /customers` with safe API consumption

### Requirement 22: Customer Create Screen

**User Story:** As a user, I want to quickly add new customers from mobile, so that I can capture customer details on-site.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/customers/new` as a single-page Konsta UI form
2. THE Mobile_App SHALL include fields: First Name (required), Last Name, Company Name, Email, Phone, Mobile Phone, Work Phone, Address (textarea)
3. THE Mobile_App SHALL render "Save" and "Save & Add Another" buttons
4. WHEN the user submits, THE Mobile_App SHALL POST to `/customers` unchanged
5. THE Mobile_App SHALL validate that First Name is provided before submission

### Requirement 23: Customer Profile Screen

**User Story:** As a user, I want to view full customer details with their history, so that I can understand the customer relationship.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/customers/:id` with a header card showing avatar (initials), name, company, and primary contact buttons (call via `tel:`, email via `mailto:`, SMS via `sms:`)
2. THE Mobile_App SHALL display tabs using Konsta UI Segmented: Profile, Invoices, Vehicles (if `vehicles` module + automotive trade), Reminders, History
3. THE Mobile_App SHALL display the Profile tab with read-only fields and an "Edit" button opening a modal form
4. THE Mobile_App SHALL display the Invoices tab with a list of the customer's invoices showing status and total
5. THE Mobile_App SHALL display the Vehicles tab with linked vehicles (only if `vehicles` module + automotive-transport trade)
6. THE Mobile_App SHALL display the Reminders tab with WOF/service reminder configuration from `GET /customers/:id/reminders`
7. THE Mobile_App SHALL call `GET /customers/:id`, `GET /invoices?customer_id=:id`, `GET /vehicles?customer_id=:id` with safe API consumption

### Requirement 24: Quote Screens

**User Story:** As a user, I want to create, view, and manage quotes on mobile, so that I can send quotes to customers from the field.

#### Acceptance Criteria

1. WHEN the `quotes` module is enabled, THE Mobile_App SHALL render route `/quotes` as a list with status filters (Draft, Sent, Accepted, Declined, Expired), FAB for "+ New Quote", and Pull_To_Refresh
2. THE Mobile_App SHALL render route `/quotes/new` as a stepper form: Step 1 (Customer), Step 2 (Line items), Step 3 (Discount, terms, notes, expiry date), Step 4 (Save/Send)
3. THE Mobile_App SHALL render route `/quotes/:id` with a hero card (customer, total, status), line items list, and bottom action sheet (Send, Convert to Invoice, Edit, Duplicate)
4. THE Mobile_App SHALL call `GET /quotes`, `POST /quotes`, `GET /quotes/:id`, `POST /quotes/:id/convert`, `POST /quotes/:id/email` unchanged
5. THE Mobile_App SHALL wrap all quote screens in a Module_Gate for the `quotes` module

### Requirement 25: Job Card List Screen

**User Story:** As a user, I want to browse job cards sorted by priority, so that I can see active work first.

#### Acceptance Criteria

1. WHEN the `jobs` module is enabled, THE Mobile_App SHALL render route `/job-cards` as a list sorted by: in_progress first, open second, completed/invoiced last (using `statusOrder` logic), then by `created_at` descending within each group
2. THE Mobile_App SHALL render each job card with: status colour pill, customer name, vehicle rego as subtitle, assigned-to avatar on the right
3. THE Mobile_App SHALL provide status filter and "assigned to me" toggle
4. THE Mobile_App SHALL display a FAB for "+ New Job Card"
5. THE Mobile_App SHALL call `GET /job-cards` with safe API consumption

### Requirement 26: Job Card Create Screen

**User Story:** As a user, I want to create job cards on mobile with customer, vehicle, parts, and labour, so that I can start jobs from the field.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/job-cards/new` as a stepper: Step 1 (Customer & Vehicle selectors), Step 2 (Description, service type, assigned staff), Step 3 (Parts from inventory, if `inventory` module enabled), Step 4 (Labour entries from labour rates), Step 5 (Save)
2. THE Mobile_App SHALL call `POST /job-cards` unchanged
3. THE Mobile_App SHALL wrap the screen in a Module_Gate for the `jobs` module

### Requirement 27: Job Card Detail Screen

**User Story:** As a user, I want to view and manage a job card with all its parts, labour, and attachments, so that I can track job progress.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/job-cards/:id` with a hero section (customer, vehicle, status, assigned staff)
2. THE Mobile_App SHALL display sections: Parts, Labour, Notes, Attachments (with Camera button for photos), Status History
3. THE Mobile_App SHALL provide bottom actions: Edit, Add Parts, Add Labour, Upload Attachment, Complete Job (creates invoice), Reassign
4. THE Mobile_App SHALL call `GET /job-cards/:id`, `PUT /job-cards/:id`, `POST /job-cards/:id/complete`, `POST /job-cards/:id/attachments` unchanged

### Requirement 28: Active Jobs Board (Timer Screen)

**User Story:** As a field worker, I want to start/stop timers on active jobs with live counters, so that I can track my work time accurately.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/jobs` as a card-based view of in-progress and open jobs
2. THE Mobile_App SHALL display each job card with: customer, vehicle, live timer (HH:MM:SS updating every second) if started
3. THE Mobile_App SHALL provide buttons per card: Start Timer / Stop Timer (toggle), Assign to Me, Take Over (if assigned to other), Confirm Done
4. WHEN the user taps Start Timer, THE Mobile_App SHALL call `POST /job-cards/:id/start-timer` and optionally request GPS location via `@capacitor/geolocation` (silent, non-blocking)
5. WHEN the user taps Stop Timer, THE Mobile_App SHALL call `POST /job-cards/:id/stop-timer`
6. THE Mobile_App SHALL trigger haptics on timer start and stop
7. IF geolocation is unavailable or permission denied, THEN THE Mobile_App SHALL continue without location data silently

### Requirement 29: Vehicle Screens

**User Story:** As an automotive trade user, I want to look up vehicles by rego and view their service history, so that I can reference vehicle details on-site.

#### Acceptance Criteria

1. WHEN the `vehicles` module is enabled AND the trade family is `automotive-transport`, THE Mobile_App SHALL render route `/vehicles` with a searchbar (search by rego) and list items showing: rego (large, monospace), make/model/year, owner name, WOF expiry pill (red if expired, amber if <30 days)
2. THE Mobile_App SHALL render route `/vehicles/:id` with: hero (large rego, make/model/year/colour), stats (WOF expiry, rego expiry, odometer, service due date), sections (Service History, Linked Customer), and "Edit" button for dates
3. THE Mobile_App SHALL call `GET /vehicles`, `GET /vehicles/:id` with safe API consumption
4. THE Mobile_App SHALL wrap vehicle screens in a Module_Gate for `vehicles` module AND trade family check for `automotive-transport`

### Requirement 30: Booking Calendar Screen

**User Story:** As a user, I want to view and manage bookings on a calendar, so that I can schedule appointments from mobile.

#### Acceptance Criteria

1. WHEN the `bookings` module is enabled, THE Mobile_App SHALL render route `/bookings` with a calendar view and list of bookings for the selected date below
2. THE Mobile_App SHALL display a FAB for "+ New Booking"
3. WHEN the user taps a booking, THE Mobile_App SHALL open an edit sheet
4. THE Mobile_App SHALL provide a "Create Job from Booking" action in the booking detail sheet
5. THE Mobile_App SHALL use a long-press menu with date picker for rescheduling (replacing desktop drag-and-drop)
6. THE Mobile_App SHALL call `GET /bookings`, `POST /bookings`, `PUT /bookings/:id`, `DELETE /bookings/:id` unchanged

### Requirement 31: Inventory Screen

**User Story:** As a user, I want to check stock levels and manage inventory from mobile, so that I can verify availability in the field.

#### Acceptance Criteria

1. WHEN the `inventory` module is enabled, THE Mobile_App SHALL render route `/inventory` with Konsta UI tabs: Stock Levels, Usage History, Update Log, Reorder Alerts, Suppliers
2. THE Mobile_App SHALL render the Stock Levels tab as a searchable list with: item name, available qty, sell price, brand as subtitle
3. WHEN the user taps a stock item, THE Mobile_App SHALL open a detail sheet with all StockItem fields and an "Adjust Stock" action
4. THE Mobile_App SHALL render Reorder Alerts as red-bordered cards
5. THE Mobile_App SHALL call `GET /inventory/stock-items`, `POST /inventory/stock-items/:id/adjust`, `GET /inventory/suppliers` with safe API consumption

### Requirement 32: Catalogue Items Screen

**User Story:** As a user, I want to manage catalogue items and labour rates from mobile, so that I can update pricing on the go.

#### Acceptance Criteria

1. WHEN the `inventory` module is enabled, THE Mobile_App SHALL render route `/items` with tabs: Items, Labour Rates, Service Types
2. THE Mobile_App SHALL render each CatalogueItem with name, default_price, and GST applicable badge
3. WHEN the user taps an item, THE Mobile_App SHALL open an edit sheet
4. THE Mobile_App SHALL display a FAB for "+ Add Item"
5. THE Mobile_App SHALL call `GET /catalogue/items`, `POST /catalogue/items`, `PUT /catalogue/items/:id`, `GET /catalogue/labour-rates` unchanged


### Requirement 33: Staff Screen

**User Story:** As a manager, I want to view and manage staff from mobile, so that I can handle team operations remotely.

#### Acceptance Criteria

1. WHEN the `staff` module is enabled, THE Mobile_App SHALL render route `/staff` as a list with staff name, role badges, branch, and status
2. WHEN the user taps a staff member, THE Mobile_App SHALL open an edit sheet
3. THE Mobile_App SHALL call `GET /api/v2/staff`, `POST /api/v2/staff`, `PUT /api/v2/staff/:id` with safe API consumption

### Requirement 34: Projects Screen

**User Story:** As a user, I want to view project progress and budgets from mobile, so that I can monitor project health remotely.

#### Acceptance Criteria

1. WHEN the `projects` module is enabled, THE Mobile_App SHALL render route `/projects` as a list with project name, status, budget, and progress bar
2. THE Mobile_App SHALL render route `/projects/:id` as a project dashboard with financials, tasks, and progress
3. THE Mobile_App SHALL call `GET /projects`, `GET /projects/:id` with safe API consumption

### Requirement 35: Expenses Screen

**User Story:** As a user, I want to log expenses with receipt photos from mobile, so that I can capture expenses immediately when they occur.

#### Acceptance Criteria

1. WHEN the `expenses` module is enabled, THE Mobile_App SHALL render route `/expenses` as a list with date, category, amount, and receipt indicator
2. THE Mobile_App SHALL provide a creation form with a Camera button for receipt capture using `@capacitor/camera`
3. THE Mobile_App SHALL include a category picker in the expense form
4. THE Mobile_App SHALL display a FAB for "+ New Expense"
5. THE Mobile_App SHALL call `GET /api/v2/expenses`, `POST /api/v2/expenses` with safe API consumption

### Requirement 36: Time Tracking Screen

**User Story:** As a field worker, I want to clock in/out and view my time entries, so that I can track my hours accurately.

#### Acceptance Criteria

1. WHEN the `time_tracking` module is enabled, THE Mobile_App SHALL render route `/time-tracking` with prominent clock-in/clock-out buttons, today's entries list, and a manual entry form
2. THE Mobile_App SHALL call `GET /api/v2/time-entries`, `POST /api/v2/time-entries` with safe API consumption

### Requirement 37: Schedule Screen

**User Story:** As a user, I want to view staff and bay schedules on a calendar, so that I can plan work allocation.

#### Acceptance Criteria

1. WHEN the `scheduling` module is enabled, THE Mobile_App SHALL render route `/schedule` as a calendar view of staff/bay schedules
2. THE Mobile_App SHALL support creating and editing schedule entries
3. THE Mobile_App SHALL call `GET /api/v2/schedule`, `POST /api/v2/schedule` with safe API consumption

### Requirement 38: POS Screen

**User Story:** As a retail/hospitality user, I want a full-screen mobile POS layout, so that I can process sales from a mobile device.

#### Acceptance Criteria

1. WHEN the `pos` module is enabled, THE Mobile_App SHALL render route `/pos` as a full-screen mobile POS layout
2. THE Mobile_App SHALL display a product grid (2-column Konsta UI Card grid) populated from catalogue items
3. THE Mobile_App SHALL display an order panel as a bottom sheet (drag up to expand) showing selected items, quantities, and running total
4. THE Mobile_App SHALL display a payment sheet as the final step with payment method selection
5. THE Mobile_App SHALL call `GET /catalogue/items` for products and `POST /invoices` + `POST /payments/cash` for order completion unchanged

### Requirement 39: Recurring Invoices Screen

**User Story:** As a user, I want to manage recurring invoice templates from mobile, so that I can control automated billing.

#### Acceptance Criteria

1. WHEN the `recurring_invoices` module is enabled, THE Mobile_App SHALL render route `/recurring` as a list with frequency badge per template
2. THE Mobile_App SHALL support swipe actions for pause and resume
3. THE Mobile_App SHALL call `GET /api/v2/recurring`, `POST /api/v2/recurring` with safe API consumption

### Requirement 40: Purchase Orders Screen

**User Story:** As a user, I want to view and manage purchase orders from mobile, so that I can track supplier orders in the field.

#### Acceptance Criteria

1. WHEN the `purchase_orders` module is enabled, THE Mobile_App SHALL render route `/purchase-orders` as a list with supplier, status, and total
2. THE Mobile_App SHALL render route `/purchase-orders/:id` with line items and a "Receive Stock" action
3. THE Mobile_App SHALL call `GET /api/v2/purchase-orders`, `GET /api/v2/purchase-orders/:id`, `PUT /api/v2/purchase-orders/:id` with safe API consumption

### Requirement 41: Construction Screens

**User Story:** As a construction trade user, I want to manage progress claims, variations, and retentions from mobile, so that I can handle construction billing on-site.

#### Acceptance Criteria

1. WHEN the `progress_claims` module is enabled AND the trade family is `building-construction`, THE Mobile_App SHALL render route `/progress-claims` as a claim list with a create form
2. WHEN the `variations` module is enabled AND the trade family is `building-construction`, THE Mobile_App SHALL render route `/variations` as a variation list with cost impact display
3. WHEN the `retentions` module is enabled AND the trade family is `building-construction`, THE Mobile_App SHALL render route `/retentions` as a retention summary by project with a release action
4. THE Mobile_App SHALL call `GET /progress-claims`, `GET /variations`, `GET /retentions` with safe API consumption

### Requirement 42: Hospitality Screens

**User Story:** As a hospitality trade user, I want to manage floor plans and kitchen orders from mobile, so that I can run front-of-house and kitchen operations.

#### Acceptance Criteria

1. WHEN the `tables` module is enabled AND the trade family is `food-hospitality`, THE Mobile_App SHALL render route `/floor-plan` as a visual table layout where tapping a table seats a customer
2. WHEN the `kitchen_display` module is enabled AND the trade family is `food-hospitality`, THE Mobile_App SHALL render route `/kitchen` as a full-screen kitchen display with large order cards, tap-to-mark-ready, and auto-refresh every 5 seconds
3. THE Mobile_App SHALL call `GET /tables`, `POST /reservations`, `GET /kitchen/orders`, `PUT /kitchen/orders/:id` with safe API consumption

### Requirement 43: Assets Screen

**User Story:** As a user, I want to track assets and their depreciation from mobile, so that I can manage company assets remotely.

#### Acceptance Criteria

1. WHEN the `assets` module is enabled, THE Mobile_App SHALL render route `/assets` as an asset list with name, category, value, and depreciation info
2. THE Mobile_App SHALL render route `/assets/:id` with depreciation schedule and maintenance log
3. THE Mobile_App SHALL call `GET /assets`, `GET /assets/:id` with safe API consumption

### Requirement 44: Compliance Documents Screen

**User Story:** As a user, I want to upload and track compliance documents with expiry alerts from mobile, so that I can maintain compliance using my phone camera.

#### Acceptance Criteria

1. WHEN the `compliance_docs` module is enabled, THE Mobile_App SHALL render route `/compliance` with a document list showing expiry pills (green=valid, amber=expiring, red=expired)
2. THE Mobile_App SHALL display summary cards at the top with counts by status (valid, expiring, expired)
3. THE Mobile_App SHALL provide upload via Camera (using `@capacitor/camera`) or file picker
4. THE Mobile_App SHALL call `GET /api/v2/compliance-docs`, `POST /api/v2/compliance-docs`, `DELETE /api/v2/compliance-docs/:id` with safe API consumption

### Requirement 45: SMS Chat Screen

**User Story:** As a user, I want to send and receive SMS messages in a chat interface, so that I can communicate with customers from the app.

#### Acceptance Criteria

1. WHEN the `sms` module is enabled, THE Mobile_App SHALL render route `/sms` with a conversation list using Konsta UI Messages component
2. THE Mobile_App SHALL render a conversation thread view with a send composer
3. THE Mobile_App SHALL call `GET /sms/conversations`, `POST /sms/send` with safe API consumption

### Requirement 46: Reports Screen

**User Story:** As a user, I want to view business reports from mobile, so that I can monitor performance remotely.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/reports` as a report hub with category cards (Sales, Finance, Operations, Industry)
2. WHEN the user selects a report, THE Mobile_App SHALL display a date range picker, run the report, and display results as chart/table
3. THE Mobile_App SHALL provide export buttons for PDF and CSV
4. THE Mobile_App SHALL call the appropriate `/reports/*` endpoints with safe API consumption

### Requirement 47: Notifications Screen

**User Story:** As a user, I want to configure my notification preferences from mobile, so that I can control which alerts I receive.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/notifications` with a preferences list using Konsta UI Toggle components
2. THE Mobile_App SHALL display overdue rules configuration
3. THE Mobile_App SHALL display reminder templates editor
4. THE Mobile_App SHALL call `GET /notifications/preferences`, `PUT /notifications/preferences`, `GET /notifications/overdue-rules`, `PUT /notifications/overdue-rules` with safe API consumption

### Requirement 48: Customer Portal Screen

**User Story:** As a customer using the self-service portal, I want a mobile-optimized experience, so that I can view invoices, pay, and book appointments from my phone.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/portal` with the existing customer self-service functionality restyled using Konsta UI components
2. THE Mobile_App SHALL preserve all portal logic (view invoices, pay online, accept quotes, book appointments) unchanged

### Requirement 49: Kiosk Screen

**User Story:** As a business with a check-in kiosk, I want the kiosk screen to work on mobile devices, so that customers can self-check-in on a tablet or phone.

#### Acceptance Criteria

1. THE Mobile_App SHALL render route `/kiosk` as a large-button check-in screen designed for tablet but functional on phone
2. WHEN the user role is `kiosk`, THE Mobile_App SHALL show the Kiosk screen instead of standard tabs
3. THE Mobile_App SHALL call `POST /kiosk/check-in` unchanged


### Requirement 50: Camera Plugin Integration

**User Story:** As a field worker, I want to take photos and attach them to invoices, job cards, compliance docs, and expenses, so that I can capture evidence on-site.

#### Acceptance Criteria

1. THE Mobile_App SHALL use `@capacitor/camera` with `CameraResultType.Uri` and `CameraSource.Prompt` (user picks camera or gallery)
2. THE Mobile_App SHALL integrate camera capture into: invoice attachments (create and detail), job card attachments, compliance document upload, expense receipt capture
3. WHEN a photo is captured, THE Mobile_App SHALL upload it as multipart to the existing attachments endpoint for that entity
4. THE Mobile_App SHALL set camera quality to 85
5. IF the app is running in a web browser (not native), THEN THE Mobile_App SHALL fall back to standard file input without calling Capacitor Camera
6. THE Mobile_App SHALL declare `NSCameraUsageDescription` and `NSPhotoLibraryUsageDescription` in iOS Info.plist
7. THE Mobile_App SHALL declare `android.permission.CAMERA` in Android AndroidManifest.xml

### Requirement 51: Geolocation Plugin Integration

**User Story:** As a business owner, I want job site locations logged when timers start, so that I can verify where work was performed.

#### Acceptance Criteria

1. THE Mobile_App SHALL use `@capacitor/geolocation` to request the current position when a job timer is started
2. THE Mobile_App SHALL use `enableHighAccuracy: false` and `timeout: 5000` for geolocation requests
3. IF the backend accepts latitude/longitude on the start-timer endpoint, THEN THE Mobile_App SHALL include coordinates in the request
4. IF the backend does not accept geo data OR permission is denied OR geolocation fails, THEN THE Mobile_App SHALL continue silently without breaking the timer start flow
5. THE Mobile_App SHALL declare `NSLocationWhenInUseUsageDescription` in iOS Info.plist
6. THE Mobile_App SHALL declare `ACCESS_COARSE_LOCATION` and `ACCESS_FINE_LOCATION` in Android AndroidManifest.xml

### Requirement 52: Push Notifications Integration

**User Story:** As a user, I want to receive push notifications for important events, so that I stay informed about payments, overdue invoices, and assigned jobs.

#### Acceptance Criteria

1. THE Mobile_App SHALL use `@capacitor/push-notifications` to request permissions and register for push notifications on login
2. WHEN registration succeeds, THE Mobile_App SHALL POST the device token to a backend endpoint (e.g., `POST /notifications/devices/register` with `{ token, platform }`)
3. WHEN a push notification is received while the app is in the foreground, THE Mobile_App SHALL display a Konsta UI Toast notification
4. WHEN the user taps a push notification, THE Mobile_App SHALL deep-link to the relevant screen based on `notification.data.route`
5. THE Mobile_App SHALL handle notifications for: invoice paid online, invoice overdue, job assigned, booking reminder, compliance document expiring, new SMS received
6. IF push notification permission is denied, THEN THE Mobile_App SHALL continue without push functionality and not block the user

### Requirement 53: Network Awareness

**User Story:** As a user, I want to know when I'm offline, so that I understand why data might not be loading.

#### Acceptance Criteria

1. THE Mobile_App SHALL use `@capacitor/network` to monitor connectivity status
2. WHEN the device goes offline, THE Mobile_App SHALL display a red banner at the top of the app indicating offline status
3. WHEN the device comes back online, THE Mobile_App SHALL hide the offline banner
4. THE Mobile_App SHALL NOT implement offline mutation queuing (out of scope for this redesign)

### Requirement 54: Status Bar and Splash Screen

**User Story:** As a user, I want the app to have a professional splash screen and appropriate status bar styling, so that the app feels polished and native.

#### Acceptance Criteria

1. THE Mobile_App SHALL configure `@capacitor/splash-screen` with the org logo and primary brand colour background
2. THE Mobile_App SHALL configure `@capacitor/status-bar` to use dark text on light backgrounds and light text on dark backgrounds (slate-900 hero screens)
3. THE Mobile_App SHALL adapt status bar style per screen context

### Requirement 55: Module Gating Preservation

**User Story:** As a developer, I want all module gating to work identically to the existing system, so that organisations only see features they've enabled.

#### Acceptance Criteria

1. THE Mobile_App SHALL use `ModuleGate` component wrapping screen content (not routes) for all module-gated screens
2. THE Mobile_App SHALL honour all 27 module slugs: vehicles, quotes, jobs, bookings, inventory, staff, projects, expenses, time_tracking, scheduling, pos, recurring_invoices, purchase_orders, progress_claims, variations, retentions, tables, kitchen_display, franchise, branch_management, assets, compliance_docs, loyalty, ecommerce, sms, customer_claims, accounting
3. THE Mobile_App SHALL fetch module state from `GET /api/v2/modules` on login via ModuleContext
4. WHEN a module is disabled, THE Mobile_App SHALL hide all UI elements gated by that module (navigation items, screens, form sections)
5. THE Mobile_App SHALL apply trade family gating: vehicles screens require `automotive-transport`, construction screens require `building-construction`, hospitality screens require `food-hospitality`

### Requirement 56: Business Logic Preservation

**User Story:** As a developer, I want all business logic preserved exactly, so that calculations, sorting, formatting, and status displays remain correct.

#### Acceptance Criteria

1. THE Mobile_App SHALL preserve the invoice calculation logic exactly: subtotal = sum of line item amounts; discount = percentage of subtotal or fixed amount; GST handles inclusive/exclusive/exempt per line item with rounding to 2 decimal places; total = afterDiscount + taxAmount + shippingCharges + adjustment
2. THE Mobile_App SHALL preserve the status colour map (STATUS_CONFIG) with exact colour assignments for all 8 invoice statuses
3. THE Mobile_App SHALL preserve job card sorting: `statusOrder` function (in_progress=0, open=1, other=2), then by `created_at` descending
4. THE Mobile_App SHALL preserve `formatNZD()` currency formatting: `NZD` prefix + locale-formatted number with 2 decimal places
5. THE Mobile_App SHALL preserve `computeCreditableAmount()` and `computePaymentSummary()` helper functions exactly
6. THE Mobile_App SHALL preserve `resolveTemplateStyles()` for org-customized invoice template colours
7. THE Mobile_App SHALL preserve safe API consumption patterns on every API call: `res.data?.items ?? []`, `res.data?.total ?? 0`, AbortController cleanup in useEffect, no `as any` type assertions

### Requirement 57: Safe API Consumption

**User Story:** As a developer, I want all API calls to follow safe consumption patterns, so that the app never crashes from unexpected API response shapes.

#### Acceptance Criteria

1. THE Mobile_App SHALL use optional chaining and nullish coalescing on every API response: `res.data?.items ?? []` for arrays, `res.data?.total ?? 0` for numbers
2. THE Mobile_App SHALL use typed generics on all Axios API calls (never `as any`)
3. THE Mobile_App SHALL include AbortController cleanup in every useEffect that makes API calls
4. THE Mobile_App SHALL use `offset` (not `skip`) and `limit` for all pagination parameters
5. THE Mobile_App SHALL guard all `.map()`, `.filter()`, `.find()` calls on API data with `?? []` fallback
6. THE Mobile_App SHALL guard all `.toLocaleString()`, `.toFixed()` calls on API data with `?? 0` fallback

### Requirement 58: Exclusions

**User Story:** As a developer, I want clear boundaries on what NOT to build, so that the mobile app stays focused on field-user needs.

#### Acceptance Criteria

1. THE Mobile_App SHALL NOT include any global admin screens (platform management, billing admin, HA replication, global user management)
2. THE Mobile_App SHALL NOT include org admin settings screens (org branding, branch management config, billing, integrations admin, security/MFA admin, modules admin, webhooks, invoice template editor, printer settings)
3. THE Mobile_App SHALL NOT include the `/settings` hub page with org_admin configuration screens
4. THE Mobile_App SHALL NOT include onboarding wizard or setup guide screens
5. THE Mobile_App SHALL NOT include `/branch-transfers` or `/staff-schedule` (adminOnly screens)
6. THE Mobile_App SHALL NOT include franchise admin pages (`/franchise/*`)
7. THE Mobile_App SHALL NOT include data import/export bulk operations (`/data`)
8. THE Mobile_App SHALL NOT include accounting editors (chart of accounts editor, journal entries editor) — view-only summary is acceptable
9. THE Mobile_App SHALL NOT include banking admin (reconciliation dashboard editor) — view-only balance display is acceptable
10. THE Mobile_App SHALL NOT include tax admin (GST period filing editor) — view-only summary is acceptable

### Requirement 59: Capacitor Plugin Dependencies

**User Story:** As a developer, I want all required Capacitor plugins installed, so that native features work on both iOS and Android.

#### Acceptance Criteria

1. THE Mobile_App SHALL include `@capacitor/camera` as a dependency
2. THE Mobile_App SHALL include `@capacitor/geolocation` as a dependency
3. THE Mobile_App SHALL include `@capacitor/push-notifications` as a dependency
4. THE Mobile_App SHALL include `@capacitor/preferences` as a dependency (already present)
5. THE Mobile_App SHALL include `@capacitor/network` as a dependency (already present)
6. THE Mobile_App SHALL include `@capacitor/haptics` as a dependency (already present)
7. THE Mobile_App SHALL include `@capacitor/status-bar` as a dependency
8. THE Mobile_App SHALL include `@capacitor/splash-screen` as a dependency
9. THE Mobile_App SHALL run `npx cap sync` after installing new plugins to sync native project configurations

### Requirement 60: Touch Targets and Accessibility

**User Story:** As a user, I want all interactive elements to be easy to tap and accessible, so that the app is usable for everyone.

#### Acceptance Criteria

1. THE Mobile_App SHALL ensure all interactive elements have a minimum touch target of 44×44 CSS pixels (Apple HIG + WCAG 2.5.8)
2. THE Mobile_App SHALL use `min-h-[44px]` on buttons, list items, and toggle rows
3. THE Mobile_App SHALL respect safe area insets using `env(safe-area-inset-*)` CSS functions
4. THE Mobile_App SHALL use minimum 12px font size for secondary text and 14px+ for primary text
5. THE Mobile_App SHALL support the viewport range from 320px (iPhone SE) to 430px (iPhone Pro Max)
6. THE Mobile_App SHALL support dark mode with `dark:` Tailwind variants on all components

### Requirement 61: Native Platform Permissions

**User Story:** As a developer, I want all native permissions properly declared, so that the app can request access to device features on both platforms.

#### Acceptance Criteria

1. THE Mobile_App SHALL declare in iOS Info.plist: `NSCameraUsageDescription` ("Capture invoice attachments, receipts and compliance documents"), `NSPhotoLibraryUsageDescription` ("Select photos for attachments and receipts"), `NSLocationWhenInUseUsageDescription` ("Tag job locations for accurate site tracking")
2. THE Mobile_App SHALL declare in Android AndroidManifest.xml: `android.permission.CAMERA`, `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`
3. THE Mobile_App SHALL guard all Capacitor plugin calls with platform detection: `!!(window as any).Capacitor?.isNativePlatform?.()` before calling native APIs
4. IF a native API call fails or permission is denied, THEN THE Mobile_App SHALL handle the error gracefully without crashing

### Requirement 62: Acceptance Testing Criteria

**User Story:** As a stakeholder, I want clear acceptance criteria for the redesign completion, so that I can verify the work is done.

#### Acceptance Criteria

1. THE Mobile_App SHALL have Konsta UI v5 installed with the app root wrapped in `<App theme={ios|material} safeAreas>`
2. THE Mobile_App SHALL render a Bottom_Tab_Bar with 5 tabs where "More" opens a sheet with all enabled module nav items
3. THE Mobile_App SHALL filter More_Drawer items using identical `module + flag + trade + role` logic as the existing sidebar
4. THE Mobile_App SHALL have a Konsta-styled mobile screen for every page listed in the redesign specification (auth, dashboard, invoices, customers, quotes, job cards, vehicles, bookings, inventory, staff, projects, expenses, time tracking, schedule, POS, recurring, purchase orders, construction, hospitality, assets, compliance, SMS, reports, notifications, portal, kiosk)
5. THE Mobile_App SHALL have all eight contexts functioning unchanged
6. THE Mobile_App SHALL have all ModuleRoute and ModuleGate usages still gating routes and components
7. THE Mobile_App SHALL call all API endpoints identically (no signature changes)
8. THE Mobile_App SHALL compute all invoice calculations matching existing logic exactly
9. THE Mobile_App SHALL have Pull_To_Refresh on every list page
10. THE Mobile_App SHALL have a FAB on every list page that supports creation
11. THE Mobile_App SHALL have Camera plugin wired into invoice attachments, job card attachments, compliance, and expenses
12. THE Mobile_App SHALL have push notification registration on login and listener on receive
13. THE Mobile_App SHALL call geolocation on job timer start (silent, optional)
14. THE Mobile_App SHALL trigger haptics on all primary actions
15. THE Mobile_App SHALL have iOS Info.plist and Android AndroidManifest.xml updated with all required permissions
16. THE Mobile_App SHALL adapt status bar style per screen
17. THE Mobile_App SHALL have splash screen configured
18. THE Mobile_App SHALL have TenantContext brand-colour overrides still applying correctly
19. THE Mobile_App SHALL NOT include any excluded screens (admin, org admin, branch transfers, staff schedule, franchise admin, data import/export, accounting/banking/tax editors)

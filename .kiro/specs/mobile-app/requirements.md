# Requirements Document — OraInvoice Mobile App

## Introduction

The OraInvoice Mobile App is a companion mobile application for the existing OraInvoice multi-tenant SaaS platform. It provides the full feature set of the web application through a mobile-first, touch-optimized interface. The Mobile_App is built with React, TypeScript, Vite, Tailwind CSS, and Capacitor, sharing the same FastAPI backend API as the web app. It runs as a separate Docker container during development and is packaged as native iOS and Android apps via Capacitor for App Store and Google Play distribution, while also being accessible as a mobile web app via browser.

The requirements are organized into four delivery phases: Phase 1 (MVP — core daily operations), Phase 2 (Extended Operations), Phase 3 (Financial and Compliance), and Phase 4 (Advanced Features).

## Glossary

- **Mobile_App**: The OraInvoice mobile application built with React + TypeScript + Capacitor
- **API_Client**: The shared Axios-based HTTP client configured with JWT auth, branch headers, and safe response handling
- **Auth_Provider**: The authentication context managing login, MFA, token refresh, and session state
- **Module_Gate**: The system that shows or hides features based on the organisation's enabled modules and trade family
- **Trade_Family**: The business type classification (automotive-transport, electrical, plumbing, construction, hospitality) that gates feature visibility
- **Branch_Context**: The context that tracks the user's selected branch and injects the X-Branch-Id header into API requests
- **Capacitor_Bridge**: The Capacitor native runtime providing access to device APIs (camera, biometrics, push notifications, filesystem)
- **Tab_Navigator**: The bottom tab navigation bar providing primary navigation between Dashboard, Invoices, Customers, Jobs, and More screens
- **Pull_Refresh**: The pull-to-refresh gesture handler that triggers data reload on list screens
- **Swipe_Action**: The horizontal swipe gesture on list items that reveals contextual action buttons
- **Touch_Target**: An interactive UI element with minimum dimensions of 44x44 CSS pixels per Apple HIG and WCAG 2.5.8
- **Offline_Queue**: The local persistence layer that stores API mutations when the device has no network connectivity
- **Deep_Link**: A URL scheme or universal link that navigates the Mobile_App directly to a specific screen
- **Biometric_Auth**: Device-level authentication using Face ID, Touch ID, or Android fingerprint via Capacitor
- **Push_Service**: The push notification delivery system using Firebase Cloud Messaging via Capacitor
- **Safe_API_Pattern**: The mandatory response handling pattern using optional chaining (`?.`) and nullish coalescing (`?? []`, `?? 0`) on all API data

## Requirements

---

## Phase 1 — MVP (Core Daily Operations)

### Requirement 1: Mobile App Shell and Navigation

**User Story:** As a trade business user, I want a mobile-first app shell with bottom tab navigation, so that I can quickly access core features with one hand on my phone.

#### Acceptance Criteria

1. THE Mobile_App SHALL render a bottom Tab_Navigator with five tabs: Dashboard, Invoices, Customers, Jobs, and More
2. WHEN a user taps a tab in the Tab_Navigator, THE Mobile_App SHALL navigate to the corresponding top-level screen within 300ms
3. THE Mobile_App SHALL render all Touch_Target elements with minimum dimensions of 44x44 CSS pixels
4. THE Mobile_App SHALL adapt its layout to screen widths ranging from 320px (iPhone SE) to 430px (iPhone Pro Max) and equivalent Android device widths
5. WHEN the device system appearance is set to dark mode, THE Mobile_App SHALL render all screens using a dark colour scheme
6. WHEN the device system appearance is set to light mode, THE Mobile_App SHALL render all screens using a light colour scheme
7. THE Mobile_App SHALL display the organisation's branding (logo and name) in the app header, matching the branding configuration from the Tenant settings
8. WHEN a user navigates between screens, THE Mobile_App SHALL preserve the scroll position of the previous screen within the same tab stack

### Requirement 2: Authentication and Session Management

**User Story:** As a user, I want to log in to the mobile app securely with my existing credentials, so that I can access my organisation's data on my phone.

#### Acceptance Criteria

1. THE Mobile_App SHALL display a login screen with email and password fields and a "Remember Me" toggle
2. WHEN a user submits valid credentials, THE Auth_Provider SHALL store the JWT access token in memory and the refresh token as an httpOnly cookie
3. WHEN a user submits invalid credentials, THE Auth_Provider SHALL display the error message returned by the backend
4. WHEN the access token expires, THE API_Client SHALL automatically refresh the token using the stored refresh cookie before retrying the failed request
5. WHEN the refresh token is invalid or expired, THE Mobile_App SHALL redirect the user to the login screen
6. WHEN a user taps "Forgot Password", THE Mobile_App SHALL navigate to the password reset request screen
7. WHEN a user submits a password reset request with a valid email, THE Mobile_App SHALL display a confirmation message indicating that a reset link has been sent
8. THE Mobile_App SHALL support Google Sign-In as an alternative login method

### Requirement 3: Multi-Factor Authentication

**User Story:** As a security-conscious user, I want to complete MFA verification on my phone, so that my account remains protected when using the mobile app.

#### Acceptance Criteria

1. WHEN the backend returns an MFA challenge after login, THE Mobile_App SHALL navigate to the MFA verification screen
2. THE Mobile_App SHALL display the available MFA methods (TOTP, SMS, backup codes) returned by the backend
3. WHEN a user selects an MFA method and submits a valid code, THE Auth_Provider SHALL complete authentication and navigate to the Dashboard
4. IF a user submits an invalid MFA code, THEN THE Mobile_App SHALL display an error message and allow the user to retry
5. THE Mobile_App SHALL support Firebase MFA verification as an alternative MFA flow

### Requirement 4: Biometric Authentication

**User Story:** As a returning user, I want to unlock the app with my fingerprint or face, so that I can access my data quickly without typing my password each time.

#### Acceptance Criteria

1. WHEN a user has previously authenticated and the device supports biometrics, THE Mobile_App SHALL offer to enable Biometric_Auth on the settings screen
2. WHEN Biometric_Auth is enabled and the user opens the Mobile_App with a valid session, THE Capacitor_Bridge SHALL prompt for biometric verification before displaying app content
3. IF biometric verification fails three consecutive times, THEN THE Mobile_App SHALL fall back to the standard login screen
4. WHEN a user disables Biometric_Auth in settings, THE Mobile_App SHALL stop prompting for biometric verification on app launch
5. IF the device does not support biometrics, THEN THE Mobile_App SHALL hide the Biometric_Auth option in settings

### Requirement 5: Module Gating

**User Story:** As a user of a specific trade business, I want to see only the features my organisation has enabled, so that the app is not cluttered with irrelevant options.

#### Acceptance Criteria

1. WHEN the Mobile_App loads after authentication, THE Module_Gate SHALL fetch the organisation's enabled modules from the `/api/v2/modules` endpoint
2. THE Tab_Navigator and More menu SHALL display only navigation items whose corresponding module is enabled for the organisation
3. WHEN a module is disabled for the organisation, THE Mobile_App SHALL hide all screens, navigation items, and quick actions associated with that module
4. THE Module_Gate SHALL filter navigation items by Trade_Family, showing automotive-specific features (Vehicles, Job Cards) only when the organisation's trade family is "automotive-transport"
5. THE Module_Gate SHALL respect role-based visibility, hiding admin-only items (Settings) from salesperson and kiosk roles

### Requirement 6: Dashboard

**User Story:** As a business owner, I want to see a summary of my business metrics on the dashboard, so that I can quickly assess how my business is performing today.

#### Acceptance Criteria

1. THE Mobile_App SHALL display a role-based dashboard with summary cards showing key metrics (revenue, outstanding invoices, jobs in progress, upcoming bookings)
2. WHEN a user performs a Pull_Refresh gesture on the Dashboard, THE Mobile_App SHALL reload all dashboard data from the backend
3. THE Dashboard SHALL display quick action buttons for creating new invoices, quotes, job cards, and customers (filtered by Module_Gate)
4. WHEN a user taps a summary card, THE Mobile_App SHALL navigate to the corresponding detail list screen
5. WHEN a user taps a quick action button, THE Mobile_App SHALL navigate to the corresponding creation screen

### Requirement 7: Customer Management

**User Story:** As a tradesperson, I want to manage my customers on my phone, so that I can look up contact details and create new customers while on a job site.

#### Acceptance Criteria

1. THE Mobile_App SHALL display a searchable, paginated list of customers with name, phone, and email visible
2. WHEN a user types in the search field, THE Mobile_App SHALL filter the customer list by matching against customer name, email, or phone number
3. WHEN a user performs a Pull_Refresh gesture on the customer list, THE Mobile_App SHALL reload the customer data from the backend
4. WHEN a user taps a customer in the list, THE Mobile_App SHALL navigate to the customer profile screen showing full contact details, invoices, quotes, and job history
5. WHEN a user taps the "New Customer" button, THE Mobile_App SHALL display a creation form requiring only the first name field, with all other fields optional
6. WHEN a user performs a Swipe_Action on a customer list item, THE Mobile_App SHALL reveal action buttons for Call, Email, and SMS
7. WHEN a user taps the Call action on a customer, THE Capacitor_Bridge SHALL initiate a phone call to the customer's primary phone number
8. WHEN a user taps the Email action on a customer, THE Capacitor_Bridge SHALL open the device email client with the customer's email pre-filled
9. WHEN a user taps the SMS action on a customer, THE Capacitor_Bridge SHALL open the device SMS app with the customer's phone number pre-filled

### Requirement 8: Invoice Management

**User Story:** As a business owner, I want to create, view, and manage invoices on my phone, so that I can bill customers immediately after completing work.

#### Acceptance Criteria

1. THE Mobile_App SHALL display a searchable, paginated list of invoices with invoice number, customer name, amount, status, and date visible
2. WHEN a user taps an invoice in the list, THE Mobile_App SHALL navigate to the invoice detail screen showing full invoice information including line items, totals, tax, and payment history
3. WHEN a user taps "New Invoice", THE Mobile_App SHALL display an invoice creation form with customer selection, line items, tax calculation, and discount fields
4. WHEN a user taps "Send" on an invoice detail screen, THE Mobile_App SHALL send the invoice to the customer via the backend email endpoint
5. WHEN a user taps "Record Payment" on an invoice detail screen, THE Mobile_App SHALL display a payment recording form with amount, method, and date fields
6. WHEN a user performs a Swipe_Action on an invoice list item, THE Mobile_App SHALL reveal action buttons for Send and Record Payment
7. WHEN a user taps "Preview PDF" on an invoice, THE Mobile_App SHALL display the invoice PDF in a full-screen viewer
8. WHEN a user performs a Pull_Refresh gesture on the invoice list, THE Mobile_App SHALL reload the invoice data from the backend

### Requirement 9: Quote Management

**User Story:** As a tradesperson, I want to create and send quotes from my phone, so that I can provide estimates to customers while on site.

#### Acceptance Criteria

1. WHERE the quotes module is enabled, THE Mobile_App SHALL display a searchable, paginated list of quotes with quote number, customer name, amount, and status visible
2. WHEN a user taps a quote in the list, THE Mobile_App SHALL navigate to the quote detail screen showing full quote information including line items and totals
3. WHEN a user taps "New Quote", THE Mobile_App SHALL display a quote creation form with customer selection, line items, tax, and discount fields
4. WHEN a user taps "Send" on a quote detail screen, THE Mobile_App SHALL send the quote to the customer via the backend email endpoint
5. WHEN a user taps "Convert to Invoice" on an accepted quote, THE Mobile_App SHALL create a new invoice pre-populated with the quote's line items and customer details
6. WHEN a user performs a Pull_Refresh gesture on the quote list, THE Mobile_App SHALL reload the quote data from the backend

### Requirement 10: Job Management

**User Story:** As a tradesperson, I want to view and update my jobs on my phone, so that I can track work progress and update job status while on site.

#### Acceptance Criteria

1. WHERE the jobs module is enabled, THE Mobile_App SHALL display jobs in both a list view and a kanban board view, switchable by the user
2. WHEN a user taps a job in the list or board, THE Mobile_App SHALL navigate to the job detail screen showing description, status, assigned staff, time entries, and linked invoices
3. WHEN a user changes the status of a job on the detail screen, THE Mobile_App SHALL update the job status via the backend API and reflect the change immediately in the UI
4. WHEN a user taps the timer button on a job detail screen, THE Mobile_App SHALL start a time tracking timer associated with that job
5. WHEN a user performs a Pull_Refresh gesture on the job list or board, THE Mobile_App SHALL reload the job data from the backend
6. WHEN a user drags a job card on the kanban board to a different column, THE Mobile_App SHALL update the job status to match the target column

### Requirement 11: Job Cards (Automotive)

**User Story:** As an automotive workshop user, I want to manage job cards with vehicle information on my phone, so that I can track vehicle repairs while in the workshop.

#### Acceptance Criteria

1. WHERE the jobs module is enabled AND the Trade_Family is "automotive-transport", THE Mobile_App SHALL display a searchable list of job cards with job card number, customer name, vehicle registration, and status visible
2. WHEN a user taps a job card in the list, THE Mobile_App SHALL navigate to the job card detail screen showing vehicle information, service items, parts, labour, and status
3. WHEN a user taps "New Job Card", THE Mobile_App SHALL display a creation form with customer selection, vehicle selection, and service description fields
4. WHEN a user performs a Pull_Refresh gesture on the job card list, THE Mobile_App SHALL reload the job card data from the backend

### Requirement 12: Push Notifications

**User Story:** As a business owner, I want to receive push notifications for important events, so that I am alerted to invoice payments, job updates, and expiry reminders without opening the app.

#### Acceptance Criteria

1. WHEN the Mobile_App is installed and the user is authenticated, THE Push_Service SHALL register the device for push notifications via Firebase Cloud Messaging through the Capacitor_Bridge
2. WHEN the backend sends a push notification, THE Mobile_App SHALL display the notification in the device notification centre with a title and body
3. WHEN a user taps a push notification, THE Mobile_App SHALL open and navigate to the relevant screen using Deep_Link routing (invoice detail, job detail, or compliance document)
4. IF the user denies push notification permissions, THEN THE Mobile_App SHALL display a message explaining the benefits of notifications and provide a link to device settings


### Requirement 13: Safe API Consumption

**User Story:** As a developer, I want all API calls in the mobile app to follow safe consumption patterns, so that the app does not crash when backend responses contain missing or unexpected fields.

#### Acceptance Criteria

1. THE API_Client SHALL use optional chaining (`?.`) and nullish coalescing (`?? []` for arrays, `?? 0` for numbers) on all properties read from API responses before setting state
2. THE API_Client SHALL use typed generics on all API calls instead of `as any` type assertions
3. THE Mobile_App SHALL wrap every `useEffect` containing an API call with an AbortController and abort the request on component unmount
4. THE API_Client SHALL inject the `X-Branch-Id` header from the Branch_Context into every API request when a specific branch is selected
5. THE Mobile_App SHALL use the same backend API endpoints and response shapes as the web app without requiring backend changes

### Requirement 14: Mobile App Infrastructure

**User Story:** As a developer, I want the mobile app to run as a separate Docker container during development, so that it can be developed and deployed independently from the web app.

#### Acceptance Criteria

1. THE Mobile_App SHALL be served by an nginx container in Docker Compose on a separate port from the web app
2. THE Mobile_App SHALL share the same Vite + React + TypeScript + Tailwind CSS build toolchain as the web app
3. THE Mobile_App SHALL use Capacitor to package the app as native iOS and Android binaries for App Store and Google Play distribution
4. THE Mobile_App SHALL be accessible as a mobile web app via browser at the configured URL path
5. THE Mobile_App SHALL share TypeScript interface definitions with the web app for API request and response types

---

## Phase 2 — Extended Operations

### Requirement 15: Invoice Line Item Management

**User Story:** As a business owner, I want to add detailed line items with tax and discounts to invoices on my phone, so that I can create accurate invoices on site.

#### Acceptance Criteria

1. WHEN creating or editing an invoice, THE Mobile_App SHALL allow adding multiple line items with description, quantity, unit price, and tax rate fields
2. WHEN a user modifies a line item, THE Mobile_App SHALL recalculate the invoice subtotal, tax amount, discount, and total in real time
3. WHEN a user taps "Add Item" on the invoice form, THE Mobile_App SHALL display an item selection screen that searches the inventory catalogue
4. WHEN a user selects an inventory item, THE Mobile_App SHALL pre-fill the line item description and unit price from the catalogue entry
5. THE Mobile_App SHALL display a running total at the bottom of the invoice form that updates as line items are added, modified, or removed

### Requirement 16: Quote Line Item Management

**User Story:** As a tradesperson, I want to add detailed line items to quotes on my phone, so that I can provide accurate estimates to customers.

#### Acceptance Criteria

1. WHERE the quotes module is enabled, WHEN creating or editing a quote, THE Mobile_App SHALL allow adding multiple line items with description, quantity, unit price, and tax rate fields
2. WHEN a user modifies a line item on a quote, THE Mobile_App SHALL recalculate the quote subtotal, tax amount, and total in real time
3. WHEN a user taps "Add Item" on the quote form, THE Mobile_App SHALL display an item selection screen that searches the inventory catalogue

### Requirement 17: Inventory Lookup

**User Story:** As a tradesperson, I want to check stock levels on my phone, so that I can verify part availability while on a job site.

#### Acceptance Criteria

1. WHERE the inventory module is enabled, THE Mobile_App SHALL display a searchable list of inventory items with name, SKU, stock level, and price visible
2. WHEN a user searches the inventory list, THE Mobile_App SHALL filter items by matching against item name or SKU
3. WHEN a user taps an inventory item, THE Mobile_App SHALL display the item detail screen showing full description, stock levels per branch, pricing, and supplier information
4. WHEN a user performs a Pull_Refresh gesture on the inventory list, THE Mobile_App SHALL reload the inventory data from the backend

### Requirement 18: Staff Management

**User Story:** As a business owner, I want to view my staff list and details on my phone, so that I can look up staff contact information and roles.

#### Acceptance Criteria

1. WHERE the staff module is enabled, THE Mobile_App SHALL display a list of staff members with name, role, and contact details visible
2. WHEN a user taps a staff member in the list, THE Mobile_App SHALL navigate to the staff detail screen showing full profile, assigned branches, and role information
3. WHEN a user performs a Swipe_Action on a staff list item, THE Mobile_App SHALL reveal action buttons for Call and Email

### Requirement 19: Time Tracking

**User Story:** As a tradesperson, I want to clock in and out and view my timesheet on my phone, so that I can track my work hours accurately while on site.

#### Acceptance Criteria

1. WHERE the time_tracking module is enabled, THE Mobile_App SHALL display a clock in/out button on the Dashboard and a dedicated Time Tracking screen
2. WHEN a user taps "Clock In", THE Mobile_App SHALL record the clock-in time via the backend API and display a running timer
3. WHEN a user taps "Clock Out", THE Mobile_App SHALL record the clock-out time via the backend API and stop the running timer
4. THE Mobile_App SHALL display a timesheet view showing daily and weekly time entries with total hours calculated
5. WHEN a user performs a Pull_Refresh gesture on the timesheet, THE Mobile_App SHALL reload the time entry data from the backend

### Requirement 20: Expense Tracking

**User Story:** As a tradesperson, I want to log expenses and photograph receipts on my phone, so that I can track business expenses immediately when they occur.

#### Acceptance Criteria

1. WHERE the expenses module is enabled, THE Mobile_App SHALL display a list of expenses with date, description, amount, and category visible
2. WHEN a user taps "New Expense", THE Mobile_App SHALL display a creation form with description, amount, category, date, and receipt photo fields
3. WHEN a user taps the camera icon on the expense form, THE Capacitor_Bridge SHALL open the device camera to capture a receipt photo
4. WHEN a user captures a receipt photo, THE Mobile_App SHALL upload the photo to the backend and attach it to the expense record
5. THE Mobile_App SHALL also allow selecting an existing photo from the device gallery as a receipt attachment
6. WHEN a user performs a Pull_Refresh gesture on the expense list, THE Mobile_App SHALL reload the expense data from the backend

### Requirement 21: Booking Calendar

**User Story:** As a business owner, I want to view and create bookings on my phone, so that I can manage my schedule while away from the office.

#### Acceptance Criteria

1. WHERE the bookings module is enabled, THE Mobile_App SHALL display a calendar view showing existing bookings with time, customer name, and service type
2. WHEN a user taps a date on the calendar, THE Mobile_App SHALL display the bookings for that date in a list format
3. WHEN a user taps "New Booking", THE Mobile_App SHALL display a booking creation form with customer selection, date, time, duration, and service type fields
4. WHEN a user taps an existing booking, THE Mobile_App SHALL navigate to the booking detail screen
5. WHEN a user performs a Pull_Refresh gesture on the calendar, THE Mobile_App SHALL reload the booking data from the backend

### Requirement 22: Vehicle Management (Automotive)

**User Story:** As an automotive workshop user, I want to view vehicle profiles and service history on my phone, so that I can look up vehicle details while in the workshop.

#### Acceptance Criteria

1. WHERE the vehicles module is enabled AND the Trade_Family is "automotive-transport", THE Mobile_App SHALL display a searchable list of vehicles with registration, make, model, and owner name visible
2. WHEN a user taps a vehicle in the list, THE Mobile_App SHALL navigate to the vehicle profile screen showing full vehicle details, owner information, and service history
3. WHEN a user searches the vehicle list, THE Mobile_App SHALL filter vehicles by matching against registration number, make, or model
4. WHEN a user performs a Pull_Refresh gesture on the vehicle list, THE Mobile_App SHALL reload the vehicle data from the backend

---

## Phase 3 — Financial and Compliance

### Requirement 23: Accounting — Chart of Accounts

**User Story:** As a business owner, I want to view my chart of accounts on my phone, so that I can review account structures while away from the office.

#### Acceptance Criteria

1. WHERE the accounting module is enabled, THE Mobile_App SHALL display the chart of accounts in a hierarchical list showing account code, name, type, and balance
2. WHEN a user taps an account, THE Mobile_App SHALL navigate to the account detail screen showing recent journal entries for that account
3. WHEN a user performs a Pull_Refresh gesture on the chart of accounts, THE Mobile_App SHALL reload the account data from the backend

### Requirement 24: Accounting — Journal Entries

**User Story:** As a business owner, I want to view journal entries on my phone, so that I can review financial transactions while away from the office.

#### Acceptance Criteria

1. WHERE the accounting module is enabled, THE Mobile_App SHALL display a paginated list of journal entries with date, description, and amount visible
2. WHEN a user taps a journal entry, THE Mobile_App SHALL navigate to the journal entry detail screen showing all debit and credit lines
3. WHEN a user performs a Pull_Refresh gesture on the journal entry list, THE Mobile_App SHALL reload the journal entry data from the backend

### Requirement 25: Banking

**User Story:** As a business owner, I want to view bank accounts and transactions on my phone, so that I can monitor cash flow while away from the office.

#### Acceptance Criteria

1. WHERE the accounting module is enabled, THE Mobile_App SHALL display a list of bank accounts with account name, institution, and current balance visible
2. WHEN a user taps a bank account, THE Mobile_App SHALL navigate to the bank transactions screen showing a paginated list of transactions for that account
3. THE Mobile_App SHALL display a reconciliation dashboard showing unreconciled transaction counts and amounts per bank account
4. WHEN a user performs a Pull_Refresh gesture on the bank accounts or transactions list, THE Mobile_App SHALL reload the data from the backend

### Requirement 26: Tax and GST

**User Story:** As a business owner, I want to view GST periods and tax position on my phone, so that I can monitor tax obligations while away from the office.

#### Acceptance Criteria

1. WHERE the accounting module is enabled, THE Mobile_App SHALL display a list of GST periods with period dates, status, and GST amounts visible
2. WHEN a user taps a GST period, THE Mobile_App SHALL navigate to the GST filing detail screen showing the breakdown of GST collected and GST paid
3. THE Mobile_App SHALL display a tax position summary screen showing the current tax liability or refund position
4. WHEN a user performs a Pull_Refresh gesture on the GST periods list, THE Mobile_App SHALL reload the data from the backend

### Requirement 27: Compliance Documents

**User Story:** As a business owner, I want to upload and track compliance documents on my phone, so that I can capture certifications and licences immediately using my phone camera.

#### Acceptance Criteria

1. WHERE the compliance_docs module is enabled, THE Mobile_App SHALL display a compliance dashboard showing document categories, counts, and expiry status
2. WHEN a user taps "Upload Document", THE Capacitor_Bridge SHALL offer the choice of capturing a new photo with the camera or selecting an existing file from the device
3. WHEN a user captures or selects a document, THE Mobile_App SHALL display a form for entering document type, description, and expiry date before uploading
4. THE Mobile_App SHALL display a list of compliance documents with name, type, expiry date, and status (valid, expiring soon, expired) visible
5. WHEN a user taps a compliance document, THE Mobile_App SHALL display a preview of the document
6. THE Mobile_App SHALL display a visual indicator (badge or colour) on documents expiring within 30 days
7. WHEN a user performs a Pull_Refresh gesture on the compliance dashboard, THE Mobile_App SHALL reload the compliance data from the backend

### Requirement 28: Reports

**User Story:** As a business owner, I want to view business reports on my phone, so that I can review performance metrics while away from the office.

#### Acceptance Criteria

1. THE Mobile_App SHALL display a reports menu listing available report types: Revenue, Job, Fleet (automotive only), Inventory, Customer Statement, Outstanding Invoices, Profit and Loss, Balance Sheet, and Aged Receivables
2. THE Mobile_App SHALL filter the reports menu by Module_Gate, showing only reports for enabled modules
3. WHEN a user selects a report, THE Mobile_App SHALL display the report data in a mobile-optimized format with summary cards and scrollable data tables
4. WHEN a user selects a date range filter on a report, THE Mobile_App SHALL reload the report data for the selected period
5. WHEN a user performs a Pull_Refresh gesture on a report screen, THE Mobile_App SHALL reload the report data from the backend

### Requirement 29: Notification Preferences

**User Story:** As a user, I want to configure which notifications I receive on my phone, so that I am only alerted to events that matter to me.

#### Acceptance Criteria

1. THE Mobile_App SHALL display a notification preferences screen listing all notification categories (invoice payments, job updates, expiry reminders, booking confirmations)
2. WHEN a user toggles a notification category on or off, THE Mobile_App SHALL update the preference via the backend API
3. THE Mobile_App SHALL display the current notification rules (overdue invoice reminders) and allow the user to enable or disable them
4. WHEN a user performs a Pull_Refresh gesture on the notification preferences screen, THE Mobile_App SHALL reload the preference data from the backend

---

## Phase 4 — Advanced Features

### Requirement 30: Offline Mode with Sync

**User Story:** As a tradesperson working in areas with poor connectivity, I want the app to work offline and sync my changes when I am back online, so that I can continue working without interruption.

#### Acceptance Criteria

1. WHEN the device loses network connectivity, THE Mobile_App SHALL display an offline indicator in the app header
2. WHILE the device is offline, THE Mobile_App SHALL serve previously loaded data from a local cache for read operations
3. WHILE the device is offline, WHEN a user creates or updates a record, THE Offline_Queue SHALL store the mutation locally with a timestamp and operation type
4. WHEN the device regains network connectivity, THE Offline_Queue SHALL replay all queued mutations to the backend in chronological order
5. IF a queued mutation fails during sync due to a conflict, THEN THE Mobile_App SHALL display the conflict to the user and allow manual resolution
6. WHEN the Offline_Queue completes syncing all mutations, THE Mobile_App SHALL display a confirmation message with the count of synced operations
7. THE Mobile_App SHALL persist the Offline_Queue across app restarts using device local storage

### Requirement 31: POS Screen

**User Story:** As a hospitality or retail business user, I want a point-of-sale screen on my phone or tablet, so that I can process sales quickly at the counter.

#### Acceptance Criteria

1. WHERE the pos module is enabled, THE Mobile_App SHALL display a POS screen with a product grid, cart, and payment section
2. WHEN a user taps a product on the POS grid, THE Mobile_App SHALL add the product to the cart with quantity defaulting to one
3. WHEN a user modifies the quantity of a cart item, THE Mobile_App SHALL recalculate the cart total in real time
4. WHEN a user taps "Pay", THE Mobile_App SHALL create an invoice for the cart items and record the payment
5. THE Mobile_App SHALL support cash, card, and other payment methods on the POS screen

### Requirement 32: Construction Module

**User Story:** As a construction business user, I want to manage progress claims, variations, and retentions on my phone, so that I can track construction project finances on site.

#### Acceptance Criteria

1. WHERE the progress_claims module is enabled, THE Mobile_App SHALL display a list of progress claims with claim number, project, amount, and status visible
2. WHERE the variations module is enabled, THE Mobile_App SHALL display a list of variations with variation number, description, amount, and status visible
3. WHERE the retentions module is enabled, THE Mobile_App SHALL display a retention summary showing total retained amounts and release schedules
4. WHEN a user taps a progress claim or variation, THE Mobile_App SHALL navigate to the detail screen showing full breakdown and approval status
5. WHEN a user performs a Pull_Refresh gesture on any construction list, THE Mobile_App SHALL reload the data from the backend

### Requirement 33: Franchise Management

**User Story:** As a franchise operator, I want to view locations and manage stock transfers on my phone, so that I can oversee multi-location operations while mobile.

#### Acceptance Criteria

1. WHERE the franchise module is enabled, THE Mobile_App SHALL display a franchise dashboard with location summary cards
2. WHEN a user taps a location card, THE Mobile_App SHALL navigate to the location detail screen showing performance metrics and staff
3. WHERE the franchise module is enabled, THE Mobile_App SHALL display a stock transfers list showing transfer number, source, destination, status, and item count
4. WHEN a user performs a Pull_Refresh gesture on the franchise dashboard, THE Mobile_App SHALL reload the data from the backend

### Requirement 34: Recurring Invoices

**User Story:** As a business owner, I want to view and manage recurring invoices on my phone, so that I can monitor automated billing while away from the office.

#### Acceptance Criteria

1. WHERE the recurring_invoices module is enabled, THE Mobile_App SHALL display a list of recurring invoice templates with customer name, amount, frequency, and next run date visible
2. WHEN a user taps a recurring invoice template, THE Mobile_App SHALL navigate to the detail screen showing the template configuration and generation history
3. WHEN a user performs a Pull_Refresh gesture on the recurring invoices list, THE Mobile_App SHALL reload the data from the backend

### Requirement 35: Purchase Orders

**User Story:** As a business owner, I want to view and manage purchase orders on my phone, so that I can track supplier orders while away from the office.

#### Acceptance Criteria

1. WHERE the purchase_orders module is enabled, THE Mobile_App SHALL display a paginated list of purchase orders with PO number, supplier, amount, and status visible
2. WHEN a user taps a purchase order, THE Mobile_App SHALL navigate to the PO detail screen showing line items, supplier details, and delivery status
3. WHEN a user performs a Pull_Refresh gesture on the purchase orders list, THE Mobile_App SHALL reload the data from the backend

### Requirement 36: Projects

**User Story:** As a project manager, I want to view project dashboards on my phone, so that I can monitor project progress and budgets while on site.

#### Acceptance Criteria

1. WHERE the projects module is enabled, THE Mobile_App SHALL display a list of projects with project name, status, and budget utilisation visible
2. WHEN a user taps a project, THE Mobile_App SHALL navigate to the project dashboard screen showing tasks, budget breakdown, linked invoices, and time entries
3. WHEN a user performs a Pull_Refresh gesture on the project list, THE Mobile_App SHALL reload the data from the backend

### Requirement 37: Schedule and Calendar

**User Story:** As a business owner, I want to view the staff schedule and calendar on my phone, so that I can manage appointments and staff availability while mobile.

#### Acceptance Criteria

1. WHERE the scheduling module is enabled, THE Mobile_App SHALL display a calendar view showing scheduled events, appointments, and staff assignments
2. WHEN a user taps a calendar event, THE Mobile_App SHALL navigate to the event detail screen
3. WHEN a user taps "New Event", THE Mobile_App SHALL display an event creation form with date, time, staff assignment, and description fields
4. WHEN a user performs a Pull_Refresh gesture on the calendar, THE Mobile_App SHALL reload the schedule data from the backend

### Requirement 38: SMS Communication

**User Story:** As a business owner, I want to send SMS messages to customers from my phone, so that I can communicate appointment reminders and updates quickly.

#### Acceptance Criteria

1. WHERE the sms module is enabled, THE Mobile_App SHALL display an SMS option on customer profile screens and invoice detail screens
2. WHEN a user taps "Send SMS" on a customer profile, THE Mobile_App SHALL display a message composition screen with the customer's phone number pre-filled
3. WHEN a user sends an SMS, THE Mobile_App SHALL submit the message via the backend SMS endpoint (Connexus provider) and display a delivery confirmation
4. IF the SMS fails to send, THEN THE Mobile_App SHALL display an error message with the failure reason

### Requirement 39: Customer Portal Deep Links

**User Story:** As a business owner, I want to share customer portal links from my phone, so that customers can view their invoices and quotes online.

#### Acceptance Criteria

1. WHEN a user taps "Share Portal Link" on an invoice or quote detail screen, THE Mobile_App SHALL generate the customer portal URL and open the device share sheet via the Capacitor_Bridge
2. THE Mobile_App SHALL support receiving Deep_Link URLs that navigate directly to specific invoices, quotes, jobs, or customer profiles

### Requirement 40: Kiosk Mode

**User Story:** As a business owner, I want to run the app in kiosk mode on a tablet, so that customers can check in or browse services at the front desk.

#### Acceptance Criteria

1. WHEN a user with the "kiosk" role logs in, THE Mobile_App SHALL display the kiosk screen instead of the standard Dashboard
2. WHILE in kiosk mode, THE Mobile_App SHALL hide the Tab_Navigator and restrict navigation to kiosk-appropriate screens only
3. THE Mobile_App SHALL optimise the kiosk layout for tablet screen sizes (768px and above)

### Requirement 41: Settings Management

**User Story:** As a business owner, I want to access organisation settings on my phone, so that I can manage basic configuration while away from the office.

#### Acceptance Criteria

1. WHEN a user with org_admin or global_admin role taps "Settings" in the More menu, THE Mobile_App SHALL navigate to the settings screen
2. THE Mobile_App SHALL display settings sections for Profile, Organisation, Notifications, Branding, and Online Payments
3. WHEN a user modifies a setting and taps "Save", THE Mobile_App SHALL update the setting via the backend API and display a success confirmation
4. THE Module_Gate SHALL hide the Settings navigation item from users with salesperson or branch_admin roles

### Requirement 42: Deep Linking and Navigation

**User Story:** As a user, I want to open specific screens in the app from push notifications and external links, so that I can navigate directly to relevant content.

#### Acceptance Criteria

1. WHEN the Mobile_App receives a Deep_Link URL matching the pattern `/invoices/:id`, THE Mobile_App SHALL navigate to the invoice detail screen for the specified invoice
2. WHEN the Mobile_App receives a Deep_Link URL matching the pattern `/jobs/:id`, THE Mobile_App SHALL navigate to the job detail screen for the specified job
3. WHEN the Mobile_App receives a Deep_Link URL matching the pattern `/customers/:id`, THE Mobile_App SHALL navigate to the customer profile screen for the specified customer
4. WHEN the Mobile_App receives a Deep_Link URL matching the pattern `/compliance`, THE Mobile_App SHALL navigate to the compliance dashboard
5. IF a Deep_Link targets a screen that requires authentication and the user is not authenticated, THEN THE Mobile_App SHALL redirect to the login screen and navigate to the target screen after successful authentication

### Requirement 43: Camera Integration

**User Story:** As a tradesperson, I want to use my phone camera within the app, so that I can capture photos for compliance documents, expense receipts, and job documentation.

#### Acceptance Criteria

1. WHEN a camera action is triggered (compliance upload, expense receipt, job photo), THE Capacitor_Bridge SHALL request camera permissions from the device operating system
2. IF the user grants camera permissions, THEN THE Capacitor_Bridge SHALL open the device camera in photo capture mode
3. IF the user denies camera permissions, THEN THE Mobile_App SHALL display a message explaining that camera access is required and provide a link to device settings
4. WHEN a photo is captured, THE Mobile_App SHALL display a preview with options to retake or confirm before uploading
5. THE Mobile_App SHALL compress captured photos to a maximum of 2MB before uploading to reduce bandwidth usage

### Requirement 44: Branch Context

**User Story:** As a multi-branch business user, I want to switch between branches on my phone, so that I can view data for different locations.

#### Acceptance Criteria

1. WHERE the branch_management module is enabled AND the user is not a branch_admin, THE Mobile_App SHALL display a branch selector in the app header
2. WHEN a user selects a branch from the selector, THE Branch_Context SHALL update the selected branch and inject the corresponding X-Branch-Id header into all subsequent API requests
3. WHEN a user selects "All Branches", THE Branch_Context SHALL remove the X-Branch-Id header so the backend returns data across all branches
4. WHILE the user has the branch_admin role, THE Mobile_App SHALL lock the Branch_Context to the user's assigned branch and hide the branch selector
5. THE Mobile_App SHALL display the active branch name as a badge in the app header

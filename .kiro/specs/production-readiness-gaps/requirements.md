# Requirements Document

## Introduction

This specification addresses the production-readiness gaps identified in the OraInvoice Universal Platform feature gap analysis. The backend is 95% complete with 56+ API modules and 500+ endpoints, but the frontend is only 60% complete — approximately 40-50% of backend functionality is inaccessible to users. Fifteen or more complete backend modules have no frontend interface at all, and the ModuleRouter.tsx uses placeholder components that render non-functional pages. This spec covers: building missing frontend interfaces for all backend modules, replacing all placeholder router components with real implementations, integrating existing context providers (FeatureFlagProvider, ModuleProvider, TerminologyProvider) into all components, adding integration tests for end-to-end workflows, and optimising interfaces for mobile/tablet use. Requirements are organised by priority tier (Critical, High, Medium) matching the gap analysis.

## Glossary

- **Platform**: The OraInvoice SaaS application including all backend API modules, frontend React/TypeScript UI, and supporting infrastructure
- **Frontend_Interface**: A React/TypeScript page or set of pages that consume backend API endpoints and present interactive UI to users
- **Placeholder_Component**: A non-functional React component in ModuleRouter.tsx that renders only a text label (e.g. `<div>Kitchen Display</div>`) instead of a real interface
- **Kitchen_Display_Frontend**: The React interface for the Kitchen Display System, consuming WebSocket and REST endpoints from the kitchen_display backend module
- **Franchise_Frontend**: The React interface for multi-location and franchise management, consuming the franchise and locations backend modules
- **Construction_Frontend**: The React interfaces for progress claims, variations, and retentions, consuming the respective backend modules
- **Webhook_Management_Frontend**: The React interface for outbound webhook configuration, testing, and delivery monitoring
- **Time_Tracking_V2_Frontend**: The enhanced React interface for time tracking with project allocation, automatic tracking, and analytics beyond the basic V1 TimeSheet
- **Jobs_V2_Frontend**: The enhanced React interface for job management with project hierarchy, advanced workflows, and resource allocation beyond the basic V1 JobBoard
- **Inventory_Advanced_Frontend**: The React interfaces for pricing rules management, advanced stock adjustments, and automated reorder management
- **Loyalty_Frontend**: The React interface for loyalty program configuration, points management, tier setup, and analytics
- **Feature_Flag_Frontend**: The React interface for organisation-level feature flag management, A/B testing configuration, and rollout monitoring
- **Module_Management_Frontend**: The React interface for dynamically enabling/disabling business modules with dependency visualisation
- **MultiCurrency_Frontend**: The React interface for currency configuration, exchange rate management, and historical rate tracking
- **Table_Management_Frontend**: The enhanced React interface for floor plan editing, real-time table status, and reservation management
- **Tipping_Frontend**: The enhanced React interface for tip distribution rules, staff allocation management, and tip analytics
- **Context_Provider**: A React context (FeatureFlagContext, ModuleContext, TerminologyContext) that provides shared state to child components
- **ModuleRouter**: The React component (ModuleRouter.tsx) that conditionally renders routes based on enabled modules and feature flags
- **Integration_Test**: An end-to-end test that verifies a complete user workflow spanning multiple modules and API calls
- **Mobile_Optimised**: A UI that is responsive and touch-friendly on tablet (768px-1024px) and phone (320px-767px) viewports
- **WebSocket_Connection**: A persistent bidirectional connection between the frontend and backend for real-time data updates (used by Kitchen Display)
- **Org_Admin**: The organisation administrator role managing a single organisation's settings, users, modules, and billing
- **Staff_Member**: A role for employees assigned to jobs, schedules, and time tracking
- **Location_Manager**: A sub-role of Org_Admin scoped to a single location within a multi-location organisation

## Requirements

### Requirement 1: Kitchen Display System Frontend (CRITICAL)

**User Story:** As a kitchen staff member, I want a real-time kitchen display interface that shows incoming orders, preparation timers, and station filtering, so that I can coordinate food preparation with front-of-house operations.

#### Acceptance Criteria

1. THE Kitchen_Display_Frontend SHALL replace the KitchenPlaceholder component in ModuleRouter.tsx with a fully functional kitchen display interface that connects to the `WebSocket /ws/kitchen` endpoint for real-time order updates
2. THE Kitchen_Display_Frontend SHALL display incoming order items grouped by table number and order time, showing for each item: item name, quantity, modifications or special instructions, table number, and elapsed time since the order was placed
3. WHEN a kitchen staff member taps an item to mark it as prepared, THE Kitchen_Display_Frontend SHALL call `PUT /api/v2/kitchen/orders/{id}/status` to update the item status to "Ready" and visually move the item to a "Ready" column
4. THE Kitchen_Display_Frontend SHALL visually highlight orders that have exceeded a configurable preparation time threshold by changing the order card colour from white to amber (at threshold) to red (at 2x threshold)
5. THE Kitchen_Display_Frontend SHALL provide a full-screen display mode with large text (minimum 18px body, 24px headings) and high contrast suitable for wall-mounted screens in kitchen environments
6. THE Kitchen_Display_Frontend SHALL support station filtering via a station selector that calls `GET /api/v2/kitchen/orders` with a station parameter, allowing different display screens to show only relevant item categories (e.g. "Hot Food", "Drinks", "Desserts")
7. WHEN the WebSocket connection is lost, THE Kitchen_Display_Frontend SHALL display a prominent "Connection Lost" banner and attempt automatic reconnection with exponential backoff (1s, 2s, 4s, 8s, max 30s)
8. THE Kitchen_Display_Frontend SHALL use the TerminologyContext to display trade-appropriate labels and the FeatureFlagContext to respect feature flag gating


### Requirement 2: Multi-Location and Franchise Management Frontend (CRITICAL)

**User Story:** As an Org_Admin with multiple business locations, I want a location management dashboard with stock transfer workflows and franchise reporting, so that I can operate and monitor all locations from a single interface.

#### Acceptance Criteria

1. THE Franchise_Frontend SHALL replace the FranchisePlaceholder component in ModuleRouter.tsx with three functional pages: a Location List page, a Franchise Dashboard page, and a Stock Transfers page
2. THE Franchise_Frontend SHALL provide a Location List page that calls `GET /api/v2/locations` and displays all locations with name, address, staff count, and status, with the ability to add, edit, and deactivate locations
3. THE Franchise_Frontend SHALL provide a Franchise Dashboard page that calls `GET /api/v2/franchise/dashboard` and displays aggregate metrics including combined revenue, combined outstanding invoices, per-location performance comparison charts, and combined inventory levels
4. THE Franchise_Frontend SHALL provide a Stock Transfers page that calls `POST /api/v2/stock-transfers` and displays a transfer creation form with source location, destination location, product selection with quantities, and transfer notes
5. THE Franchise_Frontend SHALL display a stock transfer history list showing all transfers with status (Pending, In Transit, Received, Cancelled), source, destination, item count, and timestamps
6. WHEN a Location_Manager user accesses the Franchise_Frontend, THE Franchise_Frontend SHALL filter all displayed data to only the locations assigned to that user, enforcing the RBAC scoping from the backend
7. THE Franchise_Frontend SHALL provide per-location filtering on all data views and support a combined organisation-level view for Org_Admin users
8. THE Franchise_Frontend SHALL use the ModuleContext to verify the franchise module is enabled and the FeatureFlagContext to respect feature flag gating

### Requirement 3: Construction Industry Frontend — Progress Claims (CRITICAL)

**User Story:** As a builder or contractor, I want a progress claim management interface where I can create, submit, and track progress claims against contract values, so that I can bill clients progressively as construction milestones are reached.

#### Acceptance Criteria

1. THE Construction_Frontend SHALL replace the ConstructionPlaceholder component for the `/progress-claims/*` route in ModuleRouter.tsx with a functional Progress Claim List page and a Progress Claim Form page
2. THE Construction_Frontend SHALL provide a Progress Claim List page that calls `GET /api/v2/progress-claims` and displays all claims with: claim number, project name, contract value, cumulative claimed amount, amount due this claim, status (Draft, Submitted, Approved, Paid, Disputed), and submission date
3. THE Construction_Frontend SHALL provide a Progress Claim Form page that calls `POST /api/v2/progress-claims` with fields for: project selection, work completed this period (dollar amount), description of work completed, and supporting document uploads
4. THE Construction_Frontend SHALL display auto-calculated fields on the form in real-time: revised contract value (original + approved variations), cumulative work completed to date, retention withheld, previous claims total, and amount due this claim
5. THE Construction_Frontend SHALL prevent submission when the cumulative claimed amount would exceed the revised contract value, displaying a validation error with the maximum claimable amount
6. WHEN a progress claim status changes, THE Construction_Frontend SHALL update the claim card in the list view without requiring a full page reload
7. THE Construction_Frontend SHALL provide a "Generate PDF" button that calls the progress claim PDF endpoint and opens the generated PDF in a new browser tab
8. THE Construction_Frontend SHALL use the TerminologyContext for construction-specific labels and the FeatureFlagContext to respect feature flag gating

### Requirement 4: Construction Industry Frontend — Variations (CRITICAL)

**User Story:** As a builder or contractor, I want a variation order management interface where I can create, submit, and track scope changes with approval workflows, so that contract value adjustments are documented and reflected in progress claims.

#### Acceptance Criteria

1. THE Construction_Frontend SHALL replace the ConstructionPlaceholder component for the `/variations/*` route in ModuleRouter.tsx with a functional Variation List page and a Variation Form page
2. THE Construction_Frontend SHALL provide a Variation List page that calls the variations API and displays a variation register per project showing: variation number, description, cost impact (positive or negative), status (Draft, Submitted, Approved, Rejected), and cumulative impact on contract value
3. THE Construction_Frontend SHALL provide a Variation Form page with fields for: project selection, description of scope change, cost impact amount (supporting both positive additions and negative deductions), and supporting document uploads
4. WHEN a variation order is approved, THE Construction_Frontend SHALL display the updated revised contract value on the project view and on subsequent progress claim forms
5. THE Construction_Frontend SHALL provide a "Generate PDF" button that produces a printable variation order document with the organisation's branding
6. THE Construction_Frontend SHALL prevent editing or deletion of approved variations and display a message directing the user to create an offsetting variation instead

### Requirement 5: Construction Industry Frontend — Retentions (CRITICAL)

**User Story:** As a builder or contractor, I want a retention tracking dashboard where I can see retained amounts per project and process retention releases, so that I know exactly how much is held and can release it upon project completion.

#### Acceptance Criteria

1. THE Construction_Frontend SHALL replace the ConstructionPlaceholder component for the `/retentions/*` route in ModuleRouter.tsx with a functional Retention Summary dashboard
2. THE Construction_Frontend SHALL provide a Retention Summary page that displays per-project retention data: total retained, retention released, retention outstanding, and retention percentage
3. THE Construction_Frontend SHALL provide a retention release workflow that calls `POST /api/v2/retentions/{id}/release` with fields for: release amount (partial or full), release date, and linked payment reference
4. THE Construction_Frontend SHALL display retention details on the project dashboard view alongside progress claim information
5. THE Construction_Frontend SHALL validate that a retention release amount does not exceed the outstanding retention balance and display a validation error if exceeded

### Requirement 6: Advanced Webhook Management Frontend (CRITICAL)

**User Story:** As an Org_Admin, I want a webhook management interface where I can configure outbound webhooks, monitor delivery status, and test webhook endpoints, so that I can integrate OraInvoice with external business tools.

#### Acceptance Criteria

1. THE Webhook_Management_Frontend SHALL replace any placeholder webhook component in the settings routes with a fully functional Webhook Management page accessible from organisation settings
2. THE Webhook_Management_Frontend SHALL provide a webhook list view that calls `GET /api/v2/outbound-webhooks` and displays all configured webhooks with: target URL, subscribed event types, active/inactive status, last delivery status, and failure count
3. THE Webhook_Management_Frontend SHALL provide a webhook creation and editing form with fields for: target URL (HTTPS required, validated on input), event type selection (multi-select from available events including invoice.created, invoice.paid, customer.created, job.status_changed, booking.created, payment.received, stock.low), webhook secret (auto-generated with copy-to-clipboard), and active/inactive toggle
4. THE Webhook_Management_Frontend SHALL provide a "Test Webhook" button per webhook that calls `POST /api/v2/outbound-webhooks/{id}/test` and displays the response status code, response time, and response body in a modal
5. THE Webhook_Management_Frontend SHALL provide a delivery log view per webhook that calls `GET /api/v2/outbound-webhooks/{id}/deliveries` and displays: event type, delivery timestamp, HTTP response status code, response time in milliseconds, and retry count
6. THE Webhook_Management_Frontend SHALL display a visual status indicator per webhook: green for healthy (last delivery succeeded), amber for degraded (recent failures with retries pending), and red for failing (50+ consecutive failures, auto-disabled)
7. WHEN a webhook is auto-disabled due to consecutive failures, THE Webhook_Management_Frontend SHALL display a prominent warning with a "Re-enable" button and the failure details
8. THE Webhook_Management_Frontend SHALL use the FeatureFlagContext to respect feature flag gating and the ModuleContext to verify the webhooks module is enabled

### Requirement 7: Time Tracking V2 Frontend (HIGH)

**User Story:** As a Salesperson or Staff_Member, I want an enhanced time tracking interface with project allocation, automatic time detection, and analytics, so that I can accurately track and bill time across multiple projects and jobs.

#### Acceptance Criteria

1. THE Time_Tracking_V2_Frontend SHALL enhance the existing TimeSheet.tsx component to consume V2 time tracking API endpoints, adding project allocation, task-level tracking, and analytics views
2. THE Time_Tracking_V2_Frontend SHALL provide an enhanced timer interface that supports: selecting a project and task before starting the timer, switching between tasks without stopping the timer (automatic split entries), and displaying the active timer in the application header via the HeaderTimer component
3. THE Time_Tracking_V2_Frontend SHALL provide a project-based time reporting view that displays: total hours per project, billable vs non-billable breakdown, cost analysis (hours × staff rate), and comparison against project budget
4. THE Time_Tracking_V2_Frontend SHALL provide a weekly timesheet grid view where users can enter time per project per day, with row totals per project and column totals per day
5. THE Time_Tracking_V2_Frontend SHALL provide a "Convert to Invoice" action on billable time entries that creates labour line items (hours × rate) on a draft invoice, marking converted entries as "invoiced" to prevent double-billing
6. THE Time_Tracking_V2_Frontend SHALL display overlap validation errors in real-time when a user attempts to create a time entry that overlaps with an existing entry for the same user
7. THE Time_Tracking_V2_Frontend SHALL integrate with the Job_Module by displaying a time entry panel on the Job Detail page where users can log time directly against a job

### Requirement 8: Jobs V2 and Project Management Frontend (HIGH)

**User Story:** As a Salesperson or Org_Admin, I want an enhanced job management interface with project hierarchy, advanced workflow management, and resource allocation, so that I can manage complex multi-job projects with full visibility into progress and profitability.

#### Acceptance Criteria

1. THE Jobs_V2_Frontend SHALL enhance the existing JobBoard.tsx, JobList.tsx, and JobDetail.tsx components to consume V2 jobs API endpoints, adding project hierarchy, advanced status workflows, and resource allocation
2. THE Jobs_V2_Frontend SHALL provide a project hierarchy view that displays jobs grouped under their parent project with expandable/collapsible project nodes, showing per-project totals for hours, costs, and revenue
3. THE Jobs_V2_Frontend SHALL provide an enhanced Kanban board with drag-and-drop status transitions that enforces valid status transitions (Enquiry → Scheduled → In Progress → On Hold → Completed → Invoiced → Cancelled) and displays a validation error toast when an invalid transition is attempted
4. THE Jobs_V2_Frontend SHALL provide a resource allocation view showing staff assignments across jobs with a visual timeline, highlighting scheduling conflicts where a staff member is double-booked
5. THE Jobs_V2_Frontend SHALL provide a job profitability panel on the Job Detail page showing: total revenue (linked invoices), total costs (time entries × rates + expenses + materials), and profit margin percentage, updated in real-time as linked entities change
6. THE Jobs_V2_Frontend SHALL provide a "Convert to Invoice" button on completed jobs that calls the job-to-invoice conversion API and navigates to the newly created draft invoice
7. THE Jobs_V2_Frontend SHALL support job templates selectable from a dropdown when creating a new job, pre-filling description, checklist items, and default line items based on the selected template

### Requirement 9: Enhanced Inventory Management Frontend (HIGH)

**User Story:** As an Org_Admin, I want a complete inventory management interface with pricing rules configuration, advanced stock adjustment workflows, and automated reorder management, so that I can optimise inventory operations and pricing strategies.

#### Acceptance Criteria

1. THE Inventory_Advanced_Frontend SHALL enhance the existing inventory pages (ProductList.tsx, ProductDetail.tsx, StockMovements.tsx, StockTake.tsx, CategoryTree.tsx, CSVImport.tsx) to consume all backend inventory and pricing rules API endpoints
2. THE Inventory_Advanced_Frontend SHALL provide a Pricing Rules management page that calls the pricing rules API and displays all rules with: rule type (customer-specific, volume/tiered, date-based, trade category), applicable products, conditions, and priority order
3. THE Inventory_Advanced_Frontend SHALL provide a pricing rule creation form with fields for: rule type selection, product or product category selection, condition configuration (customer, quantity thresholds, date range, or trade category), override price or discount percentage, and priority ranking
4. THE Inventory_Advanced_Frontend SHALL display a validation warning during rule creation when overlapping rules exist for the same product and condition type, showing the conflicting rules
5. THE Inventory_Advanced_Frontend SHALL provide an advanced stock adjustment workflow with: adjustment reason selection (damage, theft, expiry, count correction, other), quantity adjustment (positive or negative), reference notes, and batch adjustment support for multiple products in a single operation
6. THE Inventory_Advanced_Frontend SHALL provide a low-stock dashboard that displays all products at or below their configured low stock threshold, with a one-click "Create Purchase Order" action that pre-populates a PO with the reorder quantities
7. THE Inventory_Advanced_Frontend SHALL provide a supplier catalogue integration view that displays products grouped by preferred supplier with last purchase price, lead time, and reorder status
8. THE Inventory_Advanced_Frontend SHALL support barcode scanning via device camera on the stock take and product lookup screens using the existing barcodeScanner.ts utility

### Requirement 10: Loyalty Program Management Frontend (HIGH)

**User Story:** As an Org_Admin, I want a loyalty program management interface where I can configure points earning rates, membership tiers, and redemption rules, so that I can set up and manage customer retention programs.

#### Acceptance Criteria

1. THE Loyalty_Frontend SHALL replace the LoyaltyPlaceholder component in ModuleRouter.tsx with a fully functional Loyalty Configuration page and a Loyalty Analytics dashboard
2. THE Loyalty_Frontend SHALL provide a Loyalty Configuration page with sections for: points earning rate (points per dollar spent), redemption rate (points per dollar discount), membership tier definitions (tier name, threshold, discount percentage, benefits description), and program active/inactive toggle
3. THE Loyalty_Frontend SHALL provide a membership tier management interface where Org_Admin can create, edit, reorder, and delete tiers, with validation that tier thresholds are in ascending order and do not overlap
4. THE Loyalty_Frontend SHALL provide a customer loyalty view accessible from the customer detail page showing: current points balance, current tier, points to next tier, and a transaction history of points earned and redeemed
5. THE Loyalty_Frontend SHALL provide a Loyalty Analytics dashboard showing: total active members, members per tier, total points issued, total points redeemed, redemption rate percentage, and top customers by points balance
6. THE Loyalty_Frontend SHALL provide a points adjustment interface for manual point additions or deductions with a required reason field, for handling customer service scenarios
7. THE Loyalty_Frontend SHALL use the ModuleContext to verify the loyalty module is enabled and the FeatureFlagContext to respect feature flag gating

### Requirement 11: Feature Flag Management Frontend — Organisation Level (MEDIUM)

**User Story:** As an Org_Admin, I want an organisation-level feature flag management interface where I can view which features are enabled for my organisation and request changes, so that I have visibility and control over feature availability.

#### Acceptance Criteria

1. THE Feature_Flag_Frontend SHALL provide an organisation-level feature flags page accessible from organisation settings that calls `GET /api/v2/flags` and displays all feature flags relevant to the organisation with their current state (enabled/disabled)
2. THE Feature_Flag_Frontend SHALL group feature flags by category (core features, advanced features, beta features, experimental) with expandable sections and descriptions for each flag
3. THE Feature_Flag_Frontend SHALL display for each flag: flag name, description, current state, whether the state is inherited (from trade category, plan tier, or percentage rollout) or explicitly set, and the source of the current evaluation
4. WHERE the Global_Admin has granted organisation-level override capability for a flag, THE Feature_Flag_Frontend SHALL allow the Org_Admin to toggle the flag with the change taking effect within 5 seconds
5. THE Feature_Flag_Frontend SHALL provide a feature rollout monitoring view for Global_Admin showing: percentage of organisations with each flag enabled, adoption trends over time, and error rates correlated with flag changes
6. THE Feature_Flag_Frontend SHALL use the FeatureFlagContext to consume flag state and the ModuleContext to verify access

### Requirement 12: Module Management Frontend (MEDIUM)

**User Story:** As an Org_Admin, I want a module management interface where I can enable and disable business modules with clear dependency information, so that I can customise the platform to show only functionality relevant to my business.

#### Acceptance Criteria

1. THE Module_Management_Frontend SHALL provide a Module Configuration page accessible from organisation settings that displays all available modules grouped by category with their current enabled/disabled state
2. THE Module_Management_Frontend SHALL display for each module: module name, description, category, enabled/disabled toggle, dependency list (modules required for this module to function), and dependent modules (modules that require this module)
3. WHEN an Org_Admin attempts to disable a module that other enabled modules depend on, THE Module_Management_Frontend SHALL display a confirmation dialog listing the dependent modules that will also be disabled and require explicit confirmation
4. WHEN an Org_Admin enables a module that has dependencies, THE Module_Management_Frontend SHALL display a notification listing the dependency modules that will be automatically enabled alongside the selected module
5. THE Module_Management_Frontend SHALL display modules in a "coming soon" state as non-selectable cards with a visual badge and expected availability date
6. THE Module_Management_Frontend SHALL provide a visual dependency graph showing module relationships as a directed graph, allowing Org_Admin to understand the impact of enabling or disabling modules
7. WHEN a module is toggled, THE Module_Management_Frontend SHALL update the ModuleContext state so that the ModuleRouter immediately reflects the change without requiring a page reload

### Requirement 13: Multi-Currency Management Frontend (MEDIUM)

**User Story:** As an Org_Admin operating internationally, I want a currency management interface where I can configure enabled currencies, manage exchange rates, and view historical rate data, so that I can issue invoices in multiple currencies with accurate conversions.

#### Acceptance Criteria

1. THE MultiCurrency_Frontend SHALL provide a Currency Settings page accessible from organisation settings that displays the base currency and all enabled additional currencies with their current exchange rates
2. THE MultiCurrency_Frontend SHALL provide a currency enablement interface where Org_Admin can search and enable currencies from the ISO 4217 currency list, with each currency showing: code, name, symbol, and decimal places
3. THE MultiCurrency_Frontend SHALL provide an exchange rate management interface showing: current rate per enabled currency pair, rate source (manual or automatic provider), last update timestamp, and a manual rate entry form
4. THE MultiCurrency_Frontend SHALL provide a historical exchange rate chart per currency pair showing rate trends over a configurable date range (7 days, 30 days, 90 days, 1 year)
5. THE MultiCurrency_Frontend SHALL provide an exchange rate provider configuration section where Org_Admin can select the automatic rate provider, configure the update frequency, and view the last sync status
6. WHEN an exchange rate is not available for a currency pair, THE MultiCurrency_Frontend SHALL display a warning indicator on the currency and block invoice creation in that currency until a rate is entered
7. THE MultiCurrency_Frontend SHALL format all currency amounts according to each currency's standard format (decimal places, thousands separator, symbol position) using the formatting utilities from the multi_currency backend module

### Requirement 14: Table Management Frontend Enhancement (MEDIUM)

**User Story:** As an Org_Admin running a restaurant or café, I want an enhanced floor plan editor with drag-and-drop table placement, real-time status updates, and a reservation management interface, so that front-of-house staff can manage seating efficiently.

#### Acceptance Criteria

1. THE Table_Management_Frontend SHALL enhance the existing FloorPlan.tsx component to provide a drag-and-drop floor plan editor where Org_Admin can place, resize, move, and label tables with seat counts on a visual canvas
2. THE Table_Management_Frontend SHALL display real-time table status with colour coding: Available (green), Occupied (amber), Reserved (blue), and Needs Cleaning (red), updating via polling or WebSocket as table states change
3. WHEN a table is tapped or clicked in the floor plan view, THE Table_Management_Frontend SHALL open the associated POS order for that table or create a new order if none exists, integrating with the POS_Module
4. THE Table_Management_Frontend SHALL provide a reservation management interface that calls the reservations API and displays: upcoming reservations in a timeline view, reservation creation form (customer name, party size, date, time, duration, notes), and reservation status management
5. THE Table_Management_Frontend SHALL support table merging (selecting two adjacent tables and combining them) and splitting (separating a merged table) with visual feedback on the floor plan
6. THE Table_Management_Frontend SHALL enhance the existing ReservationList.tsx component to display reservations in both a list view and a calendar view with filtering by date and status

### Requirement 15: Tipping Management Frontend Enhancement (MEDIUM)

**User Story:** As an Org_Admin in a hospitality or service business, I want a tip management interface where I can configure distribution rules, manage staff allocations, and view tip analytics, so that tips are tracked and distributed fairly.

#### Acceptance Criteria

1. THE Tipping_Frontend SHALL enhance the existing TipPrompt.tsx component and provide additional pages for tip distribution configuration and tip analytics
2. THE Tipping_Frontend SHALL provide a Tip Distribution Rules page where Org_Admin can configure: distribution method (equal split, percentage-based, role-based), staff eligibility rules, and tip pooling settings
3. THE Tipping_Frontend SHALL provide a Staff Tip Allocation management page showing: per-staff tip totals for a configurable date range, allocation adjustments, and a tip distribution preview before finalisation
4. THE Tipping_Frontend SHALL provide a Tip Analytics dashboard showing: total tips collected (daily, weekly, monthly), average tip percentage, tips per staff member, tips by payment method, and trend charts over time
5. THE Tipping_Frontend SHALL display tip information on the POS transaction summary and on invoice detail views where tips were collected
6. THE Tipping_Frontend SHALL use the ModuleContext to verify the tipping module is enabled and the TerminologyContext for trade-appropriate labels

### Requirement 16: Router Configuration — Replace All Placeholder Components

**User Story:** As a platform user, I want every navigation route to lead to a functional page instead of a blank placeholder, so that the platform feels complete and I can access all features that my modules and feature flags allow.

#### Acceptance Criteria

1. THE ModuleRouter SHALL replace all placeholder components (KitchenPlaceholder, FranchisePlaceholder, ConstructionPlaceholder, FloorPlanPlaceholder, LoyaltyPlaceholder, and all others defined in ModuleRouter.tsx) with lazy-loaded imports of the corresponding real page components
2. THE ModuleRouter SHALL use React.lazy and Suspense for all module page imports to ensure code splitting and avoid loading unused module code
3. WHEN a user navigates to a module route that is disabled for their organisation, THE ModuleRouter SHALL redirect to the dashboard with a toast notification stating "This feature is currently disabled" (preserving the existing FlagGatedRoute behaviour)
4. WHEN a user navigates to a module route that is enabled but the page component fails to load (network error, chunk load failure), THE ModuleRouter SHALL display an error boundary with a "Retry" button instead of a blank screen
5. THE ModuleRouter SHALL replace the core route placeholders (DashboardPlaceholder, InvoicesPlaceholder, CustomersPlaceholder, SettingsPlaceholder, ReportsPlaceholder, NotificationsPlaceholder, DataPlaceholder) with lazy-loaded imports of the real page components
6. THE ModuleRouter SHALL ensure that all route paths defined in MODULE_ROUTES and CORE_ROUTES resolve to functional components that render meaningful UI and consume their respective backend API endpoints

### Requirement 17: Context Provider Integration Across All Components

**User Story:** As a platform developer, I want all frontend components to consume the FeatureFlagContext, ModuleContext, and TerminologyContext providers, so that feature gating, module visibility, and trade-specific terminology are consistently applied across the entire UI.

#### Acceptance Criteria

1. THE Platform SHALL ensure that every page component checks the ModuleContext to verify its parent module is enabled before rendering, displaying a "Module not available" message if the module is disabled
2. THE Platform SHALL ensure that every page component uses the FeatureFlagContext to conditionally render sub-features that are gated behind feature flags, hiding UI elements for disabled flags without breaking the page layout
3. THE Platform SHALL ensure that every page component uses the TerminologyContext to display trade-appropriate labels for: the primary asset/item label, the work unit label, the customer label, and line item category labels
4. WHEN the TerminologyContext does not have an override for a specific label, THE Platform SHALL fall back to the generic default label without displaying an error
5. THE Platform SHALL ensure that the FeatureFlagProvider, ModuleProvider, and TerminologyProvider are initialised before any route component renders, using a loading state during initialisation
6. THE Platform SHALL provide a custom React hook `useModuleGuard(moduleSlug)` that components can call to verify module enablement and redirect to the dashboard if the module is disabled, reducing boilerplate across page components

### Requirement 18: Integration Testing for End-to-End Workflows

**User Story:** As a platform developer, I want comprehensive integration tests that verify complete user workflows spanning multiple modules, so that cross-module interactions are validated and regressions are caught before deployment.

#### Acceptance Criteria

1. THE Platform SHALL provide integration tests for the following critical workflows: (a) POS transaction flow — product selection, order creation, payment processing, inventory decrement, receipt generation; (b) Job-to-invoice flow — job creation, time entry logging, expense logging, job completion, invoice conversion with all line items; (c) Construction flow — project creation, progress claim submission, variation approval with contract value update, retention calculation and release; (d) Multi-currency flow — currency enablement, exchange rate configuration, invoice creation in foreign currency, payment recording with exchange difference
2. THE Platform SHALL provide integration tests for the onboarding flow: signup, setup wizard completion (country, trade, business details, branding, modules), and first invoice creation with trade-specific terminology verification
3. THE Platform SHALL provide integration tests for the franchise flow: location creation, stock transfer between locations, per-location reporting, and aggregate franchise dashboard data verification
4. THE Platform SHALL provide frontend component integration tests using React Testing Library that verify: ModuleRouter renders correct components for enabled modules, ModuleRouter redirects for disabled modules, FeatureFlagContext correctly gates sub-features, and TerminologyContext correctly substitutes labels
5. WHEN an integration test fails, THE test output SHALL include: the specific workflow step that failed, the expected vs actual state, and the API request/response that caused the failure
6. THE Platform SHALL maintain integration test coverage for all workflows listed in acceptance criteria 1-3, with tests running as part of the CI/CD pipeline

### Requirement 19: Mobile and Tablet Optimisation

**User Story:** As a user accessing OraInvoice on a tablet or phone (e.g. a tradesperson on-site, a waiter at a restaurant), I want the interface to be touch-friendly and responsive, so that I can use the platform effectively on mobile devices.

#### Acceptance Criteria

1. THE Platform SHALL ensure that all new frontend interfaces created in this spec (Kitchen Display, Franchise Management, Construction modules, Webhook Management, Loyalty, Module Management, Multi-Currency, and enhanced Table/Tipping interfaces) are responsive and functional at tablet (768px-1024px) and phone (320px-767px) viewport widths
2. THE Platform SHALL ensure that touch targets (buttons, links, toggles, drag handles) have a minimum size of 44x44 CSS pixels on all interfaces to meet touch accessibility guidelines
3. THE Kitchen_Display_Frontend SHALL be optimised for landscape tablet orientation with large touch targets for marking items as prepared, suitable for use with wet or gloved hands in a kitchen environment
4. THE POS interface (POSScreen.tsx, OrderPanel.tsx, PaymentPanel.tsx, ProductGrid.tsx) SHALL be optimised for tablet use with: a responsive grid layout that adapts product columns to screen width, large payment buttons, and swipe gestures for order navigation
5. THE Table_Management_Frontend floor plan view SHALL support touch gestures: pinch-to-zoom on the floor plan, tap to select a table, and long-press to open the table context menu
6. THE Platform SHALL use CSS media queries and responsive layout patterns (flexbox, grid) rather than separate mobile components, ensuring a single codebase serves all viewport sizes
7. THE Platform SHALL ensure that all form inputs use appropriate mobile input types (type="tel" for phone numbers, type="email" for emails, inputmode="numeric" for currency amounts) to trigger the correct mobile keyboard

### Requirement 20: Placeholder Route Audit and Dead-Link Elimination

**User Story:** As a platform user, I want every menu item and navigation link to lead to a functional page, so that I never encounter a blank or broken page when navigating the platform.

#### Acceptance Criteria

1. THE Platform SHALL audit all navigation menus (sidebar, header, settings sub-menus) and verify that every link resolves to a functional page component that renders meaningful content
2. WHEN a navigation link points to a route that has no functional component (only a placeholder), THE Platform SHALL either hide the link from the menu (if the feature is not yet implemented) or replace the placeholder with the real component
3. THE Platform SHALL ensure that the sidebar navigation dynamically shows or hides menu items based on the ModuleContext (disabled modules have no menu items) and the FeatureFlagContext (disabled flags hide their associated menu items)
4. THE Platform SHALL ensure that direct URL navigation (typing a URL or using a bookmark) to a module route that is disabled returns a user-friendly "Feature not available" page with a link back to the dashboard, rather than a blank page or error
5. THE Platform SHALL ensure that the browser back button works correctly after a redirect from a disabled module route, navigating to the previous functional page rather than creating a redirect loop
6. THE Platform SHALL log (to the browser console in development mode) any route that resolves to a placeholder component, to assist developers in identifying remaining gaps during development

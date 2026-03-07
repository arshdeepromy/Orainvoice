# Requirements Document

## Introduction

OraInvoice Universal Platform is a major enhancement to the existing OraInvoice NZ workshop invoicing SaaS, expanding it into a globally capable, multi-trade, multi-industry invoicing and business management platform. The enhancement layers on top of the existing V1 foundation (PostgreSQL, FastAPI, React/TypeScript, Stripe, Celery/Redis, Carjam integration) without replacing it. Existing workshop organisations continue to operate unchanged. New capabilities include: a Trade Category Registry enabling any trade or industry, a multi-step onboarding wizard with country/trade selection, a module selection system that shows/hides entire feature groups, inventory and stock management, job and work order management, ecommerce and WooCommerce integration, POS and receipt printer support, multi-currency and internationalisation, enterprise multi-location and franchise support, global branding with "Powered By" system, and a comprehensive Global Admin console with migration tooling. The platform must support gradual rollout via feature flags, backward-compatible API versioning, data migration for existing V1 organisations, and cross-module dependency management. The guiding design philosophy remains: every interaction should feel obvious, fast, and frictionless. New trade types and modules are layered in so each organisation only sees what applies to their configured trade category.

## Glossary

- **Platform**: The OraInvoice SaaS application as a whole, including all tiers, modules, and public-facing surfaces
- **Global_Admin**: The platform owner role with access to the Global Admin Console; manages all organisations, trade categories, integrations, billing, feature flags, and platform health
- **Org_Admin**: The organisation administrator role; manages a single organisation's branding, settings, users, modules, and billing
- **Salesperson**: The end-user role within an organisation; creates customers, invoices, quotes, jobs, and records payments
- **Location_Manager**: A sub-role of Org_Admin scoped to a single location within a multi-location organisation; manages that location's staff, inventory, and operations
- **Franchise_Admin**: A read-only reporting role that can view aggregate data across multiple franchisee organisations without modifying any data
- **Staff_Member**: A role for employees or contractors assigned to jobs, schedules, and time tracking without invoice or financial access
- **Organisation**: A single subscribing business with its own isolated data space, trade category, and module configuration
- **Tenant**: Synonym for Organisation in the multi-tenant architecture context
- **Trade_Category**: A record in the Trade Category Registry defining a supported trade type with its default services, terminology, template preferences, and recommended modules
- **Trade_Family**: A grouping of related Trade Categories (e.g. "Automotive & Transport", "Building & Construction")
- **Trade_Category_Registry**: The Global Admin-managed registry of all supported trade types, their configurations, and metadata
- **Module**: A discrete feature group that can be enabled or disabled per organisation; disabled modules are completely hidden from the UI and API
- **Module_Registry**: The system that tracks all available modules, their dependencies, and their enabled/disabled state per organisation
- **Setup_Wizard**: The multi-step onboarding wizard presented to new organisations covering country, trade, business details, branding, modules, and initial data
- **Terminology_Map**: A mapping of generic UI labels to trade-specific terms stored in the Trade Category Registry (e.g. "Vehicle" → "Device" for IT trades)
- **Feature_Flag**: A configuration toggle managed by Global Admin that controls gradual rollout of new features to specific organisations, trade categories, or percentages of users
- **Invoice_Module**: The module responsible for creating, managing, searching, and issuing invoices
- **Quote_Module**: The module responsible for creating, managing, and converting quotes/estimates to invoices
- **Job_Module**: The module responsible for job and work order lifecycle management
- **Inventory_Module**: The module responsible for product catalogue, stock levels, movements, pricing rules, and purchase orders
- **POS_Module**: The module responsible for point-of-sale mode, receipt printing, and offline transaction queuing
- **Ecommerce_Module**: The module responsible for WooCommerce integration, general ecommerce webhooks, and API-based order ingestion
- **Time_Tracking_Module**: The module responsible for manual and timer-based time entry linked to jobs and invoices
- **Project_Module**: The module responsible for grouping jobs, invoices, quotes, time entries, and expenses into projects with profitability tracking
- **Expense_Module**: The module responsible for logging expenses against jobs or projects with optional pass-through to invoices
- **PurchaseOrder_Module**: The module responsible for raising purchase orders, receiving goods, and linking to jobs/projects/inventory
- **Staff_Module**: The module responsible for staff and contractor management, scheduling, job assignment, and labour cost tracking
- **Scheduling_Module**: The module responsible for visual calendar, drag-and-drop scheduling, and resource allocation
- **Booking_Module**: The module responsible for customer-facing booking pages and appointment management
- **Tipping_Module**: The module responsible for tip collection on invoices and POS transactions with staff allocation
- **Table_Module**: The module responsible for visual floor plan, table status tracking, and seat management for hospitality
- **Kitchen_Display_Module**: The module responsible for order item display and tick-off interface for food preparation
- **Retention_Module**: The module responsible for construction retention tracking per project
- **ProgressClaim_Module**: The module responsible for progress claims against contract values with variation tracking
- **Variation_Module**: The module responsible for scope change orders, approval workflows, and contract value updates
- **Compliance_Module**: The module responsible for certification and compliance document management linked to invoices
- **MultiCurrency_Module**: The module responsible for multi-currency invoicing, exchange rate management, and base currency consolidation
- **Loyalty_Module**: The module responsible for loyalty points, membership tiers, and auto-applied discounts
- **Franchise_Module**: The module responsible for franchise and multi-location organisation support
- **Recurring_Module**: The module responsible for recurring invoice schedules
- **Branding_Module**: The Global Admin module responsible for platform branding, "Powered By" configuration, and white-label settings
- **Migration_Tool**: The Global Admin tool for database migrations between environments with integrity checking and rollback
- **Compliance_Profile**: A country-specific tax and regulatory configuration (e.g. NZ GST, AU BAS, UK VAT)
- **Data_Residency_Region**: The geographic region where an organisation's data is stored (NZ/AU, UK/EU, North America)
- **Seed_Data**: Pre-configured default data (services, products, templates) associated with a Trade Category for new organisation bootstrapping
- **API_Version**: A versioned API namespace (e.g. /api/v1/, /api/v2/) ensuring backward compatibility during platform evolution
- **Webhook_Signature**: An HMAC-SHA256 signature included in outbound webhook headers for receiver verification
- **Offline_Queue**: A local IndexedDB-backed queue of transactions created while the POS is offline, pending sync when connectivity resumes
- **Sync_Conflict**: A situation where an offline-queued transaction conflicts with server-side state (e.g. stock level changed, price updated)
- **Print_Queue**: A managed queue of receipt print jobs dispatched to configured printers via ESC/POS protocol
- **ESC_POS**: The Epson Standard Code for Point of Sale, a command protocol for receipt printers
- **Cloud_Print_Agent**: A lightweight agent installed at a business location that bridges cloud print requests to local USB/network printers
- **Stock_Movement**: A record of inventory quantity change with type (sale, receive, adjustment, transfer, return), quantity, and reference
- **Pricing_Rule**: A configurable rule that overrides base product pricing based on customer, volume, date range, or trade category
- **WooCommerce_Sync**: Bidirectional synchronisation between OraInvoice product catalogue/orders and a WooCommerce store
- **Floor_Plan**: A visual layout of tables/seats for hospitality organisations used in the Table Module
- **Progress_Claim**: A periodic claim for payment against a construction contract value, tracking cumulative claimed and paid amounts
- **Retention**: A configurable percentage withheld from progress claims in construction, released upon project completion
- **Variation_Order**: A formal scope change to a construction contract that adjusts the contract value after approval

## Requirements

### Requirement 1: Platform Rebranding and API Versioning

**User Story:** As a Global_Admin, I want the platform rebranded to OraInvoice with a versioned API, so that existing V1 integrations continue working while new universal features are introduced under a new API version.

#### Acceptance Criteria

1. THE Platform SHALL use "OraInvoice" as the platform name across all UI surfaces, emails, PDFs, documentation, and public-facing pages
2. THE Platform SHALL serve new universal platform endpoints under the `/api/v2/` namespace while continuing to serve all existing V1 endpoints under `/api/v1/` without modification
3. WHEN a request is made to a deprecated `/api/v1/` endpoint, THE Platform SHALL include a `Deprecation` HTTP header with the sunset date and a `Link` header pointing to the equivalent `/api/v2/` endpoint
4. THE Platform SHALL maintain `/api/v1/` endpoints for a minimum of 12 months after `/api/v2/` general availability before any endpoint is removed
5. WHEN a `/api/v1/` endpoint is called after its sunset date, THE Platform SHALL return HTTP 410 Gone with a JSON body containing the replacement endpoint URL

### Requirement 2: Feature Flag System

**User Story:** As a Global_Admin, I want to control the rollout of new features via feature flags, so that I can gradually enable capabilities for specific organisations or trade categories without code deployments.

#### Acceptance Criteria

1. THE Platform SHALL provide a Feature Flag management interface in the Global Admin Console with create, edit, enable, disable, and archive operations
2. THE Platform SHALL support feature flag targeting by: specific organisation IDs, trade category, trade family, country, subscription plan tier, and percentage-based random rollout
3. WHEN a feature flag is evaluated, THE Platform SHALL check targeting rules in priority order (organisation override → trade category → trade family → country → plan tier → percentage) and return the first matching result
4. THE Platform SHALL cache feature flag evaluations in Redis with a configurable TTL (default 60 seconds) to avoid database lookups on every request
5. WHEN a feature flag is toggled, THE Platform SHALL invalidate the Redis cache for that flag within 5 seconds across all application instances
6. THE Platform SHALL log all feature flag state changes in the audit log with the Global_Admin who made the change, the previous state, and the new state
7. THE Platform SHALL expose a `/api/v2/flags` endpoint that returns all active feature flags for the authenticated organisation's context, so the frontend can conditionally render UI elements
8. IF a feature flag evaluation fails due to a Redis or database error, THEN THE Platform SHALL fall back to the flag's configured default value (enabled or disabled) rather than blocking the request

### Requirement 3: Trade Category Registry

**User Story:** As a Global_Admin, I want to manage a registry of supported trade categories with their default configurations, so that new trade types can be added without code deployments and each trade gets a tailored experience.

#### Acceptance Criteria

1. THE Trade_Category_Registry SHALL store for each trade category: unique slug, display name, trade family assignment, icon, description, default service items (name, description, default price, unit of measure), default product items, invoice template layout identifier, recommended modules list, terminology overrides map, and active/retired status
2. WHEN a Global_Admin creates a new trade category, THE Trade_Category_Registry SHALL validate that the slug is unique, the trade family exists, and at least one default service or product item is defined
3. WHEN a Global_Admin retires a trade category, THE Trade_Category_Registry SHALL prevent new organisations from selecting it while allowing existing organisations using that category to continue operating unchanged
4. THE Trade_Category_Registry SHALL support trade families as a grouping mechanism with: family slug, display name, icon, display order, and active status
5. WHEN a trade category's default services or terminology are updated, THE Trade_Category_Registry SHALL apply changes only to newly created organisations and not retroactively modify existing organisations' configurations
6. THE Trade_Category_Registry SHALL provide a seed data export/import mechanism in JSON format so that trade category configurations can be version-controlled and deployed across environments
7. THE Trade_Category_Registry SHALL support a "Custom / Other" trade category as a catch-all for businesses that do not fit any predefined category, with generic terminology and no pre-selected modules
8. THE Trade_Category_Registry SHALL store for each trade category a list of country-specific compliance notes (e.g. licensing requirements, tax treatment notes) that are displayed during onboarding but do not enforce restrictions

### Requirement 4: Trade-Specific Terminology and Template Adaptation

**User Story:** As an Org_Admin, I want the platform interface to use terminology and invoice layouts appropriate to my trade, so that the platform feels purpose-built for my industry.

#### Acceptance Criteria

1. THE Platform SHALL maintain a terminology mapping system that translates generic UI labels to trade-specific terms based on the organisation's configured trade category
2. THE Platform SHALL support terminology overrides for at minimum: the primary asset/item label (e.g. "Vehicle" → "Device", "Job Site", "Table"), the work unit label (e.g. "Job" → "Work Order", "Booking", "Project"), the customer label (e.g. "Customer" → "Client", "Patient", "Guest"), and the line item category labels
3. WHEN an organisation's trade category is set or changed, THE Platform SHALL apply the corresponding terminology map to all UI labels, form field labels, placeholder text, and PDF templates for that organisation
4. THE Platform SHALL allow Org_Admin to override any individual terminology mapping from the organisation settings, taking precedence over the trade category defaults
5. THE Platform SHALL render invoice PDFs using the trade-specific template layout associated with the organisation's trade category, while drawing from the same underlying invoice data model
6. WHEN a trade category does not define a terminology override for a specific label, THE Platform SHALL use the generic default label

### Requirement 5: Organisation Setup Wizard (Enhanced)

**User Story:** As a new organisation owner, I want a guided setup wizard that configures the platform for my country, trade, and business needs, so that I can start using the platform quickly with relevant defaults.

#### Acceptance Criteria

1. WHEN a new organisation is created (via signup or Global_Admin provisioning), THE Setup_Wizard SHALL present a 7-step guided flow: (1) Welcome and Country Selection, (2) Trade Area Selection, (3) Business Details, (4) Branding with live invoice preview, (5) Module Selection, (6) First Service or Product entry, (7) Ready confirmation
2. WHEN the user selects a country in Step 1, THE Setup_Wizard SHALL auto-configure: currency, date format, number format, tax label and default rate, tax inclusion default, timezone, and the applicable Compliance_Profile
3. WHEN the user selects a trade category in Step 2, THE Setup_Wizard SHALL pre-populate: recommended modules (pre-checked but editable), default service items, terminology overrides, and invoice template layout
4. WHEN the user reaches Step 4 (Branding), THE Setup_Wizard SHALL display a live preview of an invoice PDF that updates in real-time as the user changes logo, colours, and header/footer text
5. WHEN the user reaches Step 5 (Module Selection), THE Setup_Wizard SHALL display all available modules grouped by category with the trade-recommended modules pre-selected, and show dependency warnings if a user deselects a module that another selected module depends on
6. THE Setup_Wizard SHALL allow any step to be skipped and completed later from the organisation Settings page
7. THE Setup_Wizard SHALL make the workspace fully usable immediately after completion regardless of which steps were skipped, using sensible defaults for unconfigured settings
8. WHEN a user completes or skips the wizard, THE Setup_Wizard SHALL record the completion state of each step so the user can resume from where they left off
9. THE Setup_Wizard SHALL validate business details (company name required, valid email format, valid phone format) before allowing progression from Step 3
10. IF the user's selected country has specific regulatory requirements (e.g. GST number format for NZ, ABN format for AU, VAT number format for UK), THEN THE Setup_Wizard SHALL validate the tax identifier format in Step 3

### Requirement 6: Module Selection and Dependency System

**User Story:** As an Org_Admin, I want to enable or disable feature modules for my organisation, so that the platform only shows functionality relevant to my business without clutter.

#### Acceptance Criteria

1. THE Module_Registry SHALL maintain a catalogue of all available modules with: module slug, display name, description, category grouping, dependency list (other modules required), and incompatibility list (modules that cannot be active simultaneously)
2. WHEN a module is disabled for an organisation, THE Platform SHALL completely hide all UI elements, menu items, API endpoints, and background tasks associated with that module for that organisation
3. WHEN an Org_Admin attempts to disable a module that other enabled modules depend on, THE Module_Registry SHALL display a warning listing the dependent modules and require confirmation or simultaneous disabling of dependents
4. WHEN an Org_Admin enables a module that has dependencies, THE Module_Registry SHALL automatically enable the required dependency modules and notify the Org_Admin of the additional activations
5. THE Module_Registry SHALL enforce the following dependency chains: POS_Module requires Inventory_Module; Kitchen_Display_Module requires Table_Module and POS_Module; Tipping_Module requires POS_Module or Invoice_Module; ProgressClaim_Module requires Project_Module; Retention_Module requires ProgressClaim_Module; Variation_Module requires ProgressClaim_Module; Expense_Module requires Job_Module or Project_Module; PurchaseOrder_Module requires Inventory_Module; Staff_Module requires Scheduling_Module; Ecommerce_Module requires Inventory_Module
6. THE Platform SHALL check module enablement on every API request to a module-specific endpoint and return HTTP 403 with a clear error message if the module is disabled for the requesting organisation
7. WHEN a module is disabled, THE Platform SHALL retain all existing data created by that module so it can be re-enabled later without data loss
8. THE Module_Registry SHALL support a "coming soon" state for modules that are planned but not yet available, displaying them in the module selection UI as non-selectable with an expected availability indicator

### Requirement 7: V1 Organisation Data Migration

**User Story:** As a Global_Admin, I want to migrate existing V1 workshop organisations to the universal platform schema, so that current customers experience a seamless transition without data loss.

#### Acceptance Criteria

1. THE Migration_Tool SHALL provide a migration path for existing V1 organisations that: assigns them the "Vehicle Workshop" trade category, enables their currently active modules, preserves all existing data (customers, vehicles, invoices, payments, quotes, job cards, bookings, catalogue items, notification templates), and applies the workshop terminology map
2. WHEN a V1 organisation is migrated, THE Migration_Tool SHALL generate a pre-migration report listing: record counts per table, storage usage, active integrations, subscription plan, and any data that requires manual review
3. THE Migration_Tool SHALL support two modes: "Full Migration" (maintenance window, all orgs at once) and "Live Migration" (rolling, one org at a time with zero downtime)
4. WHEN a Live Migration is performed, THE Migration_Tool SHALL use a dual-write strategy during the transition period where both old and new schema paths are active, with a cutover switch per organisation
5. THE Migration_Tool SHALL run an integrity check after migration comparing record counts, financial totals (invoice amounts, payment totals), and referential integrity between source and target
6. IF the integrity check fails, THEN THE Migration_Tool SHALL automatically roll back the migration for the affected organisation and generate a detailed error report
7. THE Migration_Tool SHALL generate a post-migration report per organisation confirming: records migrated, data integrity status, new trade category assignment, enabled modules, and any warnings
8. WHEN a V1 organisation is migrated, THE Migration_Tool SHALL preserve all existing invoice numbers, customer IDs, and external integration references (Stripe customer IDs, Xero contact IDs) without modification

### Requirement 8: Extended Role-Based Access Control

**User Story:** As a platform operator, I want the permission model extended with new roles for multi-location, franchise, and staff management, so that each user has precisely the access they need.

#### Acceptance Criteria

1. THE Auth_Module SHALL support the following roles: Global_Admin, Franchise_Admin, Org_Admin, Location_Manager, Salesperson, and Staff_Member
2. WHEN a user with the Location_Manager role accesses the platform, THE Auth_Module SHALL grant access to all Salesperson functions plus staff management, inventory management, and scheduling for their assigned location only
3. WHEN a user with the Franchise_Admin role accesses the platform, THE Auth_Module SHALL grant read-only access to aggregate reporting across all organisations in their assigned franchise group, without access to individual customer or invoice records
4. WHEN a user with the Staff_Member role accesses the platform, THE Auth_Module SHALL grant access only to: their assigned jobs, their time tracking entries, their schedule, and job-related photo/document uploads
5. THE Auth_Module SHALL support custom permission overrides per user that can grant or revoke specific capabilities within their base role (e.g. a Salesperson with "can manage inventory" override)
6. THE Auth_Module SHALL enforce that Location_Manager users can only view and manage data (staff, inventory, jobs, invoices) associated with their assigned location(s)
7. THE Auth_Module SHALL enforce that role changes and permission overrides are recorded in the audit log with the administrator who made the change
8. WHEN a new role or permission override is configured, THE Auth_Module SHALL immediately apply the change to all active sessions for the affected user without requiring re-login

### Requirement 9: Inventory and Product Catalogue

**User Story:** As an Org_Admin, I want a full product catalogue with stock tracking, so that I can manage inventory, track costs, and automatically adjust stock levels when items are sold.

#### Acceptance Criteria

1. THE Inventory_Module SHALL store product records with: name, SKU (auto-generated or manual), barcode (EAN-13, UPC-A, Code 128), category path, description, unit of measure (each, kg, litre, metre, hour, box, pack), sale price, cost price, current stock quantity, low stock threshold, reorder quantity, preferred supplier reference, and up to 5 product images
2. THE Inventory_Module SHALL support unlimited depth product categories with a tree structure, where each category has a name, parent category reference, and display order
3. WHEN an invoice containing product line items is issued, THE Inventory_Module SHALL automatically decrement stock quantities for each product by the invoiced quantity
4. WHEN a credit note is issued against an invoice with product line items, THE Inventory_Module SHALL automatically increment stock quantities for the credited products by the credited quantity
5. WHEN a product's stock quantity falls to or below its configured low stock threshold, THE Inventory_Module SHALL generate a low-stock alert visible on the dashboard and optionally send an email notification to the Org_Admin
6. WHEN a product's stock quantity reaches zero, THE Inventory_Module SHALL display a zero-stock warning on the product and allow the Org_Admin to configure whether zero-stock products can still be added to invoices (backorder mode) or are blocked
7. THE Inventory_Module SHALL record every stock quantity change as a Stock_Movement with: movement type (sale, credit, receive, adjustment, transfer, return, stocktake), quantity change, resulting quantity, reference document (invoice ID, PO ID, etc.), user who performed the action, and timestamp
8. THE Inventory_Module SHALL provide a stock take function that: allows entry of counted quantities per product, calculates variance against system quantities, generates a variance report, and applies adjustments upon confirmation with an audit trail
9. THE Inventory_Module SHALL support CSV bulk import of products with: a preview screen showing parsed data and validation errors before commit, field mapping for non-standard column names, and trade-specific sample CSV templates downloadable from the import screen
10. THE Inventory_Module SHALL support barcode scanning via device camera (using the Web Barcode Detection API or a JavaScript barcode library) to look up products by barcode in the catalogue, POS, and stock take screens

### Requirement 10: Pricing Rules and Tiered Pricing

**User Story:** As an Org_Admin, I want flexible pricing rules that automatically apply the correct price based on customer, volume, or date, so that I can manage complex pricing without manual overrides on every invoice.

#### Acceptance Criteria

1. THE Inventory_Module SHALL support pricing rules with the following types: customer-specific pricing (fixed price for a specific customer), volume/tiered pricing (price breaks at quantity thresholds), date-based pricing (promotional pricing with start and end dates), and trade category pricing (different base prices per trade category for multi-trade organisations)
2. THE Inventory_Module SHALL evaluate pricing rules in a configurable priority order and apply the first matching rule, falling back to the product's base sale price if no rules match
3. WHEN a pricing rule is applied to a line item, THE Invoice_Module SHALL display the applied rule name and the original base price for transparency
4. THE Inventory_Module SHALL allow Salesperson users with explicit permission to override an applied pricing rule on a line item, recording the override reason in the audit log
5. THE Inventory_Module SHALL validate that pricing rules do not create circular or conflicting conditions and warn the Org_Admin during rule creation if overlapping rules exist

### Requirement 11: Job and Work Order Management

**User Story:** As a Salesperson, I want to manage jobs through their full lifecycle from enquiry to invoicing, so that I can track work progress and convert completed jobs to invoices.

#### Acceptance Criteria

1. THE Job_Module SHALL store job records with: auto-generated job number (with configurable prefix), customer reference, location/site address, assigned staff members, scheduled start and end dates, actual start and end dates, description, checklist items (with completion tracking), internal notes, and linked quotes/invoices/time entries/expenses
2. THE Job_Module SHALL support the following status pipeline: Enquiry → Scheduled → In Progress → On Hold → Completed → Invoiced → Cancelled
3. THE Job_Module SHALL enforce valid status transitions (e.g. a job cannot move from Enquiry directly to Completed, a Cancelled job cannot be moved to Invoiced) and reject invalid transitions with a clear error message
4. THE Job_Module SHALL provide both a Kanban board view (columns per status, drag-and-drop to change status) and a filterable list view of all jobs
5. THE Job_Module SHALL support photo and document attachments on jobs, stored as binary data counting toward the organisation's storage quota, with optional inclusion in invoice emails
6. WHEN a user converts a job to an invoice, THE Job_Module SHALL create a new Draft invoice pre-populated with: the job's customer, location, all time entries as Labour line items (hours × rate), all expenses as line items, and all materials/products used as Part line items
7. THE Job_Module SHALL support job templates that pre-fill description, checklist items, and default line items for common job types within a trade category
8. WHEN a job's status changes, THE Job_Module SHALL record the status change in the job's activity log with timestamp, user, previous status, and new status
9. THE Job_Module SHALL allow assigning multiple staff members to a single job with individual role labels (e.g. "Lead", "Assistant") and track per-staff time entries separately

### Requirement 12: Quotes and Estimates Module

**User Story:** As a Salesperson, I want to create professional quotes with their own numbering and status tracking, so that I can manage the sales pipeline and convert accepted quotes to invoices.

#### Acceptance Criteria

1. THE Quote_Module SHALL store quotes with: auto-generated quote number (with configurable prefix separate from invoice numbering), customer reference, line items (same structure as invoice line items), validity period (expiry date), terms and conditions, internal notes, and status
2. THE Quote_Module SHALL support the following status flow: Draft → Sent → Accepted → Declined → Expired → Converted
3. WHEN a quote's expiry date passes without acceptance, THE Quote_Module SHALL automatically update the status to Expired
4. WHEN a customer accepts a quote (via email link or manual status change), THE Quote_Module SHALL update the status to Accepted and enable the "Convert to Invoice" action
5. WHEN a quote is converted to an invoice, THE Quote_Module SHALL create a new Draft invoice pre-populated with all quote line items, customer, and terms, update the quote status to Converted, and store a bidirectional reference between the quote and invoice
6. THE Quote_Module SHALL allow sending quotes to customers via email with a branded PDF attachment and an optional online acceptance link
7. THE Quote_Module SHALL support quote versioning so that revised quotes maintain a link to previous versions with a version number and change summary

### Requirement 13: Time Tracking Module

**User Story:** As a Salesperson or Staff_Member, I want to track time spent on jobs using manual entry or a running timer, so that labour can be accurately billed on invoices.

#### Acceptance Criteria

1. THE Time_Tracking_Module SHALL support two entry modes: manual entry (date, start time, end time or duration, description, job reference) and a running timer (start/stop with automatic duration calculation)
2. WHEN a running timer is active, THE Time_Tracking_Module SHALL display the elapsed time prominently in the application header and persist the timer state so it survives page refreshes and browser restarts
3. THE Time_Tracking_Module SHALL associate each time entry with: the user who logged it, an optional job reference, an optional project reference, a billable/non-billable flag, an hourly rate (defaulting to the user's configured rate), and a description
4. WHEN time entries are added to an invoice (manually or via job conversion), THE Time_Tracking_Module SHALL create Labour line items with the calculated amount (hours × rate) and mark the time entries as "invoiced" to prevent double-billing
5. THE Time_Tracking_Module SHALL provide a weekly timesheet view showing all time entries per user with daily totals and a weekly total
6. THE Time_Tracking_Module SHALL prevent overlapping time entries for the same user (two entries cannot cover the same time period) and display a validation error if overlap is detected

### Requirement 14: Project Management Module

**User Story:** As an Org_Admin, I want to group related jobs, invoices, quotes, time entries, and expenses into projects, so that I can track overall project profitability and progress.

#### Acceptance Criteria

1. THE Project_Module SHALL store projects with: project name, customer reference, description, budget amount, start date, target end date, status (Active, On Hold, Completed, Cancelled), and linked entities (jobs, invoices, quotes, time entries, expenses)
2. THE Project_Module SHALL calculate and display project profitability in real-time: total revenue (sum of linked paid invoices), total costs (sum of linked expenses + labour costs from time entries), and profit margin percentage
3. THE Project_Module SHALL display a project dashboard showing: progress percentage (based on completed vs total jobs), budget consumed vs remaining, timeline status (on track, at risk, overdue), and a list of all linked entities
4. WHEN an invoice, quote, job, time entry, or expense is created, THE Platform SHALL allow optional association with an existing project
5. THE Project_Module SHALL support project-level notes and document attachments with an activity feed showing all changes across linked entities in chronological order

### Requirement 15: Expense and Cost Tracking Module

**User Story:** As a Salesperson, I want to log expenses against jobs or projects and optionally pass them through to invoices, so that all costs are tracked and recoverable.

#### Acceptance Criteria

1. THE Expense_Module SHALL store expense records with: date, description, amount, tax amount, category (materials, travel, subcontractor, equipment, other), receipt attachment (photo or PDF), linked job or project reference, and a pass-through flag indicating whether the expense should appear on the customer invoice
2. WHEN an expense is marked as pass-through and linked to a job, THE Expense_Module SHALL include the expense as a line item when the job is converted to an invoice
3. THE Expense_Module SHALL support expense categories configurable by the Org_Admin with default categories provided per trade category
4. THE Expense_Module SHALL provide an expense summary report filterable by date range, category, job, project, and user

### Requirement 16: Purchase Order Module

**User Story:** As an Org_Admin, I want to raise purchase orders for suppliers, receive goods against them, and link them to jobs or projects, so that procurement is tracked and integrated with inventory.

#### Acceptance Criteria

1. THE PurchaseOrder_Module SHALL store purchase orders with: auto-generated PO number (with configurable prefix), supplier reference, line items (product, quantity, unit cost), expected delivery date, status (Draft, Sent, Partially Received, Received, Cancelled), linked job or project reference, and internal notes
2. WHEN goods are received against a purchase order, THE PurchaseOrder_Module SHALL update the PO status, create Stock_Movement records in the Inventory_Module for each received product, and increment stock quantities
3. THE PurchaseOrder_Module SHALL support partial receiving (receiving fewer items than ordered) with tracking of outstanding quantities
4. THE PurchaseOrder_Module SHALL generate a printable/emailable PO PDF with the organisation's branding
5. WHEN a purchase order is linked to a job, THE PurchaseOrder_Module SHALL make the PO costs visible in the job's cost summary and the project's profitability calculation

### Requirement 17: Staff and Contractor Management Module

**User Story:** As an Org_Admin, I want to manage staff members and contractors with their rates, schedules, and job assignments, so that I can track labour costs and manage workforce allocation.

#### Acceptance Criteria

1. THE Staff_Module SHALL store staff/contractor profiles with: name, contact details, role (employee or contractor), hourly rate, overtime rate, availability schedule (working days and hours), assigned location(s), skills/certifications, and active/inactive status
2. THE Staff_Module SHALL allow assigning staff to jobs with a visual drag-and-drop interface on the scheduling calendar
3. THE Staff_Module SHALL calculate labour costs per job based on time entries and the staff member's configured hourly rate, distinguishing between regular and overtime hours
4. THE Staff_Module SHALL provide a staff utilisation report showing: hours worked vs available hours, job count, and revenue generated per staff member over a configurable date range
5. WHEN a staff member is deactivated, THE Staff_Module SHALL prevent new job assignments while preserving all historical time entries and job associations

### Requirement 18: Scheduling and Calendar Module

**User Story:** As an Org_Admin or Location_Manager, I want a visual calendar showing all scheduled jobs, bookings, and staff availability, so that I can manage daily operations and avoid scheduling conflicts.

#### Acceptance Criteria

1. THE Scheduling_Module SHALL display a calendar view with day, week, and month perspectives showing jobs, bookings, and staff availability as colour-coded blocks
2. THE Scheduling_Module SHALL support drag-and-drop rescheduling of jobs and bookings on the calendar with automatic date/time updates on the underlying records
3. WHEN a scheduling conflict is detected (overlapping jobs for the same staff member or resource), THE Scheduling_Module SHALL display a visual warning on the conflicting entries and allow the user to proceed or resolve the conflict
4. THE Scheduling_Module SHALL support filtering the calendar by: staff member, location, job status, and trade-specific resource types (e.g. bay number for workshops, treatment room for health)
5. THE Scheduling_Module SHALL send automated reminder notifications to assigned staff members a configurable time before their scheduled jobs (default 1 hour)

### Requirement 19: Customer-Facing Booking and Appointments Module

**User Story:** As an Org_Admin, I want to offer a customer-facing booking page where customers can self-schedule appointments, so that bookings are captured without manual phone/email coordination.

#### Acceptance Criteria

1. THE Booking_Module SHALL provide a public booking page (accessible via a unique URL per organisation) that displays available time slots based on the organisation's configured availability, existing bookings, and staff schedules
2. THE Booking_Module SHALL collect from the customer during booking: name, email, phone, preferred date/time, service type (from the organisation's catalogue), and optional notes
3. WHEN a booking is submitted, THE Booking_Module SHALL send an automatic confirmation email to the customer and a notification to the assigned staff member or Org_Admin
4. THE Booking_Module SHALL support configurable booking rules: minimum advance booking time, maximum advance booking window, booking slot duration per service type, and buffer time between appointments
5. WHEN a booking is cancelled by the customer or organisation, THE Booking_Module SHALL send a cancellation notification to both parties and free the time slot
6. THE Booking_Module SHALL allow converting a confirmed booking to a job card or directly to a draft invoice with the booking details pre-populated
7. THE Booking_Module SHALL apply the organisation's branding (logo, colours) to the public booking page

### Requirement 20: Recurring Invoices Module

**User Story:** As an Org_Admin, I want to set up recurring invoice schedules, so that repeat billing is automated without manual invoice creation each period.

#### Acceptance Criteria

1. THE Recurring_Module SHALL support recurring schedules with frequencies: weekly, fortnightly, monthly, quarterly, and annually
2. THE Recurring_Module SHALL store recurring schedules with: customer reference, line items template, frequency, start date, optional end date, next generation date, and active/paused status
3. WHEN the next generation date is reached, THE Recurring_Module SHALL automatically create a new invoice (as Draft or Issued based on configuration) with the template line items and advance the next generation date
4. THE Recurring_Module SHALL send a notification to the Org_Admin when a recurring invoice is generated, and optionally auto-email the invoice to the customer
5. WHEN a recurring schedule's customer or line items need updating, THE Recurring_Module SHALL allow editing the template without affecting previously generated invoices
6. THE Recurring_Module SHALL provide a dashboard showing all active recurring schedules with their next generation dates and total recurring revenue

### Requirement 21: Ecommerce and WooCommerce Integration Module

**User Story:** As an Org_Admin, I want to sync orders and products with my WooCommerce store and receive orders from other ecommerce platforms, so that online sales are automatically captured as invoices.

#### Acceptance Criteria

1. THE Ecommerce_Module SHALL support bidirectional WooCommerce synchronisation: orders from WooCommerce create invoices in OraInvoice, and products in OraInvoice can be pushed to WooCommerce
2. WHEN a WooCommerce order is received, THE Ecommerce_Module SHALL match the customer by email address (creating a new customer if no match exists), map products by SKU to the OraInvoice catalogue, create a Draft or Issued invoice (configurable), and decrement inventory if the Inventory_Module is enabled
3. THE Ecommerce_Module SHALL maintain a sync log per organisation showing: sync timestamp, direction (inbound/outbound), entity type, entity ID, status (success/failed/skipped), and error details for failed syncs
4. THE Ecommerce_Module SHALL provide a SKU mapping interface for cases where WooCommerce product SKUs do not match OraInvoice SKUs, allowing manual mapping with persistence
5. THE Ecommerce_Module SHALL provide a general webhook receiver endpoint (`/api/v2/ecommerce/webhook/{org_id}`) that accepts order payloads from any platform (Shopify, Squarespace, BigCommerce) in a documented JSON schema
6. WHEN a webhook is received, THE Ecommerce_Module SHALL validate the webhook signature (HMAC-SHA256 using the organisation's configured webhook secret), reject unsigned or invalid requests with HTTP 401, and log all received webhooks regardless of validation outcome
7. THE Ecommerce_Module SHALL provide API credentials (API key + secret) per organisation for REST API access, with rate limiting of 100 requests per minute per organisation
8. THE Ecommerce_Module SHALL support a Zapier-compatible REST API with standard CRUD endpoints for invoices, customers, and products to enable integration with any platform via Zapier
9. IF a WooCommerce sync fails for a specific order, THEN THE Ecommerce_Module SHALL retry the sync up to 3 times with exponential backoff (1 min, 5 min, 15 min) and flag the order as "sync failed" in the sync log after all retries are exhausted

### Requirement 22: Point of Sale Mode

**User Story:** As a Salesperson, I want a full-screen touch-optimised POS interface for walk-in sales, so that I can process transactions quickly at the counter with support for multiple payment methods.

#### Acceptance Criteria

1. THE POS_Module SHALL provide a full-screen POS interface with: a product grid panel (searchable, filterable by category, with product images and prices), a current order panel (line items, quantities, discounts, running total), and a payment panel
2. THE POS_Module SHALL support quantity adjustment on line items via +/- buttons and direct numeric input, with support for decimal quantities for weight-based products
3. THE POS_Module SHALL support per-item and order-level discounts (percentage or fixed amount) with optional discount reason entry
4. THE POS_Module SHALL support the following payment methods: cash (with change calculation), card (via connected payment terminal or Stripe), and split payment (combining cash and card for a single transaction)
5. WHEN a POS transaction is completed, THE POS_Module SHALL create an Issued invoice, record the payment, decrement inventory quantities, and trigger receipt printing if a printer is configured
6. THE POS_Module SHALL support an offline mode that queues transactions locally in IndexedDB when internet connectivity is lost, displaying a clear "Offline" indicator in the UI
7. WHEN connectivity is restored after offline operation, THE POS_Module SHALL automatically sync queued transactions to the server in chronological order, creating invoices and updating inventory for each transaction
8. IF an offline-queued transaction conflicts with server state (e.g. a product price changed, a product was deleted, or stock is insufficient), THEN THE POS_Module SHALL flag the transaction as "sync conflict", create the invoice with the original offline values, and generate a conflict report for the Org_Admin to review and resolve
9. THE POS_Module SHALL support barcode scanning via device camera or connected USB/Bluetooth barcode scanner to add products to the current order
10. THE POS_Module SHALL enforce that all POS transactions are associated with the current user for audit trail purposes and optionally with a customer record

### Requirement 23: Receipt Printer Integration

**User Story:** As an Org_Admin, I want to print receipts on thermal printers connected via USB, network, or Bluetooth, so that customers receive physical receipts at the point of sale.

#### Acceptance Criteria

1. THE POS_Module SHALL support receipt printing via ESC_POS protocol to printers connected via USB (WebUSB API), Ethernet (network print), Bluetooth (Web Bluetooth API), and WiFi (network print)
2. THE POS_Module SHALL support 58mm and 80mm paper widths with automatic layout adjustment based on the configured paper width
3. THE POS_Module SHALL include on printed receipts: organisation name and logo (if printer supports graphics), address, phone, tax identifier, receipt/invoice number, date and time, line items with quantities and prices, subtotal, tax amount, total, payment method, change given (for cash), and a configurable footer message
4. THE POS_Module SHALL provide a printer configuration screen where the Org_Admin can: add printers (specifying connection type and address), send a test print, set a default printer, and configure paper width
5. THE POS_Module SHALL manage a Print_Queue that handles print job failures gracefully: if a print fails, the job is retried up to 3 times with a 2-second delay, and if all retries fail, the job is marked as failed with an error notification to the user
6. WHERE multi-location organisations require cloud printing, THE POS_Module SHALL support a Cloud_Print_Agent (a lightweight installable agent) that receives print jobs from the cloud and dispatches them to locally connected printers
7. THE POS_Module SHALL queue print jobs locally during offline POS operation and dispatch them when connectivity is restored or when a local printer is directly connected

### Requirement 24: Tipping Module

**User Story:** As an Org_Admin in a hospitality or service business, I want to accept tips on POS transactions and invoices with optional staff allocation, so that tips are tracked and distributed fairly.

#### Acceptance Criteria

1. WHERE the Tipping_Module is enabled, THE POS_Module SHALL display a tipping prompt after payment amount entry with configurable preset percentages (e.g. 10%, 15%, 20%) and a custom amount option
2. WHERE the Tipping_Module is enabled, THE Invoice_Module SHALL include an optional tip field on invoices that customers can fill in when paying online
3. THE Tipping_Module SHALL record each tip with: amount, associated invoice/transaction, payment method, and timestamp
4. THE Tipping_Module SHALL support tip allocation to individual staff members or even split across multiple staff members assigned to the transaction
5. THE Tipping_Module SHALL provide a tip summary report filterable by date range and staff member showing: total tips collected, tips per staff member, and average tip percentage

### Requirement 25: Table and Seat Management Module (Hospitality)

**User Story:** As an Org_Admin running a restaurant or café, I want a visual floor plan showing table status and seat assignments, so that front-of-house staff can manage seating efficiently.

#### Acceptance Criteria

1. THE Table_Module SHALL provide a visual floor plan editor where the Org_Admin can place, resize, and label tables with seat counts on a drag-and-drop canvas
2. THE Table_Module SHALL display real-time table status with colour coding: Available (green), Occupied (amber), Reserved (blue), and Needs Cleaning (red)
3. WHEN a table is selected in the floor plan, THE Table_Module SHALL open the associated POS order for that table, or create a new order if none exists
4. THE Table_Module SHALL support table merging (combining two adjacent tables for a larger party) and splitting (separating a merged table back to individual tables)
5. THE Table_Module SHALL support reservations with: customer name, party size, date, time, duration, and optional notes, displayed on the floor plan at the reserved time
6. WHEN an order is completed and paid for a table, THE Table_Module SHALL update the table status to "Needs Cleaning" until a staff member marks it as "Available"

### Requirement 26: Kitchen Display Module (Hospitality)

**User Story:** As a kitchen staff member, I want to see incoming orders on a display screen with the ability to mark items as prepared, so that food preparation is coordinated with front-of-house.

#### Acceptance Criteria

1. THE Kitchen_Display_Module SHALL display incoming order items in real-time as they are added to POS orders, grouped by table number and order time
2. THE Kitchen_Display_Module SHALL show each order item with: item name, quantity, any modifications or special instructions, table number, and elapsed time since the order was placed
3. WHEN a kitchen staff member marks an item as prepared, THE Kitchen_Display_Module SHALL update the item status to "Ready" and send a notification to the front-of-house POS screen for that table
4. THE Kitchen_Display_Module SHALL visually highlight orders that have exceeded a configurable preparation time threshold (default 15 minutes) with a colour change from white to amber to red
5. THE Kitchen_Display_Module SHALL support a full-screen display mode optimised for wall-mounted screens with large text and high contrast
6. THE Kitchen_Display_Module SHALL support item categorisation so that different display stations can show only relevant items (e.g. "Hot Food" station vs "Drinks" station vs "Desserts" station)

### Requirement 27: Construction Retentions Module

**User Story:** As a builder or contractor, I want to track retention amounts withheld from progress claims, so that I know exactly how much is held and when it becomes due for release.

#### Acceptance Criteria

1. THE Retention_Module SHALL allow configuring a retention percentage per project (default 5%, configurable from 0% to 20%)
2. WHEN a progress claim is created for a project with retention configured, THE Retention_Module SHALL automatically calculate and withhold the retention amount from the claim total
3. THE Retention_Module SHALL maintain a running total of retained amounts per project showing: total retained, retention released, and retention outstanding
4. THE Retention_Module SHALL support partial and full retention release with a release date, amount, and linked payment record
5. THE Retention_Module SHALL display retention status on the project dashboard and include retention details on progress claim PDFs

### Requirement 28: Progress Claims Module (Construction)

**User Story:** As a builder or contractor, I want to submit progress claims against a contract value showing work completed to date, so that I can bill clients progressively as construction milestones are reached.

#### Acceptance Criteria

1. THE ProgressClaim_Module SHALL store progress claims with: claim number (sequential per project), project reference, contract value, variations to date, revised contract value, work completed this period, work completed to date (cumulative), retention withheld, previous claims total, amount due this claim, and status (Draft, Submitted, Approved, Paid, Disputed)
2. THE ProgressClaim_Module SHALL auto-calculate: revised contract value (original + approved variations), amount due this claim (work completed to date - retention - previous claims), and cumulative completion percentage
3. WHEN a progress claim is approved, THE ProgressClaim_Module SHALL generate an invoice for the approved amount linked to the project
4. THE ProgressClaim_Module SHALL generate a formatted progress claim PDF following standard construction industry layout with all calculated fields
5. THE ProgressClaim_Module SHALL prevent the cumulative claimed amount from exceeding the revised contract value and display a validation error if this is attempted

### Requirement 29: Variations and Change Orders Module (Construction)

**User Story:** As a builder or contractor, I want to formally track scope changes with approval workflows, so that contract value adjustments are documented and reflected in progress claims.

#### Acceptance Criteria

1. THE Variation_Module SHALL store variation orders with: variation number (sequential per project), project reference, description of scope change, cost impact (positive for additions, negative for deductions), status (Draft, Submitted, Approved, Rejected), submitted date, and approval date
2. WHEN a variation order is approved, THE Variation_Module SHALL automatically update the project's revised contract value by adding the variation's cost impact
3. THE Variation_Module SHALL display a variation register per project showing all variations with their status and cumulative impact on contract value
4. THE Variation_Module SHALL generate a printable variation order PDF with the organisation's branding and space for client signature
5. THE Variation_Module SHALL prevent deletion of approved variations and require a new offsetting variation to reverse an approved change

### Requirement 30: Compliance and Certifications Module

**User Story:** As a tradesperson, I want to attach compliance certificates and documents to invoices, so that customers receive proof of compliance with their invoice.

#### Acceptance Criteria

1. THE Compliance_Module SHALL allow uploading compliance documents (PDF, JPG, PNG) with: document type (certificate, inspection report, warranty, licence, permit), description, expiry date, and linked invoice or job reference
2. WHEN a compliance document is linked to an invoice, THE Compliance_Module SHALL include the document as an attachment in the invoice email and display a "Compliance Documents" section on the invoice PDF listing attached document names
3. THE Compliance_Module SHALL track document expiry dates and send reminder notifications to the Org_Admin 30 days and 7 days before a compliance document expires
4. THE Compliance_Module SHALL provide a compliance dashboard showing: all documents grouped by type, upcoming expiries, and expired documents requiring renewal
5. THE Compliance_Module SHALL support document templates that pre-fill common compliance document types per trade category (e.g. "Electrical Certificate of Compliance" for electricians, "Gas Safety Certificate" for gasfitters)

### Requirement 31: Multi-Currency Module

**User Story:** As an Org_Admin operating internationally, I want to issue invoices in multiple currencies and consolidate reporting to my base currency, so that I can serve international clients while maintaining accurate financial records.

#### Acceptance Criteria

1. THE MultiCurrency_Module SHALL allow the Org_Admin to configure a base currency (set during onboarding from country selection) and enable additional currencies from a list of ISO 4217 currency codes
2. WHEN creating an invoice, THE Invoice_Module SHALL allow selecting the invoice currency from the organisation's enabled currencies, defaulting to the base currency
3. THE MultiCurrency_Module SHALL maintain exchange rates per currency pair with: rate value, effective date, and source (manual entry or automatic feed)
4. THE MultiCurrency_Module SHALL support automatic exchange rate updates from a configurable external rate provider (e.g. Open Exchange Rates API) with a configurable update frequency (daily default)
5. WHEN an invoice is issued in a non-base currency, THE MultiCurrency_Module SHALL record the exchange rate at the time of issue and use that locked rate for all subsequent calculations on that invoice
6. THE MultiCurrency_Module SHALL consolidate all reporting (revenue, outstanding, profitability) to the base currency using the exchange rate recorded at the time of each transaction
7. IF an exchange rate is not available for a currency pair at the time of invoice creation, THEN THE MultiCurrency_Module SHALL display a warning and require manual exchange rate entry before the invoice can be issued
8. THE MultiCurrency_Module SHALL format currency amounts according to the currency's standard format (decimal places, thousands separator, currency symbol position) on all UI displays and PDF outputs
9. THE MultiCurrency_Module SHALL support recording payments in a different currency than the invoice currency, calculating the exchange difference and recording it as a gain or loss

### Requirement 32: Internationalisation and Localisation

**User Story:** As a platform user in any supported country, I want the platform to display in my language with my local date, number, and tax formats, so that the platform feels native to my region.

#### Acceptance Criteria

1. THE Platform SHALL support a minimum of 10 languages at launch: English (default), Spanish, French, German, Portuguese, Japanese, Chinese (Simplified), Korean, Arabic, and Hindi
2. THE Platform SHALL store all translatable strings in externally managed translation files (JSON format per language) that can be updated without code deployment
3. WHEN a user selects a language preference, THE Platform SHALL render all UI labels, messages, tooltips, and system-generated content in the selected language
4. THE Platform SHALL format dates according to the organisation's configured locale (e.g. dd/MM/yyyy for NZ/AU/UK, MM/dd/yyyy for US, yyyy-MM-dd for ISO)
5. THE Platform SHALL format numbers according to the organisation's configured locale (e.g. 1,234.56 for English locales, 1.234,56 for European locales)
6. THE Platform SHALL configure tax settings based on the Compliance_Profile: tax label (GST, VAT, Sales Tax, etc.), default tax rate, tax-inclusive or tax-exclusive default, and whether multiple tax rates are supported
7. WHEN an organisation's country is set to a country with multiple tax rates (e.g. UK VAT with standard, reduced, and zero rates), THE Platform SHALL allow configuring multiple tax rates and assigning them to individual line items
8. THE Platform SHALL support right-to-left (RTL) text rendering for Arabic and other RTL languages with appropriate layout mirroring

### Requirement 33: Global Compliance Profiles

**User Story:** As a Global_Admin, I want to manage country-specific compliance profiles that auto-configure tax and regulatory settings, so that organisations in each country get correct defaults without manual configuration.

#### Acceptance Criteria

1. THE Platform SHALL provide pre-configured Compliance Profiles for: New Zealand (GST 15%, IRD GST number format), Australia (GST 10%, ABN format, BAS reporting), United Kingdom (VAT standard 20%, reduced 5%, zero 0%, VAT number format), and a Generic profile (configurable tax label and rate, no format validation)
2. WHEN an organisation selects a country during onboarding, THE Platform SHALL automatically apply the matching Compliance_Profile, setting: tax label, default tax rate(s), tax number format validation, tax-inclusive/exclusive default, and any country-specific reporting templates
3. THE Platform SHALL allow Global_Admin to create new Compliance Profiles and edit existing ones without code deployment
4. THE Platform SHALL allow Org_Admin to override specific compliance settings (e.g. change tax rate) while displaying a warning that the override deviates from the country standard
5. WHEN a Compliance_Profile includes a tax return report template (e.g. NZ GST Return, AU BAS, UK VAT Return), THE Reporting_Module SHALL generate the report in the format required by the relevant tax authority

### Requirement 34: Data Residency and Privacy

**User Story:** As an Org_Admin, I want to choose where my organisation's data is stored, so that I comply with local data protection regulations.

#### Acceptance Criteria

1. THE Platform SHALL support data residency regions: NZ/AU (New Zealand and Australia), UK/EU (United Kingdom and European Union), and North America (United States and Canada)
2. WHEN an organisation selects a data residency region during onboarding, THE Platform SHALL ensure all organisation data (database records, file storage, backups) is stored within the selected region
3. THE Platform SHALL enforce that organisation data does not leave the selected residency region during processing, caching, or backup operations
4. THE Platform SHALL support GDPR compliance features for UK/EU organisations: configurable data retention policies (auto-delete customer data after a configurable period of inactivity), Data Processing Agreement (DPA) acceptance during onboarding, cookie consent management on customer-facing pages (booking page, customer portal), and Data Subject Access Request (DSAR) processing workflow
5. WHEN a DSAR is received, THE Platform SHALL provide a workflow for the Org_Admin to: acknowledge the request, generate a complete data export for the subject, and process deletion/anonymisation if requested, all within the GDPR-mandated 30-day response window
6. THE Platform SHALL log all data residency configuration changes and cross-region data access attempts in the audit log

### Requirement 35: Enterprise Multi-Location Support

**User Story:** As an Org_Admin with multiple business locations, I want each location to have its own address, staff, and optionally its own inventory, while sharing customers and reporting at the head-office level.

#### Acceptance Criteria

1. THE Franchise_Module SHALL support multi-location organisations where each location has: its own name, address, phone, email, assigned users, invoice number prefix (optional, can share with head office), and optionally its own inventory pool
2. THE Franchise_Module SHALL provide a head-office aggregate view showing: combined revenue, combined outstanding invoices, per-location performance comparison, and combined inventory levels
3. THE Franchise_Module SHALL support shared customers across locations within the same organisation, with customer records accessible from any location
4. WHERE locations have separate inventory pools, THE Franchise_Module SHALL support stock transfers between locations with: transfer request, approval workflow, and automatic stock movement records at both source and destination
5. THE Franchise_Module SHALL enforce that Location_Manager users can only access data (invoices, jobs, staff, inventory) for their assigned location(s) while Org_Admin users can access all locations
6. THE Franchise_Module SHALL support per-location reporting and combined organisation-level reporting with the ability to filter any report by location
7. WHEN a new location is added, THE Franchise_Module SHALL allow cloning settings (catalogue, pricing rules, notification templates) from an existing location or starting with trade category defaults

### Requirement 36: Franchise Support

**User Story:** As a franchise operator, I want read-only aggregate reporting across all franchisee organisations, so that I can monitor franchise performance without accessing individual business data.

#### Acceptance Criteria

1. THE Franchise_Module SHALL support a Franchise Group concept where multiple independent organisations are linked under a franchise umbrella, configured by Global_Admin
2. THE Franchise_Module SHALL provide the Franchise_Admin role with a dedicated dashboard showing: aggregate revenue across all franchisees, per-franchisee revenue comparison, growth trends, and module adoption
3. THE Franchise_Module SHALL enforce that Franchise_Admin users have read-only access to aggregate metrics only and cannot view individual customer records, invoice details, or staff information
4. THE Franchise_Module SHALL maintain independent billing per franchisee organisation (each franchisee has its own subscription and payment method)
5. THE Franchise_Module SHALL allow Global_Admin to add or remove organisations from a franchise group without affecting the organisations' data or operations

### Requirement 37: Global Branding and "Powered By" System

**User Story:** As a Global_Admin, I want to configure platform branding and ensure a "Powered By OraInvoice" footer appears on all outgoing documents, so that the platform brand is consistently promoted.

#### Acceptance Criteria

1. THE Branding_Module SHALL allow Global_Admin to configure: platform name, platform logo, primary and secondary brand colours, marketing website URL, support email, and terms of service URL
2. THE Platform SHALL display a "Powered by OraInvoice" footer on all outgoing documents (invoice PDFs, quote PDFs, credit note PDFs, progress claim PDFs, purchase order PDFs, receipts) below the organisation's own branding
3. THE Platform SHALL include the platform logo and a signup link with UTM tracking parameters (utm_source=invoice, utm_medium=email, utm_campaign=powered_by) in all outgoing email templates (invoice emails, quote emails, reminder emails, booking confirmations)
4. THE Platform SHALL support auto-detection of the serving domain to apply the correct branding configuration (for white-label deployments)
5. WHERE an organisation is on an Enterprise white-label plan, THE Platform SHALL allow removal of the "Powered By" footer and replacement with the organisation's own branding on all documents and emails
6. THE Branding_Module SHALL prevent non-Enterprise organisations from removing or modifying the "Powered By" footer

### Requirement 38: Loyalty and Memberships Module

**User Story:** As an Org_Admin, I want to offer a loyalty program with points and membership tiers, so that I can reward repeat customers and encourage retention.

#### Acceptance Criteria

1. THE Loyalty_Module SHALL support a points-based loyalty system where customers earn points per dollar spent (configurable rate, e.g. 1 point per $1)
2. THE Loyalty_Module SHALL support membership tiers (e.g. Bronze, Silver, Gold) with configurable thresholds (points or spend amount) and per-tier benefits (discount percentage, priority booking, free services)
3. WHEN an invoice is paid, THE Loyalty_Module SHALL automatically award loyalty points to the customer based on the invoice total and the configured earn rate
4. THE Loyalty_Module SHALL support point redemption as a discount on invoices, with a configurable redemption rate (e.g. 100 points = $1 discount)
5. THE Loyalty_Module SHALL auto-apply tier-based discounts to invoices for eligible customers, displaying the discount as a separate line item with the tier name
6. THE Loyalty_Module SHALL provide a customer-facing loyalty balance view on the Customer Portal showing: current points, current tier, points to next tier, and transaction history

### Requirement 39: Global Admin Analytics Dashboard (Enhanced)

**User Story:** As a Global_Admin, I want a comprehensive analytics dashboard showing platform-wide metrics segmented by trade, country, and module adoption, so that I can make informed decisions about platform growth.

#### Acceptance Criteria

1. THE Admin_Console SHALL display a multi-trade analytics dashboard with: total organisations by trade family, growth rate per trade category (month-over-month), revenue per trade family, and a geographic distribution map
2. THE Admin_Console SHALL display a module adoption heatmap showing: percentage of organisations using each module, segmented by trade family, with trend indicators
3. THE Admin_Console SHALL display conversion metrics: signup-to-trial conversion rate, trial-to-paid conversion rate, and churn rate, all segmentable by trade category and country
4. THE Admin_Console SHALL display platform health metrics: API response time (p50, p95, p99), error rate, active users (DAU/MAU), and infrastructure utilisation
5. THE Admin_Console SHALL support date range filtering and comparison periods (e.g. this month vs last month) on all dashboard metrics
6. THE Admin_Console SHALL allow exporting dashboard data as CSV for further analysis

### Requirement 40: Organisation Alerts and Maintenance Notifications

**User Story:** As a Global_Admin, I want to send targeted notifications to organisations about maintenance windows, platform updates, and urgent alerts, so that users are informed of platform changes.

#### Acceptance Criteria

1. THE Admin_Console SHALL support creating notifications of types: maintenance window (with start/end time), platform update (with version and changelog), urgent alert (with severity level), and general announcement
2. THE Admin_Console SHALL support targeting notifications to: all organisations, specific trade families, specific countries, specific subscription plans, or individual organisations
3. WHEN a maintenance notification is created, THE Platform SHALL display a banner in the application UI for targeted organisations showing the maintenance window timing and expected impact
4. THE Admin_Console SHALL log all sent notifications with: type, target audience, send timestamp, and delivery count
5. WHEN an urgent alert is created, THE Platform SHALL send an email notification in addition to the in-app banner to all Org_Admin users in the targeted organisations

### Requirement 41: Database Migration Tool

**User Story:** As a Global_Admin, I want a database migration tool for moving data between environments with integrity checking and automatic rollback, so that environment promotions and disaster recovery are safe and reliable.

#### Acceptance Criteria

1. THE Migration_Tool SHALL support two modes: Full Migration (maintenance window, complete database copy between environments) and Live Migration (rolling migration with dual-write and per-organisation cutover)
2. THE Migration_Tool SHALL provide a pre-migration checklist that validates: source and target environment connectivity, schema compatibility, available disk space, and active user sessions that need to be drained
3. THE Migration_Tool SHALL display real-time progress during migration showing: percentage complete, records processed, estimated time remaining, and current operation
4. THE Migration_Tool SHALL run an automatic integrity check after migration comparing: record counts per table, financial totals (invoice amounts, payment totals, subscription charges), referential integrity (no orphaned foreign keys), and file storage checksums
5. IF the integrity check fails, THEN THE Migration_Tool SHALL automatically roll back the migration, restore the previous state, and generate a detailed error report listing every discrepancy found
6. THE Migration_Tool SHALL generate a post-migration report showing: total records migrated, migration duration, integrity check results, and any warnings or anomalies detected

### Requirement 42: Security Enhancements for Multi-Trade Platform

**User Story:** As a Global_Admin, I want enhanced security controls for the expanded platform, so that the multi-trade, multi-country platform meets enterprise security standards.

#### Acceptance Criteria

1. THE Platform SHALL support SOC 2 readiness by maintaining a compliance evidence pack that includes: access control policies, encryption standards, audit log retention, incident response procedures, and change management records
2. THE Platform SHALL provide a Penetration Testing Mode that creates an isolated sandbox environment with synthetic data for security testing, preventing any impact on production data
3. THE Platform SHALL enforce webhook security by: signing all outbound webhooks with HMAC-SHA256 using a per-organisation secret, validating all inbound webhooks (Stripe, WooCommerce, ecommerce) against their respective signing secrets, and rejecting webhooks with invalid or missing signatures
4. THE Platform SHALL enforce API rate limiting per organisation: 1000 requests per minute for standard plans, 5000 for professional plans, and 10000 for enterprise plans, returning HTTP 429 with a Retry-After header when limits are exceeded
5. THE Platform SHALL encrypt all sensitive data at rest using AES-256 encryption: API keys, webhook secrets, integration credentials, and tax identifiers
6. THE Platform SHALL enforce Content Security Policy (CSP) headers that restrict script sources, prevent inline script execution (except for trusted hashes), and block mixed content
7. THE Platform SHALL log all cross-module data access (e.g. Inventory_Module accessing Invoice_Module data) in the audit log for security monitoring

### Requirement 43: Storage and Performance Management

**User Story:** As a Global_Admin, I want storage quotas and performance safeguards that scale with the expanded platform, so that no single organisation can degrade the platform for others.

#### Acceptance Criteria

1. THE Platform SHALL enforce per-organisation storage quotas that include: document attachments (job photos, compliance documents, receipts), product images, and floor plan assets, with the quota determined by the subscription plan
2. WHEN an organisation reaches 80% of its storage quota, THE Platform SHALL display a warning banner and send an email notification to the Org_Admin
3. WHEN an organisation reaches 100% of its storage quota, THE Platform SHALL prevent new file uploads while allowing all other operations to continue, and display a message directing the Org_Admin to purchase additional storage or delete unused files
4. THE Platform SHALL enforce per-organisation database row limits for high-volume tables (products, stock movements, time entries) based on subscription plan tier, with warnings at 80% and blocking at 100%
5. THE Platform SHALL implement query timeout limits (30 seconds for standard queries, 120 seconds for report generation) to prevent long-running queries from affecting other tenants
6. THE Platform SHALL use database connection pooling with per-organisation connection limits to prevent any single tenant from exhausting the connection pool
7. THE Platform SHALL implement background job priority queuing so that time-sensitive tasks (POS transactions, payment processing) are processed before lower-priority tasks (report generation, sync operations)

### Requirement 44: Offline and Sync Conflict Resolution

**User Story:** As a Salesperson using POS in an area with unreliable internet, I want clear conflict resolution when offline transactions sync, so that no data is lost and discrepancies are visible.

#### Acceptance Criteria

1. THE POS_Module SHALL store offline transactions in IndexedDB with: full transaction data, timestamp, user ID, and a unique offline transaction ID
2. WHEN connectivity is restored, THE POS_Module SHALL sync offline transactions in strict chronological order, processing each transaction sequentially to maintain data consistency
3. IF a product referenced in an offline transaction has been deleted or deactivated on the server, THEN THE POS_Module SHALL create the invoice with the product details as captured offline (name, price, SKU) and flag the line item as "product no longer active" in the sync report
4. IF a product's price has changed between the offline transaction time and sync time, THEN THE POS_Module SHALL use the price from the offline transaction (honouring the price at time of sale) and record the price discrepancy in the sync report
5. IF inventory stock is insufficient to fulfil an offline transaction at sync time, THEN THE POS_Module SHALL complete the transaction (allowing negative stock), flag the stock discrepancy, and notify the Org_Admin
6. THE POS_Module SHALL provide a sync status dashboard showing: pending offline transactions count, last successful sync timestamp, failed syncs with error details, and a manual "force sync" button
7. THE POS_Module SHALL retain offline transaction data in IndexedDB for 30 days after successful sync as a local backup, then automatically purge

### Requirement 45: Cross-Module Error Handling and Data Integrity

**User Story:** As a platform operator, I want robust error handling when operations span multiple modules, so that partial failures do not leave data in an inconsistent state.

#### Acceptance Criteria

1. WHEN an operation spans multiple modules (e.g. issuing an invoice that triggers inventory decrement, payment recording, and notification sending), THE Platform SHALL use database transactions to ensure atomicity of the core data changes (invoice + inventory + payment) and treat notification sending as a separate async operation that does not block or roll back the core transaction
2. IF a cross-module operation partially fails (e.g. invoice created but inventory update fails), THEN THE Platform SHALL roll back all database changes in the transaction, return a clear error message identifying which step failed, and log the full error context in the error log
3. THE Platform SHALL implement idempotency keys on all state-changing API endpoints to prevent duplicate operations from webhook retries, network timeouts, or user double-clicks
4. THE Platform SHALL implement a dead letter queue for failed background tasks (notifications, sync operations, report generation) that: stores the failed task with full context, retries up to 3 times with exponential backoff, and alerts the Global_Admin if a task remains in the dead letter queue for more than 1 hour
5. THE Platform SHALL validate all cross-module references (e.g. a job referencing a customer, an invoice referencing a product) at the API layer before initiating database operations, returning HTTP 422 with specific error details if a referenced entity does not exist or belongs to a different organisation

### Requirement 46: Seed Data and Trade Category Bootstrapping

**User Story:** As a Global_Admin, I want trade categories to come with pre-configured seed data, so that new organisations get useful defaults and can start working immediately.

#### Acceptance Criteria

1. THE Trade_Category_Registry SHALL store seed data per trade category including: default service items (name, description, default price, unit of measure, category), default product items (for trades that sell products), default labour rate configurations, default expense categories, default job templates with checklist items, and sample invoice/quote templates
2. WHEN a new organisation completes the Setup_Wizard, THE Platform SHALL populate the organisation's catalogue with the seed data from their selected trade category, allowing the user to modify or delete any seeded items
3. THE Platform SHALL provide trade-specific sample CSV files for bulk import (products, customers, services) downloadable from the data import screen, with column headers and example rows matching the trade's typical data
4. THE Platform SHALL allow Global_Admin to update seed data for a trade category without affecting existing organisations that have already been bootstrapped
5. THE Platform SHALL version seed data sets so that the Global_Admin can track changes and optionally offer existing organisations an "update to latest defaults" option that adds new seed items without modifying existing ones

### Requirement 47: Webhook Management and Security

**User Story:** As an Org_Admin, I want to configure outbound webhooks that notify external systems of events in my organisation, so that I can integrate OraInvoice with my other business tools.

#### Acceptance Criteria

1. THE Platform SHALL allow Org_Admin to register outbound webhook URLs with: target URL (HTTPS required), event types to subscribe to (invoice.created, invoice.paid, customer.created, job.status_changed, booking.created, payment.received, stock.low, etc.), a webhook secret for signature verification, and active/inactive status
2. WHEN a subscribed event occurs, THE Platform SHALL send an HTTP POST to the registered webhook URL with: a JSON payload containing the event type, timestamp, organisation ID, and the relevant entity data, plus an `X-OraInvoice-Signature` header containing the HMAC-SHA256 signature of the payload using the webhook secret
3. IF a webhook delivery fails (non-2xx response or timeout after 10 seconds), THEN THE Platform SHALL retry delivery up to 5 times with exponential backoff (1 min, 5 min, 15 min, 1 hour, 4 hours) and mark the webhook as "failing" after all retries are exhausted
4. THE Platform SHALL maintain a webhook delivery log per organisation showing: event type, delivery timestamp, response status code, response time, and retry count
5. THE Platform SHALL automatically disable a webhook endpoint after 50 consecutive delivery failures and send an email notification to the Org_Admin
6. THE Platform SHALL support a "test webhook" function that sends a sample event payload to the configured URL and displays the response

### Requirement 48: Vehicle and Asset Tracking Module (Extended)

**User Story:** As an Org_Admin in any trade, I want to track assets (not just vehicles) associated with customers and jobs, so that service history is maintained for any type of equipment or property.

#### Acceptance Criteria

1. THE Vehicle_Module SHALL be extended to support generic asset tracking where the asset type is determined by the organisation's trade category: vehicles (automotive trades), devices/equipment (IT trades), properties/sites (building trades), appliances (electrical/plumbing trades), or custom asset types defined by the Org_Admin
2. THE Vehicle_Module SHALL retain full Carjam integration for automotive trade categories while providing a generic asset form (serial number, make, model, description, location, custom fields) for non-automotive trades
3. THE Vehicle_Module SHALL support custom fields per asset type that the Org_Admin can define: field name, field type (text, number, date, dropdown), and whether the field is required
4. THE Vehicle_Module SHALL maintain a complete service history per asset showing all linked invoices, jobs, and quotes in chronological order regardless of trade type
5. WHEN an asset is linked to a job or invoice, THE Vehicle_Module SHALL display the asset details on the job/invoice form using the trade-appropriate terminology (e.g. "Vehicle" for workshops, "Device" for IT, "Property" for builders)

### Requirement 49: Customer Portal Enhancements

**User Story:** As a customer of an OraInvoice organisation, I want a self-service portal where I can view invoices, make payments, view asset history, and manage bookings, so that I can interact with the business without phone calls or emails.

#### Acceptance Criteria

1. THE Customer_Portal SHALL provide authenticated access via a secure token link sent by email, with token expiry configurable by the Org_Admin (default 90 days)
2. THE Customer_Portal SHALL display: all invoices (with status and payment history), all quotes (with online acceptance capability), all assets/vehicles with service history, upcoming bookings, loyalty points balance (if Loyalty_Module is enabled), and compliance documents linked to their invoices
3. THE Customer_Portal SHALL allow customers to make payments on outstanding invoices via Stripe, with support for partial payments if the organisation allows them
4. THE Customer_Portal SHALL allow customers to book appointments (if Booking_Module is enabled) using the same availability rules as the public booking page
5. THE Customer_Portal SHALL apply the organisation's branding (logo, colours) and the platform "Powered By" footer
6. THE Customer_Portal SHALL support the organisation's configured language, displaying all portal content in the appropriate language

### Requirement 50: Reporting Module Enhancements

**User Story:** As an Org_Admin, I want enhanced reporting that covers all new modules and supports multi-location and multi-currency consolidation, so that I have complete visibility into business performance.

#### Acceptance Criteria

1. THE Reporting_Module SHALL provide reports for all enabled modules including: inventory valuation report (stock value at cost and sale price), job profitability report (revenue vs costs per job), project profitability report (budget vs actual per project), staff utilisation report (hours worked vs available), time tracking summary (billable vs non-billable hours), expense summary by category, POS transaction summary (daily/weekly/monthly), loyalty program report (points issued, redeemed, outstanding), and progress claim summary per project
2. WHEN the MultiCurrency_Module is enabled, THE Reporting_Module SHALL consolidate all financial reports to the base currency using the exchange rates recorded at the time of each transaction
3. WHEN the Franchise_Module is enabled with multi-location, THE Reporting_Module SHALL support filtering all reports by location and provide a combined view across all locations
4. THE Reporting_Module SHALL support scheduling automated report generation and email delivery on a configurable frequency (daily, weekly, monthly) to specified email addresses
5. THE Reporting_Module SHALL generate tax return reports matching the format required by the organisation's Compliance_Profile (NZ GST Return, AU BAS, UK VAT Return)
6. THE Reporting_Module SHALL support exporting all reports as CSV and PDF formats

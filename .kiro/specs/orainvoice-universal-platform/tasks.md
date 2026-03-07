# Implementation Tasks

## Task Overview
This document contains the implementation tasks for the OraInvoice Universal Platform enhancement.
Tasks are organized by feature area and ordered by dependency (foundational tasks first).

## Phase 1: Database Foundation & Core Infrastructure

- [x] 1. Create Alembic migrations for core platform tables
  - [x] 1.1 Create migration 0008: trade_families and trade_categories tables with indexes
  - [x] 1.2 Create migration 0009: feature_flags table
  - [x] 1.3 Create migration 0010: module_registry and org_modules tables
  - [x] 1.4 Create migration 0011: ALTER organisations table to add trade_category_id, country_code, data_residency_region, base_currency, locale, tax_label, default_tax_rate, tax_inclusive_default, date_format, number_format, timezone, compliance_profile_id, setup_wizard_state, is_multi_location, franchise_group_id, white_label_enabled, storage_used_bytes, storage_quota_bytes columns
  - [x] 1.5 Create migration 0012: compliance_profiles table
  - [x] 1.6 Create migration 0013: setup_wizard_progress table
  - [x] 1.7 Create migration 0014: org_terminology_overrides table
  - [x] 1.8 Create migration 0015: idempotency_keys table with expiry index
  - [x] 1.9 Create migration 0016: dead_letter_queue table
  - [x] 1.10 Run all migrations and verify schema with `alembic upgrade head`

- [x] 2. Create seed data migrations
  - [x] 2.1 Create migration 0034: Seed trade_families with 15 families (Automotive & Transport, Electrical & Mechanical, Plumbing & Gas, Building & Construction, Landscaping & Outdoor, Cleaning & Facilities, IT & Technology, Creative & Professional Services, Accounting Legal & Financial, Health & Wellness, Food & Hospitality, Retail, Hair Beauty & Personal Care, Trades Support & Hire, Freelancing & Contracting)
  - [x] 2.2 Create migration 0035: Seed trade_categories with all trade types per family including slug, display_name, icon, description, recommended_modules, terminology_overrides, default_services, and default_products JSON data
  - [x] 2.3 Create migration 0036: Seed compliance_profiles for NZ (GST 15%), AU (GST 10%, ABN), UK (VAT 20%/5%/0%), and Generic profile
  - [x] 2.4 Create migration 0037: Seed module_registry with all module slugs, display names, descriptions, categories, dependency lists, and is_core flags
  - [x] 2.5 Create migration 0038: Seed platform_branding with OraInvoice defaults (name, colours, URLs)
  - [x] 2.6 Write property-based test: verify all trade categories reference valid trade families
  - [x] 2.7 Write property-based test: verify all module dependencies reference valid module slugs

- [x] 3. Implement API versioning infrastructure
  - [x] 3.1 Create `app/middleware/api_version.py` with APIVersionMiddleware that adds Deprecation and Link headers to /api/v1/ responses pointing to /api/v2/ equivalents
  - [x] 3.2 Create V2 API router in `app/main.py` mounting all new module routers under /api/v2/ prefix
  - [x] 3.3 Register APIVersionMiddleware in the FastAPI app middleware stack
  - [x] 3.4 Write tests verifying /api/v1/ endpoints still work unchanged and include deprecation headers
  - [x] 3.5 Write tests verifying /api/v2/ endpoints are accessible and return correct responses

- [x] 4. Implement feature flag system
  - [x] 4.1 Create `app/core/feature_flags.py` with FeatureFlagService class implementing evaluate() method with targeting priority: org_override → trade_category → trade_family → country → plan_tier → percentage
  - [x] 4.2 Create `app/modules/feature_flags/models.py` with SQLAlchemy FeatureFlag model
  - [x] 4.3 Create `app/modules/feature_flags/schemas.py` with Pydantic schemas for flag CRUD
  - [x] 4.4 Create `app/modules/feature_flags/router.py` with Global Admin CRUD endpoints (GET/POST/PUT/DELETE /api/v2/admin/flags) and org-context endpoint (GET /api/v2/flags)
  - [x] 4.5 Create `app/modules/feature_flags/service.py` with Redis caching (60s TTL), cache invalidation on toggle (within 5s), and fallback to default_value on Redis/DB errors
  - [x] 4.6 Write property-based test (Hypothesis): for any flag and org context, evaluation is deterministic given the same targeting rules
  - [x] 4.7 Write property-based test: cache invalidation ensures fresh evaluation within 5 seconds of flag toggle
  - [x] 4.8 Write integration test: flag evaluation falls back to default on Redis failure

- [x] 5. Implement module selection and dependency system
  - [x] 5.1 Create `app/core/modules.py` with ModuleService class implementing enable_module() (auto-enables dependencies), disable_module() (returns dependents list), and is_enabled() with Redis caching
  - [x] 5.2 Create `app/middleware/modules.py` with ModuleMiddleware that maps request paths to module slugs via MODULE_ENDPOINT_MAP and returns HTTP 403 for disabled modules
  - [x] 5.3 Create `app/modules/module_management/models.py` with ModuleRegistry and OrgModule SQLAlchemy models
  - [x] 5.4 Create `app/modules/module_management/router.py` with endpoints: GET /api/v2/modules (list with enabled state), PUT /api/v2/modules/{slug}/enable, PUT /api/v2/modules/{slug}/disable
  - [x] 5.5 Create `app/modules/module_management/schemas.py` with response schemas including dependency warnings
  - [x] 5.6 Register ModuleMiddleware in FastAPI middleware stack after auth middleware
  - [x] 5.7 Write property-based test: for any org, if module M is enabled and has dependencies [D1, D2], then D1 and D2 are also enabled (Property 10)
  - [x] 5.8 Write property-based test: for any org with module M disabled, all M's endpoints return 403 (Property 1)
  - [x] 5.9 Write integration test: enabling a module with dependencies auto-enables dependencies
  - [x] 5.10 Write integration test: disabling a module that others depend on returns warning with dependent list

- [x] 6. Implement terminology resolution service
  - [x] 6.1 Create `app/core/terminology.py` with TerminologyService class implementing get_terminology_map() that merges DEFAULT_TERMS → trade category overrides → org-level overrides
  - [x] 6.2 Create `app/modules/terminology/models.py` with OrgTerminologyOverride SQLAlchemy model
  - [x] 6.3 Create `app/modules/terminology/router.py` with endpoints: GET /api/v2/terminology (returns merged map), PUT /api/v2/terminology (set org overrides)
  - [x] 6.4 Write property-based test: for any org with trade category, terminology map contains all DEFAULT_TERMS keys (Property 18)
  - [x] 6.5 Write test: org-level overrides take precedence over trade category overrides

- [x] 7. Implement trade category registry
  - [x] 7.1 Create `app/modules/trade_categories/models.py` with TradeFamily and TradeCategory SQLAlchemy models
  - [x] 7.2 Create `app/modules/trade_categories/schemas.py` with Pydantic schemas for CRUD, including nested default_services and terminology_overrides
  - [x] 7.3 Create `app/modules/trade_categories/service.py` with TradeCategoryService implementing: list families, list categories (filterable by family), get category with seed data, create/update/retire category, seed data export/import in JSON
  - [x] 7.4 Create `app/modules/trade_categories/router.py` with endpoints: GET /api/v2/trade-families, GET /api/v2/trade-categories, GET /api/v2/trade-categories/{slug}, POST /api/v2/admin/trade-families, POST /api/v2/admin/trade-categories, PUT /api/v2/admin/trade-categories/{slug}
  - [x] 7.5 Write test: creating a trade category validates unique slug, valid family reference, and at least one default service
  - [x] 7.6 Write test: retiring a trade category prevents new org selection but existing orgs continue unchanged
  - [x] 7.7 Write test: updating trade category defaults does not retroactively modify existing orgs

- [x] 8. Implement compliance profiles
  - [x] 8.1 Create `app/modules/compliance_profiles/models.py` with ComplianceProfile SQLAlchemy model
  - [x] 8.2 Create `app/modules/compliance_profiles/service.py` with ComplianceProfileService implementing: get by country_code, list all, create/update (Global Admin)
  - [x] 8.3 Create `app/modules/compliance_profiles/router.py` with Global Admin CRUD endpoints
  - [x] 8.4 Write test: selecting NZ sets GST 15%, tax_inclusive=True, date_format=dd/MM/yyyy
  - [x] 8.5 Write test: selecting UK sets VAT with standard/reduced/zero rates

- [x] 9. Extend role-based access control
  - [x] 9.1 Update `app/middleware/rbac.py` to add new roles: franchise_admin, location_manager, staff_member with their permission sets as defined in ROLE_PERMISSIONS
  - [x] 9.2 Create LocationScopedPermission class in rbac.py that restricts location_manager to assigned locations only
  - [x] 9.3 Add custom permission overrides support: create user_permission_overrides table, update RBAC middleware to check overrides after base role permissions
  - [x] 9.4 Add users.assigned_location_ids and users.franchise_group_id columns via Alembic migration
  - [x] 9.5 Update auth middleware to include role and location assignments in JWT claims
  - [x] 9.6 Write property-based test: location_manager can only access data for assigned locations (Property 17)
  - [x] 9.7 Write test: franchise_admin has read-only access to aggregate metrics only
  - [x] 9.8 Write test: staff_member can only access assigned jobs and own time entries
  - [x] 9.9 Write test: permission overrides are recorded in audit log

- [x] 10. Implement idempotency and cross-module transaction infrastructure
  - [x] 10.1 Create `app/middleware/idempotency.py` with IdempotencyMiddleware that checks Idempotency-Key header on POST/PUT/PATCH, returns cached response if key exists, stores response after execution with 24h expiry
  - [x] 10.2 Create `app/core/transactions.py` with TransactionalOperation base class providing async context manager for cross-module DB transactions with rollback on partial failure
  - [x] 10.3 Create dead letter queue service in `app/core/dead_letter.py` with store_failed_task(), retry_task(), and alert_if_stale() methods
  - [x] 10.4 Register IdempotencyMiddleware in FastAPI middleware stack
  - [x] 10.5 Write property-based test: two requests with same idempotency key return identical responses (Property 16)
  - [x] 10.6 Write test: cross-module operation rolls back all changes on partial failure
  - [x] 10.7 Write test: dead letter queue retries failed tasks up to 3 times with exponential backoff

## Phase 2: Setup Wizard & Onboarding

- [x] 11. Implement setup wizard backend
  - [x] 11.1 Create `app/modules/setup_wizard/models.py` with SetupWizardProgress SQLAlchemy model
  - [x] 11.2 Create `app/modules/setup_wizard/schemas.py` with step-specific Pydantic schemas: CountryStepData, TradeStepData, BusinessStepData, BrandingStepData, ModulesStepData, CatalogueStepData
  - [x] 11.3 Create `app/modules/setup_wizard/service.py` with SetupWizardService implementing: process_step() for each step (applies country defaults, trade category config, business details, branding, module enablement, catalogue seeding), get_progress(), skip_step()
  - [x] 11.4 Create `app/modules/setup_wizard/router.py` with endpoints: POST /api/v2/setup-wizard/step/{step_number}, GET /api/v2/setup-wizard/progress
  - [x] 11.5 Implement country selection logic: map country_code to currency, date_format, number_format, tax_label, default_tax_rate, timezone, compliance_profile_id
  - [x] 11.6 Implement trade selection logic: apply recommended_modules, terminology_overrides, default_services from trade category
  - [x] 11.7 Implement tax identifier validation per country (NZ GST format, AU ABN format, UK VAT format)
  - [x] 11.8 Write property-based test: submitting same wizard step data twice produces same result, no duplicates (Property 19)
  - [x] 11.9 Write test: skipping all steps still creates a usable org with sensible defaults
  - [x] 11.10 Write test: wizard progress is persisted and resumable

- [x] 12. Implement setup wizard frontend
  - [x] 12.1 Create `frontend/src/pages/setup/SetupWizard.tsx` main container with step navigation, progress indicator, and skip/back/next buttons
  - [x] 12.2 Create `frontend/src/pages/setup/steps/CountryStep.tsx` with searchable country dropdown that auto-fills currency/tax/date format preview
  - [x] 12.3 Create `frontend/src/pages/setup/steps/TradeStep.tsx` with visual trade family grid (icons), expandable to show specific trade types, multi-select up to 3
  - [x] 12.4 Create `frontend/src/pages/setup/steps/BusinessStep.tsx` with form fields: business name, trading name, registration number, tax number (with country-specific validation), phone, address, website
  - [x] 12.5 Create `frontend/src/pages/setup/steps/BrandingStep.tsx` with logo upload, colour pickers, and live InvoicePreview component that updates in real-time
  - [x] 12.6 Create `frontend/src/pages/setup/steps/ModulesStep.tsx` with grouped module checklist, pre-selected based on trade, dependency warnings on deselect
  - [x] 12.7 Create `frontend/src/pages/setup/steps/CatalogueStep.tsx` with editable list of pre-populated services/products from trade category seed data, add/edit/delete capability
  - [x] 12.8 Create `frontend/src/pages/setup/steps/ReadyStep.tsx` with summary of all configured settings and edit links per section
  - [x] 12.9 Create `frontend/src/pages/setup/components/StepIndicator.tsx` progress bar component
  - [x] 12.10 Create `frontend/src/pages/setup/components/InvoicePreview.tsx` live invoice PDF preview component
  - [x] 12.11 Write frontend tests for wizard step navigation, validation, and skip functionality

- [x] 13. Implement terminology frontend integration
  - [x] 13.1 Create `frontend/src/contexts/TerminologyContext.tsx` with TerminologyProvider that fetches /api/v2/terminology and provides useTerm() hook
  - [x] 13.2 Create `frontend/src/components/common/TermLabel.tsx` component that renders trade-specific labels using useTerm()
  - [x] 13.3 Create `frontend/src/contexts/ModuleContext.tsx` with ModuleProvider that fetches /api/v2/modules and provides useModules() hook
  - [x] 13.4 Create `frontend/src/components/common/ModuleGate.tsx` component that conditionally renders children based on module enablement
  - [x] 13.5 Create `frontend/src/contexts/FeatureFlagContext.tsx` with FeatureFlagProvider that fetches /api/v2/flags and provides useFlag() hook
  - [x] 13.6 Create `frontend/src/components/common/FeatureGate.tsx` component that conditionally renders based on feature flag
  - [x] 13.7 Update `frontend/src/router/` to implement ModuleRouter with conditional route rendering based on enabled modules
  - [x] 13.8 Update main navigation sidebar to show/hide menu items based on enabled modules
  - [x] 13.9 Write frontend tests: TermLabel renders correct trade-specific text
  - [x] 13.10 Write frontend tests: ModuleGate hides content when module disabled

## Phase 3: Inventory & Stock Management

- [x] 14. Create inventory database tables
  - [x] 14.1 Create migration 0017: product_categories table with org_id, name, parent_id, display_order
  - [x] 14.2 Create migration 0018: suppliers table with org_id, name, contact details, active status
  - [x] 14.3 Create migration 0019: products table with all fields (name, SKU, barcode, category_id, unit_of_measure, sale_price, cost_price, stock_quantity, low_stock_threshold, reorder_quantity, supplier_id, images JSONB, location_id) and indexes
  - [x] 14.4 Create migration 0020: stock_movements table with product_id, location_id, movement_type, quantity_change, resulting_quantity, reference_type, reference_id, performed_by
  - [x] 14.5 Create migration 0021: pricing_rules table with product_id, rule_type, priority, customer_id, customer_tag, quantity ranges, date ranges, price_override, discount_percent
  - [x] 14.6 Run migrations and verify schema

- [x] 15. Implement inventory backend
  - [x] 15.1 Create `app/modules/products/models.py` with Product, ProductCategory, Supplier SQLAlchemy models
  - [x] 15.2 Create `app/modules/products/schemas.py` with Pydantic schemas for product CRUD, category tree, CSV import
  - [x] 15.3 Create `app/modules/products/service.py` with ProductService: CRUD, barcode lookup, category tree, stock quantity management
  - [x] 15.4 Create `app/modules/products/router.py` with all product endpoints: list (paginated/filterable), create, get, update, soft-delete, barcode lookup
  - [x] 15.5 Create `app/modules/stock/models.py` with StockMovement SQLAlchemy model
  - [x] 15.6 Create `app/modules/stock/service.py` with StockService: decrement_stock(), increment_stock(), manual_adjustment(), create_stocktake(), commit_stocktake()
  - [x] 15.7 Create `app/modules/stock/router.py` with endpoints: GET stock-movements, POST stock-adjustments, POST/PUT stocktakes
  - [x] 15.8 Create `app/modules/suppliers/models.py`, service.py, router.py for supplier CRUD
  - [x] 15.9 Implement CSV import service with preview, validation, field mapping, and trade-specific sample template generation
  - [x] 15.10 Create product category CRUD endpoints with tree structure support
  - [x] 15.11 Write property-based test: sum of all stock_movement quantity_changes equals product's current stock_quantity (Property 3)
  - [x] 15.12 Write test: invoice issuance decrements stock, credit note increments stock
  - [x] 15.13 Write test: low stock alert triggers when quantity falls below threshold
  - [x] 15.14 Write test: zero stock blocks invoice line item when backorder disabled

- [x] 16. Implement pricing rules engine
  - [x] 16.1 Create `app/modules/pricing_rules/models.py` with PricingRule SQLAlchemy model
  - [x] 16.2 Create `app/modules/pricing_rules/service.py` with PricingRuleService: evaluate_price() checking rules in priority order (customer-specific → volume → date-based → trade category → base price), create/update/delete rules, validate no circular/conflicting rules
  - [x] 16.3 Create `app/modules/pricing_rules/router.py` with CRUD endpoints
  - [x] 16.4 Write property-based test: pricing rule evaluation is deterministic for same inputs (Property 7)
  - [x] 16.5 Write test: customer-specific price overrides volume pricing when higher priority
  - [x] 16.6 Write test: date-based pricing activates and deactivates on configured dates

- [x] 17. Implement inventory frontend
  - [x] 17.1 Create `frontend/src/pages/inventory/ProductList.tsx` with paginated table, search, category filter, barcode scan button
  - [x] 17.2 Create `frontend/src/pages/inventory/ProductDetail.tsx` with full product form, image upload, stock history
  - [x] 17.3 Create `frontend/src/pages/inventory/CategoryTree.tsx` with drag-and-drop category management
  - [x] 17.4 Create `frontend/src/pages/inventory/StockMovements.tsx` with filterable movement history
  - [x] 17.5 Create `frontend/src/pages/inventory/StockTake.tsx` with counted vs system quantity entry, variance highlighting
  - [x] 17.6 Create `frontend/src/pages/inventory/CSVImport.tsx` with file upload, preview table, field mapping, and import results
  - [x] 17.7 Create `frontend/src/pages/inventory/PricingRules.tsx` with rule list, create/edit forms, priority ordering
  - [x] 17.8 Create `frontend/src/utils/barcodeScanner.ts` utility using Web Barcode Detection API with fallback to quagga2 library
  - [x] 17.9 Write frontend tests for product CRUD, CSV import preview, barcode scanning

## Phase 4: Jobs, Quotes, Time Tracking, Projects & Expenses

- [x] 18. Implement job and work order management
  - [x] 18.1 Create migration 0022: jobs, job_staff_assignments, job_attachments, job_status_history tables
  - [x] 18.2 Create `app/modules/jobs_v2/models.py` with Job, JobStaffAssignment, JobAttachment, JobStatusHistory SQLAlchemy models
  - [x] 18.3 Create `app/modules/jobs_v2/schemas.py` with Pydantic schemas for job CRUD, status change, attachment upload
  - [x] 18.4 Create `app/modules/jobs_v2/service.py` with JobService: CRUD, change_status() with valid transition enforcement, assign_staff(), add_attachment(), convert_to_invoice()
  - [x] 18.5 Create `app/modules/jobs_v2/router.py` with all job endpoints: list, create, get, update, status change, attachments, convert-to-invoice, job-templates
  - [x] 18.6 Implement job status transition validation: define valid transitions map, reject invalid transitions with clear error
  - [x] 18.7 Implement job-to-invoice conversion: create Draft invoice pre-populated with customer, location, time entries as Labour items, expenses as line items, materials as Product items
  - [x] 18.8 Implement job templates: CRUD for templates with pre-filled description, checklist, default line items per trade category
  - [x] 18.9 Write property-based test: job status transitions follow only valid paths (Property 5)
  - [x] 18.10 Write test: job-to-invoice conversion creates correct line items from time entries, expenses, and materials
  - [x] 18.11 Write test: job attachments count toward org storage quota
  - [x] 18.12 Create `frontend/src/pages/jobs/JobBoard.tsx` Kanban board view with drag-and-drop status changes
  - [x] 18.13 Create `frontend/src/pages/jobs/JobDetail.tsx` with full job form, checklist, attachments, status timeline, convert-to-invoice button
  - [x] 18.14 Create `frontend/src/pages/jobs/JobList.tsx` filterable list view
  - [x] 18.15 Write frontend tests for job board, status transitions, and attachment upload

- [x] 19. Implement quotes and estimates module
  - [x] 19.1 Create migration 0023: quotes table with quote_number, customer_id, project_id, status, expiry_date, terms, version_number, previous_version_id, converted_invoice_id, acceptance_token
  - [x] 19.2 Create `app/modules/quotes_v2/models.py` with Quote SQLAlchemy model
  - [x] 19.3 Create `app/modules/quotes_v2/service.py` with QuoteService: CRUD, send_to_customer(), accept_quote(), convert_to_invoice(), create_revision(), check_expiry()
  - [x] 19.4 Create `app/modules/quotes_v2/router.py` with all quote endpoints including public acceptance endpoint GET /api/v2/quotes/accept/{token}
  - [x] 19.5 Implement quote-to-invoice conversion with bidirectional reference storage
  - [x] 19.6 Implement quote versioning: create_revision() creates new quote linked to previous version
  - [x] 19.7 Add Celery task `check_quote_expiry` that runs daily to mark expired quotes
  - [x] 19.8 Write property-based test: converted quote has exactly one linked invoice with matching line items (Property 6)
  - [x] 19.9 Write test: quote expiry auto-updates status after expiry_date
  - [x] 19.10 Create `frontend/src/pages/quotes/QuoteList.tsx` and `QuoteDetail.tsx` with send, accept, convert, revise actions
  - [x] 19.11 Write frontend tests for quote lifecycle

- [x] 20. Implement time tracking module
  - [x] 20.1 Create migration 0024: time_entries table with user_id, staff_id, job_id, project_id, start_time, end_time, duration_minutes, is_billable, hourly_rate, is_invoiced, is_timer_active
  - [x] 20.2 Create `app/modules/time_tracking_v2/models.py` with TimeEntry SQLAlchemy model
  - [x] 20.3 Create `app/modules/time_tracking_v2/service.py` with TimeTrackingService: create_entry(), start_timer(), stop_timer(), get_active_timer(), get_timesheet(), add_to_invoice()
  - [x] 20.4 Create `app/modules/time_tracking_v2/router.py` with all time tracking endpoints including timer start/stop and weekly timesheet
  - [x] 20.5 Implement overlap detection: prevent two time entries for same user covering same time period
  - [x] 20.6 Implement add-to-invoice: create Labour line items (hours × rate), mark entries as invoiced
  - [x] 20.7 Write test: overlapping time entries are rejected with validation error
  - [x] 20.8 Write test: invoiced time entries cannot be added to another invoice (double-billing prevention)
  - [x] 20.9 Create `frontend/src/pages/time-tracking/TimeSheet.tsx` weekly view with daily/weekly totals
  - [x] 20.10 Create timer component in app header showing elapsed time, persisted via localStorage
  - [x] 20.11 Write frontend tests for timer start/stop and timesheet display

- [x] 21. Implement project management module
  - [x] 21.1 Create migration 0025: projects table with name, customer_id, budget_amount, contract_value, revised_contract_value, retention_percentage, status
  - [x] 21.2 Create `app/modules/projects/models.py` with Project SQLAlchemy model
  - [x] 21.3 Create `app/modules/projects/service.py` with ProjectService: CRUD, calculate_profitability() (revenue vs costs), get_progress(), get_activity_feed()
  - [x] 21.4 Create `app/modules/projects/router.py` with project endpoints including profitability dashboard and activity feed
  - [x] 21.5 Write test: project profitability correctly sums paid invoices vs expenses + labour costs
  - [x] 21.6 Create `frontend/src/pages/projects/ProjectList.tsx` and `ProjectDashboard.tsx` with profitability charts, progress bar, linked entities
  - [x] 21.7 Write frontend tests for project dashboard

- [x] 22. Implement expense tracking module
  - [x] 22.1 Create migration 0026: expenses table with job_id, project_id, amount, tax_amount, category, receipt_file_key, is_pass_through, is_invoiced
  - [x] 22.2 Create `app/modules/expenses/models.py` with Expense SQLAlchemy model
  - [x] 22.3 Create `app/modules/expenses/service.py` with ExpenseService: CRUD, get_summary_report(), include_in_invoice()
  - [x] 22.4 Create `app/modules/expenses/router.py` with expense CRUD and summary report endpoints
  - [x] 22.5 Write test: pass-through expenses appear as line items on job-to-invoice conversion
  - [x] 22.6 Create `frontend/src/pages/expenses/ExpenseList.tsx` with receipt upload and category filter
  - [x] 22.7 Write frontend tests for expense CRUD

## Phase 5: Purchase Orders, Staff, Scheduling & Bookings

- [x] 23. Implement purchase order module
  - [x] 23.1 Create migration 0027: purchase_orders and purchase_order_lines tables
  - [x] 23.2 Create `app/modules/purchase_orders/models.py` with PurchaseOrder and PurchaseOrderLine SQLAlchemy models
  - [x] 23.3 Create `app/modules/purchase_orders/service.py` with PurchaseOrderService: CRUD, receive_goods() (creates stock movements, updates PO status), partial_receive(), generate_pdf()
  - [x] 23.4 Create `app/modules/purchase_orders/router.py` with PO endpoints: list, create, get, update, receive, send
  - [x] 23.5 Implement PO-to-inventory integration: receiving goods increments stock via StockService
  - [x] 23.6 Implement PO PDF generation using org branding
  - [x] 23.7 Write test: receiving goods creates stock movements and increments product quantities
  - [x] 23.8 Write test: partial receiving tracks outstanding quantities correctly
  - [x] 23.9 Create `frontend/src/pages/purchase-orders/POList.tsx` and `PODetail.tsx` with receive goods interface
  - [x] 23.10 Write frontend tests for PO lifecycle

- [x] 24. Implement staff and contractor management
  - [x] 24.1 Create migration 0028: staff_members and staff_location_assignments tables
  - [x] 24.2 Create `app/modules/staff/models.py` with StaffMember and StaffLocationAssignment SQLAlchemy models
  - [x] 24.3 Create `app/modules/staff/service.py` with StaffService: CRUD, assign_to_location(), calculate_utilisation(), get_labour_costs()
  - [x] 24.4 Create `app/modules/staff/router.py` with staff endpoints: list, create, update, utilisation report
  - [x] 24.5 Write test: deactivated staff cannot be assigned to new jobs
  - [x] 24.6 Write test: labour costs correctly calculated from time entries × hourly rate
  - [x] 24.7 Create `frontend/src/pages/staff/StaffList.tsx` and `StaffDetail.tsx` with availability schedule editor
  - [x] 24.8 Write frontend tests for staff management

- [x] 25. Implement scheduling and calendar module
  - [x] 25.1 Create migration 0029: schedule_entries table with staff_id, job_id, booking_id, location_id, start_time, end_time, entry_type
  - [x] 25.2 Create `app/modules/scheduling_v2/models.py` with ScheduleEntry SQLAlchemy model
  - [x] 25.3 Create `app/modules/scheduling_v2/service.py` with SchedulingService: CRUD, detect_conflicts(), reschedule(), send_reminders()
  - [x] 25.4 Create `app/modules/scheduling_v2/router.py` with schedule endpoints: get (date range), create, update (reschedule)
  - [x] 25.5 Add Celery task for automated staff reminders (configurable time before scheduled job)
  - [x] 25.6 Write test: scheduling conflict detection flags overlapping entries for same staff
  - [x] 25.7 Create `frontend/src/pages/schedule/ScheduleCalendar.tsx` with day/week/month views, drag-and-drop reschedule, staff/location filters
  - [x] 25.8 Write frontend tests for calendar navigation and drag-and-drop

- [x] 26. Implement booking and appointments module
  - [x] 26.1 Create migration 0030: bookings and booking_rules tables
  - [x] 26.2 Create `app/modules/bookings_v2/models.py` with Booking and BookingRule SQLAlchemy models
  - [x] 26.3 Create `app/modules/bookings_v2/service.py` with BookingService: create_booking(), get_available_slots(), cancel_booking(), convert_to_job(), convert_to_invoice(), send_confirmation()
  - [x] 26.4 Create `app/modules/bookings_v2/router.py` with internal booking endpoints and public booking endpoints: GET /api/v2/public/bookings/{org_slug} (page data), POST (submit booking), GET slots
  - [x] 26.5 Implement available slot calculation based on booking rules, existing bookings, and staff schedules
  - [x] 26.6 Implement public booking page data endpoint with org branding
  - [x] 26.7 Write test: booking respects min advance time and max advance window
  - [x] 26.8 Write test: cancellation frees the time slot and sends notifications
  - [x] 26.9 Create `frontend/src/pages/bookings/BookingList.tsx` and public `BookingPage.tsx` with org branding
  - [x] 26.10 Write frontend tests for booking flow and slot availability

## Phase 6: Point of Sale & Receipt Printing

- [x] 27. Create POS database tables
  - [x] 27.1 Create migration 0031: pos_sessions table with org_id, location_id, user_id, opening_cash, closing_cash, status
  - [x] 27.2 Create migration 0032: pos_transactions table with session_id, invoice_id, customer_id, table_id, offline_transaction_id, payment_method, amounts, sync fields
  - [x] 27.3 Create migration 0033: printer_configs table with connection_type, address, paper_width, is_default, is_kitchen_printer
  - [x] 27.4 Create migration 0034: print_jobs table with printer_id, job_type, payload, status, retry_count

- [x] 28. Implement POS backend
  - [x] 28.1 Create `app/modules/pos/models.py` with POSSession, POSTransaction SQLAlchemy models
  - [x] 28.2 Create `app/modules/pos/schemas.py` with Pydantic schemas for session open/close, transaction creation, offline sync batch
  - [x] 28.3 Create `app/modules/pos/service.py` with POSService: open_session(), close_session(), complete_transaction() (creates invoice + payment + stock decrement in single transaction), sync_offline_transactions()
  - [x] 28.4 Create `app/modules/pos/router.py` with POS endpoints: open session, close session, complete transaction, sync offline batch, sync status
  - [x] 28.5 Implement complete_transaction() using TransactionalOperation: create Issued invoice, record payment, decrement inventory, award loyalty points (if enabled), queue receipt print
  - [x] 28.6 Implement sync_offline_transactions() using OfflineSyncService: process in chronological order, detect conflicts (price changes, deleted products, insufficient stock), create invoices with offline values, generate conflict report
  - [x] 28.7 Write property-based test: all offline transactions produce either success or explicit conflict/error record (Property 9)
  - [x] 28.8 Write test: POS transaction creates invoice, records payment, decrements stock atomically
  - [x] 28.9 Write test: offline sync with price change uses offline price and records discrepancy
  - [x] 28.10 Write test: offline sync with insufficient stock allows negative stock and flags discrepancy

- [x] 29. Implement POS frontend
  - [x] 29.1 Create `frontend/src/pages/pos/POSScreen.tsx` full-screen touch-optimised layout with product grid (left) and order panel (right)
  - [x] 29.2 Create `frontend/src/pages/pos/ProductGrid.tsx` with category tabs, search bar, product tiles with images and prices
  - [x] 29.3 Create `frontend/src/pages/pos/OrderPanel.tsx` with line items, quantity +/- buttons, per-item and order-level discount, running totals
  - [x] 29.4 Create `frontend/src/pages/pos/PaymentPanel.tsx` with cash (change calculation), card (Stripe terminal), and split payment support
  - [x] 29.5 Create `frontend/src/utils/posOfflineStore.ts` IndexedDB storage for offline transactions using idb library
  - [x] 29.6 Create `frontend/src/utils/posSyncManager.ts` sync manager that detects connectivity changes, syncs pending transactions in chronological order, handles conflict reports
  - [x] 29.7 Implement offline indicator banner showing "Offline" status and pending transaction count
  - [x] 29.8 Create `frontend/src/pages/pos/SyncStatus.tsx` dashboard showing pending/synced/failed transactions with force sync button
  - [x] 29.9 Integrate barcode scanner (camera + USB/Bluetooth) for adding products to order
  - [x] 29.10 Write frontend tests: POS transaction flow from product selection to payment
  - [x] 29.11 Write frontend tests: offline mode stores transactions in IndexedDB
  - [x] 29.12 Write frontend tests: sync manager processes transactions in order and handles conflicts

- [x] 30. Implement receipt printer integration
  - [x] 30.1 Create `app/modules/receipt_printer/models.py` with PrinterConfig and PrintJob SQLAlchemy models
  - [x] 30.2 Create `app/modules/receipt_printer/service.py` with PrinterService: configure_printer(), test_print(), queue_print_job(), process_print_queue()
  - [x] 30.3 Create `app/modules/receipt_printer/router.py` with printer config endpoints and print job management
  - [x] 30.4 Create `frontend/src/utils/escpos.ts` ESC/POS command builder for receipt formatting (58mm/80mm layouts, logo bitmap, line items, totals, footer)
  - [x] 30.5 Implement WebUSB printer connection in frontend for USB printers
  - [x] 30.6 Implement Web Bluetooth printer connection in frontend for Bluetooth printers
  - [x] 30.7 Implement network printer connection (HTTP POST to printer IP) for Ethernet/WiFi printers
  - [x] 30.8 Implement print queue with retry logic: 3 retries with 2s delay, mark failed after exhaustion
  - [x] 30.9 Create printer configuration UI in org settings with add printer, test print, set default
  - [x] 30.10 Write test: print job retry logic exhausts retries and marks as failed
  - [x] 30.11 Write test: receipt includes all required fields (org name, items, totals, payment method, footer)

## Phase 7: Hospitality Modules (Tables, Kitchen Display, Tipping)

- [x] 31. Implement table and floor plan management
  - [x] 31.1 Create migration 0035: floor_plans, restaurant_tables, table_reservations tables
  - [x] 31.2 Create `app/modules/tables/models.py` with FloorPlan, RestaurantTable, TableReservation SQLAlchemy models
  - [x] 31.3 Create `app/modules/tables/service.py` with TableService: CRUD floor plans, CRUD tables, update_status(), merge_tables(), split_tables(), create_reservation(), get_floor_plan_state()
  - [x] 31.4 Create `app/modules/tables/router.py` with floor plan, table, and reservation endpoints
  - [x] 31.5 Implement table status management: Available → Occupied (when POS order created) → Needs Cleaning (when paid) → Available (when staff marks clean)
  - [x] 31.6 Implement table merge/split logic with merged_with_id tracking
  - [x] 31.7 Write test: table status transitions follow correct flow
  - [x] 31.8 Write test: reservation appears on floor plan at reserved time
  - [x] 31.9 Create `frontend/src/pages/floor-plan/FloorPlan.tsx` with drag-and-drop table editor, real-time status colours, tap-to-open-order
  - [x] 31.10 Create `frontend/src/pages/floor-plan/ReservationList.tsx` with reservation management
  - [x] 31.11 Write frontend tests for floor plan interaction and table status

- [x] 32. Implement kitchen display system
  - [x] 32.1 Create migration 0036: kitchen_orders table with pos_transaction_id, table_id, item_name, quantity, modifications, station, status, prepared_at
  - [x] 32.2 Create `app/modules/kitchen_display/models.py` with KitchenOrder SQLAlchemy model
  - [x] 32.3 Create `app/modules/kitchen_display/service.py` with KitchenService: get_pending_orders(), mark_prepared(), get_orders_by_station()
  - [x] 32.4 Create `app/modules/kitchen_display/router.py` with kitchen order endpoints
  - [x] 32.5 Create WebSocket endpoint `/ws/kitchen/{org_id}/{station}` for real-time order updates using FastAPI WebSocket + Redis pub/sub
  - [x] 32.6 Implement order item routing to stations based on product category → station mapping
  - [x] 32.7 Implement preparation time highlighting: white → amber (>15min) → red (>30min)
  - [x] 32.8 Write test: new POS order items appear in kitchen display via WebSocket
  - [x] 32.9 Write test: marking item prepared sends notification to front-of-house
  - [x] 32.10 Create `frontend/src/pages/kitchen/KitchenDisplay.tsx` full-screen display with large text, station filtering, tick-off interface
  - [x] 32.11 Implement WebSocket client for real-time updates
  - [x] 32.12 Write frontend tests for kitchen display rendering and item preparation

- [x] 33. Implement tipping module
  - [x] 33.1 Create migration 0037: tips and tip_allocations tables
  - [x] 33.2 Create `app/modules/tipping/models.py` with Tip and TipAllocation SQLAlchemy models
  - [x] 33.3 Create `app/modules/tipping/service.py` with TippingService: record_tip(), allocate_to_staff(), get_tip_summary()
  - [x] 33.4 Integrate tipping into POS transaction flow: show tip prompt after payment with preset percentages
  - [x] 33.5 Integrate tipping into invoice payment flow: optional tip field on online payment
  - [x] 33.6 Implement tip allocation: split evenly or custom amounts across assigned staff
  - [x] 33.7 Create tip summary report endpoint filterable by date range and staff
  - [x] 33.8 Write test: tip is recorded with correct amount and allocated to staff
  - [x] 33.9 Write test: tip summary report shows correct totals per staff member
  - [x] 33.10 Write frontend tests for tip prompt in POS and tip report

- [x] 34. Implement recurring invoices module
  - [x] 34.1 Create migration 0038: recurring_schedules table with customer_id, line_items JSONB, frequency, start_date, end_date, next_generation_date, auto_issue, auto_email, status
  - [x] 34.2 Create `app/modules/recurring_invoices/models.py` with RecurringSchedule SQLAlchemy model
  - [x] 34.3 Create `app/modules/recurring_invoices/service.py` with RecurringService: CRUD, generate_invoice(), advance_next_date()
  - [x] 34.4 Create `app/modules/recurring_invoices/router.py` with recurring schedule CRUD and dashboard endpoint
  - [x] 34.5 Add Celery task `generate_recurring_invoices` that runs daily: find schedules where next_generation_date <= today, create invoices, advance dates, send notifications
  - [x] 34.6 Write test: recurring invoice generates on correct date and advances next_generation_date
  - [x] 34.7 Write test: editing template does not affect previously generated invoices
  - [x] 34.8 Create `frontend/src/pages/recurring/RecurringList.tsx` with schedule management and next generation dates
  - [x] 34.9 Write frontend tests for recurring schedule CRUD

## Phase 8: Construction Modules (Progress Claims, Variations, Retentions)

- [x] 35. Implement progress claims module
  - [x] 35.1 Create migration 0039: progress_claims table with project_id, claim_number, contract_value, variations_to_date, revised_contract_value, work amounts, retention_withheld, status, invoice_id
  - [x] 35.2 Create `app/modules/progress_claims/models.py` with ProgressClaim SQLAlchemy model
  - [x] 35.3 Create `app/modules/progress_claims/service.py` with ProgressClaimService: create_claim() (auto-calculates revised_contract_value, amount_due, completion_percentage), approve_claim() (generates invoice), validate_cumulative_not_exceeding_contract()
  - [x] 35.4 Create `app/modules/progress_claims/router.py` with progress claim endpoints: list, create, update, approve
  - [x] 35.5 Implement progress claim PDF generation following standard construction industry layout
  - [x] 35.6 Write property-based test: cumulative claimed amount never exceeds revised_contract_value (Property 11)
  - [x] 35.7 Write test: approving claim generates invoice for correct amount
  - [x] 35.8 Create `frontend/src/pages/construction/ProgressClaimList.tsx` and `ProgressClaimForm.tsx` with auto-calculated fields
  - [x] 35.9 Write frontend tests for progress claim creation and validation

- [x] 36. Implement variation orders module
  - [x] 36.1 Create migration 0040: variation_orders table with project_id, variation_number, description, cost_impact, status, dates
  - [x] 36.2 Create `app/modules/variations/models.py` with VariationOrder SQLAlchemy model
  - [x] 36.3 Create `app/modules/variations/service.py` with VariationService: CRUD, approve_variation() (updates project revised_contract_value), get_variation_register()
  - [x] 36.4 Create `app/modules/variations/router.py` with variation endpoints: list, create, approve, register
  - [x] 36.5 Implement variation PDF generation with org branding and signature space
  - [x] 36.6 Write property-based test: revised_contract_value equals original + sum of approved variation cost_impacts (Property 12)
  - [x] 36.7 Write test: approved variations cannot be deleted, require offsetting variation
  - [x] 36.8 Create `frontend/src/pages/construction/VariationList.tsx` and `VariationForm.tsx` with approval workflow
  - [x] 36.9 Write frontend tests for variation lifecycle

- [x] 37. Implement retention tracking module
  - [x] 37.1 Create migration 0041: retention_releases table with project_id, amount, release_date, payment_id
  - [x] 37.2 Create `app/modules/retentions/models.py` with RetentionRelease SQLAlchemy model
  - [x] 37.3 Create `app/modules/retentions/service.py` with RetentionService: calculate_retention() (called by progress claim creation), release_retention(), get_retention_summary()
  - [x] 37.4 Create `app/modules/retentions/router.py` with retention release endpoint
  - [x] 37.5 Integrate retention calculation into progress claim creation: auto-withhold configured percentage
  - [x] 37.6 Write property-based test: sum of retention releases never exceeds total retention withheld (Property 20)
  - [x] 37.7 Write test: retention details appear on progress claim PDF
  - [x] 37.8 Create retention summary view on project dashboard
  - [x] 37.9 Write frontend tests for retention release

- [x] 38. Implement compliance and certifications module
  - [x] 38.1 Create migration 0042: compliance_documents table with org_id, document_type, file_key, expiry_date, invoice_id, job_id
  - [x] 38.2 Create `app/modules/compliance_docs/models.py` with ComplianceDocument SQLAlchemy model
  - [x] 38.3 Create `app/modules/compliance_docs/service.py` with ComplianceService: upload_document(), link_to_invoice(), check_expiry(), get_dashboard()
  - [x] 38.4 Create `app/modules/compliance_docs/router.py` with compliance document endpoints: list, upload, expiring
  - [x] 38.5 Add Celery task `check_compliance_expiry` that runs daily: send reminders 30 days and 7 days before expiry
  - [x] 38.6 Implement compliance document attachment in invoice emails and PDF
  - [x] 38.7 Write test: expiry reminders sent at 30-day and 7-day marks
  - [x] 38.8 Write test: compliance documents appear in invoice email attachments
  - [x] 38.9 Create `frontend/src/pages/compliance/ComplianceDashboard.tsx` with document list, expiry tracking, upload
  - [x] 38.10 Write frontend tests for compliance document management

## Phase 9: Ecommerce, Multi-Currency, Loyalty & Webhooks

- [x] 39. Implement ecommerce and WooCommerce integration
  - [x] 39.1 Create migration 0043: woocommerce_connections, ecommerce_sync_log, sku_mappings, api_credentials tables
  - [x] 39.2 Create `app/modules/ecommerce/models.py` with WooCommerceConnection, EcommerceSyncLog, SkuMapping, ApiCredential SQLAlchemy models
  - [x] 39.3 Create `app/modules/ecommerce/woocommerce_service.py` with WooCommerceService: connect(), sync_orders_inbound(), sync_products_outbound(), get_sync_log()
  - [x] 39.4 Create `app/modules/ecommerce/webhook_receiver.py` with inbound webhook endpoint POST /api/v2/ecommerce/webhook/{org_id} that validates HMAC-SHA256 signature, parses order payload, creates invoice
  - [x] 39.5 Create `app/modules/ecommerce/api_service.py` with Zapier-compatible REST API: CRUD for invoices, customers, products with API key authentication and rate limiting (100 req/min per org)
  - [x] 39.6 Create `app/modules/ecommerce/router.py` with all ecommerce endpoints: WooCommerce connect/sync, sync log, SKU mappings, webhook receiver, API key management
  - [x] 39.7 Add Celery task `sync_woocommerce` with configurable schedule (min 15 min) and retry logic (3 retries with exponential backoff)
  - [x] 39.8 Implement SKU mapping interface for manual mapping when SKUs don't match
  - [x] 39.9 Write test: WooCommerce order creates invoice with correct customer and line items
  - [x] 39.10 Write test: webhook with invalid signature returns 401
  - [x] 39.11 Write test: API rate limiting returns 429 after limit exceeded
  - [x] 39.12 Write test: sync retry logic exhausts retries and flags as failed
  - [x] 39.13 Create `frontend/src/pages/ecommerce/WooCommerceSetup.tsx` with connection form and sync log
  - [x] 39.14 Create `frontend/src/pages/ecommerce/SkuMappings.tsx` with mapping interface
  - [x] 39.15 Create `frontend/src/pages/ecommerce/ApiKeys.tsx` with API credential management
  - [x] 39.16 Write frontend tests for ecommerce integration setup

- [x] 40. Implement multi-currency module
  - [x] 40.1 Create migration 0044: exchange_rates and org_currencies tables
  - [x] 40.2 Create `app/modules/multi_currency/models.py` with ExchangeRate and OrgCurrency SQLAlchemy models
  - [x] 40.3 Create `app/modules/multi_currency/service.py` with CurrencyService: enable_currency(), get_exchange_rate(), lock_rate_on_invoice(), convert_to_base(), record_exchange_gain_loss(), refresh_rates_from_provider()
  - [x] 40.4 Create `app/modules/multi_currency/router.py` with currency endpoints: list enabled, enable, exchange rates, manual rate entry, refresh from provider
  - [x] 40.5 Integrate with invoice creation: allow currency selection, lock exchange rate at issue time
  - [x] 40.6 Integrate with reporting: consolidate all financial reports to base currency
  - [x] 40.7 Add Celery task `refresh_exchange_rates` that runs daily to fetch from Open Exchange Rates API
  - [x] 40.8 Implement currency formatting per ISO 4217 (decimal places, symbol position, separators)
  - [x] 40.9 Write property-based test: issued invoice exchange rate is locked and not affected by subsequent rate changes (Property 14)
  - [x] 40.10 Write test: payment in different currency records exchange gain/loss
  - [x] 40.11 Write test: missing exchange rate requires manual entry before invoice can be issued
  - [x] 40.12 Create `frontend/src/pages/settings/CurrencySettings.tsx` with enabled currencies and exchange rate management
  - [x] 40.13 Write frontend tests for currency selection on invoice creation

- [x] 41. Implement loyalty and memberships module
  - [x] 41.1 Create migration 0045: loyalty_config, loyalty_tiers, loyalty_transactions tables
  - [x] 41.2 Create `app/modules/loyalty/models.py` with LoyaltyConfig, LoyaltyTier, LoyaltyTransaction SQLAlchemy models
  - [x] 41.3 Create `app/modules/loyalty/service.py` with LoyaltyService: configure(), award_points() (called on invoice payment), redeem_points(), get_customer_balance(), auto_apply_tier_discount(), check_tier_upgrade()
  - [x] 41.4 Create `app/modules/loyalty/router.py` with loyalty endpoints: config, tiers, customer balance, redeem
  - [x] 41.5 Integrate with invoice payment: auto-award points based on earn rate
  - [x] 41.6 Integrate with invoice creation: auto-apply tier discount for eligible customers
  - [x] 41.7 Write property-based test: customer loyalty balance equals sum of all transaction points (Property 13)
  - [x] 41.8 Write test: paying invoice awards correct points based on earn rate
  - [x] 41.9 Write test: tier discount auto-applied as separate line item
  - [x] 41.10 Create `frontend/src/pages/loyalty/LoyaltyConfig.tsx` with earn rate, tiers, and customer balance view
  - [x] 41.11 Write frontend tests for loyalty configuration and point display

- [x] 42. Implement outbound webhook management
  - [x] 42.1 Create migration 0046: outbound_webhooks and webhook_delivery_log tables
  - [x] 42.2 Create `app/modules/webhooks_v2/models.py` with OutboundWebhook and WebhookDeliveryLog SQLAlchemy models
  - [x] 42.3 Create `app/modules/webhooks_v2/service.py` with WebhookService: register(), update(), delete(), dispatch_event(), test_webhook(), get_delivery_log(), auto_disable_after_failures()
  - [x] 42.4 Create `app/modules/webhooks_v2/router.py` with webhook CRUD, test, and delivery log endpoints
  - [x] 42.5 Create `app/core/webhook_security.py` with sign_webhook_payload() and verify_webhook_signature() using HMAC-SHA256
  - [x] 42.6 Add Celery task `deliver_webhook` with retry logic: 5 retries with exponential backoff (1min, 5min, 15min, 1hr, 4hr)
  - [x] 42.7 Implement auto-disable after 50 consecutive failures with email notification to Org_Admin
  - [x] 42.8 Integrate webhook dispatch into all major events: invoice.created, invoice.paid, customer.created, job.status_changed, booking.created, payment.received, stock.low
  - [x] 42.9 Write property-based test: every subscribed event produces a delivery log entry (Property 15)
  - [x] 42.10 Write test: webhook with invalid signature is rejected
  - [x] 42.11 Write test: auto-disable triggers after 50 consecutive failures
  - [x] 42.12 Create `frontend/src/pages/settings/WebhookManagement.tsx` with webhook CRUD, test button, delivery log
  - [x] 42.13 Write frontend tests for webhook management

## Phase 10: Franchise, Branding, Assets & Customer Portal

- [x] 43. Implement franchise and multi-location support
  - [x] 43.1 Create migration 0047: locations, stock_transfers, franchise_groups tables
  - [x] 43.2 Create `app/modules/franchise/models.py` with Location, StockTransfer, FranchiseGroup SQLAlchemy models
  - [x] 43.3 Create `app/modules/franchise/service.py` with FranchiseService: CRUD locations, create_stock_transfer(), approve_transfer(), get_head_office_view(), get_franchise_dashboard(), clone_location_settings()
  - [x] 43.4 Create `app/modules/franchise/router.py` with location, stock transfer, and franchise dashboard endpoints
  - [x] 43.5 Implement location-scoped data queries: all list endpoints filter by user's assigned location when role is location_manager
  - [x] 43.6 Implement stock transfer workflow: request → approve → execute (creates stock movements at both locations)
  - [x] 43.7 Implement head-office aggregate view: combined revenue, outstanding, per-location comparison
  - [x] 43.8 Implement franchise dashboard: aggregate metrics across linked organisations (read-only)
  - [x] 43.9 Write test: location_manager can only see data for assigned locations
  - [x] 43.10 Write test: stock transfer creates movements at both source and destination
  - [x] 43.11 Write test: franchise_admin sees aggregate metrics but not individual records
  - [x] 43.12 Create `frontend/src/pages/franchise/LocationList.tsx` and `LocationDetail.tsx`
  - [x] 43.13 Create `frontend/src/pages/franchise/StockTransfers.tsx` with transfer request and approval
  - [x] 43.14 Create `frontend/src/pages/franchise/FranchiseDashboard.tsx` with aggregate metrics
  - [x] 43.15 Write frontend tests for multi-location management

- [x] 44. Implement global branding and "Powered By" system
  - [x] 44.1 Create migration 0048: platform_branding table with platform_name, logo_url, colours, URLs, auto_detect_domain
  - [x] 44.2 Create `app/modules/branding/models.py` with PlatformBranding SQLAlchemy model
  - [x] 44.3 Create `app/modules/branding/service.py` with BrandingService: get_branding(), update_branding(), get_powered_by_config(), is_white_label()
  - [x] 44.4 Create `app/modules/branding/router.py` with Global Admin branding endpoints
  - [x] 44.5 Update all PDF templates (invoice, quote, credit note, PO, progress claim, variation, receipt) to include "Powered by OraInvoice" footer below org branding
  - [x] 44.6 Update all email templates to include platform logo and signup link with UTM parameters (utm_source=invoice, utm_medium=email, utm_campaign=powered_by)
  - [x] 44.7 Implement white-label check: Enterprise orgs with white_label_enabled can remove Powered By footer
  - [x] 44.8 Implement domain auto-detection for white-label deployments
  - [x] 44.9 Write test: non-Enterprise orgs cannot remove Powered By footer
  - [x] 44.10 Write test: UTM parameters are correctly appended to signup links in emails
  - [x] 44.11 Write test: white-label orgs can replace Powered By with own branding
  - [x] 44.12 Write frontend tests for branding configuration

- [x] 45. Implement extended asset tracking
  - [x] 45.1 Create migration 0049: assets table with org_id, customer_id, asset_type, identifier, make, model, serial_number, custom_fields JSONB, carjam_data JSONB
  - [x] 45.2 Create `app/modules/assets/models.py` with Asset SQLAlchemy model
  - [x] 45.3 Create `app/modules/assets/service.py` with AssetService: CRUD, get_service_history(), link_to_job(), link_to_invoice(), carjam_lookup() (only for automotive trades)
  - [x] 45.4 Create `app/modules/assets/router.py` with asset endpoints
  - [x] 45.5 Implement custom fields per asset type: Org_Admin defines field name, type (text/number/date/dropdown), required flag
  - [x] 45.6 Implement asset type determination from trade category: vehicles for automotive, devices for IT, properties for building, etc.
  - [x] 45.7 Migrate existing vehicles table data to assets table for V1 orgs
  - [x] 45.8 Write test: Carjam integration only available for automotive trade categories
  - [x] 45.9 Write test: asset service history shows all linked invoices, jobs, quotes
  - [x] 45.10 Create `frontend/src/pages/assets/AssetList.tsx` and `AssetDetail.tsx` with trade-specific terminology
  - [x] 45.11 Write frontend tests for asset management

- [x] 46. Enhance customer portal
  - [x] 46.1 Update `app/modules/portal/` to add: quote acceptance view, asset/vehicle service history, booking management, loyalty balance display
  - [x] 46.2 Add quote acceptance endpoint to portal: display quote details, accept button that triggers quote status update
  - [x] 46.3 Add asset service history to portal: list all assets with linked invoices and jobs
  - [x] 46.4 Add booking capability to portal: show available slots, submit booking using same rules as public page
  - [x] 46.5 Add loyalty balance to portal: current points, current tier, points to next tier, transaction history
  - [x] 46.6 Apply org branding and Powered By footer to all portal pages
  - [x] 46.7 Support org's configured language for portal content
  - [x] 46.8 Write test: portal token authentication with configurable expiry
  - [x] 46.9 Write test: portal displays correct loyalty balance
  - [x] 46.10 Update `frontend/src/pages/portal/` with new portal sections
  - [x] 46.11 Write frontend tests for enhanced portal features

## Phase 11: Global Admin Console Enhancements

- [x] 47. Implement global admin analytics dashboard
  - [x] 47.1 Create `app/modules/admin/analytics_service.py` with GlobalAnalyticsService: get_platform_overview() (total orgs, active orgs, MRR, churn rate), get_trade_distribution() (org count per trade family/category), get_module_adoption() (heatmap of module enablement rates per trade), get_geographic_distribution() (org count per country/region), get_revenue_metrics() (MRR, ARR, ARPU, LTV by plan tier), get_conversion_funnel() (signup → wizard complete → first invoice → paid subscription)
  - [x] 47.2 Create `app/modules/admin/analytics_router.py` with Global Admin analytics endpoints: GET /api/v2/admin/analytics/overview, /trade-distribution, /module-adoption, /geographic, /revenue, /conversion-funnel
  - [x] 47.3 Implement time-series data aggregation with configurable periods (daily, weekly, monthly) using PostgreSQL date_trunc
  - [x] 47.4 Implement Redis caching for expensive analytics queries (5-minute TTL for overview, 1-hour TTL for historical)
  - [x] 47.5 Write test: analytics overview returns correct counts matching database state
  - [x] 47.6 Write test: module adoption heatmap correctly calculates percentages per trade category
  - [x] 47.7 Write test: conversion funnel correctly tracks each stage
  - [x] 47.8 Create `frontend/src/pages/admin/AnalyticsDashboard.tsx` with charts (trade distribution pie, module heatmap, geographic map, revenue line chart, conversion funnel)
  - [x] 47.9 Write frontend tests for analytics dashboard rendering

- [x] 48. Implement platform notification system
  - [x] 48.1 Create migration 0050: platform_notifications table with notification_type (maintenance, alert, feature, info), title, message, severity, target_type (all, country, trade_family, plan_tier, specific_orgs), target_value, scheduled_at, published_at, expires_at
  - [x] 48.2 Create `app/modules/admin/notifications_service.py` with PlatformNotificationService: create_notification(), publish_notification(), get_active_for_org() (filters by target matching), dismiss_for_user(), schedule_maintenance_window()
  - [x] 48.3 Create `app/modules/admin/notifications_router.py` with Global Admin CRUD endpoints and org-facing GET /api/v2/notifications/active endpoint
  - [x] 48.4 Implement targeted notification delivery: match org against target_type/target_value to determine visibility
  - [x] 48.5 Implement maintenance window scheduling: create notification with start/end times, display countdown banner in frontend
  - [x] 48.6 Add Celery task `publish_scheduled_notifications` that runs every minute to publish notifications at scheduled_at time
  - [x] 48.7 Write test: targeted notification only visible to matching orgs
  - [x] 48.8 Write test: maintenance window notification shows countdown and auto-expires
  - [x] 48.9 Create `frontend/src/components/common/PlatformNotificationBanner.tsx` with dismissible notification bar
  - [x] 48.10 Create `frontend/src/pages/admin/NotificationManager.tsx` with notification CRUD and targeting UI
  - [x] 48.11 Write frontend tests for notification display and dismissal

- [x] 49. Implement database migration tool for onboarding
  - [x] 49.1 Create `app/modules/admin/migration_service.py` with DataMigrationService: create_migration_job(), validate_source_data(), execute_full_migration(), execute_live_migration(), run_integrity_checks(), rollback_migration()
  - [x] 49.2 Create `app/modules/admin/migration_router.py` with Global Admin migration endpoints: POST /api/v2/admin/migrations (create job), POST /execute, GET /status, POST /rollback
  - [x] 49.3 Implement full migration mode: import all data from CSV/JSON source files into new org (customers, invoices, products, payments, jobs)
  - [x] 49.4 Implement live migration mode: dual-write period where data goes to both old and new system, with sync verification
  - [x] 49.5 Implement integrity checks: verify record counts, financial totals, customer references, invoice numbering continuity
  - [x] 49.6 Implement rollback: soft-delete all migrated records, restore org to pre-migration state
  - [x] 49.7 Add Celery task `execute_migration_job` for background processing with progress tracking
  - [x] 49.8 Write test: full migration imports all records with correct references
  - [x] 49.9 Write test: integrity check detects missing customer references
  - [x] 49.10 Write test: rollback removes all migrated data without affecting pre-existing records
  - [x] 49.11 Create `frontend/src/pages/admin/MigrationTool.tsx` with source upload, mapping, progress tracking, and integrity report
  - [x] 49.12 Write frontend tests for migration workflow

## Phase 12: Internationalisation, Security & Performance

- [x] 50. Implement internationalisation and localisation
  - [x] 50.1 Create `app/core/i18n.py` with I18nService: get_translations(), get_locale_config(), format_date(), format_number(), format_currency() using locale-specific rules
  - [x] 50.2 Create translation files directory `app/i18n/` with JSON files for 10 languages: en, mi (Māori), fr, es, de, pt, zh, ja, ar, hi
  - [x] 50.3 Create translation keys for all user-facing strings: invoice labels, email templates, portal text, error messages, setup wizard text
  - [x] 50.4 Implement RTL (right-to-left) support for Arabic: CSS direction, mirrored layouts, RTL-aware PDF generation
  - [x] 50.5 Implement locale-aware formatting: date formats (dd/MM/yyyy, MM/dd/yyyy, yyyy-MM-dd), number formats (1,000.00 vs 1.000,00), currency symbol placement
  - [x] 50.6 Create `app/modules/i18n/router.py` with endpoints: GET /api/v2/i18n/translations/{locale}, GET /api/v2/i18n/locales
  - [x] 50.7 Update invoice PDF generation to use org's configured language for all labels
  - [x] 50.8 Update email templates to use org's configured language
  - [x] 50.9 Write property-based test: for any supported locale, all required translation keys exist (no missing keys) (Property 18 extended)
  - [x] 50.10 Write test: RTL locale produces correctly mirrored PDF layout
  - [x] 50.11 Write test: currency formatting matches ISO 4217 rules for each supported currency
  - [x] 50.12 Create `frontend/src/i18n/` with i18next configuration and translation JSON files for all 10 languages
  - [x] 50.13 Create `frontend/src/contexts/LocaleContext.tsx` with LocaleProvider and useLocale() hook
  - [x] 50.14 Update all frontend components to use translation keys via useTranslation() hook
  - [x] 50.15 Implement language switcher in user settings
  - [x] 50.16 Write frontend tests for language switching and RTL layout

- [x] 51. Implement security enhancements
  - [x] 51.1 Create `app/middleware/security_headers.py` with SecurityHeadersMiddleware: Content-Security-Policy (strict), X-Content-Type-Options, X-Frame-Options, Strict-Transport-Security, Referrer-Policy, Permissions-Policy headers
  - [x] 51.2 Create `app/core/encryption.py` with EncryptionService: encrypt_field() and decrypt_field() using AES-256-GCM for PII fields (tax numbers, bank details, API keys) with key rotation support
  - [x] 51.3 Implement field-level encryption for sensitive columns: organisations.tax_number, api_credentials.api_secret, webhook.signing_secret, staff.bank_account_number
  - [x] 51.4 Create `app/middleware/rate_limiter.py` with RateLimiterMiddleware: configurable per-endpoint limits using Redis sliding window (default 100/min for API, 20/min for auth, 5/min for password reset)
  - [x] 51.5 Implement SOC 2 readiness audit logging: ensure all data access, modification, and deletion events are recorded in audit_log with user_id, ip_address, user_agent, action, resource_type, resource_id, changes JSONB
  - [x] 51.6 Create `app/core/pen_test_mode.py` with PenTestMode: when enabled via env var, adds response headers showing SQL query count, cache hit/miss ratio, and timing breakdown (disabled in production)
  - [x] 51.7 Implement CORS configuration per environment with strict origin allowlisting
  - [x] 51.8 Implement session management: configurable JWT expiry, refresh token rotation, concurrent session limits
  - [x] 51.9 Write test: CSP headers block inline scripts and external resources not in allowlist
  - [x] 51.10 Write test: encrypted fields are not readable in raw database queries
  - [x] 51.11 Write test: rate limiter returns 429 with Retry-After header when limit exceeded
  - [x] 51.12 Write test: pen test mode headers only present when PEN_TEST_MODE env var is set
  - [x] 51.13 Write test: refresh token rotation invalidates old refresh token

- [x] 52. Implement storage and performance management
  - [x] 52.1 Create `app/core/storage_manager.py` with StorageManager: check_quota(), increment_usage(), decrement_usage(), get_usage_report(), enforce_quota() (reject uploads when quota exceeded)
  - [x] 52.2 Implement storage quota enforcement: check on file upload (attachments, logos, receipts, compliance docs), return 413 with usage details when exceeded
  - [x] 52.3 Create `app/core/query_optimizer.py` with QueryOptimizer: add_row_limit() (configurable max rows per query, default 10000), add_query_timeout() (configurable per-endpoint, default 30s), log_slow_queries() (threshold 1s)
  - [x] 52.4 Implement connection pooling configuration: min 5, max 20 connections per worker, overflow 10, pool recycle 3600s, pool pre-ping enabled
  - [x] 52.5 Create `app/core/job_queue.py` with JobPriorityQueue: high priority (payments, POS), medium priority (invoices, sync), low priority (reports, analytics), with configurable worker allocation
  - [x] 52.6 Implement Redis cache warming on app startup for frequently accessed data: trade categories, module registry, compliance profiles, feature flags
  - [x] 52.7 Add database indexes for common query patterns: invoices by org+status+date, customers by org+search, products by org+sku, jobs by org+status
  - [x] 52.8 Write test: file upload rejected when storage quota exceeded with correct error message
  - [x] 52.9 Write test: query timeout kills long-running queries and returns 504
  - [x] 52.10 Write test: job priority queue processes high-priority tasks before low-priority
  - [x] 52.11 Write test: slow query logging captures queries exceeding threshold

## Phase 13: V1 Organisation Data Migration

- [x] 53. Implement V1 organisation data migration
  - [x] 53.1 Create migration 0051: Add default values for new organisation columns (trade_category_id defaults to 'general-automotive', country_code defaults to 'NZ', base_currency defaults to 'NZD', locale defaults to 'en-NZ', tax_label defaults to 'GST', default_tax_rate defaults to 15.0, tax_inclusive_default defaults to true, date_format defaults to 'dd/MM/yyyy', timezone defaults to 'Pacific/Auckland')
  - [x] 53.2 Create `app/modules/migration/v1_migration_service.py` with V1MigrationService: migrate_org() that backfills all new columns for existing V1 orgs, enable_core_modules() that enables invoicing, customers, vehicles, bookings, notifications modules for all V1 orgs
  - [x] 53.3 Create data migration script `scripts/migrate_v1_orgs.py` that: queries all existing orgs, applies NZ defaults, enables V1 modules, sets setup_wizard_state to 'completed', logs migration results
  - [x] 53.4 Implement dual-write period: new V1 API endpoints write to both old and new column structures during transition
  - [x] 53.5 Implement integrity checks: verify all V1 orgs have valid trade_category_id, compliance_profile_id, and at least core modules enabled after migration
  - [x] 53.6 Create rollback script `scripts/rollback_v1_migration.py` that reverts column values to NULL for failed migrations
  - [x] 53.7 Write property-based test: for any V1 org, migration produces valid V2 org with all required fields populated (Property 2)
  - [x] 53.8 Write test: migrated V1 org can access all previously available features without re-setup
  - [x] 53.9 Write test: V1 API endpoints continue to work identically after migration
  - [x] 53.10 Write test: rollback script correctly reverts migration for specified orgs

## Phase 14: Enhanced Reporting

- [x] 54. Implement enhanced reporting system
  - [x] 54.1 Create `app/modules/reports_v2/service.py` with ReportService: generate_report() dispatcher that routes to specific report generators based on report_type
  - [x] 54.2 Implement inventory reports: stock valuation (cost × quantity per product), stock movement summary (by period), low stock alert report, dead stock report (no movement in X days)
  - [x] 54.3 Implement job reports: job profitability (revenue vs labour + materials + expenses), jobs by status summary, average completion time by trade category, staff utilisation report
  - [x] 54.4 Implement project reports: project profitability (contract value vs costs), progress claim summary, variation register, retention summary
  - [x] 54.5 Implement POS reports: daily sales summary (by payment method, by product category), session reconciliation (expected vs actual cash), hourly sales heatmap
  - [x] 54.6 Implement hospitality reports: table turnover rate, average order value, kitchen preparation times, tip summary by staff
  - [x] 54.7 Implement multi-currency consolidation: all financial reports convert to base currency using locked exchange rates for historical data and current rates for unrealised amounts
  - [x] 54.8 Implement multi-location filtering: all reports accept optional location_id filter, franchise_admin sees aggregate across all locations
  - [x] 54.9 Implement scheduled reports: create report_schedules table, add Celery task `generate_scheduled_reports` that runs daily, generates configured reports, emails PDF to recipients
  - [x] 54.10 Implement tax return reports: GST return (NZ), BAS (AU), VAT return (UK) with correct box mappings per compliance profile
  - [x] 54.11 Create `app/modules/reports_v2/router.py` with report endpoints: GET /api/v2/reports/{report_type} with date range, location, currency filters, POST /api/v2/reports/schedule
  - [x] 54.12 Write property-based test: for any date range, sum of invoice line items in report equals sum of individual invoice totals (Property 4)
  - [x] 54.13 Write test: multi-currency report correctly converts all amounts to base currency
  - [x] 54.14 Write test: location-filtered report excludes data from other locations
  - [x] 54.15 Write test: scheduled report generates and emails PDF on configured schedule
  - [x] 54.16 Write test: GST return report matches manual calculation for sample data
  - [x] 54.17 Create `frontend/src/pages/reports/ReportBuilder.tsx` with report type selector, date range picker, location filter, currency selector, export buttons (PDF, CSV, Excel)
  - [x] 54.18 Create report-specific frontend pages: InventoryReport, JobReport, ProjectReport, POSReport, HospitalityReport, TaxReturn
  - [x] 54.19 Create `frontend/src/pages/reports/ScheduledReports.tsx` with schedule management
  - [x] 54.20 Write frontend tests for report generation and filtering

## Phase 15: Comprehensive Testing Suite

- [x] 55. Implement comprehensive property-based testing suite
  - [x] 55.1 Create `tests/properties/conftest.py` with shared Hypothesis strategies: org_strategy (generates valid org with random trade category, country, modules), invoice_strategy (generates valid invoice with random line items, tax, currency), customer_strategy, product_strategy, job_strategy
  - [x] 55.2 Create `tests/properties/test_invoice_properties.py` with properties: P4 (line item sum equals total), P8 (tax-inclusive total = subtotal + tax), P14 (locked exchange rate), P16 (idempotency)
  - [x] 55.3 Create `tests/properties/test_inventory_properties.py` with properties: P3 (stock movement sum equals current quantity), P7 (pricing rule determinism)
  - [x] 55.4 Create `tests/properties/test_job_properties.py` with properties: P5 (valid status transitions), P6 (quote-invoice linkage)
  - [x] 55.5 Create `tests/properties/test_module_properties.py` with properties: P1 (disabled module returns 403), P10 (dependency enforcement)
  - [x] 55.6 Create `tests/properties/test_construction_properties.py` with properties: P11 (cumulative claims ≤ contract), P12 (revised contract = original + variations), P20 (retention releases ≤ withheld)
  - [x] 55.7 Create `tests/properties/test_loyalty_properties.py` with property: P13 (balance = sum of transactions)
  - [x] 55.8 Create `tests/properties/test_webhook_properties.py` with property: P15 (every event produces delivery log)
  - [x] 55.9 Create `tests/properties/test_pos_properties.py` with property: P9 (offline transactions produce success or conflict)
  - [x] 55.10 Create `tests/properties/test_feature_flag_properties.py` with property: P19 (wizard idempotency), flag evaluation determinism
  - [x] 55.11 Create `tests/properties/test_terminology_properties.py` with property: P18 (all default keys present)
  - [x] 55.12 Create `tests/properties/test_migration_properties.py` with property: P2 (V1 migration produces valid V2 org)
  - [x] 55.13 Create `tests/properties/test_rbac_properties.py` with property: P17 (location-scoped access)
  - [x] 55.14 Run full property-based test suite and verify all 20 properties pass

- [x] 56. Implement end-to-end integration testing
  - [x] 56.1 Create `tests/integration/conftest.py` with test database setup, test org factory, authenticated client fixtures
  - [x] 56.2 Create `tests/integration/test_onboarding_flow.py`: complete setup wizard → verify org configured → verify modules enabled → verify terminology applied → create first invoice → verify PDF uses correct branding and terminology
  - [x] 56.3 Create `tests/integration/test_invoice_lifecycle.py`: create customer → create product → create draft invoice → add line items → issue → send email → record payment → verify stock decremented → verify loyalty points awarded → verify webhook dispatched
  - [x] 56.4 Create `tests/integration/test_job_to_invoice_flow.py`: create job → assign staff → log time → add expenses → add materials → convert to invoice → verify all items present → issue → pay
  - [x] 56.5 Create `tests/integration/test_quote_to_invoice_flow.py`: create quote → send to customer → customer accepts via portal → convert to invoice → verify linkage
  - [x] 56.6 Create `tests/integration/test_pos_flow.py`: open session → complete transactions → process offline sync → close session → verify reconciliation
  - [x] 56.7 Create `tests/integration/test_construction_flow.py`: create project → add variations → submit progress claims → verify cumulative amounts → release retention
  - [x] 56.8 Create `tests/integration/test_multi_location_flow.py`: create locations → assign staff → create stock transfer → verify location-scoped queries
  - [x] 56.9 Create `tests/integration/test_ecommerce_flow.py`: connect WooCommerce → receive webhook → verify invoice created → sync products outbound
  - [x] 56.10 Create `tests/integration/test_multi_currency_flow.py`: enable currencies → create invoice in foreign currency → record payment → verify exchange gain/loss
  - [x] 56.11 Create `tests/integration/test_v1_compatibility.py`: migrate V1 org → verify all V1 endpoints still work → verify V2 endpoints accessible → verify no data loss
  - [x] 56.12 Run full integration test suite and verify all tests pass
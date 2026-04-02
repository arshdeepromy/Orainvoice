# Implementation Plan: Customer Claims & Returns

## Overview

This implementation plan covers the Customer Claims & Returns module, which provides a centralised system for tracking customer complaints, warranty issues, and managing resolution processes. The module integrates with existing Payment, Invoice, Stock, and Job Card services to orchestrate downstream actions.

## Tasks

- [x] 1. Database migration and models
  - [x] 1.1 Create Alembic migration for customer_claims and claim_actions tables
    - Create `customer_claims` table with all columns per design (id, org_id, branch_id, customer_id, invoice_id, job_card_id, line_item_ids, claim_type, status, description, resolution fields, cost tracking fields, audit fields)
    - Create `claim_actions` table for timeline tracking
    - Add all indexes (idx_claims_org, idx_claims_customer, idx_claims_status, idx_claims_branch, idx_claims_created, idx_claim_actions_claim, idx_claim_actions_performed)
    - Add CHECK constraints for claim_type, status, resolution_type, and source_reference
    - _Requirements: 1.1, 1.2, 2.1, 3.1, 5.5_

  - [x] 1.2 Create SQLAlchemy models for CustomerClaim and ClaimAction
    - Implement `CustomerClaim` model with all mapped columns and relationships (organisation, branch, customer, invoice, job_card, warranty_job, refund, credit_note, actions)
    - Implement `ClaimAction` model with relationships (claim, performed_by_user)
    - Add enums: ClaimType, ClaimStatus, ResolutionType
    - Define VALID_CLAIM_TRANSITIONS dict for workflow validation
    - _Requirements: 1.1, 2.1, 3.1_

- [x] 2. Pydantic schemas
  - [x] 2.1 Create request/response schemas for claims
    - `ClaimCreateRequest` with customer_id, claim_type, description, optional invoice_id, job_card_id, line_item_ids, branch_id
    - `ClaimStatusUpdateRequest` with new_status and optional notes
    - `ClaimResolveRequest` with resolution_type, optional resolution_amount, resolution_notes, return_stock_item_ids
    - `ClaimNoteRequest` for adding internal notes
    - `ClaimResponse` with all claim fields including nested customer, invoice, job_card info
    - `ClaimListResponse` with items list and total count
    - `ClaimTimelineResponse` for action history
    - `CostBreakdownSchema` for cost tracking
    - `CustomerClaimsSummaryResponse` with total_claims, open_claims, total_cost_to_business
    - _Requirements: 1.1, 1.5, 2.1, 3.1, 5.5, 7.1, 7.2, 9.2_

- [x] 3. Claim service with CRUD operations
  - [x] 3.1 Implement create_claim function
    - Validate customer_id exists in organisation
    - Validate at least one source reference (invoice_id, job_card_id, or line_item_id) is provided
    - Validate referenced invoice/job_card belongs to same organisation
    - Inherit branch_id from linked invoice/job_card if not explicitly provided
    - Create claim with status "open"
    - Record created_by and created_at
    - Write audit log entry with action "claim.created"
    - Create initial ClaimAction record
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 11.4, 12.1_

  - [x] 3.2 Write property test for claim creation data integrity
    - **Property 1: Claim Creation Data Integrity**
    - **Validates: Requirements 1.1, 1.6, 1.7**

  - [x] 3.3 Write property test for source reference validation
    - **Property 2: Source Reference Validation**
    - **Validates: Requirements 1.3, 1.8**

  - [x] 3.4 Write property test for claim type validation
    - **Property 3: Claim Type Validation**
    - **Validates: Requirements 1.5**

  - [x] 3.5 Implement update_claim_status function
    - Validate status transition against VALID_CLAIM_TRANSITIONS
    - Return validation error with allowed transitions if invalid
    - Record status change timestamp and user
    - Create ClaimAction record with action_type "status_change"
    - Write audit log entry with action "claim.status_changed"
    - _Requirements: 2.1, 2.2, 2.3, 2.6, 2.7, 12.2_

  - [x] 3.6 Write property test for status workflow validity
    - **Property 4: Status Workflow Validity**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.6**

  - [x] 3.7 Write property test for approved to resolved transition guard
    - **Property 5: Approved to Resolved Transition Guard**
    - **Validates: Requirements 2.4**

  - [x] 3.8 Write property test for status change timeline recording
    - **Property 16: Status Change Timeline Recording**
    - **Validates: Requirements 2.7, 7.2**

  - [x] 3.9 Implement get_claim function
    - Return claim details with customer info, original transaction, claim type, status, description, resolution
    - Include timeline of all status changes with timestamps and user names
    - Include links to related entities (invoice, job_card, credit_note, refund, stock_movements, warranty_job)
    - Include cost_breakdown and total cost_to_business
    - Include attached notes/internal comments
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 3.10 Implement list_claims function
    - Return paginated claim lists with total count
    - Support filtering by status, claim_type, customer_id, date_range, branch_id
    - Support searching by customer name, invoice number, claim description
    - Order by created_at descending by default
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 3.11 Write property test for pagination correctness
    - **Property 11: Pagination Correctness**
    - **Validates: Requirements 6.1**

  - [x] 3.12 Write property test for filtering correctness
    - **Property 12: Filtering Correctness**
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.5**

  - [x] 3.13 Implement get_customer_claims_summary function
    - Return all claims for a specific customer_id
    - Return summary statistics: total_claims, open_claims, total_cost_to_business
    - Order customer claims by created_at descending
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 3.14 Write property test for customer claims summary accuracy
    - **Property 13: Customer Claims Summary Accuracy**
    - **Validates: Requirements 9.1, 9.2, 9.3**

  - [x] 3.15 Write property test for branch inheritance
    - **Property 14: Branch Inheritance**
    - **Validates: Requirements 11.4**

  - [x] 3.16 Write unit tests for claim service
    - Test valid claim creation with all field combinations
    - Test missing required fields validation
    - Test invalid reference validation
    - Test all valid status transitions
    - Test all invalid status transitions
    - Test branch scoping and inheritance
    - _Requirements: 1.1-1.8, 2.1-2.7, 6.1-6.5, 9.1-9.3, 11.1-11.4_

- [x] 4. Checkpoint - Ensure claim service tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Resolution engine with downstream action orchestration
  - [x] 5.1 Implement ResolutionEngine.execute_resolution function
    - Validate claim is in "approved" status before resolution
    - Dispatch to appropriate resolution handler based on resolution_type
    - Store references to all created downstream entities
    - Update claim status to "resolved"
    - Write audit log entry with action "claim.resolution_action"
    - _Requirements: 2.4, 3.1, 3.8, 12.3_

  - [x] 5.2 Implement _process_full_refund handler
    - Call PaymentService.process_refund for full invoice amount
    - Store refund_id on claim
    - _Requirements: 3.2_

  - [x] 5.3 Implement _process_partial_refund handler
    - Call PaymentService.process_refund for specified resolution_amount
    - Store refund_id on claim
    - _Requirements: 3.3_

  - [x] 5.4 Implement _process_credit_note handler
    - Call InvoiceService.create_credit_note linked to original invoice
    - Store credit_note_id on claim
    - _Requirements: 3.4_

  - [x] 5.5 Implement _process_exchange handler
    - Create StockMovement with movement_type "return", reference_type "claim", reference_id = claim.id
    - Check if catalogue entry is archived or has zero resale value
    - Flag movement as write-off if applicable
    - Store return_movement_ids on claim
    - Optionally create new invoice for replacement item
    - _Requirements: 3.5, 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 5.6 Implement _process_redo_service handler
    - Create JobCard with zero charge linked to original claim
    - Store warranty_job_id on claim
    - _Requirements: 3.6_

  - [x] 5.7 Write property test for resolution action dispatch
    - **Property 6: Resolution Action Dispatch**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

  - [x] 5.8 Write property test for downstream entity reference storage
    - **Property 7: Downstream Entity Reference Storage**
    - **Validates: Requirements 3.8**

  - [x] 5.9 Write property test for stock return movement linking
    - **Property 8: Stock Return Movement Linking**
    - **Validates: Requirements 4.1, 4.2**

  - [x] 5.10 Write property test for write-off flagging
    - **Property 9: Write-off Flagging**
    - **Validates: Requirements 4.3, 4.4, 4.5, 4.6**

  - [x] 5.11 Write unit tests for resolution engine
    - Test each resolution type triggers correct downstream action
    - Test downstream action verification with mocked services
    - Test error handling and rollback on service failures
    - _Requirements: 3.1-3.8, 4.1-4.6_

- [x] 6. Cost tracker
  - [x] 6.1 Implement CostTracker.calculate_claim_cost function
    - Calculate labour_cost from warranty job time entries (hours × hourly_rate)
    - Calculate parts_cost from warranty job parts (quantity × cost_price)
    - Calculate write_off_cost from flagged stock returns
    - Return CostBreakdown with all components
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 6.2 Implement CostTracker.update_claim_cost function
    - Update claim's cost_breakdown JSON field with itemised costs
    - Update cost_to_business as sum of all cost components
    - Create ClaimAction record with action_type "cost_updated"
    - _Requirements: 5.5, 5.6_

  - [x] 6.3 Implement update_claim_cost_on_job_completion hook
    - Called when warranty job card is completed
    - Find claim linked to warranty job
    - Calculate and update labour and parts costs
    - _Requirements: 5.2, 5.3, 5.6_

  - [x] 6.4 Write property test for cost calculation accuracy
    - **Property 10: Cost Calculation Accuracy**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

  - [x] 6.5 Write unit tests for cost tracker
    - Test labour cost calculation from time entries
    - Test parts cost calculation from job card items
    - Test write-off cost calculation
    - Test cost_to_business equals sum of components
    - _Requirements: 5.1-5.6_

- [x] 7. Checkpoint - Ensure resolution engine and cost tracker tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. API router with all endpoints
  - [x] 8.1 Implement POST /api/claims endpoint
    - Create new claim with validation
    - Pre-populate from invoice if invoice_id provided
    - Support line item selection
    - Return created claim with 201 status
    - _Requirements: 1.1-1.8, 8.1, 8.2, 8.3, 8.4_

  - [x] 8.2 Implement GET /api/claims endpoint
    - List claims with pagination
    - Support all filter query params (status, claim_type, customer_id, date_from, date_to, branch_id, search)
    - Apply branch context filtering for non-admin users
    - _Requirements: 6.1-6.5, 11.2, 11.3_

  - [x] 8.3 Implement GET /api/claims/{id} endpoint
    - Return full claim details with timeline and related entities
    - _Requirements: 7.1-7.5_

  - [x] 8.4 Implement PATCH /api/claims/{id}/status endpoint
    - Update claim status with workflow validation
    - _Requirements: 2.1-2.7_

  - [x] 8.5 Implement POST /api/claims/{id}/resolve endpoint
    - Apply resolution and trigger downstream actions
    - _Requirements: 2.4, 2.5, 3.1-3.8_

  - [x] 8.6 Implement POST /api/claims/{id}/notes endpoint
    - Add internal note to claim
    - Create ClaimAction record with action_type "note_added"
    - _Requirements: 7.5_

  - [x] 8.7 Implement GET /api/customers/{id}/claims endpoint
    - Return customer claims with summary statistics
    - _Requirements: 9.1-9.3_

  - [x] 8.8 Write property test for audit log completeness
    - **Property 15: Audit Log Completeness**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**

  - [x] 8.9 Write unit tests for API router
    - Test all endpoints with valid requests
    - Test validation error responses
    - Test authentication and authorization
    - Test branch scoping
    - _Requirements: 1.1-1.8, 2.1-2.7, 3.1-3.8, 6.1-6.5, 7.1-7.5, 8.1-8.4, 9.1-9.3, 11.1-11.4, 12.1-12.5_

- [x] 9. Reports endpoints
  - [x] 9.1 Implement GET /api/claims/reports/by-period endpoint
    - Return claim_count, total_cost, average_resolution_time grouped by period
    - Support date range filtering
    - Support branch_id filtering
    - _Requirements: 10.1, 10.5, 10.6_

  - [x] 9.2 Implement GET /api/claims/reports/cost-overhead endpoint
    - Return total_refunds, total_credit_notes, total_write_offs, total_labour_cost
    - Support date range and branch filtering
    - _Requirements: 10.2, 10.5, 10.6_

  - [x] 9.3 Implement GET /api/claims/reports/supplier-quality endpoint
    - Return parts with highest return rates
    - Support date range and branch filtering
    - _Requirements: 10.3, 10.5, 10.6_

  - [x] 9.4 Implement GET /api/claims/reports/service-quality endpoint
    - Return technicians with most redo claims
    - Support date range and branch filtering
    - _Requirements: 10.4, 10.5, 10.6_

  - [x] 9.5 Write unit tests for reports endpoints
    - Test period aggregation calculations
    - Test cost overhead calculations
    - Test quality metrics calculations
    - Test date range and branch filtering
    - _Requirements: 10.1-10.6_

- [x] 10. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 11. Frontend - Claims list page
  - [x] 11.1 Create ClaimsList.tsx page component
    - Display paginated table of claims with columns: ID, Customer, Type, Status, Created, Cost
    - Implement status badge styling (open=blue, investigating=yellow, approved=green, rejected=red, resolved=gray)
    - Add filter controls for status, claim_type, date range, search
    - Add "New Claim" button linking to claim creation
    - Implement row click navigation to claim detail
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 11.2 Implement claims list API integration
    - Create useClaimsList hook with react-query
    - Handle pagination state
    - Handle filter state
    - Handle loading and error states
    - _Requirements: 6.1-6.5_

  - [x] 11.3 Write unit tests for ClaimsList component
    - Test rendering with mock data
    - Test filter interactions
    - Test pagination
    - Test navigation to detail
    - _Requirements: 6.1-6.5_

- [x] 12. Frontend - Claim detail page
  - [x] 12.1 Create ClaimDetail.tsx page component
    - Display claim header with status badge and customer info
    - Display original transaction section (invoice/job card link)
    - Display description and claim type
    - Display resolution section (if resolved)
    - Display cost breakdown section
    - Display timeline of all actions
    - Display related entities section with links
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 12.2 Implement status transition actions
    - Add "Start Investigation" button (open → investigating)
    - Add "Approve" and "Reject" buttons (investigating → approved/rejected)
    - Add "Resolve" button opening resolution modal (approved → resolved)
    - Disable invalid transitions
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 12.3 Create ClaimResolveModal component
    - Resolution type selector (full_refund, partial_refund, credit_note, exchange, redo_service, no_action)
    - Conditional amount input for partial_refund
    - Conditional stock item selector for exchange
    - Resolution notes textarea
    - Submit and cancel buttons
    - _Requirements: 3.1-3.7_

  - [x] 12.4 Create ClaimNoteModal component
    - Textarea for internal note
    - Submit and cancel buttons
    - _Requirements: 7.5_

  - [x] 12.5 Implement claim detail API integration
    - Create useClaimDetail hook with react-query
    - Create useUpdateClaimStatus mutation
    - Create useResolveClaim mutation
    - Create useAddClaimNote mutation
    - Handle loading and error states
    - _Requirements: 2.1-2.7, 3.1-3.8, 7.1-7.5_

  - [x] 12.6 Write unit tests for ClaimDetail component
    - Test rendering with mock claim data
    - Test status transition button states
    - Test resolution modal flow
    - Test note addition flow
    - _Requirements: 2.1-2.7, 3.1-3.8, 7.1-7.5_

- [x] 13. Frontend - Claim creation form
  - [x] 13.1 Create ClaimCreateForm component
    - Customer selector (searchable dropdown)
    - Claim type selector
    - Description textarea
    - Optional invoice selector (filtered by customer)
    - Optional job card selector (filtered by customer)
    - Optional line item multi-select (when invoice selected)
    - Submit and cancel buttons
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 8.2, 8.3_

  - [x] 13.2 Implement claim creation API integration
    - Create useCreateClaim mutation
    - Handle validation errors
    - Navigate to claim detail on success
    - _Requirements: 1.1-1.8_

  - [x] 13.3 Write unit tests for ClaimCreateForm component
    - Test form validation
    - Test customer selection
    - Test invoice/job card selection
    - Test line item selection
    - Test submission
    - _Requirements: 1.1-1.8, 8.1-8.4_

- [x] 14. Checkpoint - Ensure frontend claims pages tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Frontend - Invoice integration (Report Issue button)
  - [x] 15.1 Add "Report Issue" button to InvoiceDetail page
    - Add button in invoice actions section
    - Button opens claim creation with pre-populated invoice_id and customer_id
    - _Requirements: 8.1_

  - [x] 15.2 Implement line item selection for claim from invoice
    - Display invoice line items as checkboxes
    - Pre-populate claim_type based on selected line item types (part → defect, service → service_redo)
    - _Requirements: 8.2, 8.3, 8.4_

  - [x] 15.3 Write unit tests for Report Issue integration
    - Test button visibility
    - Test pre-population of claim fields
    - Test line item selection
    - Test claim type inference
    - _Requirements: 8.1-8.4_

- [x] 16. Frontend - Customer profile claims tab
  - [x] 16.1 Add Claims tab to CustomerProfile page
    - Display claims list filtered by customer_id
    - Display summary statistics (total_claims, open_claims, total_cost_to_business)
    - Add "New Claim" button pre-populated with customer_id
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 16.2 Implement customer claims API integration
    - Create useCustomerClaims hook
    - Fetch claims and summary for customer
    - _Requirements: 9.1-9.3_

  - [x] 16.3 Write unit tests for customer claims tab
    - Test summary statistics display
    - Test claims list rendering
    - Test new claim button
    - _Requirements: 9.1-9.3_

- [x] 17. Frontend - Claims reports page
  - [x] 17.1 Create ClaimsReports.tsx page component
    - Tab navigation for different report types
    - Date range picker for filtering
    - Branch selector for multi-branch orgs
    - _Requirements: 10.5, 10.6_

  - [x] 17.2 Implement claims-by-period report view
    - Display chart/table with claim_count, total_cost, average_resolution_time
    - Group by day/week/month based on date range
    - _Requirements: 10.1_

  - [x] 17.3 Implement cost-overhead report view
    - Display total_refunds, total_credit_notes, total_write_offs, total_labour_cost
    - Display as summary cards and/or breakdown chart
    - _Requirements: 10.2_

  - [x] 17.4 Implement supplier-quality report view
    - Display table of parts with highest return rates
    - Include part name, return count, return rate percentage
    - _Requirements: 10.3_

  - [x] 17.5 Implement service-quality report view
    - Display table of technicians with most redo claims
    - Include technician name, redo count, percentage of their jobs
    - _Requirements: 10.4_

  - [x] 17.6 Implement reports API integration
    - Create useClaimsByPeriodReport hook
    - Create useCostOverheadReport hook
    - Create useSupplierQualityReport hook
    - Create useServiceQualityReport hook
    - _Requirements: 10.1-10.6_

  - [x] 17.7 Write unit tests for ClaimsReports component
    - Test each report view rendering
    - Test date range filtering
    - Test branch filtering
    - _Requirements: 10.1-10.6_

- [x] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Default Main Branch fix
  - [x] 19.1 Update organisation creation to auto-create "Main" branch
    - Modify organisation service to create a default branch named "Main" with is_active=true and is_default=true when a new org is created
    - _Requirements: 14.1, 14.2_

  - [x] 19.2 Update demo seed script to ensure "Main" branch exists
    - Add logic to `scripts/seed_demo_org_admin.py` to check if demo org has a "Main" branch
    - If no "Main" branch exists, create one for the demo org
    - Assign all existing branchless entities (invoices, job_cards, etc.) to the Main branch
    - _Requirements: 14.3, 14.4_

  - [x] 19.3 Verify branch switcher shows Main branch
    - Ensure the frontend BranchContext/BranchSelector shows "Main" branch and "All Branches" options
    - When a second branch is created, both branches appear in the dropdown
    - _Requirements: 14.5, 14.6, 14.7_

- [x] 20. Playwright E2E tests
  - [x] 20.1 Create Playwright test setup with demo account login
    - Create `tests/e2e/frontend/claims.spec.ts`
    - Implement login helper that authenticates via frontend login form using demo@orainvoice.com / demo123
    - Verify login succeeds and dashboard loads
    - _Requirements: 13.1_

  - [x] 20.2 Write E2E test: Create claim from Claims list page
    - Navigate to Claims list page
    - Click "New Claim" button
    - Fill in customer, claim type, description, invoice
    - Submit and verify claim appears in list with status "open"
    - _Requirements: 13.2_

  - [x] 20.3 Write E2E test: Full approval workflow (full_refund)
    - Create a claim
    - Click "Start Investigation" → verify status changes to "investigating"
    - Click "Approve" → verify status changes to "approved"
    - Click "Resolve" → select "Full Refund" → submit → verify status "resolved"
    - Verify refund was created via claim detail linked entities
    - _Requirements: 13.3, 13.11_

  - [x] 20.4 Write E2E test: Rejection workflow (no_action)
    - Create a claim → investigate → reject → resolve with no_action
    - Verify each status transition in the UI
    - _Requirements: 13.4_

  - [x] 20.5 Write E2E test: Credit note resolution
    - Create claim → investigate → approve → resolve with credit_note
    - Verify credit note is created and linked in claim detail
    - _Requirements: 13.5_

  - [x] 20.6 Write E2E test: Redo service resolution
    - Create claim → investigate → approve → resolve with redo_service
    - Verify warranty job card is created and linked
    - _Requirements: 13.6_

  - [x] 20.7 Write E2E test: Exchange resolution
    - Create claim → investigate → approve → resolve with exchange
    - Verify stock return movements are created
    - _Requirements: 13.7_

  - [x] 20.8 Write E2E test: Report Issue from InvoiceDetail
    - Navigate to an invoice detail page
    - Click "Report Issue" button
    - Verify claim form is pre-populated with invoice_id and customer_id
    - Submit and verify claim is created
    - _Requirements: 13.8_

  - [x] 20.9 Write E2E test: Customer profile Claims tab
    - Navigate to a customer profile
    - Click Claims tab
    - Verify summary statistics (total_claims, open_claims, total_cost_to_business) are displayed
    - _Requirements: 13.9_

  - [x] 20.10 Write E2E test: Add internal note to claim
    - Open a claim detail page
    - Click "Add Note" → enter note text → submit
    - Verify note appears in the timeline
    - _Requirements: 13.10_

- [x] 21. Rebuild containers and git push
  - [x] 21.1 Rebuild Docker containers with all changes
    - Run `docker compose build app --no-cache`
    - Run `docker compose up -d app`
    - Verify app starts successfully and migrations run
    - _Requirements: 13.12_

  - [x] 21.2 Git commit and push all changes
    - Stage all new and modified files
    - Commit with descriptive message
    - Push to remote
    - _Requirements: 13.12_

- [x] 22. Final E2E checkpoint
  - Run all Playwright E2E tests against the running containers
  - Verify all tests pass end-to-end
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Frontend tasks assume React with TypeScript and react-query for data fetching
- Backend uses Python with FastAPI, SQLAlchemy, and Hypothesis for property testing

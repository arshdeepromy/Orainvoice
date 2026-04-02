# Requirements Document

## Introduction

The Customer Claims & Returns module provides a centralised system for tracking customer complaints, warranty issues, faulty products/services, and managing the resolution process. This module ties together the customer complaint, original invoice/job being disputed, resolution decision, and all downstream actions (refunds, credit notes, stock returns, warranty jobs). It also tracks business costs associated with claims, including write-offs for archived or zero-stock items.

## Glossary

- **Claim**: A customer-initiated complaint or dispute record linked to an invoice, job card, or specific line item
- **Claim_Service**: The backend service responsible for claim lifecycle management and resolution orchestration
- **Resolution_Engine**: The component that triggers downstream actions based on resolution type
- **Cost_Tracker**: The component that calculates and records business costs for each claim
- **Stock_Service**: Existing service for stock movements (increment_stock with movement_type="return")
- **Payment_Service**: Existing service for refunds (process_refund)
- **Credit_Note_Service**: Existing service for creating credit notes
- **Job_Card_Service**: Existing service for creating job cards
- **Write_Off**: A stock return where the item cannot be resold (archived catalogue entry or zero stock value)

## Requirements

### Requirement 1: Claim Creation

**User Story:** As a staff member, I want to create a claim linked to a customer and their original transaction, so that I can formally track and resolve their complaint.

#### Acceptance Criteria

1. WHEN a staff member submits a new claim, THE Claim_Service SHALL create a claim record with status "open"
2. THE Claim_Service SHALL require a customer_id and at least one of: invoice_id, job_card_id, or line_item_id
3. THE Claim_Service SHALL validate that the referenced invoice, job card, or line item belongs to the same organisation
4. WHEN a branch_id is provided, THE Claim_Service SHALL scope the claim to that branch
5. THE Claim_Service SHALL accept a claim_type from: warranty, defect, service_redo, exchange, refund_request
6. THE Claim_Service SHALL store a description field for the customer's complaint details
7. THE Claim_Service SHALL record the created_by user and created_at timestamp
8. IF the referenced invoice or job card does not exist, THEN THE Claim_Service SHALL return a validation error

### Requirement 2: Claim Status Workflow

**User Story:** As a staff member, I want claims to follow a defined workflow, so that I can track progress and ensure proper review before resolution.

#### Acceptance Criteria

1. THE Claim_Service SHALL enforce the status workflow: open → investigating → approved/rejected → resolved
2. WHEN a claim is in "open" status, THE Claim_Service SHALL allow transition to "investigating"
3. WHEN a claim is in "investigating" status, THE Claim_Service SHALL allow transition to "approved" or "rejected"
4. WHEN a claim is in "approved" status, THE Claim_Service SHALL allow transition to "resolved" only after resolution actions are completed
5. WHEN a claim is in "rejected" status, THE Claim_Service SHALL allow transition to "resolved" with resolution_type "no_action"
6. IF an invalid status transition is attempted, THEN THE Claim_Service SHALL return a validation error with the allowed transitions
7. THE Claim_Service SHALL record status change timestamps and the user who made the change

### Requirement 3: Resolution Types and Actions

**User Story:** As a staff member, I want to select a resolution type that triggers the appropriate downstream actions, so that refunds, credit notes, and stock returns are handled automatically.

#### Acceptance Criteria

1. THE Claim_Service SHALL support resolution types: full_refund, partial_refund, credit_note, exchange, redo_service, no_action
2. WHEN resolution_type is "full_refund", THE Resolution_Engine SHALL call Payment_Service.process_refund for the full invoice amount
3. WHEN resolution_type is "partial_refund", THE Resolution_Engine SHALL call Payment_Service.process_refund for the specified amount
4. WHEN resolution_type is "credit_note", THE Resolution_Engine SHALL create a CreditNote linked to the original invoice
5. WHEN resolution_type is "exchange", THE Resolution_Engine SHALL create a stock return movement and optionally a new invoice for the replacement item
6. WHEN resolution_type is "redo_service", THE Resolution_Engine SHALL create a new JobCard with zero charge linked to the original claim
7. WHEN resolution_type is "no_action", THE Resolution_Engine SHALL only update the claim status to resolved without triggering downstream actions
8. THE Claim_Service SHALL store references to all created downstream entities (refund_id, credit_note_id, return_movement_id, warranty_job_id)

### Requirement 4: Stock Return Handling

**User Story:** As a staff member, I want returned items to be properly tracked in inventory, so that stock levels are accurate and returns are auditable.

#### Acceptance Criteria

1. WHEN a claim involves a physical product return, THE Resolution_Engine SHALL create a StockMovement with movement_type "return"
2. THE Resolution_Engine SHALL link the stock movement to the claim via reference_type "claim" and reference_id
3. WHEN the returned item's catalogue entry is archived, THE Resolution_Engine SHALL still create the stock movement for audit purposes
4. WHEN the returned item's catalogue entry is archived, THE Resolution_Engine SHALL flag the movement as a write-off
5. WHEN the returned item has zero resale value, THE Resolution_Engine SHALL flag the movement as a write-off
6. THE Cost_Tracker SHALL capture the financial impact of write-offs in the claim's cost_to_business field

### Requirement 5: Business Cost Tracking

**User Story:** As a business owner, I want to track the total cost of each claim, so that I can understand the financial impact of returns and complaints.

#### Acceptance Criteria

1. THE Cost_Tracker SHALL calculate cost_to_business for each claim including: labour_cost, parts_cost, write_off_cost
2. WHEN a redo_service resolution is completed, THE Cost_Tracker SHALL add the labour cost to the claim's cost_to_business
3. WHEN parts are used in a warranty repair, THE Cost_Tracker SHALL add the parts cost to the claim's cost_to_business
4. WHEN a stock return is flagged as write-off, THE Cost_Tracker SHALL add the item's cost price to write_off_cost
5. THE Claim_Service SHALL store a cost_breakdown JSON field with itemised costs
6. THE Claim_Service SHALL update cost_to_business whenever a linked action is completed

### Requirement 6: Claim Listing and Filtering

**User Story:** As a staff member, I want to view and filter claims, so that I can manage my workload and find specific claims quickly.

#### Acceptance Criteria

1. THE Claim_Service SHALL return paginated claim lists with total count
2. THE Claim_Service SHALL support filtering by: status, claim_type, customer_id, date_range, branch_id
3. THE Claim_Service SHALL support searching by: customer name, invoice number, claim description
4. THE Claim_Service SHALL return claims ordered by created_at descending by default
5. WHEN branch_id filter is applied, THE Claim_Service SHALL return only claims scoped to that branch

### Requirement 7: Claim Detail View

**User Story:** As a staff member, I want to view the full details of a claim including its timeline, so that I can understand the history and current state.

#### Acceptance Criteria

1. THE Claim_Service SHALL return claim details including: customer info, original transaction, claim type, status, description, resolution
2. THE Claim_Service SHALL return a timeline of all status changes with timestamps and user names
3. THE Claim_Service SHALL return links to all related entities: invoice, job card, credit note, refund, stock movements, warranty job
4. THE Claim_Service SHALL return the cost_breakdown and total cost_to_business
5. THE Claim_Service SHALL return any attached notes or internal comments

### Requirement 8: Quick Claim Creation from Invoice

**User Story:** As a staff member viewing an invoice, I want to quickly create a claim, so that I can efficiently handle customer complaints.

#### Acceptance Criteria

1. WHEN a "Report Issue" action is triggered from an invoice, THE Claim_Service SHALL pre-populate the claim with invoice_id and customer_id
2. THE Claim_Service SHALL allow selection of specific line items from the invoice to include in the claim
3. WHEN line items are selected, THE Claim_Service SHALL store the line_item_ids in the claim record
4. THE Claim_Service SHALL pre-populate the claim_type based on line item types (part → defect, service → service_redo)

### Requirement 9: Customer Profile Claims Tab

**User Story:** As a staff member viewing a customer profile, I want to see all their claims, so that I can understand their complaint history.

#### Acceptance Criteria

1. THE Claim_Service SHALL return all claims for a specific customer_id
2. THE Claim_Service SHALL return summary statistics: total_claims, open_claims, total_cost_to_business
3. THE Claim_Service SHALL order customer claims by created_at descending

### Requirement 10: Claims Reporting

**User Story:** As a business owner, I want reports on claims, so that I can identify trends and improve quality.

#### Acceptance Criteria

1. THE Claim_Service SHALL provide a claims-by-period report with: claim_count, total_cost, average_resolution_time
2. THE Claim_Service SHALL provide a cost-overhead report showing: total_refunds, total_credit_notes, total_write_offs, total_labour_cost
3. THE Claim_Service SHALL provide a supplier-quality report showing parts with highest return rates
4. THE Claim_Service SHALL provide a service-quality report showing technicians with most redo claims
5. THE Claim_Service SHALL support date range filtering for all reports
6. WHEN branch_id is provided, THE Claim_Service SHALL scope reports to that branch

### Requirement 11: Branch Scoping

**User Story:** As a multi-branch business, I want claims to be scoped to branches, so that each location can manage their own claims.

#### Acceptance Criteria

1. THE Claim_Service SHALL store branch_id on each claim record
2. WHEN a user has branch context, THE Claim_Service SHALL filter claims to that branch by default
3. THE Claim_Service SHALL allow org_admin users to view claims across all branches
4. WHEN creating a claim, THE Claim_Service SHALL inherit branch_id from the linked invoice or job card if not explicitly provided

### Requirement 12: Audit Trail

**User Story:** As a business owner, I want all claim actions to be audited, so that I have a complete record for compliance and dispute resolution.

#### Acceptance Criteria

1. WHEN a claim is created, THE Claim_Service SHALL write an audit log entry with action "claim.created"
2. WHEN a claim status changes, THE Claim_Service SHALL write an audit log entry with action "claim.status_changed"
3. WHEN a resolution action is triggered, THE Claim_Service SHALL write an audit log entry with action "claim.resolution_action"
4. THE Claim_Service SHALL include before_value and after_value in all audit log entries
5. THE Claim_Service SHALL record the user_id and ip_address for all audit entries

### Requirement 13: Playwright End-to-End Tests

**User Story:** As a developer, I want comprehensive Playwright E2E tests that exercise the full claims workflow from the browser, so that I can verify the entire system works end-to-end including UI interactions, API calls, and database state changes.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL authenticate using the demo account (demo@orainvoice.com / demo123) via the frontend login form before running any test.
2. THE E2E_Test_Suite SHALL include a test that creates a claim from the Claims list page, fills in all required fields, submits, and verifies the claim appears in the list with status "open".
3. THE E2E_Test_Suite SHALL include a test that transitions a claim through the full workflow: open → investigating → approved → resolved (with full_refund resolution), verifying each status change in the UI.
4. THE E2E_Test_Suite SHALL include a test that transitions a claim through: open → investigating → rejected → resolved (with no_action), verifying the rejection flow.
5. THE E2E_Test_Suite SHALL include a test that resolves a claim with credit_note resolution and verifies the credit note is created and linked.
6. THE E2E_Test_Suite SHALL include a test that resolves a claim with redo_service resolution and verifies a warranty job card is created.
7. THE E2E_Test_Suite SHALL include a test that resolves a claim with exchange resolution and verifies stock return movements are created.
8. THE E2E_Test_Suite SHALL include a test that creates a claim via the "Report Issue" button on the InvoiceDetail page and verifies pre-population of invoice_id and customer_id.
9. THE E2E_Test_Suite SHALL include a test that views the Claims tab on a customer profile and verifies summary statistics are displayed.
10. THE E2E_Test_Suite SHALL include a test that adds an internal note to a claim and verifies it appears in the timeline.
11. THE E2E_Test_Suite SHALL verify database state after each workflow by checking the customer_claims and claim_actions tables via API responses.
12. AFTER all E2E tests pass, THE deployment script SHALL automatically rebuild Docker containers and push to git.

### Requirement 14: Default Main Branch on Organisation Creation

**User Story:** As a business owner, I want my organisation to automatically have a "Main" branch when created, so that the branch system works correctly from day one and I can create additional branches and switch between them.

#### Acceptance Criteria

1. WHEN a new organisation is created (via signup or seed script), THE Branch_Service SHALL automatically create a default branch named "Main" for that organisation.
2. THE default "Main" branch SHALL be marked as is_active=true and is_default=true.
3. WHEN the demo org (Demo Workshop) is seeded, THE seed script SHALL ensure a "Main" branch exists for the demo org.
4. IF the demo org already exists but has no "Main" branch, THE seed script SHALL create one and assign all existing branchless entities to it.
5. WHEN a user creates a second branch, THE Branch_Switcher SHALL display both the "Main" branch and the new branch in the branch selector dropdown.
6. THE Branch_Switcher SHALL allow switching between branches and "All Branches" view.
7. WHEN an organisation has only the default "Main" branch, THE Branch_Switcher SHALL still be visible but show only "Main" and "All Branches" options.

# Requirements Document

## Introduction

This document specifies the requirements for a comprehensive branch management system within the multi-location invoicing SaaS platform. The system extends the existing branch infrastructure (CRUD basics, user assignment) to include full lifecycle management, per-branch billing via Stripe, branch context switching across the UI, branch-scoped data filtering for all business entities, branch-level dashboards and reports, inter-branch stock transfers, staff scheduling, global admin oversight, and branch-specific notifications. The goal is to enable organisations with multiple physical locations to operate each branch semi-independently while maintaining centralised billing and administration.

## Glossary

- **Branch**: A physical location within an Organisation, stored in the `branches` table with RLS. Each Branch has a name, address, contact details, and settings.
- **Organisation**: A tenant in the platform. One Organisation can have many Branches.
- **Org_Admin**: The administrator role for an Organisation. Manages branches, billing, and users.
- **Salesperson**: A staff role within an Organisation. Can be assigned to one or more Branches.
- **Global_Admin**: A platform-wide administrator who can view all Organisations and Branches for support purposes.
- **Branch_Context**: The currently selected Branch (or "All Branches") that filters all data views in the UI. Stored in the user's session/localStorage.
- **HQ_Branch**: The first Branch created for an Organisation, which serves as the master account for billing purposes.
- **Stock_Transfer**: A request to move inventory items from one Branch to another, following a request → approve → ship → receive workflow.
- **Branch_Selector**: A dropdown component in the top navigation bar that allows users to switch between Branches they have access to.
- **Billing_Engine**: The existing Stripe-based billing subsystem (app/modules/billing/) that processes subscription charges.
- **Branch_Multiplier**: The pricing model where each active Branch multiplies the base subscription cost.
- **Branch_Settings**: Per-branch configuration including address, phone, email, logo override, operating hours, and timezone.
- **Transfer_Status**: The lifecycle state of a Stock_Transfer: pending, approved, shipped, received, or cancelled.
- **Branch_Dashboard**: A dashboard view showing performance metrics scoped to a specific Branch or aggregated across all Branches.
- **Branch_Report**: An existing report type extended with a branch filter parameter.

## Requirements

### Requirement 1: Branch Update

**User Story:** As an Org_Admin, I want to update branch details, so that I can keep branch information current as locations change.

#### Acceptance Criteria

1. WHEN an Org_Admin submits a PUT request to `/org/branches/{branch_id}` with updated fields, THE Branch_Service SHALL update the corresponding Branch record and return the updated Branch data.
2. WHEN a PUT request includes a `name` field with an empty string, THE Branch_Service SHALL reject the request with a 400 status code and a descriptive error message.
3. WHEN a PUT request targets a Branch that does not belong to the requesting user's Organisation, THE Branch_Service SHALL return a 404 status code.
4. WHEN a Branch is successfully updated, THE Branch_Service SHALL write an audit log entry recording the before and after values.
5. THE Branch_Update_Schema SHALL accept optional fields: name, address, phone, email, logo_url, operating_hours, and timezone.

### Requirement 2: Branch Soft-Delete and Deactivation

**User Story:** As an Org_Admin, I want to deactivate a branch, so that I can stop operations at a location without losing historical data.

#### Acceptance Criteria

1. WHEN an Org_Admin submits a DELETE request to `/org/branches/{branch_id}`, THE Branch_Service SHALL set the Branch `is_active` field to false instead of deleting the record.
2. WHEN a Branch is deactivated, THE Branch_Service SHALL prevent new Invoices, Quotes, Job_Cards, Bookings, Expenses, and Purchase_Orders from being created with that Branch's ID.
3. WHEN a Branch is deactivated, THE Branch_Service SHALL retain all historical records associated with that Branch.
4. IF the target Branch is the only active Branch in the Organisation, THEN THE Branch_Service SHALL reject the deactivation with a 400 status code and the message "Cannot deactivate the only active branch".
5. WHEN a Branch is deactivated, THE Branch_Service SHALL write an audit log entry recording the deactivation.
6. WHEN an Org_Admin submits a POST request to `/org/branches/{branch_id}/reactivate`, THE Branch_Service SHALL set the Branch `is_active` field to true.

### Requirement 3: Branch-Level Settings

**User Story:** As an Org_Admin, I want to configure per-branch settings, so that each location can have its own contact details, branding, and operating hours.

#### Acceptance Criteria

1. THE Branch_Settings SHALL include the following fields: address, phone, email, logo_url, operating_hours (JSON object with day-of-week keys and open/close time values), and timezone (IANA timezone string).
2. WHEN a Branch has a logo_url configured, THE Invoice_Renderer SHALL use the Branch logo instead of the Organisation logo on invoices generated for that Branch.
3. WHEN a Branch has a timezone configured, THE Branch_Dashboard SHALL display timestamps in the Branch timezone.
4. WHEN operating_hours are configured for a Branch, THE Booking_System SHALL validate new bookings against the Branch operating hours.
5. IF an invalid IANA timezone string is provided, THEN THE Branch_Service SHALL reject the update with a 400 status code and a descriptive error message.

### Requirement 4: Per-Branch Billing — Cost Multiplication

**User Story:** As an Org_Admin, I want the subscription cost to scale with the number of active branches, so that billing reflects actual usage.

#### Acceptance Criteria

1. THE Billing_Engine SHALL calculate the subscription charge as: base_plan_price × number_of_active_branches × interval_multiplier.
2. WHEN an Organisation has one active Branch, THE Billing_Engine SHALL charge the base plan price (1× multiplier).
3. WHEN a new Branch is activated, THE Billing_Engine SHALL prorate the additional charge for the remainder of the current billing period.
4. WHEN a Branch is deactivated, THE Billing_Engine SHALL prorate a credit for the remainder of the current billing period.
5. THE Billing_Dashboard SHALL display a per-branch cost breakdown showing each active Branch name and its contribution to the total subscription cost.
6. WHEN the billing interval is annual, THE Billing_Engine SHALL apply the annual discount rate to the per-branch cost before multiplication.

### Requirement 5: Per-Branch Billing — Activation Confirmation

**User Story:** As an Org_Admin, I want to see a cost confirmation before adding a branch, so that I understand the billing impact.

#### Acceptance Criteria

1. WHEN an Org_Admin initiates branch creation, THE Branch_UI SHALL display a confirmation dialog showing: "Adding a branch will increase your subscription by ${amount}/{interval}".
2. THE Confirmation_Dialog SHALL calculate the amount as: base_plan_price × interval_multiplier for the current billing interval.
3. WHEN the Org_Admin confirms the dialog, THE Branch_Service SHALL create the Branch and THE Billing_Engine SHALL create the prorated Stripe charge.
4. WHEN the Org_Admin cancels the dialog, THE Branch_Service SHALL not create the Branch.
5. IF the Stripe charge fails, THEN THE Branch_Service SHALL roll back the Branch creation and display an error message to the Org_Admin.

### Requirement 6: Per-Branch Billing — HQ Master Account

**User Story:** As an Org_Admin, I want the first branch to serve as the billing master, so that all branch charges are consolidated on one account.

#### Acceptance Criteria

1. THE Billing_Engine SHALL designate the first Branch created for an Organisation as the HQ_Branch.
2. THE HQ_Branch SHALL be the billing anchor — all branch charges appear on the Organisation's single Stripe subscription.
3. THE HQ_Branch SHALL not be deactivatable while other active Branches exist.
4. WHEN the Billing_Dashboard is viewed, THE Billing_Dashboard SHALL show the HQ_Branch label next to the first Branch in the cost breakdown.

### Requirement 7: Per-Branch Billing — Global Admin Revenue View

**User Story:** As a Global_Admin, I want to see branch counts and revenue impact per organisation, so that I can monitor platform growth.

#### Acceptance Criteria

1. THE Global_Admin_Dashboard SHALL display a table of Organisations with columns: org name, active branch count, total monthly revenue, and per-branch average revenue.
2. WHEN a Global_Admin clicks on an Organisation row, THE Global_Admin_Dashboard SHALL show the list of Branches with individual revenue figures.
3. THE Global_Admin_Dashboard SHALL display a platform-wide summary: total active branches, total branch-related revenue, and average branches per organisation.

### Requirement 8: Branch Context Switching — Selector Component

**User Story:** As a user, I want to select which branch I'm working in, so that I see only relevant data for my current location.

#### Acceptance Criteria

1. THE Branch_Selector SHALL appear in the top navigation bar as a dropdown.
2. THE Branch_Selector SHALL list all Branches the current user has access to (based on the user's branch_ids array).
3. THE Branch_Selector SHALL include an "All Branches" option that shows aggregated data across all accessible Branches.
4. WHEN a user has access to only one Branch, THE Branch_Selector SHALL pre-select that Branch and still allow switching to "All Branches".
5. WHEN a user selects a Branch, THE Branch_Selector SHALL store the selection in localStorage under the key `selected_branch_id`.
6. THE Branch_Selector SHALL persist the selected Branch across page navigations and browser refreshes.

### Requirement 9: Branch Context Switching — API Integration

**User Story:** As a developer, I want API requests to include branch context, so that the backend can filter data by branch.

#### Acceptance Criteria

1. WHEN a Branch is selected (not "All Branches"), THE API_Client SHALL include an `X-Branch-Id` header with the selected Branch UUID on every API request.
2. WHEN "All Branches" is selected, THE API_Client SHALL omit the `X-Branch-Id` header.
3. WHEN the backend receives a request with an `X-Branch-Id` header, THE Backend_Middleware SHALL validate that the header value is a valid UUID belonging to the requesting user's Organisation.
4. IF the `X-Branch-Id` header contains an invalid UUID or a Branch not belonging to the user's Organisation, THEN THE Backend_Middleware SHALL return a 403 status code with the message "Invalid branch context".
5. WHEN the backend receives a request without an `X-Branch-Id` header, THE Backend_Middleware SHALL treat the request as "All Branches" scope.

### Requirement 10: Branch-Scoped Invoices

**User Story:** As a user, I want invoices filtered by branch, so that I can manage billing per location.

#### Acceptance Criteria

1. WHEN a Branch is selected in the Branch_Context, THE Invoice_List SHALL display only Invoices with a matching branch_id.
2. WHEN "All Branches" is selected, THE Invoice_List SHALL display Invoices across all accessible Branches.
3. WHEN creating a new Invoice with a Branch selected, THE Invoice_Service SHALL automatically set the branch_id to the current Branch_Context value.
4. THE Invoice_List SHALL display a "Branch" column showing the Branch name for each Invoice.
5. WHEN an Invoice is viewed in detail, THE Invoice_Detail SHALL display the Branch name and Branch-specific contact details.

### Requirement 11: Branch-Scoped Quotes

**User Story:** As a user, I want quotes associated with branches, so that I can track quotes per location.

#### Acceptance Criteria

1. THE Quote_Table SHALL have a `branch_id` foreign key column referencing the `branches` table, nullable for backward compatibility.
2. WHEN a Branch is selected in the Branch_Context, THE Quote_List SHALL display only Quotes with a matching branch_id.
3. WHEN "All Branches" is selected, THE Quote_List SHALL display Quotes across all accessible Branches.
4. WHEN creating a new Quote with a Branch selected, THE Quote_Service SHALL automatically set the branch_id to the current Branch_Context value.

### Requirement 12: Branch-Scoped Job Cards

**User Story:** As a user, I want job cards associated with branches, so that I can track work per location.

#### Acceptance Criteria

1. THE Job_Card_Table SHALL have a `branch_id` foreign key column referencing the `branches` table, nullable for backward compatibility.
2. WHEN a Branch is selected in the Branch_Context, THE Job_Card_List SHALL display only Job_Cards with a matching branch_id.
3. WHEN "All Branches" is selected, THE Job_Card_List SHALL display Job_Cards across all accessible Branches.
4. WHEN creating a new Job_Card with a Branch selected, THE Job_Card_Service SHALL automatically set the branch_id to the current Branch_Context value.

### Requirement 13: Branch-Scoped Customers

**User Story:** As a user, I want customers associated with branches, so that I can manage customer relationships per location.

#### Acceptance Criteria

1. THE Customer_Table SHALL have a `branch_id` foreign key column referencing the `branches` table, representing the customer's primary Branch. The column SHALL be nullable for backward compatibility.
2. WHEN a Branch is selected in the Branch_Context, THE Customer_List SHALL display Customers whose branch_id matches the selected Branch OR Customers marked as shared (branch_id is NULL).
3. WHEN "All Branches" is selected, THE Customer_List SHALL display all Customers across all accessible Branches.
4. THE Customer_Create_Form SHALL include a "Branch" dropdown defaulting to the current Branch_Context.
5. THE Customer_Create_Form SHALL include a "Shared across branches" checkbox that sets branch_id to NULL.

### Requirement 14: Branch-Scoped Expenses, Bookings, Purchase Orders, and Projects

**User Story:** As a user, I want all business entities associated with branches, so that I can track operations per location.

#### Acceptance Criteria

1. THE Expense_Table SHALL have a `branch_id` foreign key column referencing the `branches` table, nullable for backward compatibility.
2. THE Purchase_Order_Table SHALL have a `branch_id` foreign key column referencing the `branches` table, nullable for backward compatibility.
3. THE Project_Table SHALL have a `branch_id` foreign key column referencing the `branches` table, nullable for backward compatibility.
4. WHEN a Branch is selected in the Branch_Context, THE list views for Expenses, Bookings, Purchase_Orders, and Projects SHALL display only records with a matching branch_id.
5. WHEN "All Branches" is selected, THE list views for Expenses, Bookings, Purchase_Orders, and Projects SHALL display records across all accessible Branches.
6. WHEN creating a new Expense, Booking, Purchase_Order, or Project with a Branch selected, THE respective Service SHALL automatically set the branch_id to the current Branch_Context value.


### Requirement 15: Branch-Scoped Dashboards — Per-Branch Metrics

**User Story:** As an Org_Admin, I want to see performance metrics per branch, so that I can compare location performance.

#### Acceptance Criteria

1. WHEN a Branch is selected in the Branch_Context, THE Branch_Dashboard SHALL display metrics scoped to that Branch: revenue, invoice count and value, customer count, staff count, and expense breakdown.
2. WHEN "All Branches" is selected, THE Branch_Dashboard SHALL display aggregated metrics across all accessible Branches.
3. THE Branch_Dashboard SHALL include a revenue chart (bar or line) with data points per Branch.
4. THE Branch_Dashboard SHALL include a summary table with columns: Branch name, revenue, invoice count, customer count, staff count, and total expenses.

### Requirement 16: Branch-Scoped Dashboards — Comparison View

**User Story:** As an Org_Admin, I want to compare branch performance side by side, so that I can identify underperforming locations.

#### Acceptance Criteria

1. THE Branch_Dashboard SHALL include a "Compare Branches" view accessible via a toggle or tab.
2. THE Compare_View SHALL allow the Org_Admin to select two or more Branches for side-by-side comparison.
3. THE Compare_View SHALL display comparison charts for: revenue, invoice count, customer count, and expense totals.
4. THE Compare_View SHALL highlight the highest and lowest performing Branch in each metric using visual indicators.

### Requirement 17: Stock/Inventory Transfers Between Branches

**User Story:** As a user, I want to transfer stock between branches, so that I can balance inventory across locations.

#### Acceptance Criteria

1. WHEN a user initiates a stock transfer, THE Transfer_Service SHALL create a Stock_Transfer record with status "pending" and fields: from_branch_id, to_branch_id, product_id, quantity, and requested_by.
2. WHEN an Org_Admin or branch manager approves a pending transfer, THE Transfer_Service SHALL update the Transfer_Status to "approved" and record the approved_by user.
3. WHEN an approved transfer is marked as shipped, THE Transfer_Service SHALL update the Transfer_Status to "shipped" and deduct the quantity from the source Branch stock level.
4. WHEN a shipped transfer is marked as received, THE Transfer_Service SHALL update the Transfer_Status to "received", add the quantity to the destination Branch stock level, and record the completed_at timestamp.
5. IF a transfer is cancelled at any stage before "received", THEN THE Transfer_Service SHALL update the Transfer_Status to "cancelled" and, if stock was already deducted (status was "shipped"), restore the quantity to the source Branch.
6. THE Transfer_History_View SHALL display all transfers with columns: date, from branch, to branch, product, quantity, status, and requested by.

### Requirement 18: Per-Branch Stock Levels

**User Story:** As a user, I want to see stock levels per branch, so that I can manage inventory at each location.

#### Acceptance Criteria

1. THE Stock_Item_Table SHALL have a `branch_id` foreign key column referencing the `branches` table.
2. WHEN a Branch is selected in the Branch_Context, THE Stock_Level_View SHALL display stock quantities for that Branch only.
3. WHEN "All Branches" is selected, THE Stock_Level_View SHALL display aggregated stock quantities across all Branches with a per-branch breakdown column.
4. THE Reorder_Alert_Service SHALL evaluate reorder thresholds per Branch independently.
5. WHEN a stock item at a specific Branch falls below its reorder threshold, THE Reorder_Alert_Service SHALL generate a reorder alert tagged with the Branch name.

### Requirement 19: Staff Scheduling Per Branch

**User Story:** As an Org_Admin, I want to schedule staff per branch, so that I can manage rosters across locations.

#### Acceptance Criteria

1. THE Schedule_Table SHALL have columns: id, org_id, branch_id, user_id, shift_date, start_time, end_time, and notes.
2. WHEN an Org_Admin creates a schedule entry, THE Schedule_Service SHALL validate that the user_id is assigned to the target branch_id (exists in the user's branch_ids array).
3. WHEN a Branch is selected in the Branch_Context, THE Schedule_View SHALL display only schedule entries for that Branch.
4. WHEN "All Branches" is selected, THE Schedule_View SHALL display schedule entries across all accessible Branches grouped by Branch name.
5. IF a schedule entry overlaps with an existing entry for the same user on the same date, THEN THE Schedule_Service SHALL reject the creation with a 409 status code and a descriptive error message.

### Requirement 20: Branch-Level Reports

**User Story:** As an Org_Admin, I want existing reports to support branch filtering, so that I can generate location-specific financial reports.

#### Acceptance Criteria

1. THE Revenue_Report SHALL accept an optional branch_id parameter and, when provided, return revenue data for that Branch only.
2. THE GST_Return_Report SHALL accept an optional branch_id parameter and, when provided, calculate GST for that Branch only.
3. THE Outstanding_Invoices_Report SHALL accept an optional branch_id parameter and, when provided, list outstanding invoices for that Branch only.
4. THE Customer_Statement_Report SHALL accept an optional branch_id parameter and, when provided, include only transactions associated with that Branch.
5. WHEN a Branch is selected in the Branch_Context, THE Report_UI SHALL automatically pass the branch_id to the report endpoint.
6. WHEN "All Branches" is selected, THE Report_UI SHALL omit the branch_id parameter, returning organisation-wide data.

### Requirement 21: Global Admin Branch Overview

**User Story:** As a Global_Admin, I want to see all branches across all organisations, so that I can provide support and monitor the platform.

#### Acceptance Criteria

1. THE Global_Admin_Branch_View SHALL display a paginated table of all Branches across all Organisations with columns: organisation name, branch name, status, created date, and branch settings summary.
2. THE Global_Admin_Branch_View SHALL support filtering by organisation name and branch status (active/inactive).
3. WHEN a Global_Admin clicks on a Branch row, THE Global_Admin_Branch_View SHALL display the full Branch details including settings, assigned users, and recent activity.
4. THE Global_Admin_Branch_View SHALL display a summary card showing: total active branches platform-wide, total inactive branches, and average branches per organisation.

### Requirement 22: Branch Notifications

**User Story:** As an Org_Admin, I want to receive notifications about branch changes, so that I stay informed about location management events.

#### Acceptance Criteria

1. WHEN a new Branch is created, THE Notification_Service SHALL send a "New branch added" notification to all Org_Admin users in the Organisation.
2. WHEN a Branch is deactivated, THE Notification_Service SHALL send a "Branch deactivated" notification to all Org_Admin users in the Organisation.
3. WHEN a Branch activation or deactivation changes the subscription cost, THE Notification_Service SHALL send a "Billing updated" notification to all Org_Admin users with the new monthly total.
4. THE Branch_Settings SHALL include a `notification_preferences` JSON field allowing per-branch configuration of which notification types are enabled.
5. WHEN a Stock_Transfer is created targeting a Branch, THE Notification_Service SHALL send a "Stock transfer request" notification to users assigned to the destination Branch.

### Requirement 23: Branch Data Migration for Existing Records

**User Story:** As a developer, I want existing records without branch_id to remain accessible, so that the migration does not break current functionality.

#### Acceptance Criteria

1. THE Database_Migration SHALL add nullable `branch_id` columns to: quotes, job_cards, customers, expenses, purchase_orders, and projects tables.
2. THE Database_Migration SHALL not set a default branch_id on existing records — existing records SHALL have branch_id = NULL.
3. WHEN a list view is filtered by Branch, THE query SHALL include records where branch_id matches the selected Branch.
4. WHEN "All Branches" is selected, THE query SHALL include all records regardless of branch_id value (including NULL).
5. THE Database_Migration SHALL add foreign key constraints from each new branch_id column to the branches table with ON DELETE SET NULL.
6. THE Database_Migration SHALL add indexes on each new branch_id column for query performance.

### Requirement 24: Branch Context Persistence and Validation

**User Story:** As a user, I want my branch selection to be validated on each page load, so that I never see data from a branch I no longer have access to.

#### Acceptance Criteria

1. WHEN the application loads, THE Branch_Context_Provider SHALL read the stored branch_id from localStorage.
2. WHEN the stored branch_id is not found in the user's current branch_ids array, THE Branch_Context_Provider SHALL reset the selection to "All Branches" and remove the stale value from localStorage.
3. WHEN the user's branch_ids array is updated (e.g., by an Org_Admin removing access), THE Branch_Context_Provider SHALL re-validate the current selection on the next API response.
4. THE Branch_Context_Provider SHALL expose the current branch_id (or null for "All Branches") via a React context accessible to all components.

### Requirement 25: End-to-End Testing — Branch CRUD User Flows

**User Story:** As a developer, I want automated E2E tests that simulate real user interactions for all branch CRUD operations, so that regressions are caught before deployment.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a Playwright test that navigates to Settings > Branches, clicks "Add Branch", fills in name/address/phone fields, clicks "Create", and verifies the new branch appears in the table.
2. THE E2E_Test_Suite SHALL include a test that clicks "Edit" on an existing branch row, modifies the name, clicks "Update", and verifies the updated name appears in the table.
3. THE E2E_Test_Suite SHALL include a test that clicks "Deactivate" on a branch, confirms the deactivation dialog, and verifies the branch status changes to "Inactive".
4. THE E2E_Test_Suite SHALL include a test that clicks "Reactivate" on an inactive branch and verifies the status returns to "Active".
5. THE E2E_Test_Suite SHALL include a test that attempts to deactivate the only active branch and verifies an error message is displayed.
6. THE E2E_Test_Suite SHALL include a test that clicks "Assign Users" on a branch, toggles user checkboxes, clicks "Done", and verifies the assignment persists on page reload.

### Requirement 26: End-to-End Testing — Branch Context Switching User Flows

**User Story:** As a developer, I want automated E2E tests for the branch selector, so that context switching works correctly across all pages.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that clicks the Branch_Selector dropdown in the navbar, selects a specific branch, and verifies the invoice list filters to show only invoices for that branch.
2. THE E2E_Test_Suite SHALL include a test that selects "All Branches" in the Branch_Selector and verifies invoices from all branches are displayed.
3. THE E2E_Test_Suite SHALL include a test that selects a branch, navigates to a different page (e.g., Customers), and verifies the branch selection persists.
4. THE E2E_Test_Suite SHALL include a test that selects a branch, refreshes the browser, and verifies the branch selection is restored from localStorage.
5. THE E2E_Test_Suite SHALL include a test that verifies a user with access to only one branch sees that branch pre-selected in the Branch_Selector.
6. THE E2E_Test_Suite SHALL include a test that verifies the Branch_Selector only shows branches the current user has access to (not all org branches).

### Requirement 27: End-to-End Testing — Branch Billing User Flows

**User Story:** As a developer, I want automated E2E tests for branch billing interactions, so that subscription changes from branch operations are correct.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that initiates branch creation, verifies the billing confirmation dialog appears with the correct amount, clicks "Confirm", and verifies the branch is created.
2. THE E2E_Test_Suite SHALL include a test that initiates branch creation, clicks "Cancel" on the billing confirmation dialog, and verifies no branch is created.
3. THE E2E_Test_Suite SHALL include a test that navigates to Settings > Billing, and verifies the per-branch cost breakdown table shows all active branches with their individual costs.
4. THE E2E_Test_Suite SHALL include a test that creates a branch, then navigates to Billing, and verifies the total subscription amount increased by the per-branch cost.
5. THE E2E_Test_Suite SHALL include a test that deactivates a branch, then navigates to Billing, and verifies the total subscription amount decreased.

### Requirement 28: End-to-End Testing — Branch-Scoped Data Creation User Flows

**User Story:** As a developer, I want automated E2E tests that verify new records are automatically tagged with the selected branch, so that branch scoping works end-to-end.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that selects Branch A in the Branch_Selector, creates a new invoice, and verifies the invoice's branch_id is set to Branch A.
2. THE E2E_Test_Suite SHALL include a test that selects Branch A, creates a new quote, and verifies the quote's branch_id is set to Branch A.
3. THE E2E_Test_Suite SHALL include a test that selects Branch A, creates a new expense, and verifies the expense's branch_id is set to Branch A.
4. THE E2E_Test_Suite SHALL include a test that selects Branch A, creates a new customer, and verifies the customer's branch_id is set to Branch A.
5. THE E2E_Test_Suite SHALL include a test that selects Branch A, creates a new customer with "Shared across branches" checked, and verifies the customer's branch_id is NULL.
6. THE E2E_Test_Suite SHALL include a test that selects "All Branches", creates a new invoice, and verifies the invoice's branch_id is NULL (no branch assigned).

### Requirement 29: End-to-End Testing — Stock Transfer User Flows

**User Story:** As a developer, I want automated E2E tests for the full stock transfer lifecycle, so that inter-branch inventory movements work correctly.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that navigates to Inventory > Stock Transfers, clicks "New Transfer", selects source branch, destination branch, product, and quantity, clicks "Submit", and verifies the transfer appears with "Pending" status.
2. THE E2E_Test_Suite SHALL include a test that clicks "Approve" on a pending transfer and verifies the status changes to "Approved".
3. THE E2E_Test_Suite SHALL include a test that clicks "Mark Shipped" on an approved transfer and verifies the source branch stock level decreases by the transfer quantity.
4. THE E2E_Test_Suite SHALL include a test that clicks "Mark Received" on a shipped transfer and verifies the destination branch stock level increases by the transfer quantity.
5. THE E2E_Test_Suite SHALL include a test that clicks "Cancel" on a shipped transfer and verifies the source branch stock level is restored.
6. THE E2E_Test_Suite SHALL include a test that views the transfer history and verifies all transfers are listed with correct dates, branches, products, quantities, and statuses.

### Requirement 30: End-to-End Testing — Branch Dashboard and Reports User Flows

**User Story:** As a developer, I want automated E2E tests for branch dashboards and reports, so that branch-scoped analytics display correctly.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that selects a branch in the Branch_Selector, navigates to the Dashboard, and verifies the revenue, invoice count, customer count, and expense metrics are scoped to that branch.
2. THE E2E_Test_Suite SHALL include a test that selects "All Branches", navigates to the Dashboard, and verifies aggregated metrics across all branches are displayed.
3. THE E2E_Test_Suite SHALL include a test that opens the "Compare Branches" view, selects two branches, and verifies comparison charts render with data for both branches.
4. THE E2E_Test_Suite SHALL include a test that navigates to Reports > Revenue, selects a branch filter, clicks "Generate", and verifies the report data is scoped to the selected branch.
5. THE E2E_Test_Suite SHALL include a test that navigates to Reports > Outstanding Invoices with a branch filter and verifies only invoices for that branch appear.
6. THE E2E_Test_Suite SHALL include a test that navigates to Reports > GST Return with a branch filter and verifies the GST calculation is scoped to that branch.

### Requirement 31: End-to-End Testing — Branch Settings and Notifications User Flows

**User Story:** As a developer, I want automated E2E tests for branch settings and notification preferences, so that per-branch configuration works correctly.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that opens branch settings, updates the operating hours for Monday, clicks "Save", and verifies the updated hours persist on page reload.
2. THE E2E_Test_Suite SHALL include a test that uploads a branch-specific logo, saves, and verifies the logo URL is stored in the branch settings.
3. THE E2E_Test_Suite SHALL include a test that sets a branch timezone, saves, and verifies timestamps on the branch dashboard display in the configured timezone.
4. THE E2E_Test_Suite SHALL include a test that creates a new branch and verifies an in-app notification "New branch added" appears for the Org_Admin.
5. THE E2E_Test_Suite SHALL include a test that deactivates a branch and verifies a "Branch deactivated" notification appears.
6. THE E2E_Test_Suite SHALL include a test that creates a stock transfer and verifies a "Stock transfer request" notification appears for users assigned to the destination branch.

### Requirement 32: End-to-End Testing — Global Admin Branch Views

**User Story:** As a developer, I want automated E2E tests for the global admin branch overview, so that platform-wide branch monitoring works correctly.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a test that logs in as Global_Admin, navigates to the branch overview page, and verifies the table shows branches across multiple organisations.
2. THE E2E_Test_Suite SHALL include a test that filters the global branch table by organisation name and verifies only branches for that organisation are displayed.
3. THE E2E_Test_Suite SHALL include a test that filters by branch status (active/inactive) and verifies the results match.
4. THE E2E_Test_Suite SHALL include a test that clicks on a branch row and verifies the detail panel shows branch settings, assigned users, and recent activity.
5. THE E2E_Test_Suite SHALL include a test that verifies the summary card shows correct totals for active branches, inactive branches, and average branches per organisation.

### Requirement 33: End-to-End Testing — Backend API Integration Tests

**User Story:** As a developer, I want automated API integration tests for every branch endpoint, so that the backend contract is verified independently of the frontend.

#### Acceptance Criteria

1. THE API_Test_Suite SHALL include tests for all branch CRUD endpoints: POST /org/branches (create), PUT /org/branches/{id} (update), DELETE /org/branches/{id} (deactivate), POST /org/branches/{id}/reactivate.
2. THE API_Test_Suite SHALL include tests for branch billing: verify Stripe subscription quantity updates when branches are created/deactivated, verify proration calculations.
3. THE API_Test_Suite SHALL include tests for the X-Branch-Id header: verify data filtering when header is present, verify "All Branches" behavior when header is absent, verify 403 when header contains invalid branch UUID.
4. THE API_Test_Suite SHALL include tests for stock transfer endpoints: create, approve, ship, receive, cancel — verifying stock level changes at each step.
5. THE API_Test_Suite SHALL include tests for branch-scoped list endpoints: verify invoices, quotes, job_cards, customers, expenses, bookings, purchase_orders, and projects filter correctly by branch_id.
6. THE API_Test_Suite SHALL include tests for branch-scoped report endpoints: verify revenue, GST, outstanding invoices, and customer statement reports accept and respect the branch_id parameter.
7. THE API_Test_Suite SHALL include RBAC tests: verify org_admin can perform all branch operations, salesperson can only read branches, and users without branch access receive 403.

### Requirement 34: End-to-End Testing — Property-Based Tests for Branch Billing Correctness

**User Story:** As a developer, I want property-based tests that verify billing invariants hold for any number of branches, so that edge cases in billing calculations are caught.

#### Acceptance Criteria

1. THE Property_Test_Suite SHALL include a property test that verifies: for any number of active branches N >= 1, the total subscription charge equals base_price × N × interval_multiplier.
2. THE Property_Test_Suite SHALL include a property test that verifies: creating and then immediately deactivating a branch results in a net zero billing change (proration cancels out).
3. THE Property_Test_Suite SHALL include a property test that verifies: the sum of per-branch prorated charges equals the total prorated charge for the billing period.
4. THE Property_Test_Suite SHALL include a property test that verifies: deactivating the HQ branch while other branches exist is always rejected.
5. THE Property_Test_Suite SHALL include a property test that verifies: for any stock transfer quantity Q, the source branch stock decreases by Q on ship and the destination increases by Q on receive, and cancellation restores the source.

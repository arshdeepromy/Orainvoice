# Requirements Document

## Introduction

This document specifies the requirements for two enhancements to the existing branch management system: (1) adding a staff assignment step to the branch creation flow, allowing admins to assign existing staff members to a new branch during creation, and (2) enhancing the BranchSelector component to provide more prominent visual feedback when a branch is active. Both features build on existing infrastructure — the `assign_user_branches` service function, the staff module (`/api/v2/staff`), the `BranchContext` provider, and the `BranchSelector` component — without creating new backend modules.

## Glossary

- **Branch_Creation_Modal**: The existing "Add Branch" modal in `BranchManagement.tsx` that currently collects name, address, and phone fields. This modal will be enhanced with a staff assignment step.
- **Staff_Member**: A record in the `staff_members` table representing an employee or contractor. Each Staff_Member has an optional `user_id` field linking to the `users` table.
- **Linked_Staff**: A Staff_Member whose `user_id` is not null, meaning the staff member has an associated user account and can log in to the system.
- **Unlinked_Staff**: A Staff_Member whose `user_id` is null, meaning the staff member does not have a user account and cannot log in.
- **Org_Admin**: The administrator role for an Organisation. Manages branches, staff, and users.
- **Branch_Selector**: The existing dropdown component in the top navigation bar (`BranchSelector.tsx`) that allows users to switch between branches.
- **Branch_Context**: The React context provider (`BranchContext.tsx`) that manages the currently selected branch and exposes it to all components.
- **Staff_API**: The existing staff module at `/api/v2/staff` that provides CRUD operations for staff members.
- **Assign_User_Branches_Service**: The existing `assign_user_branches` function in `app/modules/organisations/service.py` that assigns a user to one or more branches by updating the user's `branch_ids` JSONB array.
- **Active_Branch_Indicator**: A visual element in the header that shows the currently selected branch name with a colored badge or border, providing clear feedback that the user is operating within a specific branch scope.

## Requirements

### Requirement 1: Staff List in Branch Creation Modal

**User Story:** As an Org_Admin, I want to see a list of existing staff members when creating a branch, so that I can assign staff to the new branch in a single workflow.

#### Acceptance Criteria

1. WHEN an Org_Admin opens the "Add Branch" modal, THE Branch_Creation_Modal SHALL display a two-step flow: Step 1 for branch details (name, address, phone) and Step 2 for staff assignment.
2. WHEN Step 1 is completed with a valid branch name, THE Branch_Creation_Modal SHALL allow the Org_Admin to proceed to Step 2.
3. WHEN Step 2 is displayed, THE Branch_Creation_Modal SHALL fetch the list of active staff members from the Staff_API endpoint `GET /api/v2/staff`.
4. IF the Staff_API request fails, THEN THE Branch_Creation_Modal SHALL display an error message and allow the Org_Admin to retry or skip staff assignment.
5. THE Branch_Creation_Modal SHALL display each Staff_Member with their name, position, and email fields.

### Requirement 2: Linked Staff Selection via Checkboxes

**User Story:** As an Org_Admin, I want to select staff members who have user accounts via checkboxes, so that I can grant them access to the new branch.

#### Acceptance Criteria

1. WHEN a Staff_Member is a Linked_Staff (user_id is not null), THE Branch_Creation_Modal SHALL display a checkbox next to the Staff_Member's name labelled "Grant branch access".
2. WHEN the Org_Admin checks the checkbox for a Linked_Staff member, THE Branch_Creation_Modal SHALL add that Staff_Member to the list of users to be assigned to the new branch.
3. WHEN the Org_Admin unchecks the checkbox for a Linked_Staff member, THE Branch_Creation_Modal SHALL remove that Staff_Member from the assignment list.
4. THE Branch_Creation_Modal SHALL visually distinguish Linked_Staff from Unlinked_Staff by showing a "Has account" badge next to Linked_Staff members.

### Requirement 3: Invite Unlinked Staff to Manage Branch

**User Story:** As an Org_Admin, I want to invite staff members without user accounts to manage the new branch, so that I can onboard them during branch creation.

#### Acceptance Criteria

1. WHEN a Staff_Member is an Unlinked_Staff (user_id is null), THE Branch_Creation_Modal SHALL display an "Invite to manage this branch" checkbox next to the Staff_Member's name.
2. WHEN the Org_Admin checks the "Invite to manage this branch" checkbox for an Unlinked_Staff member, THE Branch_Creation_Modal SHALL add that Staff_Member to the list of staff to be invited.
3. IF an Unlinked_Staff member does not have an email address, THEN THE Branch_Creation_Modal SHALL disable the "Invite to manage this branch" checkbox and display a tooltip stating "Email address required to create account".
4. THE Branch_Creation_Modal SHALL visually distinguish Unlinked_Staff by showing a "No account" badge next to their name.

### Requirement 4: Branch Creation with Staff Assignment Execution

**User Story:** As an Org_Admin, I want the branch creation to assign selected staff and invite unlinked staff in one operation, so that the branch is ready to use immediately.

#### Acceptance Criteria

1. WHEN the Org_Admin clicks "Create" on Step 2, THE Branch_Creation_Modal SHALL first create the branch via `POST /org/branches` with the name, address, and phone fields.
2. WHEN the branch is created successfully and Linked_Staff members are selected, THE Branch_Creation_Modal SHALL call the existing `PUT /org/users/{user_id}` endpoint for each selected Linked_Staff member to add the new branch ID to their `branch_ids` array using the Assign_User_Branches_Service.
3. WHEN the branch is created successfully and Unlinked_Staff members are marked for invitation, THE Branch_Creation_Modal SHALL call `POST /api/v2/staff/{staff_id}/create-account` for each invited Unlinked_Staff member, followed by assigning the new branch to the created user account.
4. IF any staff assignment fails, THEN THE Branch_Creation_Modal SHALL display a warning toast identifying which staff members could not be assigned, while keeping the successfully created branch.
5. WHEN the Org_Admin clicks "Skip" on Step 2, THE Branch_Creation_Modal SHALL create the branch without any staff assignments.
6. WHEN all operations complete, THE Branch_Creation_Modal SHALL close and refresh the branch list.

### Requirement 5: Enhanced Branch Selector Visual Prominence

**User Story:** As an Org_Admin, I want the branch selector to be more visually prominent, so that I can clearly see which branch I am currently working in.

#### Acceptance Criteria

1. WHEN a specific branch is selected (not "All Branches"), THE Branch_Selector SHALL display the branch name in a colored badge style instead of a plain dropdown appearance.
2. WHEN a specific branch is selected, THE Branch_Selector SHALL apply a distinct background color to the selector element to differentiate it from the "All Branches" state.
3. WHEN "All Branches" is selected, THE Branch_Selector SHALL display in the default neutral style without a colored indicator.
4. THE Branch_Selector SHALL remain a dropdown element with the same selection behaviour as the current implementation.

### Requirement 6: Active Branch Name in Header

**User Story:** As an Org_Admin, I want to see the active branch name displayed prominently in the header, so that I always know which branch scope I am operating in.

#### Acceptance Criteria

1. WHEN a specific branch is selected, THE Header SHALL display the active branch name as a visible badge adjacent to the Branch_Selector.
2. THE Active_Branch_Indicator SHALL use a colored dot or border to visually signal that a branch filter is active.
3. WHEN "All Branches" is selected, THE Header SHALL hide the Active_Branch_Indicator.
4. WHEN the user switches branches via the Branch_Selector, THE Active_Branch_Indicator SHALL update immediately to reflect the new selection.
5. THE Active_Branch_Indicator SHALL be readable at all viewport widths supported by the application.

### Requirement 7: Staff Assignment Step is Optional

**User Story:** As an Org_Admin, I want the staff assignment step to be optional, so that I can quickly create a branch without assigning staff if needed.

#### Acceptance Criteria

1. THE Branch_Creation_Modal SHALL allow the Org_Admin to skip Step 2 entirely by clicking a "Skip" button.
2. WHEN the Org_Admin skips Step 2, THE Branch_Creation_Modal SHALL create the branch with only the details from Step 1.
3. THE Branch_Creation_Modal SHALL allow the Org_Admin to go back from Step 2 to Step 1 to modify branch details before creation.
4. WHEN no staff members exist in the organisation, THE Branch_Creation_Modal SHALL display a message "No staff members found" and allow the Org_Admin to create the branch without assignments.

### Requirement 8: Staff Search and Filtering in Assignment Step

**User Story:** As an Org_Admin, I want to search and filter staff members in the assignment step, so that I can quickly find specific staff in large organisations.

#### Acceptance Criteria

1. THE Branch_Creation_Modal Step 2 SHALL include a search input that filters the staff list by name, email, or position.
2. WHEN the Org_Admin types in the search input, THE staff list SHALL filter in real-time to show only matching Staff_Members.
3. WHEN the search input is cleared, THE staff list SHALL show all active Staff_Members.
4. THE Branch_Creation_Modal SHALL display the count of selected staff members (e.g., "3 staff selected").

### Requirement 9: End-to-End Testing with Playwright

**User Story:** As a developer, I want automated E2E tests that simulate real user interactions for the branch creation with staff assignment and the enhanced branch selector, so that regressions are caught before deployment.

#### Acceptance Criteria

1. THE E2E_Test_Suite SHALL include a Playwright test that navigates to Settings > Branches, opens the "Add Branch" modal, fills in Step 1 details, proceeds to Step 2, selects a linked staff member, clicks "Create", and verifies the branch appears in the table with the staff member assigned.
2. THE E2E_Test_Suite SHALL include a test that skips Step 2 and verifies the branch is created without staff assignments.
3. THE E2E_Test_Suite SHALL include a test that selects an unlinked staff member with the "Invite" checkbox, creates the branch, and verifies the account creation and branch assignment.
4. THE E2E_Test_Suite SHALL include a test that verifies unlinked staff without email have a disabled invite checkbox.
5. THE E2E_Test_Suite SHALL include a test that types in the search input on Step 2 and verifies the staff list filters correctly.
6. THE E2E_Test_Suite SHALL include a test that selects a branch in the BranchSelector, verifies the colored active styling, verifies the ActiveBranchIndicator shows the branch name, then switches to "All Branches" and verifies neutral styling and hidden indicator.
7. THE E2E_Test_Suite SHALL include a test that selects a branch, navigates to different pages, and verifies the branch indicator persists across navigation and browser refresh.

### Requirement 10: Deployment and Build Verification

**User Story:** As a developer, I want the implementation to be deployed to the local dev environment with a rebuilt frontend, any pending migrations applied, and all changes pushed to git, so that the feature is immediately testable.

#### Acceptance Criteria

1. AFTER all implementation tasks are complete, THE Deployment_Process SHALL rebuild the Vite frontend in the Docker container using `docker compose build frontend --no-cache`.
2. THE Deployment_Process SHALL restart the frontend and nginx containers to serve the new build.
3. THE Deployment_Process SHALL run `docker compose exec -T app alembic upgrade head` to apply any pending database migrations.
4. THE Deployment_Process SHALL commit all changes with a descriptive commit message and push to the current git branch.
5. THE Deployment_Process SHALL verify the push succeeds without errors.

# Requirements Document

## Introduction

This feature introduces a new `branch_admin` role that sits between `org_admin` and `salesperson` in the role hierarchy. A branch admin is locked to a single assigned branch and has full operational control within that branch (invoices, customers, job cards, bookings, claims, inventory, etc.) but cannot access organisation-level settings, billing, module configuration, branch management, user role changes, or data from other branches. The branch assignment UI is also updated to exclude `org_admin` and `kiosk` users from the assignable user list, since org_admin already has implicit access via the branch switcher and kiosk is a special-purpose role.

## Glossary

- **Branch_Admin**: A new user role scoped to a single branch. Has full operational permissions within that branch but no access to org-level administration.
- **Org_Admin**: The organisation-level administrator with full access to all branches, settings, billing, modules, and user management.
- **Salesperson**: An org-scoped role with access to customer, invoice, quote, job card, and booking operations but no admin capabilities.
- **Kiosk**: A special-purpose role restricted to customer check-in and branding endpoints only.
- **Branch_Switcher**: The UI component that allows `org_admin` users to switch between branches or view "All Branches" aggregate data.
- **Branch_Assignment_Modal**: The modal dialog in Branch Management settings where org_admin assigns users to branches.
- **RBAC_Engine**: The backend role-based access control system (`app/modules/auth/rbac.py`) that enforces path-based and permission-based access rules.
- **Branch_Context_Middleware**: The backend middleware (`app/core/branch_context.py`) that reads the `X-Branch-Id` header and scopes requests to a specific branch.
- **Org_Level_Settings**: Settings pages restricted to org_admin: Billing, Module configuration, Branch management, User role assignment, and organisation-wide preferences.

## Requirements

### Requirement 1: Add branch_admin to the Role System

**User Story:** As an org_admin, I want to create users with a `branch_admin` role, so that I can delegate full branch-level operations without granting organisation-wide access.

#### Acceptance Criteria

1. THE RBAC_Engine SHALL recognise `branch_admin` as a valid role in the set of all roles.
2. THE User model SHALL accept `branch_admin` as a valid value for the `role` column check constraint.
3. WHEN a user with the `branch_admin` role authenticates, THE RBAC_Engine SHALL grant permissions equivalent to `org_admin` for branch-scoped operations (invoices, customers, vehicles, quotes, job cards, bookings, inventory, catalogue, expenses, purchase orders, scheduling, POS, staff, projects, time tracking, claims, notifications, data import/export, and reports).
4. WHEN a user with the `branch_admin` role authenticates, THE RBAC_Engine SHALL deny access to org-level administration paths: billing endpoints, module configuration endpoints, branch management endpoints, user role assignment endpoints, and organisation settings write endpoints.

### Requirement 2: Branch Scoping for branch_admin

**User Story:** As a branch_admin, I want my entire session to be scoped to my assigned branch, so that I only see and manage data belonging to my branch.

#### Acceptance Criteria

1. WHEN a `branch_admin` user logs in, THE Branch_Context_Middleware SHALL automatically set the branch context to the single branch in the user's `branch_ids` array without requiring an `X-Branch-Id` header.
2. WHILE a `branch_admin` user is authenticated, THE Branch_Context_Middleware SHALL reject any request that attempts to set `X-Branch-Id` to a branch not present in the user's `branch_ids` array, returning HTTP 403.
3. WHILE a `branch_admin` user is authenticated, THE Branch_Context_Middleware SHALL reject any request that omits the `X-Branch-Id` header (the "All Branches" scope), returning HTTP 403.
4. IF a `branch_admin` user has an empty `branch_ids` array, THEN THE RBAC_Engine SHALL deny all data-access requests and return HTTP 403 with a descriptive error message indicating no branch assignment exists.

### Requirement 3: branch_admin Cannot Access Other Branches

**User Story:** As an org_admin, I want branch_admin users to be completely isolated to their assigned branch, so that sensitive data from other branches (including Main) remains protected.

#### Acceptance Criteria

1. WHILE a `branch_admin` user is authenticated, THE RBAC_Engine SHALL filter all data queries to include only records belonging to the user's assigned branch.
2. WHEN a `branch_admin` user requests data for a branch not in the user's `branch_ids` array, THE RBAC_Engine SHALL return HTTP 403.
3. THE Branch_Context_Middleware SHALL enforce that `branch_admin` users cannot access Main branch data unless Main is explicitly present in the user's `branch_ids` array.

### Requirement 4: branch_admin UI Experience

**User Story:** As a branch_admin, I want a clean single-branch view that looks like a normal org dashboard scoped to my branch, so that I can manage my branch without confusion.

#### Acceptance Criteria

1. WHILE a `branch_admin` user is viewing the application, THE OrgLayout SHALL hide the Branch_Switcher component entirely.
2. WHILE a `branch_admin` user is viewing the application, THE OrgLayout SHALL hide navigation items marked as `adminOnly` (Settings, Branch Transfers, Staff Schedule).
3. WHILE a `branch_admin` user is viewing the application, THE OrgLayout SHALL display all non-admin navigation items that the user has module access to (Dashboard, Customers, Invoices, Quotes, Job Cards, Bookings, Inventory, Catalogue, Expenses, etc.).
4. WHEN a `branch_admin` user navigates to an org-level settings URL directly, THE application SHALL redirect the user to the Dashboard page.
5. THE OrgLayout SHALL display the assigned branch name in the header area so the branch_admin knows which branch context is active.

### Requirement 5: Org-Level Settings Restricted to org_admin

**User Story:** As an org_admin, I want to be the only role that can access organisation-level settings, so that critical configuration remains under my control.

#### Acceptance Criteria

1. THE RBAC_Engine SHALL restrict access to billing and subscription management endpoints to `org_admin` and `global_admin` roles only.
2. THE RBAC_Engine SHALL restrict access to module enable/disable endpoints to `org_admin` and `global_admin` roles only.
3. THE RBAC_Engine SHALL restrict access to branch creation and branch management endpoints to `org_admin` and `global_admin` roles only.
4. THE RBAC_Engine SHALL restrict access to user role assignment endpoints to `org_admin` and `global_admin` roles only.
5. THE RBAC_Engine SHALL restrict write access to organisation-level settings endpoints to `org_admin` and `global_admin` roles only.
6. WHEN a `branch_admin` user attempts to access any endpoint listed in criteria 1 through 5, THE RBAC_Engine SHALL return HTTP 403 with a descriptive denial message.

### Requirement 6: Branch Assignment Modal Filtering

**User Story:** As an org_admin, I want the branch assignment modal to only show users whose roles make sense for branch assignment, so that I do not accidentally assign org_admin or kiosk users to branches.

#### Acceptance Criteria

1. WHEN the Branch_Assignment_Modal is opened, THE BranchManagement page SHALL display only users with roles `branch_admin`, `salesperson`, `location_manager`, and `staff_member`.
2. WHEN the Branch_Assignment_Modal is opened, THE BranchManagement page SHALL exclude users with the `org_admin` role from the assignable user list.
3. WHEN the Branch_Assignment_Modal is opened, THE BranchManagement page SHALL exclude users with the `kiosk` role from the assignable user list.
4. WHEN the Branch_Assignment_Modal is opened, THE BranchManagement page SHALL exclude users with the `global_admin` role from the assignable user list.

### Requirement 7: branch_admin Cannot Create Branches or Manage Roles

**User Story:** As an org_admin, I want to ensure branch_admin users cannot create new branches or change user roles, so that the organisational structure remains under my control.

#### Acceptance Criteria

1. WHEN a `branch_admin` user sends a POST request to the branch creation endpoint, THE RBAC_Engine SHALL return HTTP 403.
2. WHEN a `branch_admin` user sends a PUT or PATCH request to a user role assignment endpoint, THE RBAC_Engine SHALL return HTTP 403.
3. WHEN a `branch_admin` user sends a DELETE request to a branch endpoint, THE RBAC_Engine SHALL return HTTP 403.
4. WHEN a `branch_admin` user sends a request to the branch switcher data endpoint, THE RBAC_Engine SHALL return HTTP 403.

### Requirement 8: Database Migration for branch_admin Role

**User Story:** As a developer, I want the database schema updated to support the new branch_admin role, so that the system can persist and validate the role correctly.

#### Acceptance Criteria

1. THE database migration SHALL update the `ck_users_role` check constraint on the `users` table to include `branch_admin` in the allowed values.
2. THE database migration SHALL be backward-compatible, preserving all existing user records and their current role values.
3. WHEN the migration is applied, THE `users` table SHALL accept `branch_admin` as a valid role value for new and updated records.

### Requirement 9: branch_admin Permission Set

**User Story:** As a developer, I want a clearly defined permission set for branch_admin, so that the RBAC engine can enforce consistent access control.

#### Acceptance Criteria

1. THE RBAC_Engine SHALL define a `branch_admin` permission set that includes: `invoices.*`, `customers.*`, `vehicles.*`, `quotes.*`, `jobs.*`, `bookings.*`, `inventory.*`, `catalogue.*`, `expenses.*`, `purchase_orders.*`, `scheduling.*`, `pos.*`, `staff.*`, `projects.*`, `time_tracking.*`, `claims.*`, `notifications.*`, `data_io.*`, and `reports.*`.
2. THE RBAC_Engine SHALL define the `branch_admin` permission set to exclude: `billing.*`, `modules.*`, `settings.write`, `users.role_assign`, `branches.create`, `branches.delete`, and `org.*`.
3. WHEN the `branch_admin` permission set is checked via `has_permission()`, THE RBAC_Engine SHALL return correct grant/deny results consistent with criteria 1 and 2.

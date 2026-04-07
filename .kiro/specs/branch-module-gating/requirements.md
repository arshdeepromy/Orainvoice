# Requirements Document

## Introduction

This document specifies the requirements for gating all branch-related features behind a "Branch Management" module (`branch_management` slug) in the existing module_registry system. When the module is disabled for an organisation, the application behaves as a single-location system: branch selectors, branch-scoped navigation, branch_admin role options, and branch context middleware scoping are all suppressed. When enabled, everything works as currently implemented. This allows organisations that operate from a single location to have a cleaner, simpler UI without branch-related complexity, and enables the platform to offer branch management as a paid add-on module.

The gating touches every layer of the stack:
- **Frontend**: BranchSelector component, BranchContext provider, OrgLayout (branch switcher, active branch badge), nav items (Branch Transfers, Staff Schedule), settings pages (BranchManagement, BranchSettings), StockTransfers page, GlobalBranchOverview (global admin)
- **Backend**: BranchContextMiddleware (`app/core/branch_context.py`), org/branches endpoints (`app/modules/organisations/router.py`), branch_admin role in RBAC (`app/modules/auth/rbac.py`), branch_ids in JWT claims
- **Module system**: ModuleRegistry seed, ModuleService (`app/core/modules.py`), ModuleContext on frontend

## Glossary

- **Branch_Management_Module**: A new entry in the `module_registry` table with slug `branch_management`. Controls whether branch-related features are available for an organisation.
- **Module_Registry**: The `module_registry` database table that catalogues all available modules with their slug, display name, category, dependencies, and core status.
- **Org_Module**: The `org_modules` database table that tracks per-organisation module enablement (org_id + module_slug + is_enabled).
- **Module_Service**: The backend service (`app/core/modules.py`) that checks module enablement via Redis cache and DB fallback.
- **Module_Context**: The frontend React context (`ModuleContext.tsx`) that exposes `isEnabled(slug)` to all components.
- **Branch_Selector**: The dropdown component (`BranchSelector.tsx`) in the top navigation bar that allows users to switch between branches.
- **Branch_Context**: The React context provider (`BranchContext.tsx`) that manages the currently selected branch and exposes it to all components.
- **Branch_Context_Middleware**: The backend ASGI middleware (`app/core/branch_context.py`) that reads the `X-Branch-Id` header and scopes requests to a specific branch.
- **Org_Layout**: The main application layout (`OrgLayout.tsx`) that renders the sidebar navigation, header, branch selector, and active branch indicator.
- **Branch_Admin**: A user role scoped to a single branch with full operational permissions within that branch but no org-level admin access.
- **RBAC_Engine**: The backend role-based access control system (`app/modules/auth/rbac.py`) that enforces path-based and permission-based access rules.
- **Single_Location_Mode**: The application state when `branch_management` is disabled — all data is treated as belonging to a single implicit location with no branch scoping.
- **Gated_Nav_Items**: Navigation items that are only visible when `branch_management` is enabled: "Branch Transfers" and "Staff Schedule".
- **Gated_Settings_Pages**: Settings sub-pages that are only accessible when `branch_management` is enabled: "Branch Management" (`BranchManagement.tsx`) and "Branch Settings" (`BranchSettings.tsx`).

## Requirements

### Requirement 1: Register branch_management in Module Registry

**User Story:** As a platform operator, I want `branch_management` registered as a module in the module registry, so that it can be toggled on/off per organisation like any other module.

#### Acceptance Criteria

1. THE Database_Migration SHALL insert a row into `module_registry` with slug `branch_management`, display_name "Branch Management", category "operations", is_core `false`, dependencies `[]`, and status "available".
2. THE Database_Migration SHALL use `ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING` to be idempotent.
3. THE Database_Migration SHALL NOT auto-enable `branch_management` for any existing organisation — existing orgs retain their current state until explicitly enabled.
4. WHEN a new organisation is created via the signup wizard, THE Signup_Service SHALL enable `branch_management` by default only if the organisation's subscription plan includes it in `enabled_modules`.

### Requirement 2: Auto-Enable for Existing Multi-Branch Organisations

**User Story:** As a platform operator, I want existing organisations that already use branches to have the module auto-enabled during migration, so that their workflows are not disrupted.

#### Acceptance Criteria

1. THE Database_Migration SHALL identify all organisations that have more than one row in the `branches` table.
2. FOR EACH identified multi-branch organisation, THE Database_Migration SHALL insert a row into `org_modules` with `module_slug = 'branch_management'` and `is_enabled = true`.
3. THE Database_Migration SHALL use `ON CONFLICT DO NOTHING` to avoid duplicates if the migration is re-run.
4. WHEN the migration completes, THE Module_Service SHALL return `true` for `is_enabled("branch_management")` for every organisation that had multiple branches.

### Requirement 3: Frontend — Hide Branch Selector When Module Disabled

**User Story:** As a user in a single-location organisation, I want the branch selector hidden from the navigation bar, so that I have a cleaner interface without irrelevant branch switching controls.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled for the user's organisation, THE Org_Layout SHALL not render the Branch_Selector component in the header.
2. WHEN `branch_management` is disabled, THE Org_Layout SHALL not render the active branch indicator badge in the header.
3. WHEN `branch_management` is enabled, THE Org_Layout SHALL render the Branch_Selector and active branch indicator as currently implemented.
4. THE Org_Layout SHALL read the module enablement state from the Module_Context `isEnabled('branch_management')` function.

### Requirement 4: Frontend — Hide Branch-Related Navigation Items When Module Disabled

**User Story:** As a user in a single-location organisation, I want branch-specific navigation items hidden from the sidebar, so that I only see features relevant to my setup.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled, THE Org_Layout SHALL hide the "Branch Transfers" navigation item from the sidebar.
2. WHEN `branch_management` is disabled, THE Org_Layout SHALL hide the "Staff Schedule" navigation item from the sidebar.
3. WHEN `branch_management` is enabled, THE Org_Layout SHALL show "Branch Transfers" and "Staff Schedule" navigation items as currently implemented (subject to existing `adminOnly` gating).
4. THE nav item definitions for "Branch Transfers" and "Staff Schedule" SHALL include `module: 'branch_management'` so the existing `visibleNavItems` filter handles the gating automatically.

### Requirement 5: Frontend — Gate Branch Management and Branch Settings Pages

**User Story:** As a user in a single-location organisation, I want branch management and branch settings pages inaccessible, so that I cannot accidentally navigate to features that do not apply.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled and a user navigates to the Branch Management settings URL directly, THE Application SHALL redirect the user to the Dashboard page.
2. WHEN `branch_management` is disabled and a user navigates to the Branch Settings URL directly, THE Application SHALL redirect the user to the Dashboard page.
3. WHEN `branch_management` is enabled, THE Application SHALL allow access to Branch Management and Branch Settings pages as currently implemented.
4. THE Settings page navigation (within the settings area) SHALL hide "Branch Management" and "Branch Settings" links when `branch_management` is disabled.

### Requirement 6: Frontend — Gate Stock Transfers Page

**User Story:** As a user in a single-location organisation, I want the stock transfers page inaccessible, so that inter-branch transfer workflows are hidden when there is only one location.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled and a user navigates to the Stock Transfers URL directly, THE Application SHALL redirect the user to the Dashboard page.
2. WHEN `branch_management` is enabled, THE Application SHALL allow access to the Stock Transfers page as currently implemented.

### Requirement 7: Frontend — BranchContext Behaviour When Module Disabled

**User Story:** As a developer, I want the BranchContext to operate in a no-op mode when branch_management is disabled, so that downstream components receive consistent null branch context without making unnecessary API calls.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled, THE Branch_Context_Provider SHALL skip fetching branches from the `/org/branches` endpoint.
2. WHEN `branch_management` is disabled, THE Branch_Context_Provider SHALL set `selectedBranchId` to `null` (equivalent to "All Branches" scope).
3. WHEN `branch_management` is disabled, THE Branch_Context_Provider SHALL set `branches` to an empty array.
4. WHEN `branch_management` is disabled, THE Branch_Context_Provider SHALL still expose the context value so that downstream components using `useBranch()` do not throw errors.
5. WHEN `branch_management` is enabled, THE Branch_Context_Provider SHALL behave as currently implemented — fetching branches, validating selections, and persisting to localStorage.

### Requirement 8: Backend — Skip Branch Context Scoping When Module Disabled

**User Story:** As a developer, I want the BranchContextMiddleware to pass through without scoping when branch_management is disabled, so that all data queries return unscoped results for single-location organisations.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled for the requesting user's organisation, THE Branch_Context_Middleware SHALL set `request.state.branch_id` to `None` regardless of the `X-Branch-Id` header value.
2. WHEN `branch_management` is disabled, THE Branch_Context_Middleware SHALL not validate the `X-Branch-Id` header against the organisation's branches.
3. WHEN `branch_management` is disabled, THE Branch_Context_Middleware SHALL not return 403 errors for invalid or missing branch headers.
4. WHEN `branch_management` is enabled, THE Branch_Context_Middleware SHALL behave as currently implemented — validating headers, enforcing branch_admin scoping, and rejecting invalid branch contexts.
5. THE Branch_Context_Middleware SHALL determine module enablement by calling `Module_Service.is_enabled(org_id, "branch_management")` using the Redis-cached check for performance.

### Requirement 9: Backend — Gate Branch CRUD Endpoints When Module Disabled

**User Story:** As a developer, I want branch CRUD endpoints to return appropriate errors when branch_management is disabled, so that the API is consistent with the UI gating.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled and a request is made to `POST /org/branches` (create branch), THE Branch_Router SHALL return HTTP 403 with the message "Branch management module is not enabled for this organisation".
2. WHEN `branch_management` is disabled and a request is made to `PUT /org/branches/{id}` (update branch), THE Branch_Router SHALL return HTTP 403 with the same message.
3. WHEN `branch_management` is disabled and a request is made to `DELETE /org/branches/{id}` (deactivate branch), THE Branch_Router SHALL return HTTP 403 with the same message.
4. WHEN `branch_management` is disabled, THE Branch_Router SHALL still allow `GET /org/branches` to return the single default branch (for backward compatibility with components that may reference branch data).
5. WHEN `branch_management` is enabled, THE Branch_Router SHALL allow all branch CRUD operations as currently implemented.

### Requirement 10: Backend — Hide branch_admin Role Option When Module Disabled

**User Story:** As an org_admin in a single-location organisation, I want the branch_admin role hidden from user role assignment options, so that I cannot assign a role that depends on branch infrastructure.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled, THE User_Role_Assignment endpoint SHALL exclude `branch_admin` from the list of assignable roles.
2. WHEN `branch_management` is disabled and a request attempts to set a user's role to `branch_admin`, THE User_Role_Assignment endpoint SHALL return HTTP 400 with the message "branch_admin role requires the Branch Management module to be enabled".
3. WHEN `branch_management` is enabled, THE User_Role_Assignment endpoint SHALL include `branch_admin` in the assignable roles as currently implemented.
4. WHEN `branch_management` is disabled, THE Frontend role selector component SHALL not display `branch_admin` as an option.

### Requirement 11: Backend — Gate Stock Transfer Endpoints When Module Disabled

**User Story:** As a developer, I want stock transfer API endpoints gated behind branch_management, so that inter-branch transfer operations are unavailable for single-location organisations.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled and a request is made to any stock transfer endpoint (`/org/stock-transfers/*`), THE Transfer_Router SHALL return HTTP 403 with the message "Branch management module is not enabled for this organisation".
2. WHEN `branch_management` is enabled, THE Transfer_Router SHALL allow all stock transfer operations as currently implemented.

### Requirement 12: Backend — Gate Scheduling Endpoints When Module Disabled

**User Story:** As a developer, I want branch-scoped scheduling endpoints gated behind branch_management, so that per-branch staff scheduling is unavailable for single-location organisations.

#### Acceptance Criteria

1. WHEN `branch_management` is disabled and a request is made to branch-scoped scheduling endpoints, THE Scheduling_Router SHALL return HTTP 403 with the message "Branch management module is not enabled for this organisation".
2. WHEN `branch_management` is enabled, THE Scheduling_Router SHALL allow all scheduling operations as currently implemented.

### Requirement 13: Global Admin — Branch Overview Respects Module State

**User Story:** As a global admin, I want the branch overview to indicate which organisations have branch_management enabled, so that I can provide accurate support.

#### Acceptance Criteria

1. THE Global_Admin_Branch_Overview SHALL display a "Module Status" column indicating whether `branch_management` is enabled or disabled for each organisation.
2. WHEN a Global_Admin filters the branch overview, THE Global_Admin_Branch_Overview SHALL support filtering by module status (enabled/disabled).

### Requirement 14: Module Toggle — Disable Safeguards

**User Story:** As an org_admin, I want safeguards when disabling branch_management, so that I understand the impact on existing branch data and users before proceeding.

#### Acceptance Criteria

1. WHEN an org_admin attempts to disable `branch_management` and the organisation has more than one active branch, THE Module_Management_UI SHALL display a confirmation warning: "Disabling Branch Management will hide all branch features. Your existing branch data will be preserved but branch scoping will be suspended. Users with the branch_admin role will lose branch-specific access."
2. WHEN an org_admin confirms the disable action, THE Module_Service SHALL set `branch_management` to disabled for the organisation.
3. WHEN `branch_management` is disabled and the organisation has users with the `branch_admin` role, THE Module_Service SHALL NOT automatically change those users' roles — the org_admin must reassign roles manually.
4. WHEN `branch_management` is re-enabled, THE Application SHALL restore all branch features using the preserved branch data without requiring reconfiguration.

### Requirement 15: Dependency Registration

**User Story:** As a developer, I want branch_management registered in the module dependency graph, so that modules depending on branch infrastructure are correctly gated.

#### Acceptance Criteria

1. THE DEPENDENCY_GRAPH in `app/core/modules.py` SHALL NOT list `branch_management` as a dependency for any existing module (branch features are orthogonal to other modules).
2. THE Module_Service SHALL treat `branch_management` as an independent, non-core module with no dependencies and no dependents.
3. WHEN `branch_management` is disabled, THE Module_Service SHALL not cascade-disable any other modules.
4. WHEN `branch_management` is enabled, THE Module_Service SHALL not require any other modules to be enabled first.

# Implementation Plan: branch_admin Role

## Overview

Introduce the `branch_admin` role across four layers: database migration, backend RBAC + middleware, JWT claims, and frontend UI. Each task builds incrementally — database first, then backend permissions, then middleware scoping, then frontend. Property tests validate correctness at each layer.

## Tasks

- [x] 1. Database migration — add branch_admin to role CHECK constraint
  - Create `alembic/versions/2026_04_04_0900-0136_add_branch_admin_role.py`
  - Drop existing `ck_users_role` constraint and recreate with `branch_admin` added between `org_admin` and `location_manager`
  - Follow the exact pattern from migration `0124_add_kiosk_role.py`
  - Downgrade must restore the constraint without `branch_admin`
  - _Requirements: 8.1, 8.2, 8.3_

- [x] 2. Backend RBAC — role constant, permissions, and path-based access rules
  - [x] 2.1 Add `BRANCH_ADMIN` constant and permission set to `app/modules/auth/rbac.py`
    - Add `BRANCH_ADMIN = "branch_admin"` constant
    - Add `"branch_admin"` to `ALL_ROLES` set
    - Add `"branch_admin"` permission entry to `ROLE_PERMISSIONS` with granted domains: `invoices.*`, `customers.*`, `vehicles.*`, `quotes.*`, `jobs.*`, `bookings.*`, `inventory.*`, `catalogue.*`, `expenses.*`, `purchase_orders.*`, `scheduling.*`, `pos.*`, `staff.*`, `projects.*`, `time_tracking.*`, `claims.*`, `notifications.*`, `data_io.*`, `reports.*`
    - _Requirements: 1.1, 1.3, 9.1_

  - [x] 2.2 Add branch_admin denied prefixes and path-based access rules
    - Add `BRANCH_ADMIN_DENIED_PREFIXES` tuple: `/api/v1/org/users`, `/api/v1/billing/`, `/api/v1/billing`, `/api/v1/admin/`, `/api/v1/org/branches`
    - Add `branch_admin` case to `check_role_path_access()` — deny `GLOBAL_ADMIN_ONLY_PREFIXES`, deny `BRANCH_ADMIN_DENIED_PREFIXES`, deny write methods on `/api/v1/org/settings`
    - _Requirements: 1.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.1, 7.2, 7.3, 7.4_

  - [x] 2.3 Update convenience dependency functions
    - Add `BRANCH_ADMIN` to the org-scoped role check in `require_role()` inner function
    - Update `require_any_org_role()` to include `BRANCH_ADMIN`
    - Update `require_any_org_member()` to include `BRANCH_ADMIN`
    - Add `require_branch_admin_or_above()` convenience dependency
    - _Requirements: 1.3, 9.1_

  - [x] 2.4 Write property tests for branch_admin granted permissions
    - **Property 1: branch_admin granted permissions are correct**
    - **Validates: Requirements 1.3, 9.1**

  - [x] 2.5 Write property tests for branch_admin denied permissions
    - **Property 2: branch_admin denied permissions are correct**
    - **Validates: Requirements 1.4, 9.2**

  - [x] 2.6 Write property tests for branch_admin denied org-level paths
    - **Property 3: branch_admin denied org-level paths**
    - **Validates: Requirements 1.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. JWT and AuthMiddleware — add branch_ids claim
  - [x] 4.1 Add `branch_ids` parameter to `create_access_token()` in `app/modules/auth/jwt.py`
    - Add `branch_ids: list[str] | None = None` parameter
    - Include `"branch_ids": [str(bid) for bid in (branch_ids or [])]` in the JWT payload
    - _Requirements: 2.1_

  - [x] 4.2 Update all `create_access_token()` call sites to pass `branch_ids`
    - Update `app/modules/auth/service.py` — all calls (login, refresh, MFA verify, Google login, passkey login, signup) to pass `user.branch_ids`
    - Update `app/modules/auth/mfa_service.py` — MFA completion call to pass `user.branch_ids`
    - _Requirements: 2.1_

  - [x] 4.3 Update AuthMiddleware to extract `branch_ids` from JWT payload
    - Add `request.state.branch_ids = payload.get("branch_ids", [])` in the auth middleware JWT decode path
    - _Requirements: 2.1_

- [x] 5. Backend middleware — branch_admin auto-scoping in BranchContextMiddleware
  - [x] 5.1 Add branch_admin scoping logic to `app/core/branch_context.py`
    - After existing auth check, read `role` from `request.state`
    - If `role == "branch_admin"`: check `branch_ids` from `request.state`; if empty return 403 "No branch assignment"; validate `X-Branch-Id` matches `branch_ids[0]` or reject with 403; reject missing header with 403; set `request.state.branch_id` to assigned branch
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3_

  - [x] 5.2 Write property test for branch_admin auto-scoped to assigned branch
    - **Property 4: branch_admin auto-scoped to assigned branch**
    - **Validates: Requirements 2.1**

  - [x] 5.3 Write property test for branch_admin cross-branch rejection
    - **Property 5: branch_admin cross-branch rejection**
    - **Validates: Requirements 2.2, 3.2, 3.3**

  - [x] 5.4 Write property test for branch_admin all-branches scope rejection
    - **Property 6: branch_admin all-branches scope rejection**
    - **Validates: Requirements 2.3**

- [x] 6. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend AuthContext — add branch_admin role type and branch_ids
  - Update `UserRole` type union in `frontend/src/contexts/AuthContext.tsx` to include `'branch_admin'`
  - Add `branch_ids?: string[]` to the `AuthUser` interface
  - Update `userFromToken()` to extract `branch_ids` from JWT payload
  - Add `isBranchAdmin: user?.role === 'branch_admin'` computed property to `AuthContextValue` and the provider value
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 8. Frontend BranchContext — auto-lock for branch_admin
  - In `frontend/src/contexts/BranchContext.tsx`:
  - When `user.role === 'branch_admin'`, auto-set `selectedBranchId` to `user.branch_ids?.[0]` and persist to localStorage; skip the branch fetch + validation flow
  - Add `isBranchLocked: boolean` to `BranchContextValue` — true when role is `branch_admin`
  - _Requirements: 2.1, 4.1_

- [x] 9. Frontend OrgLayout — hide admin nav and branch switcher for branch_admin
  - In `frontend/src/layouts/OrgLayout.tsx`:
  - In `visibleNavItems` filter: treat `branch_admin` like non-admin — exclude items where `adminOnly === true`
  - Conditionally hide `<BranchSelector />` when `user.role === 'branch_admin'`
  - Display the assigned branch name as a static badge in the header when role is `branch_admin`
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 10. Frontend route guard — redirect branch_admin from /settings
  - In `frontend/src/App.tsx`:
  - Add a `RequireOrgAdmin` (or similar) route guard component that redirects `branch_admin` users away from `/settings` routes to `/dashboard`
  - Wrap the settings route(s) with this guard
  - _Requirements: 4.4_

- [x] 11. Frontend BranchManagement — filter assignment modal by role
  - In `frontend/src/pages/settings/BranchManagement.tsx`:
  - In the "Assign Users" modal, filter the `users` list to only show users with roles: `branch_admin`, `salesperson`, `location_manager`, `staff_member`
  - Exclude `org_admin`, `global_admin`, `franchise_admin`, and `kiosk` from the assignable list
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 12. Frontend property tests
  - [x] 12.1 Write property test for branch_admin nav item visibility
    - **Property 7: branch_admin nav item visibility**
    - **Validates: Requirements 4.2, 4.3**

  - [x] 12.2 Write property test for branch assignment modal role filtering
    - **Property 8: Branch assignment modal role filtering**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**

- [x] 13. Final checkpoint — Ensure all unit and property tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Playwright E2E tests for branch_admin role
  - [x] 14.1 Create Playwright test setup for branch_admin login
    - Create `tests/e2e/frontend/branch-admin.spec.ts`
    - Mock a branch_admin user login with a single assigned branch
    - Verify login succeeds and dashboard loads with branch-scoped view
    - _Requirements: 2.1, 4.1_

  - [x] 14.2 Write E2E test: branch_admin sees no branch switcher
    - Login as branch_admin → verify BranchSelector is NOT rendered
    - Verify the assigned branch name is displayed as a static badge in the header
    - _Requirements: 4.1, 4.5_

  - [x] 14.3 Write E2E test: branch_admin cannot access Settings
    - Login as branch_admin → navigate to /settings → verify redirect to /dashboard
    - Verify Settings nav item is NOT visible in the sidebar
    - _Requirements: 4.2, 4.4_

  - [x] 14.4 Write E2E test: branch_admin can access operational pages
    - Login as branch_admin → navigate to /invoices, /customers, /job-cards, /bookings
    - Verify each page loads successfully (no 403 errors)
    - _Requirements: 1.3, 4.3_

  - [x] 14.5 Write E2E test: branch assignment modal excludes org_admin and kiosk
    - Login as org_admin → navigate to Settings → Branches → click Assign Users on a branch
    - Verify org_admin and kiosk users are NOT shown in the assignable list
    - Verify branch_admin and salesperson users ARE shown
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 14.6 Write E2E test: branch_admin denied billing and admin endpoints
    - Login as branch_admin → attempt to navigate to /settings/billing (via direct URL)
    - Verify redirect to /dashboard or 403 response
    - _Requirements: 5.1, 5.6, 7.1_

- [x] 15. Rebuild containers and deploy
  - [x] 15.1 Rebuild Docker backend container with all changes
    - Run `docker compose build app --no-cache`
    - Run `docker compose up -d app`
    - Verify app starts successfully and migration 0136 runs
    - _Requirements: 8.1, 8.3_

  - [x] 15.2 Rebuild Docker frontend container (Vite build)
    - Run `docker compose build frontend --no-cache`
    - Run `docker compose up -d frontend nginx`
    - Verify frontend serves the updated build with branch_admin UI changes
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 15.3 Run demo seed script to update demo org
    - Run `docker compose exec app python scripts/seed_demo_org_admin.py`
    - Verify all modules and flags are synced

- [ ] 16. Git commit and push all changes
  - [-] 16.1 Stage, commit, and push to remote
    - Stage all new and modified files
    - Commit with descriptive message: "feat: add branch_admin role with single-branch scoping and RBAC"
    - Push to remote
    - _Requirements: all_

- [~] 17. Final E2E checkpoint
  - Verify all Playwright E2E tests pass against the running containers
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The design uses Python (backend) and TypeScript/React (frontend) — no language selection needed
- Migration sequence number is 0136, following the latest migration 0135

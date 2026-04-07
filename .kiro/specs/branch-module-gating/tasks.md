# Implementation Plan: Branch Module Gating

## Overview

Gate all branch-related features behind a `branch_management` module toggle. Implementation proceeds bottom-up: database migration first, then backend middleware/router gating, then frontend context/layout/route guards, then global admin enhancements and disable safeguards. Each task builds incrementally on the previous — no orphaned code.

## Tasks

- [x] 1. Database migration — register branch_management module and auto-enable for multi-branch orgs
  - [x] 1.1 Create Alembic migration `alembic/versions/2026_04_05_0900-0137_register_branch_management_module.py`
    - Insert into `module_registry`: slug `branch_management`, display_name "Branch Management", description "Multi-branch support: branch selector, branch-scoped data, inter-branch transfers, per-branch scheduling, and branch_admin role.", category "operations", is_core `false`, dependencies `[]`, incompatibilities `[]`, status "available"
    - Use `ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING` for idempotency
    - Subquery: find all `org_id` from `branches` grouped by `org_id` having `COUNT(*) > 1`
    - For each, insert into `org_modules` with `module_slug = 'branch_management'`, `is_enabled = true`, using `ON CONFLICT DO NOTHING`
    - Downgrade: delete from `org_modules` where `module_slug = 'branch_management'`, then delete from `module_registry` where `slug = 'branch_management'`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4_

  - [x] 1.2 Write property test for migration auto-enable correctness
    - **Property 1: Migration auto-enable correctness**
    - Generate random sets of orgs with varying branch counts; verify module enablement matches branch count > 1
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 1.3, 2.2, 2.4**

- [x] 2. Backend — shared `require_branch_module` dependency and middleware changes
  - [x] 2.1 Create `require_branch_module` FastAPI dependency
    - Add to `app/modules/organisations/router.py` (or a shared deps file)
    - Extract `org_id` from `request.state`, instantiate `ModuleService(db)`, call `is_enabled(org_id, "branch_management")`
    - If disabled, raise `HTTPException(status_code=403, detail="Branch management module is not enabled for this organisation")`
    - _Requirements: 9.1, 9.2, 9.3, 11.1, 12.1_

  - [x] 2.2 Update `BranchContextMiddleware` in `app/core/branch_context.py`
    - Add early check after extracting `org_id`: if `org_id` and module disabled → set `request.state.branch_id = None` and pass through immediately (no header validation, no DB lookup, no 403)
    - Add `_is_branch_module_enabled(org_id)` helper using `ModuleService.is_enabled` with a lightweight DB session
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 2.3 Write property test for middleware passthrough when disabled
    - **Property 6: Middleware passthrough when disabled**
    - Generate random X-Branch-Id headers (valid UUIDs, invalid strings, None); verify branch_id=None and no 403 when module disabled
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 8.1, 8.3**

- [x] 3. Backend — gate branch CRUD, transfer, and scheduling routers
  - [x] 3.1 Add `require_branch_module` dependency to mutating branch endpoints in `app/modules/organisations/router.py`
    - Gate: `POST /org/branches` (create), `PUT /org/branches/{id}` (update), `DELETE /org/branches/{id}` (deactivate), `POST /org/branches/{id}/reactivate`
    - Leave `GET /org/branches` ungated for backward compatibility
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 3.2 Add `require_branch_module` dependency to all endpoints in `app/modules/inventory/transfer_router.py`
    - Gate all transfer endpoints: create, list, approve, ship, receive, cancel
    - _Requirements: 11.1, 11.2_

  - [x] 3.3 Add `require_branch_module` dependency to all endpoints in `app/modules/scheduling/router.py`
    - Gate all scheduling endpoints: create, list, update, delete
    - _Requirements: 12.1, 12.2_

  - [x] 3.4 Write property tests for branch CRUD mutation gating
    - **Property 7: Branch CRUD mutation gating**
    - Generate random HTTP methods (POST/PUT/DELETE) and branch IDs; verify 403 when module disabled
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 9.1, 9.2, 9.3**

  - [x] 3.5 Write property test for GET /org/branches accessible when disabled
    - **Property 8: GET /org/branches accessible when disabled**
    - Generate random orgs with module disabled; verify GET returns 200
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 9.4**

  - [x] 3.6 Write property test for transfer and scheduling endpoint gating
    - **Property 10: Transfer and scheduling endpoint gating**
    - Generate random transfer/scheduling endpoints; verify 403 when module disabled
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 11.1, 12.1**

- [x] 4. Backend — gate branch_admin role assignment
  - [x] 4.1 Update `invite_user` and `update_user` in `app/modules/organisations/router.py`
    - When `branch_management` is disabled and requested role is `branch_admin`, return HTTP 400 with "branch_admin role requires the Branch Management module to be enabled"
    - When listing assignable roles, exclude `branch_admin` if module disabled
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 4.2 Write property test for role assignment gating
    - **Property 9: Role assignment gating**
    - Generate random user/role combinations; verify branch_admin rejected when disabled, accepted when enabled
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**

- [x] 5. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [x] 6. Frontend — BranchContext no-op mode when module disabled
  - [x] 6.1 Update `frontend/src/contexts/BranchContext.tsx`
    - Import `useModules` from `ModuleContext`
    - Read `isEnabled('branch_management')` at the top of `BranchProvider`
    - When disabled: skip `fetchBranches` effect entirely (no API call to `/org/branches`), set `branches` to `[]`, set `selectedBranchId` to `null`, still expose context value so `useBranch()` consumers don't throw
    - When enabled: no change from current implementation
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 6.2 Write property test for BranchContext no-op mode
    - **Property 5: BranchContext no-op mode**
    - Generate random module states; verify context values when disabled (null branch, empty array, no API call)
    - Test file: `frontend/src/pages/__tests__/branch-module-gating.properties.test.ts`
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

- [x] 7. Frontend — OrgLayout changes (BranchSelector, nav items)
  - [x] 7.1 Update nav item definitions in `frontend/src/layouts/OrgLayout.tsx`
    - Add `module: 'branch_management'` to the "Branch Transfers" nav item (`{ to: '/branch-transfers', ... }`)
    - Add `module: 'branch_management'` to the "Staff Schedule" nav item (`{ to: '/staff-schedule', ... }`)
    - The existing `visibleNavItems` filter already checks `item.module` against `isEnabled()` — no filter logic changes needed
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 7.2 Conditionally render BranchSelector and active branch badge in OrgLayout header
    - Read `isEnabled('branch_management')` from `useModules()`
    - Wrap `<BranchSelector />` and active branch indicator in `{isBranchModuleEnabled && ...}`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 7.3 Write property test for BranchSelector conditional rendering
    - **Property 2: BranchSelector and badge conditional rendering**
    - Generate random module states; verify BranchSelector presence matches enablement
    - Test file: `frontend/src/pages/__tests__/branch-module-gating.properties.test.ts`
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 7.4 Write property test for nav item visibility gating
    - **Property 3: Nav item visibility gating**
    - Generate random module states; verify nav item filtering for Branch Transfers and Staff Schedule
    - Test file: `frontend/src/pages/__tests__/branch-module-gating.properties.test.ts`
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [x] 8. Frontend — route guards for branch-gated pages
  - [x] 8.1 Add module gate to `frontend/src/pages/settings/BranchManagement.tsx`
    - Check `isEnabled('branch_management')` at top of component; if disabled, render `<Navigate to="/dashboard" replace />`
    - _Requirements: 5.1, 5.3_

  - [x] 8.2 Add module gate to `frontend/src/pages/settings/BranchSettings.tsx`
    - Same pattern: redirect to `/dashboard` when module disabled
    - _Requirements: 5.2, 5.3_

  - [x] 8.3 Add module gate to `frontend/src/pages/inventory/StockTransfers.tsx`
    - Same pattern: redirect to `/dashboard` when module disabled
    - _Requirements: 6.1, 6.2_

  - [x] 8.4 Hide "Branch Management" and "Branch Settings" links in settings page sidebar when module disabled
    - Read `isEnabled('branch_management')` and conditionally render the settings nav links
    - _Requirements: 5.4_

  - [x] 8.5 Filter out `branch_admin` from frontend role selector when module disabled
    - In the user invite/edit role dropdown, exclude `branch_admin` option when `isEnabled('branch_management')` is false
    - _Requirements: 10.4_

  - [x] 8.6 Write property test for branch-gated page redirect
    - **Property 4: Branch-gated page redirect**
    - Generate random module states + page URLs; verify redirect behavior
    - Test file: `frontend/src/pages/__tests__/branch-module-gating.properties.test.ts`
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 6.1, 6.2**

- [x] 9. Checkpoint — Ensure all frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Global admin — branch overview module status column
  - [x] 10.1 Extend `GET /admin/branches` backend endpoint in `app/modules/admin/router.py`
    - Add `branch_module_enabled: boolean` per row via LEFT JOIN on `org_modules` where `module_slug = 'branch_management'`
    - _Requirements: 13.1_

  - [x] 10.2 Update `frontend/src/pages/admin/GlobalBranchOverview.tsx`
    - Add `branch_module_enabled` to `BranchRow` interface
    - Add "Module Status" column to the table showing enabled/disabled badge per org
    - Add "Module Status" filter dropdown (enabled/disabled/all) alongside existing status filter
    - Pass `module_status` query param to backend
    - Use safe API patterns: `res.data?.branches ?? []`
    - _Requirements: 13.1, 13.2_

- [x] 11. Module disable safeguards UI
  - [x] 11.1 Add confirmation dialog to module management UI
    - When org_admin toggles `branch_management` off and org has >1 active branch, show confirmation warning: "Disabling Branch Management will hide all branch features. Your existing branch data will be preserved but branch scoping will be suspended. Users with the branch_admin role will lose branch-specific access."
    - On confirm: proceed with disable via existing `ModuleService.force_disable_module`
    - No automatic role changes — org_admin must reassign `branch_admin` users manually
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 11.2 Write property test for disable preserves branch_admin user roles
    - **Property 11: Disable preserves branch_admin user roles**
    - Generate orgs with branch_admin users; disable module; verify roles unchanged in DB
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 14.3**

  - [x] 11.3 Write property test for disable/re-enable round trip
    - **Property 12: Disable/re-enable round trip**
    - Generate orgs with branch data; disable then re-enable; verify state restored
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 14.4**

  - [x] 11.4 Write property test for module independence
    - **Property 13: Module independence — no cascade effects**
    - Generate random module states; enable/disable branch_management; verify no other modules changed
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 15.2, 15.3, 15.4**

  - [x] 11.5 Write property test for signup plan gating
    - **Property 14: Signup plan gating**
    - Generate random plans with/without branch_management; create org; verify enablement matches plan
    - Test file: `tests/properties/test_branch_module_gating_properties.py`
    - **Validates: Requirements 1.4**

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The design uses Python (backend) and TypeScript/React (frontend) — no language selection needed
- Migration sequence number is 0137, following the latest migration 0136
- The `require_branch_module` dependency is reused across branch CRUD, transfer, and scheduling routers
- `GET /org/branches` is intentionally left ungated for backward compatibility

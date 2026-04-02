# Implementation Plan: Branch Staff Assignment and Switcher

## Overview

Frontend-only implementation that enhances BranchManagement.tsx with a two-step branch creation modal (details → staff assignment), upgrades BranchSelector.tsx with conditional active styling, and adds an ActiveBranchIndicator to OrgLayout.tsx. All changes consume existing API endpoints with safe-api-consumption patterns. No backend changes or migrations.

## Tasks

- [x] 1. Add TypeScript interfaces and staff-fetching logic to BranchManagement.tsx
  - [x] 1.1 Define `StaffMemberFromAPI`, `StaffAssignmentSelection`, and `ModalStep` types inline in BranchManagement.tsx
    - Add `StaffMemberFromAPI` interface matching `GET /api/v2/staff` response shape
    - Add `StaffAssignmentSelection` interface with `staffId`, `userId`, `email`, `name`, `selected`, `canInvite` fields
    - Add `ModalStep = 'details' | 'staff'` type alias
    - _Requirements: 1.3, 1.5_

  - [x] 1.2 Implement `useStaffForBranch` local hook inside BranchManagement.tsx
    - Fetch `GET /api/v2/staff` with `params: { is_active: true }` and `AbortController` cleanup
    - Use safe consumption: `res.data?.staff ?? []` for the staff array
    - Return `{ staff, loading, error, retry }` tuple
    - _Requirements: 1.3, 1.4_

- [x] 2. Implement two-step branch creation modal in BranchManagement.tsx
  - [x] 2.1 Convert existing "Add Branch" modal to Step 1 (details) with step navigation
    - Add `modalStep` state defaulting to `'details'`
    - Keep existing name/address/phone fields in Step 1
    - Add "Next" button (enabled only when `form.name.trim().length > 0`) to proceed to Step 2
    - Add "Create" button to skip Step 2 and create branch immediately (existing `saveBranch` flow)
    - Reset `modalStep` to `'details'` when modal closes
    - _Requirements: 1.1, 1.2, 7.1, 7.2_

  - [x] 2.2 Write property test: Step navigation requires valid branch name (Property 1)
    - **Property 1: Step navigation requires valid branch name**
    - Generate arbitrary strings with `fc.string()`. Verify "Next" is enabled iff `name.trim().length > 0`
    - **Validates: Requirements 1.2**

  - [x] 2.3 Implement Step 2 — staff list display with linked/unlinked distinction
    - Call `useStaffForBranch` on Step 2 mount to fetch active staff
    - Render each staff member with name, position, email (or placeholder for null)
    - Show "Has account" `<Badge variant="info">` for linked staff (`user_id !== null`)
    - Show "No account" `<Badge variant="neutral">` for unlinked staff (`user_id === null`)
    - Show "Grant branch access" checkbox for linked staff
    - Show "Invite to manage this branch" checkbox for unlinked staff
    - Disable checkbox + show tooltip "Email address required to create account" for unlinked staff with no email
    - Show "No staff members found" message when staff list is empty
    - Show error message with "Retry" and "Skip" buttons on fetch failure
    - _Requirements: 1.3, 1.4, 1.5, 2.1, 2.4, 3.1, 3.3, 3.4, 7.4_

  - [x] 2.4 Write property test: Badge classification by account status (Property 3)
    - **Property 3: Badge classification by account status**
    - Generate staff objects with `user_id` as either `null` or `fc.uuid()`. Verify badge text is "Has account" when `user_id !== null`, "No account" when `user_id === null`
    - **Validates: Requirements 2.4, 3.4**

  - [x] 2.5 Write property test: Unlinked staff without email cannot be invited (Property 5)
    - **Property 5: Unlinked staff without email cannot be invited**
    - Generate unlinked staff (`user_id: null`) with `email` as `null` or `fc.constant('')`. Verify checkbox is disabled and staff cannot be added to selection
    - **Validates: Requirements 3.3**

- [x] 3. Implement staff selection and search in Step 2
  - [x] 3.1 Implement checkbox toggle selection management
    - Track selections in a `Map<string, StaffAssignmentSelection>` or array state
    - Toggle adds/removes staff from selection set on checkbox change
    - Display "N staff selected" count below the search input
    - _Requirements: 2.2, 2.3, 3.2_

  - [x] 3.2 Write property test: Checkbox toggle manages selection set (Property 4)
    - **Property 4: Checkbox toggle manages selection set**
    - Generate a list of staff and random toggle sequences. Verify selection set size changes by exactly 1 per toggle
    - **Validates: Requirements 2.2, 2.3, 3.2**

  - [x] 3.3 Implement search input filtering by name, email, or position
    - Add search `<Input>` at top of Step 2 staff list
    - Filter staff in-memory using case-insensitive substring match on `name`, `email`, `position`
    - Clear search restores full list
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 3.4 Write property test: Staff search filters correctly (Property 9)
    - **Property 9: Staff search filters by name, email, or position**
    - Generate random staff lists and search queries. Verify filtered results contain exactly those staff whose name, email, or position contains the query as case-insensitive substring
    - **Validates: Requirements 8.1, 8.2, 8.3**

  - [x] 3.5 Write property test: Selected count matches actual selections (Property 10)
    - **Property 10: Selected count matches actual selections**
    - Generate random toggle sequences. Verify displayed count equals selection set size
    - **Validates: Requirements 8.4**

  - [x] 3.6 Add "Back", "Skip", and "Create" buttons to Step 2
    - "Back" returns to Step 1 preserving form data
    - "Skip" creates branch without staff assignments (calls `POST /org/branches` only)
    - "Create" triggers full creation flow with staff assignments
    - _Requirements: 7.1, 7.2, 7.3, 4.5_

- [x] 4. Checkpoint — Verify modal flow
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement branch creation with staff assignment execution
  - [x] 5.1 Implement the sequential creation flow on "Create" click
    - Step 1: `POST /org/branches` with `{ name, address, phone }`, extract `branchRes.data?.id ?? ''`
    - Step 2: For each selected linked staff, call `POST /org/branches/assign-user` with `{ user_id, branch_ids: [newBranchId] }`
    - Step 3: For each selected unlinked staff, call `POST /api/v2/staff/{id}/create-account` with `{ password: <generated> }`, extract `res.data?.user_id ?? ''`, then call `POST /org/branches/assign-user`
    - Use `Promise.allSettled` for parallel staff assignments after branch creation
    - On partial failure: show warning toast listing failed staff names, keep the branch
    - On full success: show success toast, close modal, refresh branch list via `fetchData()`
    - All API responses use safe consumption patterns (`?.` and `?? fallback`)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 5.2 Write property test: API call orchestration matches staff type (Property 6)
    - **Property 6: API call orchestration matches staff type**
    - Generate mixed lists of linked and unlinked staff selections. Verify correct count of `assign-user` calls (one per linked) and `create-account` + `assign-user` call pairs (one per invitable unlinked)
    - **Validates: Requirements 4.2, 4.3**

- [x] 6. Enhance BranchSelector.tsx with conditional active styling
  - [x] 6.1 Add conditional Tailwind classes to BranchSelector based on selection state
    - When `selectedBranchId !== null`: apply `bg-blue-50 border-blue-400 text-blue-700 font-medium` classes
    - When `selectedBranchId === null` ("All Branches"): keep current neutral `bg-gray-50 border-gray-300 text-gray-700` classes
    - Keep the component as a `<select>` with the same `onChange` handler
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 6.2 Write property test: Branch selector styling reflects selection state (Property 7)
    - **Property 7: Branch selector styling reflects selection state**
    - Generate random branch IDs (including null). Verify active CSS classes applied when `selectedBranchId !== null`, neutral classes when `null`
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 7. Add ActiveBranchIndicator to OrgLayout.tsx header
  - [x] 7.1 Implement ActiveBranchIndicator inline in OrgLayout.tsx
    - Import `useBranch` from BranchContext
    - Render adjacent to `<BranchSelector />` in the header
    - When `selectedBranchId !== null`: show colored dot (●) + branch name text in a pill/badge
    - When `selectedBranchId === null`: render nothing (hidden)
    - Truncate branch name on small viewports with `truncate` and `max-w-[120px] sm:max-w-[200px]`
    - Update immediately on branch switch (reactive via context)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 7.2 Write property test: Active branch indicator matches current selection (Property 8)
    - **Property 8: Active branch indicator matches current selection**
    - Generate sequences of branch switches. Verify indicator text equals the currently selected branch name, and is hidden when "All Branches" is selected
    - **Validates: Requirements 6.1, 6.4**

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Write Playwright E2E tests for branch staff assignment and switcher
  - [x] 9.1 Write E2E test: Two-step branch creation with staff assignment
    - Navigate to Settings > Branches, click "Add Branch"
    - Fill in branch name/address/phone in Step 1, click "Next"
    - Verify Step 2 shows staff list fetched from API
    - Select a linked staff member via checkbox, verify "Has account" badge visible
    - Click "Create", verify branch appears in table
    - Verify the assigned staff member has the new branch in their branch_ids
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 4.1, 4.2_

  - [x] 9.2 Write E2E test: Skip staff assignment step
    - Open "Add Branch" modal, fill Step 1 details
    - Click "Skip" on Step 2 (or "Create" on Step 1)
    - Verify branch is created without staff assignments
    - _Requirements: 7.1, 7.2, 4.5_

  - [x] 9.3 Write E2E test: Invite unlinked staff during branch creation
    - Open "Add Branch" modal, proceed to Step 2
    - Find an unlinked staff member (no account badge)
    - Check "Invite to manage this branch" checkbox
    - Click "Create", verify account creation + branch assignment
    - _Requirements: 3.1, 3.2, 4.3_

  - [x] 9.4 Write E2E test: Unlinked staff without email has disabled checkbox
    - Open "Add Branch" modal, proceed to Step 2
    - Find an unlinked staff member without email
    - Verify checkbox is disabled with tooltip "Email address required to create account"
    - _Requirements: 3.3_

  - [x] 9.5 Write E2E test: Staff search filtering in Step 2
    - Open "Add Branch" modal, proceed to Step 2
    - Type a staff member's name in the search input
    - Verify the list filters to show only matching staff
    - Clear search, verify full list restored
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 9.6 Write E2E test: Enhanced BranchSelector visual feedback
    - Login as Org_Admin, navigate to dashboard
    - Select a specific branch from the BranchSelector dropdown
    - Verify the selector shows colored/active styling (blue background)
    - Verify the ActiveBranchIndicator shows the branch name with colored dot
    - Switch to "All Branches", verify neutral styling and indicator hidden
    - _Requirements: 5.1, 5.2, 5.3, 6.1, 6.3_

  - [x] 9.7 Write E2E test: Branch selector persists across navigation
    - Select a branch, navigate to different pages (invoices, customers, etc.)
    - Verify the branch indicator stays visible and correct on each page
    - Refresh the browser, verify the selection is restored
    - _Requirements: 6.4_

- [-] 10. Deployment — Rebuild frontend, run migrations, git push
  - [-] 10.1 Rebuild Vite frontend in Docker container
    - Run `docker compose build frontend --no-cache` to rebuild the frontend with all new component changes
    - Verify the build completes without errors (check for TypeScript/Vite build warnings)
    - Run `docker compose up -d frontend nginx` to deploy the new frontend
    - _No backend changes or migrations needed for this feature_

  - [~] 10.2 Run Alembic migrations on local dev containers (if any pending)
    - Run `docker compose exec -T app alembic upgrade head` to apply any pending migrations
    - Verify migrations complete successfully
    - _Note: This feature has no new migrations, but run to ensure environment is current_

  - [~] 10.3 Git commit and push all changes
    - Stage all modified and new files
    - Commit with message: "feat(branch): add staff assignment to branch creation + enhanced branch selector"
    - Push to the current branch
    - Verify push succeeds

- [~] 11. Final verification — End-to-end smoke test
  - Open the app in browser at the deployed URL
  - Create a new branch with staff assignment
  - Verify the enhanced BranchSelector shows active styling when a branch is selected
  - Verify the ActiveBranchIndicator appears in the header
  - Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- This is a frontend-only feature — no backend changes, no migrations
- All API calls must follow safe-api-consumption patterns (`.data?.property ?? fallback`, `AbortController` cleanup)
- Property tests use `fast-check` with `{ numRuns: 100 }` minimum
- Existing APIs reused: `GET /api/v2/staff`, `POST /org/branches`, `POST /org/branches/assign-user`, `POST /api/v2/staff/{id}/create-account`
- Files modified: `BranchManagement.tsx`, `BranchSelector.tsx`, `OrgLayout.tsx`

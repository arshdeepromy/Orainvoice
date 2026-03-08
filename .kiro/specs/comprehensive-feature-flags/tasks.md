# Implementation Plan: Comprehensive Feature Flags

## Overview

Extend the existing feature flag system to provide end-to-end feature gating across the entire platform. This involves schema enhancements, a comprehensive seed migration (~45 flags), backend middleware for API gating, frontend FeatureGate component and enhanced context, a redesigned admin UI with category grouping/search/filters, bulk evaluation in the engine, and route/navigation gating. The implementation uses the existing `evaluate_flag` pure function, `FeatureFlagCRUDService`, `FeatureFlagContext`, and `BaseHTTPMiddleware` patterns.

## Tasks

- [x] 1. Database schema migration and model update
  - [x] 1.1 Create Alembic migration to add `category`, `access_level`, `dependencies`, `updated_by` columns and indexes
    - Add `category` (String, default `"Core"`, indexed) to `feature_flags` table
    - Add `access_level` (String, default `"all_users"`) to `feature_flags` table
    - Add `dependencies` (JSONB array, default `[]`) to `feature_flags` table
    - Add `updated_by` (UUID, FK to `users.id`, nullable) to `feature_flags` table
    - Add index on `is_active` column
    - Add index on `category` column
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 1.2 Update the `FeatureFlag` SQLAlchemy model in `app/modules/feature_flags/models.py`
    - Add `category`, `access_level`, `dependencies`, `updated_by` mapped columns matching the migration
    - Ensure `updated_at` has `onupdate=func.now()` for auto-update on modification
    - _Requirements: 6.1, 6.5_

  - [x] 1.3 Update `FeatureFlagCRUDService` schemas and service in `app/modules/feature_flags/service.py`
    - Add `category`, `access_level`, `dependencies`, `updated_by` to `FeatureFlagResponse` schema
    - Update `create_flag` and `update_flag` methods to accept and persist the new fields
    - Update `_to_response` to include new fields
    - _Requirements: 6.1_

- [x] 2. Seed migration for comprehensive feature flags
  - [x] 2.1 Create Alembic seed migration inserting ~45 platform feature flags
    - Use `INSERT ... ON CONFLICT (key) DO NOTHING` for idempotency
    - Each flag has: key, display_name, description, category, access_level, dependencies, default_value
    - Core modules (invoicing, customers, notifications) default to `true`; non-core default to `false`
    - Assign each flag to exactly one category from: Core, Sales, Operations, Inventory, POS, Hospitality, Staff, Construction, Finance, Compliance, Engagement, Enterprise, Ecommerce, Admin, Banking & Payments, AI & Automation, Reports, Data
    - Cover all modules listed in Requirement 1.1
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 2.2 Write property test for seed data completeness and validity
    - **Property 1: Seed data completeness and validity**
    - Verify all flags have valid snake_case keys, non-empty display_name/description, valid category, valid access_level, and all dependency keys exist in the seed data
    - **Validates: Requirements 1.2, 1.3**

  - [ ]* 2.3 Write property test for seed migration idempotency
    - **Property 2: Seed migration idempotency**
    - Verify running the seed insert logic N times produces the same set of flag rows as running it once
    - **Validates: Requirements 1.4, 1.5**

- [x] 3. Checkpoint - Ensure schema and seed migrations work
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Evaluation engine enhancement
  - [x] 4.1 Add `evaluate_flags_bulk` function to `app/core/feature_flags.py`
    - Accepts a list of flag dicts and an `OrgContext`, returns `dict[str, bool]`
    - Calls existing `evaluate_flag` for each flag
    - Remains a pure function with no I/O
    - _Requirements: 5.4, 5.5_

  - [ ]* 4.2 Write property test for bulk evaluation equals individual evaluation
    - **Property 13: Bulk evaluation equals individual evaluation**
    - Generate random flags and org context, verify `evaluate_flags_bulk` result matches individual `evaluate_flag` calls for every key
    - **Validates: Requirements 5.5**

  - [ ]* 4.3 Write property test for evaluation determinism
    - **Property 14: Evaluation determinism**
    - Generate random flag + org context, evaluate twice, verify same result
    - **Validates: Requirements 5.6**

  - [ ]* 4.4 Write property test for targeting rule priority
    - **Property 11: Evaluation respects targeting rule priority**
    - Generate flag with multiple targeting rules matching an org context, verify highest-priority rule wins
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 4.5 Write property test for inactive flag returns default value
    - **Property 12: Inactive flag returns default value**
    - Generate inactive flag with random rules + org context, verify result equals default_value
    - **Validates: Requirements 5.3**

- [x] 5. Backend feature flag middleware
  - [x] 5.1 Create `FeatureFlagMiddleware` in `app/middleware/feature_flags.py`
    - Define `FLAG_ENDPOINT_MAP` mapping API path prefixes to flag keys for all gated modules
    - Define `CORE_FLAGS` set: `{"invoicing", "customers", "notifications"}`
    - Implement `dispatch` method: skip non-API/public paths, resolve path to flag key, skip core flags, check Redis cache (`ff:{org_id}`), evaluate via service on cache miss, return 403 JSON if flag is false, fail-open on any error
    - Cache evaluated flags in Redis with configurable TTL (default 30s)
    - Return 403 with `{"detail": "Feature '{key}' is disabled for your organisation.", "flag_key": "{key}"}`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 5.2 Register `FeatureFlagMiddleware` in `app/main.py` middleware stack
    - Insert between RBAC (step 6) and Idempotency (step 7) in the middleware order
    - _Requirements: 2.1_

  - [x] 5.3 Add cache invalidation to `FeatureFlagCRUDService` on flag update
    - On flag update via admin API, invalidate all `ff:*` Redis keys to ensure propagation within 5 seconds
    - _Requirements: 2.8_

  - [ ]* 5.4 Write property test for middleware gating correctness
    - **Property 3: Middleware gating correctness**
    - Generate random non-core flag key, org context, and flag state; verify middleware returns 403 iff flag evaluates to false
    - **Validates: Requirements 2.2, 2.3, 2.4**

  - [ ]* 5.5 Write property test for core flags always pass middleware
    - **Property 4: Core flags always pass middleware**
    - Generate random org context and core flag key; verify middleware always allows regardless of flag value
    - **Validates: Requirements 2.5**

- [x] 6. Checkpoint - Ensure backend middleware and evaluation tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend FeatureGate component and enhanced context
  - [x] 7.1 Add `FeatureGate` component to `frontend/src/contexts/FeatureFlagContext.tsx`
    - Export `FeatureGate` component accepting `flagKey`, optional `fallback`, and `children` props
    - Render `children` when `useFlag(flagKey)` returns `true`
    - Render `fallback` (or nothing) when `false`
    - Render nothing while `isLoading` is `true`
    - Ensure `isLoading` and `refetch` are already exposed (verify existing context)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [ ]* 7.2 Write property test for FeatureGate renders if and only if flag is true
    - **Property 5: FeatureGate renders if and only if flag is true**
    - Generate random flag map, verify FeatureGate renders children iff flag is true, renders fallback when false
    - **Validates: Requirements 3.2, 3.3, 3.5**

- [x] 8. Redesigned admin UI for comprehensive flag management
  - [x] 8.1 Rewrite `frontend/src/pages/admin/FeatureFlags.tsx` with category-based layout
    - Display all flags grouped by `category` in collapsible sections
    - Each category header shows `{enabled}/{total}` count
    - Each flag row: display_name, description, code key badge, access_level badge, dependency chips, toggle switch for `is_active`
    - Toggle sends `PUT /api/v2/admin/flags/{key}` with optimistic update; revert on error with error toast
    - Add search input filtering across display_name, key, description (case-insensitive)
    - Add filter dropdown for category, access_level, enabled/disabled status
    - Show dependency warning modal when disabling a flag that other enabled flags depend on
    - Call `refetch` on the FeatureFlagContext after successful toggle to propagate changes
    - Accessible only to Global Admin role
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [ ]* 8.2 Write property test for admin search filters correctly
    - **Property 7: Admin search filters correctly**
    - Generate random flags + search term, verify filter returns exactly flags where term appears in display_name, key, or description
    - **Validates: Requirements 4.5**

  - [ ]* 8.3 Write property test for admin category and status filters
    - **Property 8: Admin category and status filters correctly**
    - Generate random flags + filter criteria, verify filter returns correct subset
    - **Validates: Requirements 4.6**

  - [ ]* 8.4 Write property test for dependency warning on disable
    - **Property 9: Dependency warning on disable**
    - Generate flag with dependents, verify warning shown on disable attempt
    - **Validates: Requirements 4.7**

  - [ ]* 8.5 Write property test for category enabled count accuracy
    - **Property 10: Category enabled count accuracy**
    - Generate random flags by category, verify enabled/total count matches actual data
    - **Validates: Requirements 4.8**

  - [ ]* 8.6 Write property test for admin UI flag row displays all required fields
    - **Property 6: Admin UI flag row displays all required fields**
    - Generate random flag data, verify rendered row contains display_name, description, key, access_level badge, dependency list, toggle switch
    - **Validates: Requirements 4.2**

- [x] 9. Checkpoint - Ensure admin UI and frontend context tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Route and navigation gating
  - [x] 10.1 Add flag-based route gating to `frontend/src/router/ModuleRouter.tsx`
    - Define `FLAG_ROUTE_MAP` mapping route path prefixes to flag keys
    - A route renders only if both the module is enabled AND the corresponding flag evaluates to true via `useFlag`
    - Direct URL navigation to a disabled feature redirects to `/dashboard` with a toast notification
    - _Requirements: 8.2, 8.3, 8.4_

  - [x] 10.2 Add flag-based sidebar navigation gating in `frontend/src/layouts/AdminLayout.tsx` and the main app sidebar
    - Wrap sidebar navigation items with `useFlag` checks to hide links for disabled features
    - Re-evaluate navigation visibility when flag values change (after refetch)
    - _Requirements: 8.1, 8.4_

  - [ ]* 10.3 Write property test for disabled feature hides navigation, routes, and redirects
    - **Property 18: Disabled feature hides navigation, routes, and redirects**
    - Generate random flag map with some flags false, verify nav items hidden, routes not mounted, direct URL redirects to dashboard
    - **Validates: Requirements 8.1, 8.2, 8.3**

- [x] 11. End-to-end wiring and consistency
  - [x] 11.1 Wire the `evaluate_flags_bulk` function into the `/v2/flags` endpoint response
    - Ensure the bulk evaluation endpoint in the feature flags service uses `evaluate_flags_bulk` from `app/core/feature_flags.py`
    - Ensure the middleware and the `/v2/flags` endpoint use the same `evaluate_flag` engine for consistency
    - _Requirements: 7.5, 7.6_

  - [ ]* 11.2 Write property test for backend and frontend evaluation consistency
    - **Property 17: Backend and frontend evaluation consistency**
    - Generate flag + org context, compare backend bulk eval result with the value served to frontend
    - **Validates: Requirements 7.5, 7.6**

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1-18)
- The implementation reuses existing patterns: `BaseHTTPMiddleware`, `FeatureFlagCRUDService`, `FeatureFlagContext`, and `evaluate_flag` pure function
- Backend: Python (FastAPI + SQLAlchemy + Alembic + Redis)
- Frontend: TypeScript (React + react-router-dom)

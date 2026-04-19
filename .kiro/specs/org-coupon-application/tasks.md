# Implementation Plan: Organisation Coupon Application from Global Admin Console

## Overview

Implement the ability for Global Admins to apply coupons directly to organisations from the Organisations page. The backend adds a utility function for generating human-readable coupon benefit descriptions, a service function that validates and applies coupons (with audit logging and in-app notification), new Pydantic schemas, and a dedicated admin endpoint. The frontend adds an ApplyCouponModal component inline in Organisations.tsx with coupon search, selection, and error handling. Property-based tests validate the benefit description generator, coupon search filtering, and the apply-coupon service logic. An E2E test script covers the full flow including OWASP checks.

## Tasks

- [x] 1. Implement backend utility function and service logic
  - [x] 1.1 Add `generate_coupon_benefit_description()` pure function to `app/modules/admin/service.py`
    - Accepts `discount_type: str`, `discount_value: float`, `duration_months: int | None`
    - Returns human-readable string based on discount type:
      - `"percentage"` → `"{X}% discount on your subscription for {Y} months"` or `"... ongoing"`
      - `"fixed_amount"` → `"${X} off per billing cycle for {Y} months"` or `"... ongoing"`
      - `"trial_extension"` → `"Trial extended by {X} days"`
    - Pure function — no DB access, no side effects
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 1.2 Add `admin_apply_coupon_to_org()` async service function to `app/modules/admin/service.py`
    - Signature: `async def admin_apply_coupon_to_org(db, *, org_id, coupon_id, applied_by, ip_address=None) -> dict`
    - SELECT coupon WHERE id = coupon_id FOR UPDATE (row lock for atomic update)
    - Validate: coupon exists, `is_active=True`, not expired (`expires_at`), not before start (`starts_at`), usage limit not exceeded
    - SELECT organisation WHERE id = org_id — validate org exists and is not deleted
    - SELECT organisation_coupons WHERE org_id AND coupon_id — check duplicate
    - INSERT organisation_coupons with `applied_at=now()`
    - UPDATE coupons SET `times_redeemed += 1`
    - If `discount_type == "trial_extension"`: extend `organisation.trial_ends_at` by `discount_value` days
    - Call `write_audit_log(action="coupon.admin_applied", ...)` with admin user, org, and coupon details
    - Call `PlatformNotificationService.create_notification()` with `target_type="specific_orgs"`, `target_value=json.dumps([str(org_id)])`, title `"Coupon Applied by Oraflows Limited"`, message from `generate_coupon_benefit_description()`, type `"info"`, severity `"info"`, `published_at=now()`
    - Wrap notification creation in try/except — log error but do not roll back coupon application
    - Return dict: `{ organisation_coupon_id, coupon_code, benefit_description, message }`
    - Error mapping: coupon not found/inactive → `ValueError("Coupon not found")`, expired → `ValueError("Coupon has expired")`, not yet active → `ValueError("Coupon is not yet active")`, usage limit → `ValueError("Coupon usage limit reached")`, already applied → `ValueError("Coupon already applied to this organisation")`, org not found → `ValueError("Organisation not found")`
    - Import `OrganisationCoupon` from `app.modules.admin.models`, `PlatformNotification` from notification models
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 2. Add backend schemas and API endpoint
  - [x] 2.1 Add `AdminApplyCouponRequest` and `AdminApplyCouponResponse` Pydantic schemas to `app/modules/admin/schemas.py`
    - `AdminApplyCouponRequest`: `coupon_id: str = Field(..., description="UUID of the coupon to apply")`
    - `AdminApplyCouponResponse`: `message: str`, `organisation_coupon_id: str`, `coupon_code: str`, `benefit_description: str`
    - _Requirements: 7.2, 7.4_

  - [x] 2.2 Add `POST /admin/organisations/{org_id}/apply-coupon` endpoint to `app/modules/admin/router.py`
    - Auth: `dependencies=[require_role("global_admin")]`
    - Path param: `org_id` (string, validated as UUID)
    - Request body: `AdminApplyCouponRequest`
    - Parse `org_id` as UUID — return 400 if invalid format
    - Parse `coupon_id` as UUID — return 422 via Pydantic if invalid
    - Call `admin_apply_coupon_to_org(db, org_id=org_uuid, coupon_id=coupon_uuid, applied_by=user_uuid, ip_address=ip_address)`
    - Error handling: `ValueError` with "not found" → 404, "already applied" → 409, other `ValueError` → 400, unexpected `Exception` → 500 with generic message
    - Import `AdminApplyCouponRequest`, `AdminApplyCouponResponse` from schemas, `admin_apply_coupon_to_org` from service
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 3.7, 3.8, 3.9_

- [x] 3. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Property-based tests for backend logic
  - [x] 4.1 Write property test for `generate_coupon_benefit_description()` (Property 1)
    - **Property 1: Benefit description format matches coupon type**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - Test file: `tests/test_coupon_benefit_description_props.py`
    - Use Hypothesis to generate `discount_type` from `sampled_from(["percentage", "fixed_amount", "trial_extension"])`, `discount_value` from `floats(min_value=0.01, max_value=10000)`, `duration_months` from `one_of(none(), integers(min_value=1, max_value=120))`
    - Assert: result is non-empty string containing the discount value
    - Assert: `percentage` → contains "%" and "discount on your subscription"
    - Assert: `fixed_amount` → contains "$" and "off per billing cycle"
    - Assert: `trial_extension` → contains "Trial extended by" and "days"
    - Assert: when `duration_months` is set (non-trial_extension) → contains "for {N} months"
    - Assert: when `duration_months` is None (non-trial_extension) → contains "ongoing"
    - `@settings(max_examples=100)`
    - Tag: `# Feature: org-coupon-application, Property 1: Benefit description format matches coupon type`

  - [x] 4.2 Write property test for coupon search filter logic (Property 2)
    - **Property 2: Coupon search filter returns only matching coupons**
    - **Validates: Requirements 2.4**
    - Test file: `tests/test_coupon_search_filter_props.py`
    - Extract the client-side filter logic into a testable pure function: `filter_coupons(coupons: list[dict], search: str) -> list[dict]`
    - Use Hypothesis to generate lists of coupon dicts with `code` and `description` fields, and arbitrary search strings
    - Assert: filtered list is a subset of the original list
    - Assert: every item in filtered list has `search.lower()` in `code.lower()` or `description.lower()`
    - Assert: no item excluded from filtered list matches the search criteria
    - `@settings(max_examples=100)`
    - Tag: `# Feature: org-coupon-application, Property 2: Coupon search filter returns only matching coupons`

  - [x] 4.3 Write property tests for `admin_apply_coupon_to_org()` validation and success (Properties 3, 4, 5)
    - **Property 3: Validation rejects invalid coupon applications**
    - **Property 4: Successful application creates correct state**
    - **Property 5: Successful response contains required fields**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8, 3.9**
    - Test file: `tests/test_admin_apply_coupon_props.py`
    - Use Hypothesis to generate coupon states (active/inactive, expired/valid, usage limit reached/available, already applied/new)
    - Property 3: for any invalid coupon state, assert `ValueError` is raised and no `OrganisationCoupon` record is created
    - Property 4: for any valid coupon + existing org, assert `OrganisationCoupon` record exists with correct fields, `times_redeemed` incremented by 1, and `trial_ends_at` extended when `discount_type == "trial_extension"`
    - Property 5: for any successful application, assert response dict contains `organisation_coupon_id` (valid UUID string), `coupon_code` (non-empty), `benefit_description` (non-empty), `message` (non-empty)
    - Mock DB session using `AsyncMock` or use in-memory SQLite if feasible
    - `@settings(max_examples=100)` per property
    - Tags: `# Feature: org-coupon-application, Property 3/4/5`

- [x] 5. Implement frontend ApplyCouponModal and integrate into Organisations page
  - [x] 5.1 Add `ApplyCouponModal` component inline in `frontend/src/pages/admin/Organisations.tsx`
    - Follow existing modal pattern (ProvisionModal, SuspendModal, etc.) — inline function component
    - Props: `open: boolean`, `onClose: () => void`, `onSuccess: () => void`, `orgName: string`, `orgId: string`
    - State: `coupons: CouponItem[]`, `search: string`, `selectedCouponId: string | null`, `loading: boolean`, `applying: boolean`, `error: string`
    - On open: fetch `GET /admin/coupons` with AbortController cleanup in useEffect
    - Set coupons safely: `setCoupons(res.data?.coupons ?? [])`
    - Filter coupons client-side by code/description matching search text (case-insensitive)
    - Display each coupon: code, description, discount type badge, discount value, remaining uses (`usage_limit - times_redeemed` or "Unlimited")
    - On coupon select: highlight row, show benefit description preview using client-side `generateBenefitDescription()` helper
    - On "Apply" click: POST `/admin/organisations/${orgId}/apply-coupon` with `{ coupon_id: selectedCouponId }`
    - On success: call `onSuccess()` callback
    - On error: set inline error based on status code — 409 → "This coupon has already been applied to this organisation", 400/404 → backend `detail`, other → "Failed to apply coupon. Please try again."
    - Use typed API generics — no `as any`
    - All API data access uses `?.` and `?? []` / `?? 0` fallbacks per safe-api-consumption steering
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 6.1, 6.2, 6.3, 6.4_

  - [x] 5.2 Integrate ApplyCouponModal into the Organisations page
    - Add `applyCouponOrg` state: `useState<Organisation | null>(null)`
    - Add "Apply Coupon" button in the actions column — after "Billing date" button, before "Soft Delete" button
    - Only show when `row.status !== 'deleted'` (matches Requirement 1.1)
    - Add `<ApplyCouponModal>` alongside existing modals at the bottom of the component
    - Pass `open={!!applyCouponOrg}`, `onClose={() => setApplyCouponOrg(null)}`, `onSuccess={handleApplyCouponSuccess}`, `orgName={applyCouponOrg?.name ?? ''}`, `orgId={applyCouponOrg?.id ?? ''}`
    - Add `handleApplyCouponSuccess` callback: close modal (`setApplyCouponOrg(null)`), show success toast (`addToast('success', \`Coupon applied to ${applyCouponOrg?.name}\`)`), refresh org list (`fetchData()`)
    - _Requirements: 1.1, 1.2, 6.1_

- [x] 6. Checkpoint — Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. End-to-end test script
  - [x] 7.1 Create `scripts/test_org_coupon_application_e2e.py`
    - Follow feature-testing-workflow steering pattern (httpx, asyncio, ok/fail helpers)
    - Login as global_admin (`admin@orainvoice.com` / `admin123`)
    - List organisations (`GET /admin/organisations`) — verify response shape
    - List coupons (`GET /admin/coupons`) — verify response shape
    - Pick a test org and a test coupon (or create test coupon if none exist)
    - Apply coupon (`POST /admin/organisations/{org_id}/apply-coupon`) — verify 200 response with `organisation_coupon_id`, `coupon_code`, `benefit_description`, `message`
    - Verify OrganisationCoupon record exists via direct DB query (asyncpg)
    - Verify coupon `times_redeemed` incremented
    - Verify PlatformNotification created for the org with correct title and message
    - Verify audit log entry exists with `action="coupon.admin_applied"`
    - Try applying same coupon again — verify 409 with "already applied" message
    - Try applying with non-existent coupon_id — verify 404
    - Try applying with non-existent org_id — verify 404
    - OWASP A1: try without auth token → 401
    - OWASP A1: try with org_admin token (non-global_admin) → 403
    - OWASP A3: SQL injection in coupon_id field → 422
    - OWASP A3: XSS payload in coupon_id → 422
    - OWASP A5: error responses contain no stack traces or internal paths
    - Clean up: delete OrganisationCoupon record, decrement times_redeemed, delete test PlatformNotification
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.1, 4.2, 4.3, 4.4, 4.5, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the `generate_coupon_benefit_description` pure function, coupon search filtering, and the `admin_apply_coupon_to_org` service logic using Hypothesis with `@settings(max_examples=100)`
- Unit tests validate specific examples and edge cases
- No database migrations are needed — uses existing `Coupon`, `OrganisationCoupon`, `PlatformNotification`, and `Organisation` models
- The ApplyCouponModal follows the existing inline modal pattern in Organisations.tsx (ProvisionModal, SuspendModal, etc.)
- The notification creation is non-blocking — if it fails, the coupon application still succeeds
- Frontend code follows safe-api-consumption steering rules: `?.`, `?? []`, `?? 0`, AbortController cleanup, typed generics, no `as any`

# Implementation Plan: Coupon System

## Overview

Full-stack implementation across data layer (Alembic migration), backend (models, schemas, service, router), and frontend (admin Coupons tab, signup coupon code input). The backend follows existing admin module patterns. The frontend extends `SubscriptionPlans.tsx` with a tab bar and adds coupon code entry to `Signup.tsx`. Property-based tests use Hypothesis (Python) and fast-check (TypeScript).

## Tasks

- [x] 1. Create Alembic migration for coupon tables
  - [x] 1.1 Create `alembic/versions/2026_03_17_1000-0093_create_coupon_tables.py`
    - Revision ID: `0093`, Revises: `0092`
    - Create `coupons` table with columns: `id` (UUID PK, gen_random_uuid()), `code` (String(50), unique, not null), `description` (String(255), nullable), `discount_type` (String(20), not null), `discount_value` (Numeric(10,2), not null), `duration_months` (Integer, nullable), `usage_limit` (Integer, nullable), `times_redeemed` (Integer, not null, default 0), `is_active` (Boolean, not null, default true), `starts_at` (DateTime(tz), nullable), `expires_at` (DateTime(tz), nullable), `created_at` (DateTime(tz), not null, server_default now()), `updated_at` (DateTime(tz), not null, server_default now())
    - Add check constraint `ck_coupons_discount_type` on `discount_type` allowing only `'percentage'`, `'fixed_amount'`, `'trial_extension'`
    - Create index `ix_coupons_code` on `coupons(code)`
    - Do NOT enable RLS on `coupons` table (global admin table, same pattern as `subscription_plans`)
    - Create `organisation_coupons` table with columns: `id` (UUID PK, gen_random_uuid()), `org_id` (UUID FK → organisations.id, not null), `coupon_id` (UUID FK → coupons.id, not null), `applied_at` (DateTime(tz), not null), `billing_months_used` (Integer, not null, default 0), `is_expired` (Boolean, not null, default false), `created_at` (DateTime(tz), not null, server_default now())
    - Add unique constraint `uq_organisation_coupons_org_coupon` on `(org_id, coupon_id)`
    - Create indexes `ix_organisation_coupons_org_id` on `(org_id)` and `ix_organisation_coupons_coupon_id` on `(coupon_id)`
    - Enable RLS on `organisation_coupons`: `ALTER TABLE organisation_coupons ENABLE ROW LEVEL SECURITY`
    - Create tenant isolation policy: `CREATE POLICY tenant_isolation ON organisation_coupons USING (org_id = current_setting('app.current_org_id')::uuid)`
    - Implement `downgrade()`: drop RLS policy, disable RLS, drop `organisation_coupons`, drop `coupons`
    - _Requirements: 1.1–1.10, 9.1–9.8_

- [x] 2. Create SQLAlchemy models for Coupon and OrganisationCoupon
  - [x] 2.1 Add `Coupon` model to `app/modules/admin/models.py`
    - Follow existing `SubscriptionPlan` model pattern (UUID PK, server_default gen_random_uuid(), DateTime with timezone, etc.)
    - All columns matching migration schema from Task 1.1
    - Add `CheckConstraint` on `discount_type` matching migration
    - Add `Index` on `code`
    - Add relationship: `organisation_coupons: Mapped[list[OrganisationCoupon]] = relationship(back_populates="coupon")`
    - _Requirements: 1.1–1.6_

  - [x] 2.2 Add `OrganisationCoupon` model to `app/modules/admin/models.py`
    - UUID PK, ForeignKey to `organisations.id` and `coupons.id`
    - `UniqueConstraint("org_id", "coupon_id", name="uq_organisation_coupons_org_coupon")` in `__table_args__`
    - Add relationships: `coupon: Mapped[Coupon]` (back_populates), `organisation: Mapped[Organisation]`
    - _Requirements: 1.7–1.10_

- [x] 3. Create Pydantic schemas for coupon API
  - [x] 3.1 Add coupon schemas to `app/modules/admin/schemas.py`
    - `CouponCreateRequest`: code (str, min 3, max 50), description (str|None, max 255), discount_type (str), discount_value (float, gt 0), duration_months (int|None, gt 0), usage_limit (int|None, gt 0), starts_at (datetime|None), expires_at (datetime|None)
    - `CouponUpdateRequest`: all fields optional — description, discount_value, duration_months, usage_limit, is_active, starts_at, expires_at
    - `CouponResponse`: all coupon fields including times_redeemed, created_at, updated_at
    - `CouponListResponse`: coupons list + total count (follows `PlanListResponse` pattern)
    - `CouponRedemptionRow`: id, org_id, organisation_name, applied_at, billing_months_used, is_expired
    - `CouponDetailResponse(CouponResponse)`: adds redemptions list
    - `CouponValidateRequest`: code (str, min 1)
    - `CouponValidateResponse`: valid (bool), coupon (CouponResponse|None), error (str|None)
    - `CouponRedeemRequest`: code (str, min 1), org_id (str)
    - `CouponRedeemResponse`: message (str), organisation_coupon_id (str)
    - _Requirements: 10.1–10.8_

- [x] 4. Checkpoint — Validate data layer
  - Verify migration file syntax, model definitions, and schema definitions compile without errors. Ask the user if questions arise.

- [x] 5. Implement coupon service functions
  - [x] 5.1 Add `calculate_effective_price` utility to `app/modules/admin/service.py`
    - Pure function: `calculate_effective_price(plan_price: float, discount_type: str, discount_value: float, is_expired: bool) -> float`
    - If `is_expired` is True, return `plan_price`
    - If `discount_type == "trial_extension"`, return `plan_price`
    - If `discount_type == "percentage"`, return `round(plan_price * (1 - discount_value / 100), 2)`
    - If `discount_type == "fixed_amount"`, return `round(max(0.0, plan_price - discount_value), 2)`
    - _Requirements: 11.1–11.6_

  - [x] 5.2 Add `create_coupon` to `app/modules/admin/service.py`
    - Normalise code to uppercase, strip whitespace
    - Check for duplicate code (case-insensitive via `func.upper`)
    - Raise `ValueError` if duplicate found
    - Create `Coupon` record, flush, write audit log (`coupon.created`), refresh timestamps
    - Return dict matching `CouponResponse` schema
    - _Requirements: 2.2, 2.6, 2.7_

  - [x] 5.3 Add `list_coupons` to `app/modules/admin/service.py`
    - Query `Coupon` table, optionally filter by `is_active`, order by `created_at` desc
    - Support pagination (page, page_size)
    - Return dict with `coupons` list and `total` count
    - _Requirements: 2.1_

  - [x] 5.4 Add `get_coupon` to `app/modules/admin/service.py`
    - Fetch coupon by ID, raise `ValueError("Coupon not found")` if missing
    - Join `organisation_coupons` → `organisations` to get redemption list with org names
    - Return dict matching `CouponDetailResponse` schema
    - _Requirements: 2.3_

  - [x] 5.5 Add `update_coupon` to `app/modules/admin/service.py`
    - Fetch coupon by ID, raise `ValueError` if not found
    - If `usage_limit` in updates and new value < `times_redeemed`, raise `ValueError` with descriptive message
    - Apply updates, write audit log (`coupon.updated`), commit
    - Return updated coupon dict
    - _Requirements: 2.4, 2.8, 6.3, 6.4_

  - [x] 5.6 Add `deactivate_coupon` and `reactivate_coupon` to `app/modules/admin/service.py`
    - `deactivate_coupon`: set `is_active = False`, audit log (`coupon.deactivated`)
    - `reactivate_coupon`: set `is_active = True`, audit log (`coupon.reactivated`)
    - Both raise `ValueError` if coupon not found
    - _Requirements: 2.5_

  - [x] 5.7 Add `validate_coupon` to `app/modules/admin/service.py`
    - Lookup by code (case-insensitive, `func.upper`)
    - Check: exists → `is_active` → `starts_at` → `expires_at` → `usage_limit` vs `times_redeemed`
    - Return `{"valid": True, "coupon": {...}}` on success
    - Return `{"valid": False, "error": "..."}` with specific message on failure
    - Error messages: "Coupon not found", "Coupon has expired", "Coupon is not yet active", "Coupon usage limit reached"
    - _Requirements: 3.1–3.3_

  - [x] 5.8 Add `redeem_coupon` to `app/modules/admin/service.py`
    - `SELECT ... FOR UPDATE` on coupon row for atomic operation
    - Validate coupon (reuse validation logic)
    - Check org exists, check no existing `organisation_coupons` record for this org+coupon pair (raise 409 if duplicate)
    - Create `OrganisationCoupon` record with `applied_at = now()`, `billing_months_used = 0`, `is_expired = False`
    - Increment `coupon.times_redeemed`
    - If `discount_type == "trial_extension"`: update `organisation.trial_ends_at += timedelta(days=discount_value)`
    - Flush and return `{"message": "Coupon redeemed successfully", "organisation_coupon_id": str(org_coupon.id)}`
    - _Requirements: 3.4–3.8_

  - [x] 5.9 Add `get_coupon_redemptions` to `app/modules/admin/service.py`
    - Query `organisation_coupons` joined with `organisations` for a given `coupon_id`
    - Return list of dicts matching `CouponRedemptionRow` schema
    - _Requirements: 5.6_

- [x] 6. Implement admin coupon router endpoints
  - [x] 6.1 Add coupon CRUD endpoints to `app/modules/admin/router.py`
    - `GET /admin/coupons` — list coupons, query params: `include_inactive` (bool), `page` (int), `page_size` (int). Response: `CouponListResponse`. Auth: `require_role("global_admin")`
    - `POST /admin/coupons` — create coupon. Body: `CouponCreateRequest`. Response: `CouponResponse` (201). Handle `ValueError` → 409 for duplicate code
    - `GET /admin/coupons/{coupon_id}` — get coupon detail + redemptions. Response: `CouponDetailResponse`. Handle not found → 404
    - `PUT /admin/coupons/{coupon_id}` — update coupon. Body: `CouponUpdateRequest`. Response: `CouponResponse`. Handle not found → 404, usage_limit violation → 422
    - `DELETE /admin/coupons/{coupon_id}` — soft-delete (deactivate). Response: `CouponResponse`. Handle not found → 404
    - `PUT /admin/coupons/{coupon_id}/reactivate` — reactivate. Response: `CouponResponse`. Handle not found → 404
    - `GET /admin/coupons/{coupon_id}/redemptions` — list redemptions. Response: list of `CouponRedemptionRow`
    - All endpoints: validate UUID format, write audit logs, follow existing router patterns (try/except ValueError, JSONResponse for errors)
    - _Requirements: 2.1–2.8_

  - [x] 6.2 Add public coupon endpoints to `app/modules/admin/router.py` (or a separate public router)
    - `POST /coupons/validate` — public, no auth. Body: `CouponValidateRequest`. Response: `CouponValidateResponse` (always 200)
    - `POST /coupons/redeem` — public, no auth. Body: `CouponRedeemRequest`. Response: `CouponRedeemResponse`. Handle duplicate → 409, org not found → 404
    - Mount on a separate `APIRouter` without auth dependencies, registered at `/api/v1/coupons`
    - _Requirements: 3.1–3.8_

- [x] 7. Checkpoint — Validate backend API
  - Verify all endpoints respond correctly. Ask the user if questions arise.

- [x] 8. Implement admin Coupons tab in SubscriptionPlans.tsx
  - [x] 8.1 Add top-level tab bar to `SubscriptionPlans` component in `frontend/src/pages/admin/SubscriptionPlans.tsx`
    - Add `activeMainTab` state: `'plans' | 'coupons'`, default `'plans'`
    - Render tab bar with "Plans" and "Coupons" buttons below the page heading, above `ToastContainer`
    - "Plans" tab shows existing content (GlobalStoragePricing, plans table, PlanFormModal)
    - "Coupons" tab shows new `CouponsContent` section
    - Move "Create plan" button inside Plans tab content
    - _Requirements: 7.1_

  - [x] 8.2 Add `Coupon` TypeScript interface and coupon state to `SubscriptionPlans.tsx`
    - Interface: `id`, `code`, `description`, `discount_type`, `discount_value`, `duration_months`, `usage_limit`, `times_redeemed`, `is_active`, `starts_at`, `expires_at`, `created_at`, `updated_at`
    - State: `coupons: Coupon[]`, `couponsLoading: boolean`, `couponsError: boolean`, `couponFormOpen: boolean`, `editCoupon: Coupon | null`, `couponSaving: boolean`
    - `fetchCoupons` function calling `GET /admin/coupons`
    - Fetch coupons when Coupons tab is active (useEffect keyed on `activeMainTab`)
    - _Requirements: 7.2, 7.9, 7.10_

  - [x] 8.3 Implement `CouponsContent` section in `SubscriptionPlans.tsx`
    - Loading state: `<Spinner label="Loading coupons" />`
    - Error state: `<AlertBanner variant="error">Could not load coupons.</AlertBanner>`
    - Header with "Coupons" title and "Create Coupon" button
    - DataTable with columns:
      - Code: monospace font, uppercase
      - Description: truncated text
      - Type: Badge — "Percentage" (blue), "Fixed Amount" (green), "Trial Extension" (purple)
      - Value: formatted based on type — "20%", "$10.00", "+30 days"
      - Duration: "3 months", "Perpetual", or "—"
      - Usage: "15 / 50 used" or "15 / ∞"
      - Status: Badge — "Active" (green) or "Inactive" (warning)
      - Created: formatted date
      - Actions: Edit button, Deactivate/Reactivate button
    - Deactivate action shows confirmation dialog before calling `DELETE /admin/coupons/{id}`
    - Reactivate action calls `PUT /admin/coupons/{id}/reactivate`
    - _Requirements: 7.2–7.3, 7.5–7.10_

  - [x] 8.4 Implement `CouponFormModal` in `SubscriptionPlans.tsx`
    - Modal with form fields: code (text input), description (text input), discount_type (select dropdown), discount_value (number input), duration_months (number input, optional), usage_limit (number input, optional), starts_at (datetime-local input, optional), expires_at (datetime-local input, optional)
    - Dynamic discount_value label: "Percentage (1-100)" for percentage, "Amount (NZD)" for fixed_amount, "Additional trial days" for trial_extension
    - Hide duration_months field when discount_type is "trial_extension" (trial extensions don't have monthly duration)
    - Client-side validation:
      - code: non-empty, alphanumeric/hyphens/underscores, 3–50 chars
      - discount_type: required
      - discount_value: 1–100 for percentage, > 0 for fixed_amount, whole number > 0 for trial_extension
      - duration_months: if provided, whole number > 0
      - usage_limit: if provided, whole number > 0
      - expires_at > starts_at if both provided
    - On submit: `POST /admin/coupons` (create) or `PUT /admin/coupons/{id}` (edit)
    - Disable code field when editing (code is immutable after creation)
    - Reset form state on open/close
    - Loading state on submit button
    - Inline error display from API responses
    - _Requirements: 7.3–7.5, 8.1–8.10_

- [x] 9. Implement coupon code entry in Signup.tsx
  - [x] 9.1 Add coupon code section to `frontend/src/pages/auth/Signup.tsx`
    - Add state: `couponCode`, `couponApplied` (CouponResponse | null), `couponError`, `couponValidating`, `showCouponInput`
    - Add "Have a coupon code?" expandable link between plan selector and CAPTCHA section
    - When expanded: text input + "Apply" button
    - On Apply: call `POST /api/v1/coupons/validate` with `{code: couponCode}`
    - On success: set `couponApplied`, show discount preview with green styling
    - On error: show error message inline below input from `response.error` field
    - "Remove" button clears `couponApplied` and `couponCode`
    - _Requirements: 4.1, 4.2, 4.5, 4.6_

  - [x] 9.2 Add discount preview display to Signup.tsx
    - When coupon is applied, show discount info next to plan price:
      - Percentage: "20% off" or "20% off for 3 months"
      - Fixed amount: "$10.00 off/mo" or "$10.00 off/mo for 6 months"
      - Trial extension: "+30 days free trial"
    - Calculate and display effective price for percentage/fixed_amount coupons
    - _Requirements: 4.3, 4.4_

  - [x] 9.3 Add coupon redemption on signup success in Signup.tsx
    - After successful `POST /auth/signup` response (which returns `org_id`), if `couponApplied` is set:
      - Call `POST /api/v1/coupons/redeem` with `{code: couponApplied.code, org_id: response.org_id}`
      - On success: proceed to success screen as normal
      - On failure: log error to console, proceed to success screen anyway (signup already succeeded, non-blocking)
    - Add `coupon_code` to the signup form data sent to backend (optional field for backend awareness)
    - _Requirements: 4.7_

- [x] 10. Checkpoint — Validate frontend implementation
  - Verify admin Coupons tab renders correctly, CRUD operations work, and signup coupon flow works end-to-end. Ask the user if questions arise.

- [x] 11. Write property-based tests


  - [x] 11.1 Create `tests/properties/test_coupon_properties.py` with Hypothesis tests
    - **Property 2: Effective price calculation bounds** — For any plan_price ≥ 0, any discount_type, any discount_value > 0, any is_expired boolean: `0 ≤ calculate_effective_price(...) ≤ plan_price`. **Validates: Requirements 11.2–11.6**
    - **Property 3: Percentage discount calculation** — For any plan_price ≥ 0 and percentage 1–100, when not expired: result == `round(plan_price * (1 - pct/100), 2)`. **Validates: Requirements 5.3, 11.3**
    - **Property 4: Fixed amount discount calculation** — For any plan_price ≥ 0 and fixed_amount > 0, when not expired: result == `max(0, round(plan_price - amount, 2))`. **Validates: Requirements 5.4, 11.4**
    - **Property 5: Expired coupon returns full price** — For any valid params, when is_expired=True: result == plan_price. **Validates: Requirements 11.2**
    - **Property 6: Trial extension does not affect price** — For any plan_price and trial days, discount_type="trial_extension": result == plan_price regardless of is_expired. **Validates: Requirements 11.5**
    - Use `@given(...)` decorator with minimum `@settings(max_examples=100)`
    - Tag format: `# Feature: coupon-system, Property {N}: {title}`
    - _Requirements: 11.1–11.6_

  - [x] 11.2 Create `frontend/src/pages/admin/__tests__/coupon-system.properties.test.ts` with fast-check tests
    - **Property 12: Coupon form validation — discount_value by type** — For any discount_type, validate that: percentage accepts 1–100, fixed_amount accepts > 0, trial_extension accepts whole numbers > 0. Values outside ranges are rejected. **Validates: Requirements 8.3–8.5**
    - Use `fc.assert(fc.property(...))` pattern with minimum 100 iterations
    - Tag format: `// Feature: coupon-system, Property 12: {title}`
    - _Requirements: 8.3–8.5_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Run all property-based tests and unit tests. Ask the user if questions arise.

## Notes

- Migration number is 0093, revising 0092 (the latest migration)
- `coupons` table has NO RLS (global admin managed, same as `subscription_plans`)
- `organisation_coupons` table HAS RLS scoped to `org_id`
- Coupon codes are stored uppercase, lookups are case-insensitive
- `DELETE /admin/coupons/{id}` is a soft-delete (sets `is_active = false`), not a hard delete
- Public endpoints (`/coupons/validate`, `/coupons/redeem`) have no auth — they're called during signup
- Coupon redemption after signup is non-blocking — if it fails, signup still succeeds
- No Stripe sync in this iteration — effective price is for display and future billing integration
- All frontend components use existing UI library (DataTable, Modal, Input, Button, Badge, Spinner, AlertBanner, ToastContainer)

# Implementation Plan: SMS Pricing & Packages

## Overview

Implement the SMS billing subsystem by following the existing Carjam overage and storage tier pricing patterns. Work proceeds bottom-up: migration → models → schemas → service functions → notification integration → API endpoints → frontend UI. Each step builds on the previous one so there is no orphaned code.

## Tasks

- [x] 1. Database migration and model layer
  - [x] 1.1 Create Alembic migration for SMS billing fields
    - Add `per_sms_cost_nzd` (Numeric(10,4), default 0) to `subscription_plans`
    - Add `sms_included_quota` (Integer, default 0) to `subscription_plans`
    - Add `sms_package_pricing` (JSONB, nullable, default '[]') to `subscription_plans`
    - Add `sms_sent_this_month` (Integer, default 0) to `organisations`
    - Add `sms_sent_reset_at` (DateTime with timezone, nullable) to `organisations`
    - Create `sms_package_purchases` table with columns: `id` (UUID PK), `org_id` (UUID FK → organisations), `tier_name` (String(100)), `sms_quantity` (Integer), `price_nzd` (Numeric(10,2)), `credits_remaining` (Integer), `purchased_at` (DateTime tz), `created_at` (DateTime tz)
    - Include `downgrade()` that reverses all changes
    - Copy migration file into Docker container and run `alembic upgrade head`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 1.2 Add new columns to SubscriptionPlan model in `app/modules/admin/models.py`
    - Add `per_sms_cost_nzd`, `sms_included_quota`, `sms_package_pricing` mapped columns matching the migration
    - Follow the exact pattern of existing `storage_tier_pricing` and `carjam_lookups_included` columns
    - _Requirements: 1.1, 1.2, 5.1_

  - [x] 1.3 Add new columns to Organisation model in `app/modules/admin/models.py`
    - Add `sms_sent_this_month` and `sms_sent_reset_at` mapped columns matching the migration
    - Follow the exact pattern of existing `carjam_lookups_this_month`
    - _Requirements: 2.1, 2.2_

  - [x] 1.4 Create SmsPackagePurchase model in `app/modules/admin/models.py`
    - New SQLAlchemy model with all columns from the design: id, org_id, tier_name, sms_quantity, price_nzd, credits_remaining, purchased_at, created_at
    - Add relationship to Organisation
    - _Requirements: 6.3, 9.6_

- [x] 2. Pydantic schemas
  - [x] 2.1 Create SMS-specific Pydantic schemas in `app/modules/admin/schemas.py`
    - `SmsPackageTierPricing` — mirrors `StorageTierPricing` with `tier_name` (min_length=1), `sms_quantity` (gt=0), `price_nzd` (ge=0)
    - `OrgSmsUsageRow`, `AdminSmsUsageResponse`, `OrgSmsUsageResponse` — mirrors Carjam usage schemas
    - `SmsPackagePurchaseResponse`, `SmsPackagePurchaseRequest`
    - _Requirements: 5.2, 5.4, 2.6, 2.7_

  - [x] 2.2 Update PlanCreateRequest, PlanUpdateRequest, and PlanResponse schemas
    - Add `per_sms_cost_nzd` (float, ge=0, default 0), `sms_included_quota` (int, ge=0, default 0), `sms_package_pricing` (list[SmsPackageTierPricing], optional, default [])
    - Add same fields to PlanResponse
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 5.3_

  - [x] 2.3 Update PublicPlanResponse in `app/modules/auth/schemas.py`
    - Add `sms_included_quota` and `per_sms_cost_nzd` to the public plan response so signup page can show SMS info
    - _Requirements: 1.3_

  - [x] 2.4 Write property tests for schema validation (backend)
    - Create `tests/properties/test_sms_pricing_properties.py`
    - **Property 2: Negative SMS cost and quota values are rejected by validation**
    - **Validates: Requirements 1.5, 1.6**
    - **Property 11: SMS package tier validation rejects invalid entries**
    - **Validates: Requirements 5.2**

- [x] 3. Core service functions
  - [x] 3.1 Implement `compute_sms_overage` in `app/modules/admin/service.py`
    - `compute_sms_overage(total_sent: int, included_quota: int) -> int` returning `max(0, total_sent - included_quota)`
    - Follow the exact pattern of `compute_carjam_overage`
    - _Requirements: 3.1, 3.5, 3.6_

  - [x] 3.2 Write property test for SMS overage computation
    - Add to `tests/properties/test_sms_pricing_properties.py`
    - **Property 1: SMS overage computation is `max(0, total_sent - included_quota)`**
    - **Validates: Requirements 3.1, 3.5, 3.6**

  - [x] 3.3 Implement `get_effective_sms_quota` in `app/modules/admin/service.py`
    - Query plan's `sms_included_quota` + sum of `credits_remaining` from `sms_package_purchases`
    - When `sms_included` is false on the plan, return 0 regardless
    - _Requirements: 3.3, 3.4, 1.7_

  - [x] 3.4 Implement `get_org_sms_usage` and `get_all_orgs_sms_usage` in `app/modules/admin/service.py`
    - Mirror `get_all_orgs_carjam_usage` pattern exactly
    - Include package credits in effective quota calculation
    - Return org name, total sent, included quota, package credits, effective quota, overage count, overage charge
    - _Requirements: 2.6, 2.7_

  - [x] 3.5 Write property tests for effective quota and overage charge
    - Add to `tests/properties/test_sms_pricing_properties.py`
    - **Property 4: When `sms_included` is false, effective quota is 0**
    - **Validates: Requirements 1.7, 3.4**
    - **Property 8: Overage charge equals overage count times per-SMS cost**
    - **Validates: Requirements 3.2**
    - **Property 9: Effective quota includes package credits**
    - **Validates: Requirements 3.3**

  - [x] 3.6 Implement `increment_sms_usage` in `app/modules/admin/service.py`
    - Atomically increment `sms_sent_this_month` using `UPDATE ... SET sms_sent_this_month = sms_sent_this_month + 1`
    - _Requirements: 2.3_

  - [x] 3.7 Implement `purchase_sms_package` and `get_org_sms_packages` in `app/modules/admin/service.py`
    - Validate tier exists in plan's `sms_package_pricing`
    - Create Stripe one-time charge for `price_nzd`
    - On success, create `SmsPackagePurchase` record with `credits_remaining = sms_quantity`
    - On Stripe failure, return error without creating record
    - `get_org_sms_packages` returns active packages ordered by `purchased_at ASC`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_

  - [x] 3.8 Implement `compute_sms_overage_for_billing` in `app/modules/admin/service.py`
    - Calculate overage considering package credits (FIFO deduction from oldest package)
    - Return dict with overage count, per-SMS cost, total charge for renewal invoice line item
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 3.9 Write property test for FIFO credit deduction
    - Add to `tests/properties/test_sms_pricing_properties.py`
    - **Property 14: FIFO credit deduction from oldest package first**
    - **Validates: Requirements 6.7**

  - [x] 3.10 Update `create_plan` and `update_plan` in `app/modules/admin/service.py`
    - Handle new SMS fields (`per_sms_cost_nzd`, `sms_included_quota`, `sms_package_pricing`) in plan creation and update
    - _Requirements: 1.3, 1.4, 5.3_

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Notification service integration
  - [x] 5.1 Integrate SMS usage tracking into notification service
    - In `app/modules/notifications/service.py`, after successful business SMS dispatch in `process_overdue_reminders()` and `process_wof_rego_reminders()`, call `increment_sms_usage(db, org_id)`
    - Ensure `mfa_service._send_sms_otp()` code path does NOT call `increment_sms_usage` — MFA SMS must never be counted
    - Usage tracking is best-effort: log errors but do not block SMS delivery
    - _Requirements: 2.3, 2.4, 8.1, 8.2, 8.3, 8.4_

  - [x] 5.2 Write property test for MFA SMS exclusion
    - Add to `tests/properties/test_sms_pricing_properties.py`
    - **Property 6: MFA SMS never affects usage counter or package credits**
    - **Validates: Requirements 2.4, 8.1, 8.2, 8.3**

- [x] 6. API endpoints
  - [x] 6.1 Add admin SMS usage endpoint to `app/modules/admin/router.py`
    - `GET /api/v1/admin/sms-usage` — returns all orgs SMS usage (Global Admin only)
    - Uses `get_all_orgs_sms_usage` service function
    - _Requirements: 7.4_

  - [x] 6.2 Add org SMS endpoints (usage, packages, purchase)
    - `GET /api/v1/org/sms-usage` — org's own SMS usage
    - `GET /api/v1/org/sms-packages` — org's active package purchases
    - `POST /api/v1/org/sms-packages/purchase` — purchase a package by tier_name
    - Add to existing org router or create endpoints in `app/modules/admin/router.py`
    - _Requirements: 6.5, 6.6, 7.1_

  - [x] 6.3 Add SMS usage report endpoint
    - `GET /api/v1/reports/sms-usage` — returns total sent, included, overage, charge, daily breakdown
    - Follow the same pattern as the Carjam usage report endpoint
    - _Requirements: 7.1_

  - [x] 6.4 Write unit tests for SMS API endpoints
    - Add to `tests/test_sms_pricing.py`
    - Test plan CRUD with SMS fields, usage increment/reset, package purchase success/failure, overage billing, MFA exclusion
    - _Requirements: 1.3, 1.4, 2.3, 2.4, 6.1–6.7, 7.1_

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Frontend — Admin plan form SMS fields
  - [x] 8.1 Extend SubscriptionPlans.tsx plan form with SMS fields
    - Add `per_sms_cost_nzd` numeric input (shown when `sms_included` is toggled on)
    - Add `sms_included_quota` integer input (shown when `sms_included` is toggled on)
    - Add SMS package tier table with add/remove rows — follow the exact pattern of the storage tier pricing table (`StorageTierRow`)
    - Wire new fields into create/update API calls
    - _Requirements: 1.3, 1.4, 5.3, 5.6_

  - [x] 8.2 Write frontend unit tests for SMS plan form fields
    - Add to `frontend/src/__tests__/sms-pricing.test.tsx`
    - Test SMS fields render when `sms_included` is toggled, tier table add/remove, form submission includes SMS fields
    - _Requirements: 1.3, 5.6_

- [x] 9. Frontend — SMS Usage report page
  - [x] 9.1 Create `frontend/src/pages/reports/SmsUsage.tsx`
    - Mirror `CarjamUsage.tsx` layout: summary cards (Total SMS Sent, Included in Plan, Overage Count, Overage Charge), daily breakdown bar chart
    - Add active SMS packages section showing remaining credits per package
    - Add package purchase section showing available tiers with purchase buttons and confirmation dialog
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 9.2 Add SmsUsage route and navigation
    - Add route in `frontend/src/App.tsx` for the SMS usage report page
    - Add navigation link in the reports section (follow pattern of CarjamUsage route)
    - _Requirements: 7.2_

  - [x] 9.3 Write frontend unit tests for SmsUsage page
    - Add to `frontend/src/__tests__/sms-pricing.test.tsx`
    - Test summary cards render, daily chart renders, packages section renders, purchase dialog works
    - _Requirements: 7.2, 7.3_

  - [x] 9.4 Write frontend property tests for SMS calculations
    - Create `frontend/src/__tests__/sms-pricing.property.test.ts`
    - **Property 1: SMS overage computation is `max(0, total_sent - included_quota)`**
    - **Validates: Requirements 3.1, 3.5, 3.6**
    - **Property 4: When `sms_included` is false, effective quota is 0**
    - **Validates: Requirements 1.7, 3.4**
    - **Property 8: Overage charge equals overage count times per-SMS cost**
    - **Validates: Requirements 3.2**

- [x] 10. SMS overage billing integration
  - [x] 10.1 Add SMS overage line item to subscription renewal invoice
    - In the renewal invoice generation logic, call `compute_sms_overage_for_billing(db, org_id)`
    - When overage > 0, add line item: description "SMS overage: {count} messages × ${per_sms_cost_nzd}", quantity = overage count, unit price = per_sms_cost_nzd
    - When overage = 0, do not add line item
    - Reset `sms_sent_this_month` to 0 after capturing overage
    - Log to audit log with action `sms_overage.billed`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 10.2 Write property test for overage line item presence
    - Add to `tests/properties/test_sms_pricing_properties.py`
    - **Property 10: SMS overage line item appears if and only if overage is greater than 0**
    - **Validates: Requirements 4.2, 4.3**

- [x] 11. Monthly SMS counter reset
  - [x] 11.1 Add SMS counter reset to the monthly billing cycle
    - In `app/tasks/scheduled.py` or the existing monthly reset logic, reset `sms_sent_this_month` to 0 and update `sms_sent_reset_at` for all organisations
    - Follow the same pattern as the existing Carjam counter reset if one exists
    - _Requirements: 2.5_

  - [x] 11.2 Write property test for monthly reset
    - Add to `tests/properties/test_sms_pricing_properties.py`
    - **Property 7: Monthly reset sets counter to 0**
    - **Validates: Requirements 2.5**

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The existing 8 pre-existing test failures are unrelated and should be ignored
- Docker commands for migrations: `docker cp <file> invoicing-app-1:/app/<file>` then `docker exec invoicing-app-1 alembic upgrade head`
- Frontend tests run with `cwd: "frontend"` for vitest
- The `sms_included` boolean already exists on plans — do not re-add it
- MFA/verification SMS must NEVER be restricted or counted

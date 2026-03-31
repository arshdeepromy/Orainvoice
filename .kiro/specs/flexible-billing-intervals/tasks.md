# Implementation Plan: Flexible Billing Intervals

## Overview

Extend the billing system from monthly-only to support weekly, fortnightly, monthly, and annual intervals. Implementation follows a bottom-up approach: database → pure pricing logic → schemas → APIs → frontend → Stripe integration → reporting. Each task builds on the previous, ensuring no orphaned code.

## Tasks

- [x] 1. Database migration and ORM model changes
  - [x] 1.1 Create Alembic migration to add `interval_config` JSONB column to `subscription_plans` and `billing_interval` VARCHAR(20) column to `organisations`
    - Add check constraint `ck_organisations_billing_interval` for valid interval values
    - Backfill existing plans with default monthly-only config `[{"interval": "monthly", "enabled": true, "discount_percent": 0}]`
    - Backfill existing orgs with `billing_interval = 'monthly'`
    - Preserve existing `monthly_price_nzd` column unchanged
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 1.2 Update `SubscriptionPlan` ORM model in `app/modules/admin/models.py` to add `interval_config` mapped column (JSONB, server_default='[]')
    - _Requirements: 1.5_

  - [x] 1.3 Update `Organisation` ORM model to add `billing_interval` mapped column (String(20), server_default='monthly')
    - _Requirements: 6.4_

- [x] 2. Price calculation module (pure functions)
  - [x] 2.1 Create `app/modules/billing/interval_pricing.py` with pure pricing functions
    - Implement `compute_effective_price(base_monthly_price, interval, discount_percent)` using formula: `round((base × 12 / periods_per_year) × (1 − discount / 100), 2)`
    - Implement `compute_savings_amount(base_monthly_price, interval, discount_percent)`
    - Implement `compute_equivalent_monthly(effective_price, interval)`
    - Implement `validate_interval_config(config)` — reject all-disabled, reject discounts outside 0–100
    - Implement `build_default_interval_config()` — monthly enabled at 0% discount
    - Implement `apply_coupon_to_interval_price(effective_price, coupon_discount_type, coupon_discount_value)`
    - Implement `convert_coupon_duration_to_cycles(duration_months, interval)`
    - Implement `normalise_to_mrr(effective_price, interval)`
    - Use `INTERVAL_PERIODS_PER_YEAR` dict: weekly=52, fortnightly=26, monthly=12, annual=1
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 11.1, 11.2, 11.3, 12.1_

  - [x] 2.2 Write property test: effective price formula correctness
    - **Property 1: Effective price formula correctness**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6**
    - File: `tests/properties/test_billing_interval_properties.py`
    - Generator: random base price (0–10000), random interval, random discount (0–100)

  - [x] 2.3 Write property test: equivalent monthly rate never exceeds base price
    - **Property 2: Equivalent monthly rate never exceeds base price**
    - **Validates: Requirements 2.5**
    - Generator: random base price, random interval, random discount

  - [x] 2.4 Write property test: savings equals undiscounted minus effective
    - **Property 6: Savings amount equals undiscounted minus effective price**
    - **Validates: Requirements 3.3, 5.4, 13.3, 13.4**
    - Generator: random base price, random interval, random discount

  - [x] 2.5 Write property test: interval config validation rejects invalid inputs
    - **Property 4: Interval config validation rejects invalid inputs**
    - **Validates: Requirements 1.2, 1.7, 4.3, 4.4**
    - Generator: random configs with all disabled or invalid discounts

  - [x] 2.6 Write property test: coupon stacking with interval pricing
    - **Property 11: Coupon stacking with interval pricing**
    - **Validates: Requirements 11.1, 11.2**
    - Generator: random effective prices, random coupon types and values

  - [x] 2.7 Write property test: coupon duration conversion to billing cycles
    - **Property 12: Coupon duration conversion to billing cycles**
    - **Validates: Requirements 11.3**
    - Generator: random duration_months (1–36), random intervals

  - [x] 2.8 Write property test: MRR normalisation correctness
    - **Property 13: MRR normalisation correctness**
    - **Validates: Requirements 12.1**
    - Generator: random effective prices, random intervals

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Pydantic schema changes
  - [x] 4.1 Add `IntervalConfigItem` and `IntervalPricing` schemas to `app/modules/admin/schemas.py`
    - Add `interval_config` field to `PlanCreateRequest` and `PlanUpdateRequest` (optional, defaults to None)
    - Add `interval_config` and computed `intervals` fields to `PlanResponse`
    - _Requirements: 4.1, 4.2, 4.5_

  - [x] 4.2 Add billing interval schemas to `app/modules/billing/schemas.py`
    - Add `IntervalChangeRequest` with `billing_interval` field
    - Add `IntervalChangeResponse` with success, message, new_interval, new_effective_price, effective_immediately, effective_at
    - Extend `PlanChangeRequest` with optional `billing_interval` field
    - Extend `BillingDashboardResponse` with `billing_interval`, `interval_effective_price`, `equivalent_monthly_price`, `pending_interval_change`
    - _Requirements: 7.1, 7.2, 8.4, 9.1, 9.3, 9.4_

  - [x] 4.3 Extend `frontend/src/pages/auth/signup-types.ts` with `IntervalPricing` interface and add `intervals` to `PublicPlan`, add `billing_interval` to `SignupFormData`
    - _Requirements: 3.1, 5.5_

- [x] 5. Admin plan API changes
  - [x] 5.1 Update `app/modules/admin/service.py` plan create/update methods to accept and store `interval_config`
    - Call `validate_interval_config` on input
    - Default to `build_default_interval_config()` when not provided
    - Compute `intervals` (IntervalPricing list) on plan read using `compute_effective_price`, `compute_savings_amount`, `compute_equivalent_monthly`
    - _Requirements: 1.5, 1.6, 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 5.2 Update `app/modules/admin/router.py` plan endpoints to pass through `interval_config` and return computed `intervals`
    - _Requirements: 4.1, 4.2_

  - [x] 5.3 Write property test: interval config round-trip persistence
    - **Property 3: Interval config round-trip persistence**
    - **Validates: Requirements 1.5, 1.6, 4.1, 4.2**
    - File: `tests/properties/test_billing_interval_properties.py`
    - Generator: random valid interval configs

- [x] 6. Admin plan form frontend — new Pricing tab
  - [x] 6.1 Add "Pricing" tab to the plan form modal in `frontend/src/pages/admin/SubscriptionPlans.tsx`
    - Toggle switches for each interval (weekly, fortnightly, monthly, annual)
    - Monthly always enabled and cannot be disabled
    - Discount percentage input (0–100) for each enabled interval
    - Read-only effective price preview per interval computed from base monthly price
    - Validation: reject discount outside 0–100, reject all intervals disabled
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7_

- [x] 7. Public plans API changes
  - [x] 7.1 Update the public plans endpoint in `app/modules/auth/router.py` (`GET /api/v1/auth/plans`) to compute and return `intervals` array for each plan
    - Only include enabled intervals in the response
    - Compute effective_price, savings_amount, equivalent_monthly for each enabled interval
    - Legacy plans with no interval_config default to monthly-only
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 7.2 Write property test: public API returns only enabled intervals
    - **Property 5: Public API returns only enabled intervals**
    - **Validates: Requirements 3.1, 3.2**
    - File: `frontend/src/pages/admin/__tests__/billing-intervals.properties.test.ts`
    - Generator: random interval configs with mixed enabled/disabled

- [x] 8. Signup wizard frontend — IntervalSelector and plan cards
  - [x] 8.1 Create reusable `IntervalSelector` component at `frontend/src/components/billing/IntervalSelector.tsx`
    - Segmented toggle with labels for each available interval
    - Props: `intervals`, `selected`, `onChange`, `recommendedInterval`
    - Highlight recommended interval (default: monthly)
    - Animate price transitions within 300ms
    - _Requirements: 13.1, 13.2, 13.6_

  - [x] 8.2 Integrate `IntervalSelector` into `frontend/src/pages/auth/SignupWizard.tsx` plan selection step
    - Render IntervalSelector above plan cards, default to monthly
    - Update plan cards to show effective_price for selected interval
    - Show plans not supporting selected interval as unavailable
    - Display savings badge ("Save X%") and savings amount on discounted intervals
    - Display equivalent monthly cost below main price for non-monthly intervals
    - Include `billing_interval` in signup request payload
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 13.3, 13.4, 13.5_

  - [x] 8.3 Write property test: plan availability determined by interval support
    - **Property 7: Plan availability determined by interval support**
    - **Validates: Requirements 5.3, 8.3**
    - File: `frontend/src/pages/admin/__tests__/billing-intervals.properties.test.ts`
    - Generator: random interval configs, random selected intervals

- [x] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Pending signup and auth API changes
  - [x] 10.1 Update `app/modules/auth/pending_signup.py` to store `billing_interval` in the Redis pending signup blob
    - _Requirements: 5.5, 6.4_

  - [x] 10.2 Update `POST /api/v1/auth/signup` in `app/modules/auth/router.py` to accept `billing_interval` in request body
    - Compute effective_price for the selected interval when creating PaymentIntent
    - Pass billing_interval through to pending signup storage
    - _Requirements: 5.5, 6.2_

  - [x] 10.3 Update signup confirmation flow to create org with `billing_interval` and pass interval params to Stripe subscription creation
    - _Requirements: 6.1, 6.3, 6.4_

- [x] 11. Stripe integration changes
  - [x] 11.1 Extend `create_subscription_from_trial` in `app/integrations/stripe_billing.py` to accept `interval_amount_cents`, `billing_interval`, and `interval_count` parameters
    - Map billing intervals to Stripe: weekly→week/1, fortnightly→week/2, monthly→month/1, annual→year/1
    - Set `price_data.recurring.interval` and `price_data.recurring.interval_count` accordingly
    - Set `unit_amount` to effective_price in cents
    - Skip Stripe subscription creation for free plans (effective_price = 0)
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 11.2 Create `update_subscription_interval` function in `app/integrations/stripe_billing.py`
    - Accept subscription_id, new_amount_cents, stripe_interval, interval_count, proration_behavior
    - Update Stripe subscription's recurring interval and amount
    - _Requirements: 7.5_

  - [x] 11.3 Write property test: Stripe interval mapping correctness
    - **Property 8: Stripe interval mapping correctness**
    - **Validates: Requirements 6.1, 6.2**
    - File: `tests/properties/test_billing_interval_properties.py`
    - Generator: all 4 intervals with random prices

- [x] 12. Billing API — interval change and available intervals
  - [x] 12.1 Create `GET /api/v1/billing/available-intervals` endpoint in `app/modules/billing/router.py`
    - Load current plan's interval_config
    - Return available intervals with effective prices and savings amounts
    - _Requirements: 7.2_

  - [x] 12.2 Create `POST /api/v1/billing/change-interval` endpoint in `app/modules/billing/router.py`
    - Validate requested interval is enabled for current plan
    - Compute new effective_price
    - Longer interval (fewer periods/year) → immediate update with proration via Stripe
    - Shorter interval (more periods/year) → schedule change at period end, store pending change in org.settings
    - Update org.billing_interval on success
    - Rollback org.billing_interval on Stripe failure
    - Return IntervalChangeResponse
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

  - [x] 12.3 Update `GET /api/v1/billing` dashboard endpoint to return `billing_interval`, `interval_effective_price`, `equivalent_monthly_price`, and `pending_interval_change`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 12.4 Write property test: interval change direction determines timing
    - **Property 9: Interval change direction determines timing**
    - **Validates: Requirements 7.3, 7.4**
    - File: `tests/properties/test_billing_interval_properties.py`
    - Generator: random pairs of intervals

  - [x] 12.5 Write property test: interval change rollback on Stripe failure
    - **Property 10: Interval change rollback on Stripe failure**
    - **Validates: Requirements 7.6**
    - File: `tests/properties/test_billing_interval_properties.py`

- [x] 13. Billing settings frontend — interval display and change modal
  - [x] 13.1 Update `frontend/src/pages/settings/Billing.tsx` to display current billing interval alongside plan name and price
    - Show interval-labelled price (e.g., "$49.00/mo", "$470.00/yr")
    - Show equivalent monthly cost for non-monthly intervals
    - Show next billing date based on active interval
    - Show pending interval/downgrade change notice with effective date
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x] 13.2 Add "Change interval" button and modal to `frontend/src/pages/settings/Billing.tsx`
    - Fetch available intervals from `GET /api/v1/billing/available-intervals`
    - Render IntervalSelector with effective prices and savings
    - Confirmation step explaining proration (immediate) or scheduling (period end)
    - Submit to `POST /api/v1/billing/change-interval`
    - Show error toast and revert UI on failure
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 14. Plan upgrade/downgrade with interval awareness
  - [x] 14.1 Update upgrade/downgrade endpoints in `app/modules/billing/router.py` to accept optional `billing_interval` in `PlanChangeRequest`
    - Compute effective_price for new plan at selected interval
    - Upgrade: apply immediately with proration based on interval effective price
    - Downgrade: schedule at period end, store new plan_id and billing_interval in pending settings
    - Return error if target plan doesn't support selected interval
    - Same effective price → return "no change needed" message
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 14.2 Update Plan_Change_Modal in `frontend/src/pages/settings/Billing.tsx` to include IntervalSelector
    - Default to current org billing_interval
    - Show effective prices per plan for selected interval
    - Show plans not supporting selected interval as unavailable
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 15. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Coupon compatibility with billing intervals
  - [x] 16.1 Update coupon application logic in billing service to use `apply_coupon_to_interval_price` for percentage and fixed-amount coupons
    - Percentage coupon: `round(effective_price × (1 − coupon_value / 100), 2)`
    - Fixed amount coupon: `max(0, round(effective_price − coupon_value, 2))`
    - Coupon discount applied after interval discount
    - _Requirements: 11.1, 11.2_

  - [x] 16.2 Update coupon duration handling to use `convert_coupon_duration_to_cycles` for non-monthly intervals
    - Convert `duration_months` to equivalent billing cycles per interval
    - _Requirements: 11.3_

  - [x] 16.3 Display coupon-adjusted price alongside interval price in signup wizard and billing settings
    - _Requirements: 11.4_

- [x] 17. MRR reporting adjustments
  - [x] 17.1 Update MRR report in `app/modules/admin/router.py` (or reporting service) to normalise revenue across intervals using `normalise_to_mrr`
    - Weekly × 52/12, fortnightly × 26/12, monthly × 1, annual / 12
    - Add interval breakdown: count of orgs and revenue contribution per interval
    - Display interval distribution in Global Admin dashboard MRR section
    - _Requirements: 12.1, 12.2, 12.3_

- [x] 18. Scheduled tasks update
  - [x] 18.1 Update billing renewal and trial conversion tasks in `app/tasks/scheduled.py` to read `org.billing_interval` and pass correct interval parameters to Stripe
    - _Requirements: 6.1, 6.4_

- [x] 19. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The price calculation module (task 2) is pure functions with no dependencies — ideal for early testing
- Stripe integration uses inline `price_data` matching the existing pattern in `create_subscription_from_trial`

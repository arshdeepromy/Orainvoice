# Implementation Plan: Direct Stripe Billing

## Overview

Replace Stripe Subscription management with direct PaymentIntent-based charging. The application manages billing cycles locally via `next_billing_date` on Organisation, and uses Stripe solely as a payment processor through `charge_org_payment_method`. All Stripe Subscription CRUD functions are removed.

## Tasks

- [x] 1. Database migration and model update for next_billing_date
  - [x] 1.1 Add `next_billing_date` column to Organisation model
    - Add `next_billing_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)` to the `Organisation` class in `app/modules/admin/models.py`
    - _Requirements: 1.1_
  - [x] 1.2 Create Alembic migration for `next_billing_date`
    - Create `alembic/versions/XXXX_add_next_billing_date.py` with `op.add_column("organisations", sa.Column("next_billing_date", sa.DateTime(timezone=True), nullable=True))`
    - Include `downgrade` that drops the column
    - _Requirements: 1.1_

- [x] 2. Add `compute_interval_duration` helper and payment exceptions
  - [x] 2.1 Implement `compute_interval_duration` in `app/modules/billing/interval_pricing.py`
    - Add function that maps `BillingInterval` to `timedelta` or `relativedelta`: weekly→7 days, fortnightly→14 days, monthly→1 month, annual→1 year
    - Import `timedelta` from `datetime` and `relativedelta` from `dateutil.relativedelta`
    - _Requirements: 1.2, 1.3, 5.4, 6.2_
  - [x] 2.2 Add `PaymentFailedError` and `PaymentActionRequiredError` exception classes in `app/integrations/stripe_billing.py`
    - `PaymentFailedError(message, decline_code=None)` stores `decline_code` as attribute
    - `PaymentActionRequiredError` for payments requiring additional authentication
    - _Requirements: 2.4, 2.5_
  - [x] 2.3 Implement `charge_org_payment_method` in `app/integrations/stripe_billing.py`
    - Async function accepting `customer_id`, `payment_method_id`, `amount_cents`, `currency="nzd"`, `metadata=None`
    - Call `stripe.PaymentIntent.create` with `off_session=True`, `confirm=True`
    - On success return `{"payment_intent_id": ..., "status": ..., "amount_cents": ...}`
    - On `CardError` raise `PaymentFailedError` with message and `decline_code`
    - On `requires_action` status raise `PaymentActionRequiredError`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 3. Checkpoint — Verify model, migration, helper, and charge function
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement `process_recurring_billing_task` and update trial conversion
  - [x] 4.1 Implement `process_recurring_billing_task` in `app/tasks/subscriptions.py`
    - Query orgs where `status='active'`, `next_billing_date IS NOT NULL`, `next_billing_date <= utcnow()`
    - For each due org: load plan + interval config, call `compute_effective_price`, apply active coupon via `apply_coupon_to_interval_price`, get default `OrgPaymentMethod`, call `charge_org_payment_method`
    - On success: advance `next_billing_date` by `compute_interval_duration(org.billing_interval)`, reset `billing_retry_count` to 0 in `org.settings`
    - On failure: increment `billing_retry_count` in `org.settings`, transition to `grace_period` after `MAX_BILLING_RETRIES` (3) consecutive failures
    - Skip orgs with no default payment method (log warning, do not transition to grace_period)
    - Process each org independently — one failure must not block others
    - Add constants `MAX_BILLING_RETRIES = 3` and `GRACE_PERIOD_DAYS = 7`
    - Return summary dict with `charged`, `failed`, `skipped` counts
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 4.2 Rewrite `_convert_trial_to_active` in `app/tasks/subscriptions.py`
    - Replace `create_subscription_from_trial` call with `charge_org_payment_method`
    - On success: set `org.status = "active"`, set `org.next_billing_date = now + compute_interval_duration(org.billing_interval)`
    - On failure: set `org.status = "grace_period"`, log the error
    - Do not set `org.stripe_subscription_id`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.1_
  - [x] 4.3 Register `process_recurring_billing_task` in `app/tasks/scheduled.py`
    - Add to `_DAILY_TASKS` (or equivalent task list) with 900-second (15-minute) interval
    - Wire it through `_run_task_safe` like existing tasks
    - _Requirements: 5.1_

- [x] 5. Modify signup flow — remove Stripe Subscription creation
  - [x] 5.1 Update `confirm_signup_payment` in `app/modules/auth/router.py`
    - Remove import of `create_subscription_from_trial`
    - Remove the entire "5b. Create Stripe Subscription" block (lines that compute interval mapping, call `create_subscription_from_trial`, and set `org.stripe_subscription_id`)
    - After org creation, for paid plans with `interval_amount_cents > 0`: set `org.next_billing_date = datetime.now(timezone.utc) + compute_interval_duration(billing_interval)`
    - Import `compute_interval_duration` from `app.modules.billing.interval_pricing`
    - _Requirements: 3.1, 3.2, 3.3, 9.1_

- [x] 6. Modify billing interval changes — remove Stripe calls
  - [x] 6.1 Rewrite `change_billing_interval` in `app/modules/billing/router.py`
    - Remove imports of `update_subscription_interval` and `get_subscription_details`
    - Remove `_STRIPE_INTERVAL_MAP` usage and all Stripe API calls
    - Remove Stripe rollback logic and 502 error responses
    - **Immediate change (longer interval):** Update `org.billing_interval`, set `org.next_billing_date = datetime.now(timezone.utc) + compute_interval_duration(new_interval)`
    - **Scheduled change (shorter interval):** Store pending change in `org.settings["pending_interval_change"]` with `effective_at = org.next_billing_date`. Keep `org.billing_interval` as the current interval until the recurring task applies it.
    - Import `compute_interval_duration` from `app.modules.billing.interval_pricing`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.1_

- [x] 7. Modify billing dashboard — read local next_billing_date
  - [x] 7.1 Update `get_billing_dashboard` in `app/modules/billing/router.py`
    - Remove `get_subscription_details` call and the Stripe-based `next_billing_date` lookup block
    - Remove the fallback `relativedelta(months=1)` walk-forward logic
    - Read `next_billing_date` directly from `org.next_billing_date`
    - Return `None` for `next_billing_date` when `org.status == "trial"`
    - _Requirements: 8.1, 8.2, 8.3, 9.2, 9.3_

- [x] 8. Checkpoint — Verify all modified endpoints work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Remove obsolete Stripe Subscription functions
  - [x] 9.1 Delete 5 functions from `app/integrations/stripe_billing.py`
    - Remove `create_subscription_from_trial`
    - Remove `update_subscription_interval`
    - Remove `update_subscription_plan`
    - Remove `get_subscription_details`
    - Remove `handle_subscription_webhook`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [x] 9.2 Remove all dead imports of deleted functions across the codebase
    - Search for imports of the 5 removed functions in all files
    - Remove any remaining references (billing router, auth router, subscriptions task, etc.)
    - Verify retained functions still exist: `create_stripe_customer`, `create_setup_intent`, `create_payment_intent`, `create_payment_intent_no_customer`, `list_payment_methods`, `set_default_payment_method`, `detach_payment_method`, `create_invoice_item`, `report_metered_usage`, `create_billing_portal_session`
    - _Requirements: 7.6_

- [x] 10. Checkpoint — Verify no broken imports and retained functions intact
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Property-based tests for direct billing
  - [x] 11.1 Write property test: active org next_billing_date is set correctly
    - **Property 1: Active org next_billing_date is set correctly**
    - **Validates: Requirements 1.2, 1.3, 3.1, 3.3, 4.2**
  - [x] 11.2 Write property test: trial orgs have null next_billing_date
    - **Property 2: Trial orgs have null next_billing_date**
    - **Validates: Requirements 1.4, 8.3**
  - [x] 11.3 Write property test: charge_org_payment_method creates correct PaymentIntent
    - **Property 3: charge_org_payment_method creates correct PaymentIntent**
    - **Validates: Requirements 2.2, 2.3**
  - [x] 11.4 Write property test: CardError raises PaymentFailedError with decline code
    - **Property 4: CardError raises PaymentFailedError with decline code**
    - **Validates: Requirements 2.4**
  - [x] 11.5 Write property test: recurring billing query returns exactly due orgs
    - **Property 5: Recurring billing query returns exactly due orgs**
    - **Validates: Requirements 5.1**
  - [x] 11.6 Write property test: charge amount matches pricing formula
    - **Property 6: Charge amount matches pricing formula**
    - **Validates: Requirements 5.2**
  - [x] 11.7 Write property test: successful charge advances next_billing_date by interval duration
    - **Property 7: Successful charge advances next_billing_date by interval duration**
    - **Validates: Requirements 5.4**
  - [x] 11.8 Write property test: consecutive charge failures transition to grace_period
    - **Property 8: Consecutive charge failures transition to grace_period**
    - **Validates: Requirements 4.4, 5.5**
  - [x] 11.9 Write property test: independent org processing on failure
    - **Property 9: Independent org processing on failure**
    - **Validates: Requirements 5.6**
  - [x] 11.10 Write property test: immediate interval change recalculates next_billing_date
    - **Property 10: Immediate interval change recalculates next_billing_date**
    - **Validates: Requirements 6.2**
  - [x] 11.11 Write property test: scheduled interval change stores pending change
    - **Property 11: Scheduled interval change stores pending change**
    - **Validates: Requirements 6.3**
  - [x] 11.12 Write property test: dashboard returns local next_billing_date
    - **Property 12: Dashboard returns local next_billing_date**
    - **Validates: Requirements 8.1**

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- All property tests use `hypothesis` and go in `tests/properties/test_direct_billing_properties.py`
- Unit tests go in `tests/test_direct_billing.py`
- Each task references specific requirements for traceability
- The design uses Python throughout — no language selection needed
- `stripe_subscription_id` column is retained on the table but no code reads/writes it for billing logic

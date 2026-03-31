# Requirements Document

## Introduction

Replace Stripe Subscriptions with direct PaymentIntent-based charging. The application manages plans, billing intervals, and subscription lifecycle locally. Stripe is used solely as a payment processor via `PaymentIntent.create(off_session=True, confirm=True)` against saved payment methods. This aligns the codebase with reality — the Stripe account has 0 subscriptions and the existing `create_subscription_from_trial` call was silently failing due to a stripe v14 `product_data` incompatibility.

## Glossary

- **Billing_Engine**: The application-side billing logic that computes charges, tracks billing cycles, and initiates payments via Stripe PaymentIntents.
- **Organisation**: A tenant record representing a customer business. Holds plan, billing interval, payment method references, and billing cycle state.
- **Scheduled_Billing_Task**: The periodic task (`app/tasks/subscriptions.py`) that finds organisations due for payment and charges them.
- **Stripe_Billing_Integration**: The module `app/integrations/stripe_billing.py` that wraps Stripe API calls.
- **OrgPaymentMethod**: The local table storing saved card references (`stripe_payment_method_id`, brand, last4, expiry).
- **SubscriptionPlan**: The local table defining available plans with pricing and interval configuration.
- **next_billing_date**: A datetime field on Organisation indicating when the next recurring charge is due.

## Requirements

### Requirement 1: Add next_billing_date to Organisation

**User Story:** As a billing system, I want each Organisation to have a `next_billing_date` field, so that the scheduled task knows when to charge each org.

#### Acceptance Criteria

1. THE Organisation model SHALL include a nullable `next_billing_date` column of type `DateTime(timezone=True)`.
2. WHEN an Organisation transitions from trial to active status, THE Billing_Engine SHALL set `next_billing_date` to the current timestamp plus the Organisation's billing interval duration.
3. WHEN a new Organisation is created with status "active" (paid signup, no trial), THE Billing_Engine SHALL set `next_billing_date` to the current timestamp plus the Organisation's billing interval duration.
4. WHILE an Organisation has status "trial", THE Organisation SHALL have `next_billing_date` set to NULL.

### Requirement 2: Direct PaymentIntent Charging Function

**User Story:** As a developer, I want a single `charge_org_payment_method` function in `stripe_billing.py`, so that recurring billing charges a saved card directly without creating Stripe Subscriptions.

#### Acceptance Criteria

1. THE Stripe_Billing_Integration SHALL expose an async function `charge_org_payment_method` that accepts `customer_id`, `payment_method_id`, `amount_cents`, `currency`, and `metadata` parameters.
2. WHEN `charge_org_payment_method` is called, THE Stripe_Billing_Integration SHALL create a Stripe PaymentIntent with `customer`, `payment_method`, `amount`, `off_session=True`, and `confirm=True`.
3. WHEN the PaymentIntent succeeds, THE `charge_org_payment_method` function SHALL return a dict containing `payment_intent_id`, `status`, and `amount_cents`.
4. IF the PaymentIntent fails with a `CardError`, THEN THE `charge_org_payment_method` function SHALL raise an exception containing the Stripe error message and decline code.
5. IF the PaymentIntent requires additional authentication, THEN THE `charge_org_payment_method` function SHALL raise an exception indicating that the payment requires action.

### Requirement 3: Remove Stripe Subscription Creation from Signup

**User Story:** As a developer, I want the signup flow to stop creating Stripe Subscriptions, so that billing is handled entirely through direct charges.

#### Acceptance Criteria

1. WHEN `confirm_signup_payment` completes successfully for a paid plan, THE Auth_Router SHALL set `next_billing_date` on the new Organisation instead of calling `create_subscription_from_trial`.
2. THE `confirm_signup_payment` endpoint SHALL NOT call `create_subscription_from_trial` or set `stripe_subscription_id`.
3. WHEN `confirm_signup_payment` creates an Organisation with a paid plan, THE Auth_Router SHALL set `next_billing_date` to the current timestamp plus the selected billing interval duration.

### Requirement 4: Remove Stripe Subscription Creation from Trial Conversion

**User Story:** As a developer, I want trial-to-active conversion to use direct charges instead of creating Stripe Subscriptions, so that the billing model is consistent.

#### Acceptance Criteria

1. WHEN a trial Organisation's `trial_ends_at` has passed and the Organisation has a valid default payment method, THE Scheduled_Billing_Task SHALL charge the Organisation's saved card using `charge_org_payment_method`.
2. WHEN trial conversion charging succeeds, THE Scheduled_Billing_Task SHALL set the Organisation status to "active" and set `next_billing_date` to the current timestamp plus the billing interval duration.
3. THE `_convert_trial_to_active` function SHALL NOT call `create_subscription_from_trial` or set `stripe_subscription_id`.
4. IF trial conversion charging fails, THEN THE Scheduled_Billing_Task SHALL set the Organisation status to "grace_period" and log the failure.

### Requirement 5: Recurring Billing via Scheduled Task

**User Story:** As a billing system, I want a scheduled task that periodically charges organisations whose billing cycle is due, so that recurring revenue is collected without Stripe Subscriptions.

#### Acceptance Criteria

1. THE Scheduled_Billing_Task SHALL query for all Organisations where `status` is "active", `next_billing_date` is not NULL, and `next_billing_date` is less than or equal to the current timestamp.
2. FOR EACH due Organisation, THE Scheduled_Billing_Task SHALL compute the charge amount based on the Organisation's plan, billing interval, interval discount, and any active coupon discounts.
3. FOR EACH due Organisation, THE Scheduled_Billing_Task SHALL retrieve the default OrgPaymentMethod and call `charge_org_payment_method` with the Organisation's `stripe_customer_id` and the payment method's `stripe_payment_method_id`.
4. WHEN a recurring charge succeeds, THE Scheduled_Billing_Task SHALL advance `next_billing_date` by the Organisation's billing interval duration.
5. IF a recurring charge fails, THEN THE Scheduled_Billing_Task SHALL increment a retry counter, log the failure, and transition the Organisation to "grace_period" status after a configurable number of retries.
6. THE Scheduled_Billing_Task SHALL process each Organisation independently so that one failure does not block other charges.

### Requirement 6: Remove Stripe Subscription Interval Updates from Billing Interval Changes

**User Story:** As a developer, I want billing interval changes to only update local data, so that the app does not attempt to modify non-existent Stripe Subscriptions.

#### Acceptance Criteria

1. WHEN an org admin changes the billing interval, THE Billing_Router SHALL update `org.billing_interval` in the database without calling `update_subscription_interval`.
2. WHEN an org admin changes to a longer billing interval (immediate change), THE Billing_Router SHALL recalculate `next_billing_date` based on the new interval from the current date.
3. WHEN an org admin changes to a shorter billing interval (scheduled change), THE Billing_Router SHALL store the pending change and apply the new `next_billing_date` at the end of the current billing period.
4. THE `change_billing_interval` endpoint SHALL NOT call any Stripe Subscription API methods.
5. THE `change_billing_interval` endpoint SHALL NOT return a 502 error due to Stripe failures, since Stripe is not involved in interval changes.

### Requirement 7: Remove Obsolete Stripe Subscription Functions

**User Story:** As a developer, I want to remove dead code that manages Stripe Subscriptions, so that the codebase is clean and does not confuse future maintainers.

#### Acceptance Criteria

1. THE Stripe_Billing_Integration SHALL NOT contain the `create_subscription_from_trial` function.
2. THE Stripe_Billing_Integration SHALL NOT contain the `update_subscription_interval` function.
3. THE Stripe_Billing_Integration SHALL NOT contain the `update_subscription_plan` function.
4. THE Stripe_Billing_Integration SHALL NOT contain the `get_subscription_details` function.
5. THE Stripe_Billing_Integration SHALL NOT contain the `handle_subscription_webhook` function.
6. THE Stripe_Billing_Integration SHALL retain `create_stripe_customer`, `create_setup_intent`, `create_payment_intent`, `create_payment_intent_no_customer`, `list_payment_methods`, `set_default_payment_method`, and `detach_payment_method` functions.

### Requirement 8: Billing Dashboard next_billing_date from Local Data

**User Story:** As an org admin, I want the billing dashboard to show the next billing date from local data, so that it works correctly without Stripe Subscriptions.

#### Acceptance Criteria

1. WHEN the billing dashboard is loaded, THE Billing_Router SHALL read `next_billing_date` directly from the Organisation record instead of querying Stripe subscription details.
2. THE `get_billing_dashboard` endpoint SHALL NOT call `get_subscription_details` to determine the next billing date.
3. WHEN an Organisation has status "trial", THE Billing_Router SHALL return `next_billing_date` as NULL in the dashboard response.

### Requirement 9: Deprecate stripe_subscription_id Field

**User Story:** As a developer, I want to stop writing to `stripe_subscription_id` on Organisation, so that the field can be safely removed in a future migration.

#### Acceptance Criteria

1. THE Billing_Engine SHALL NOT write new values to `Organisation.stripe_subscription_id` in any code path.
2. THE Organisation model SHALL retain the `stripe_subscription_id` column to avoid a breaking migration, but no code SHALL read from the field for billing logic.
3. WHEN the billing dashboard or any endpoint previously checked `stripe_subscription_id` to determine billing state, THE endpoint SHALL use `next_billing_date` and `org.status` instead.

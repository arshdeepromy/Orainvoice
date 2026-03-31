# Requirements Document

## Introduction

The platform currently supports only monthly billing (`monthly_price_nzd` on `SubscriptionPlan`). This feature introduces flexible billing intervals — weekly, fortnightly, monthly, and annual — for every subscription plan. Admins configure a base monthly price and per-interval discount percentages; the system computes effective prices, displays savings to end users, and synchronises with Stripe for recurring charges at the chosen interval. The feature integrates with the existing signup wizard, org billing settings (upgrade/downgrade), coupon system, and Stripe payment methods without introducing dead ends.

## Glossary

- **Billing_Interval**: One of `weekly`, `fortnightly`, `monthly`, or `annual` — the cadence at which a subscription is charged.
- **Plan_Interval_Config**: A JSON structure stored on `SubscriptionPlan` that maps each enabled `Billing_Interval` to its discount percentage and computed price.
- **Base_Monthly_Price**: The `monthly_price_nzd` value on `SubscriptionPlan`, used as the reference for computing all interval prices.
- **Interval_Discount**: A percentage (0–100) applied to the annualised cost derived from `Base_Monthly_Price` for a given `Billing_Interval`.
- **Effective_Price**: The final price charged per billing cycle for a given `Billing_Interval`, after applying the `Interval_Discount`.
- **Savings_Amount**: The monetary difference between the undiscounted interval price and the `Effective_Price`, displayed to the user.
- **Interval_Selector**: A UI toggle/tab component that lets users switch between available `Billing_Interval` options to compare prices.
- **Admin_Plan_Form**: The modal form in `SubscriptionPlans.tsx` used by Global Admins to create and edit plans.
- **Signup_Wizard**: The multi-step signup flow (`SignupWizard.tsx` / `SignupForm.tsx`) where new organisations select a plan.
- **Billing_Settings_Page**: The org settings page (`Billing.tsx`) where org admins view their current plan and change plans.
- **Plan_Change_Modal**: The modal in `Billing_Settings_Page` used for upgrading or downgrading plans.
- **Stripe_Subscription**: The Stripe `Subscription` object managed via `stripe_billing.py` for recurring charges.
- **Organisation**: A tenant record in the `organisations` table, linked to a `SubscriptionPlan` via `plan_id`.
- **Proration**: Stripe's mechanism for adjusting charges when a subscription changes mid-cycle.

## Requirements

### Requirement 1: Plan Interval Configuration by Admin

**User Story:** As a Global Admin, I want to configure which billing intervals are available for each plan and set discount percentages per interval, so that I can offer flexible pricing to customers.

#### Acceptance Criteria

1. WHEN a Global Admin creates a plan, THE Admin_Plan_Form SHALL display an "Intervals & Discounts" configuration section with toggles for each Billing_Interval (weekly, fortnightly, monthly, annual).
2. THE Admin_Plan_Form SHALL enable the monthly interval by default and prevent the admin from disabling all intervals (at least one Billing_Interval must remain enabled).
3. WHEN a Global Admin enables a Billing_Interval, THE Admin_Plan_Form SHALL display a discount percentage input field (0–100) for that interval, defaulting to 0.
4. THE Admin_Plan_Form SHALL compute and display a read-only preview of the Effective_Price for each enabled Billing_Interval based on the Base_Monthly_Price and the entered Interval_Discount.
5. WHEN a Global Admin saves a plan with interval configuration, THE Plan_Service SHALL store the Plan_Interval_Config as a JSONB column on the `subscription_plans` table.
6. WHEN a Global Admin edits an existing plan, THE Admin_Plan_Form SHALL load and display the current Plan_Interval_Config for modification.
7. IF a Global Admin enters a discount percentage outside the range 0–100, THEN THE Admin_Plan_Form SHALL display a validation error and prevent saving.

### Requirement 2: Effective Price Calculation

**User Story:** As the system, I want to compute accurate per-interval prices from the base monthly price and discount percentages, so that all pricing is consistent and correct.

#### Acceptance Criteria

1. THE Billing_Service SHALL compute the weekly Effective_Price as: `(Base_Monthly_Price × 12 / 52) × (1 − Interval_Discount / 100)`, rounded to 2 decimal places.
2. THE Billing_Service SHALL compute the fortnightly Effective_Price as: `(Base_Monthly_Price × 12 / 26) × (1 − Interval_Discount / 100)`, rounded to 2 decimal places.
3. THE Billing_Service SHALL compute the monthly Effective_Price as: `Base_Monthly_Price × (1 − Interval_Discount / 100)`, rounded to 2 decimal places.
4. THE Billing_Service SHALL compute the annual Effective_Price as: `(Base_Monthly_Price × 12) × (1 − Interval_Discount / 100)`, rounded to 2 decimal places.
5. FOR ALL valid Plan_Interval_Config values, computing the Effective_Price and then deriving the equivalent monthly rate SHALL produce a value less than or equal to the Base_Monthly_Price (round-trip consistency property).
6. IF the Base_Monthly_Price is 0 (free plan), THEN THE Billing_Service SHALL return an Effective_Price of 0 for all Billing_Intervals regardless of discount.

### Requirement 3: Public Plan API with Interval Pricing

**User Story:** As a frontend consumer, I want the public plans API to return interval pricing details, so that I can display pricing cards with interval options.

#### Acceptance Criteria

1. WHEN the public plans endpoint (`GET /api/v1/auth/plans`) is called, THE Auth_Router SHALL return each plan with an `intervals` array containing objects with `interval`, `enabled`, `discount_percent`, `effective_price`, and `savings_amount` fields.
2. THE Auth_Router SHALL only include intervals where `enabled` is true in the public response.
3. THE Auth_Router SHALL compute `savings_amount` as the difference between the undiscounted interval price and the Effective_Price for each interval.
4. WHEN a plan has no Plan_Interval_Config (legacy plan), THE Auth_Router SHALL default to returning only the monthly interval with 0 discount and the existing `monthly_price_nzd` as the Effective_Price.

### Requirement 4: Admin Plan API with Interval Configuration

**User Story:** As a Global Admin, I want the admin plan API to accept and return interval configuration, so that I can manage interval pricing through the API.

#### Acceptance Criteria

1. WHEN a Global Admin creates a plan via `POST /api/v1/admin/plans`, THE Admin_Router SHALL accept an optional `interval_config` field containing a list of interval objects with `interval`, `enabled`, and `discount_percent` properties.
2. WHEN a Global Admin updates a plan via `PUT /api/v1/admin/plans/{id}`, THE Admin_Router SHALL accept the `interval_config` field and update the stored Plan_Interval_Config.
3. THE Admin_Router SHALL validate that at least one interval is enabled in the submitted `interval_config`.
4. THE Admin_Router SHALL validate that each `discount_percent` value is between 0 and 100 inclusive.
5. IF no `interval_config` is provided during plan creation, THEN THE Admin_Router SHALL default to monthly-only with 0 discount.

### Requirement 5: Interval Selection During Signup

**User Story:** As a new user signing up, I want to choose a billing interval when selecting a plan, so that I can pick the payment frequency that suits me.

#### Acceptance Criteria

1. WHEN the Signup_Wizard displays the plan selection step, THE Signup_Wizard SHALL render an Interval_Selector above or alongside the plan cards, showing all intervals available across the displayed plans.
2. WHEN a user selects a Billing_Interval via the Interval_Selector, THE Signup_Wizard SHALL update all plan cards to show the Effective_Price for the selected interval.
3. WHEN a plan does not support the currently selected Billing_Interval, THE Signup_Wizard SHALL display that plan card as unavailable with a message indicating the interval is not offered for that plan.
4. THE Signup_Wizard SHALL display the Savings_Amount on each plan card when the selected interval has a non-zero discount, formatted as "Save $X.XX" or "Save X%".
5. WHEN a user submits the signup form, THE Signup_Wizard SHALL include the selected `billing_interval` in the signup request payload alongside the `plan_id`.
6. THE Signup_Wizard SHALL default the Interval_Selector to the monthly interval on initial load.

### Requirement 6: Stripe Subscription Creation with Interval

**User Story:** As the system, I want to create Stripe subscriptions with the correct billing interval and amount, so that customers are charged at the frequency they chose.

#### Acceptance Criteria

1. WHEN a new subscription is created (post-signup or post-trial), THE Stripe_Billing_Service SHALL create the Stripe Subscription with the `recurring.interval` matching the selected Billing_Interval (`week` for weekly, `week` with `interval_count=2` for fortnightly, `month` for monthly, `year` for annual).
2. THE Stripe_Billing_Service SHALL set the `unit_amount` on the Stripe Price to the Effective_Price in cents for the selected Billing_Interval.
3. WHEN a free plan (Effective_Price = 0) is selected, THE Stripe_Billing_Service SHALL skip Stripe subscription creation entirely.
4. THE Organisation record SHALL store the selected `billing_interval` so the system knows the current interval for the subscription.

### Requirement 7: Interval Change for Existing Organisations

**User Story:** As an org admin, I want to change my billing interval (e.g., switch from monthly to annual) without changing my plan, so that I can take advantage of discounts.

#### Acceptance Criteria

1. WHEN an org admin opens the Billing_Settings_Page, THE Billing_Settings_Page SHALL display the current Billing_Interval alongside the current plan name and price.
2. THE Billing_Settings_Page SHALL provide a "Change interval" option that opens a modal showing all available intervals for the current plan with their Effective_Prices and Savings_Amounts.
3. WHEN an org admin selects a longer interval (e.g., monthly → annual), THE Billing_Service SHALL treat the change as an immediate update with proration via Stripe.
4. WHEN an org admin selects a shorter interval (e.g., annual → monthly), THE Billing_Service SHALL schedule the change to take effect at the end of the current billing period.
5. WHEN an interval change is confirmed, THE Billing_Service SHALL update the Organisation's `billing_interval` field and the Stripe Subscription's recurring interval and amount.
6. IF the Stripe subscription update fails during an interval change, THEN THE Billing_Service SHALL roll back the Organisation's `billing_interval` to its previous value and return an error message.

### Requirement 8: Plan Upgrade/Downgrade with Interval Awareness

**User Story:** As an org admin, I want to upgrade or downgrade my plan while keeping or changing my billing interval, so that I have full flexibility over my subscription.

#### Acceptance Criteria

1. WHEN an org admin opens the Plan_Change_Modal, THE Plan_Change_Modal SHALL display an Interval_Selector defaulting to the organisation's current Billing_Interval.
2. THE Plan_Change_Modal SHALL show each available plan's Effective_Price for the selected Billing_Interval, along with the Savings_Amount where applicable.
3. WHEN a plan does not support the selected Billing_Interval, THE Plan_Change_Modal SHALL display that plan as unavailable with a note indicating which intervals the plan supports.
4. WHEN an org admin confirms a plan change, THE Billing_Service SHALL send both the `new_plan_id` and the selected `billing_interval` to the upgrade or downgrade endpoint.
5. THE upgrade endpoint SHALL apply the new plan immediately with proration calculated based on the Effective_Price of the new plan at the selected Billing_Interval.
6. THE downgrade endpoint SHALL schedule the plan change at the end of the current billing period, storing both the new plan ID and the new Billing_Interval in the pending downgrade settings.
7. IF the target plan and interval combination results in the same Effective_Price as the current subscription, THEN THE Billing_Service SHALL return a message indicating no change is needed.

### Requirement 9: Billing Dashboard Interval Display

**User Story:** As an org admin, I want my billing dashboard to reflect my chosen billing interval, so that I see accurate billing information.

#### Acceptance Criteria

1. THE Billing_Settings_Page SHALL display the current plan price labelled with the active Billing_Interval (e.g., "$49.00/mo", "$470.00/yr", "$12.00/wk").
2. THE Billing_Settings_Page SHALL display the next billing date based on the active Billing_Interval cycle.
3. WHEN the organisation has a pending downgrade or interval change, THE Billing_Settings_Page SHALL display a notice showing the upcoming change and its effective date.
4. THE Billing_Settings_Page SHALL display the equivalent monthly cost alongside the interval price for non-monthly intervals, so the org admin can compare.

### Requirement 10: Migration of Existing Plans and Organisations

**User Story:** As the system, I want existing plans and organisations to continue working after the migration, so that no current customer is disrupted.

#### Acceptance Criteria

1. WHEN the database migration runs, THE Migration SHALL add a `billing_interval` column (default `monthly`) to the `organisations` table and an `interval_config` JSONB column to the `subscription_plans` table.
2. THE Migration SHALL set `billing_interval` to `monthly` for all existing Organisation records.
3. THE Migration SHALL set `interval_config` to a default monthly-only configuration (monthly enabled, 0 discount) for all existing SubscriptionPlan records.
4. WHEN an existing plan has no `interval_config`, THE system SHALL treat the plan as monthly-only with the existing `monthly_price_nzd` as the Effective_Price.
5. THE Migration SHALL preserve the existing `monthly_price_nzd` column and all existing data without modification.

### Requirement 11: Coupon Compatibility with Billing Intervals

**User Story:** As the system, I want coupons to work correctly with all billing intervals, so that discounts are applied accurately regardless of payment frequency.

#### Acceptance Criteria

1. WHEN a coupon with a percentage discount is applied, THE Billing_Service SHALL apply the coupon discount to the Effective_Price of the selected Billing_Interval (coupon discount stacks on top of interval discount).
2. WHEN a coupon with a fixed amount discount is applied, THE Billing_Service SHALL apply the fixed discount to the per-cycle Effective_Price of the selected Billing_Interval.
3. WHEN a coupon has a `duration_months` limit, THE Billing_Service SHALL convert the duration to the equivalent number of billing cycles for the active Billing_Interval (e.g., 3 months = 3 monthly cycles, 12 weekly cycles, 6 fortnightly cycles, or apply proportionally for annual).
4. THE Billing_Service SHALL display the coupon-adjusted price alongside the interval price on the Signup_Wizard and Billing_Settings_Page.

### Requirement 12: MRR and Revenue Reporting with Intervals

**User Story:** As a Global Admin, I want revenue reports to normalise all subscriptions to a monthly equivalent, so that MRR calculations remain accurate across mixed billing intervals.

#### Acceptance Criteria

1. THE Reporting_Service SHALL compute MRR by normalising each organisation's Effective_Price to a monthly equivalent: weekly × 52/12, fortnightly × 26/12, monthly × 1, annual / 12.
2. WHEN the MRR report is generated, THE Reporting_Service SHALL include a breakdown by Billing_Interval showing the count of organisations and revenue contribution per interval.
3. THE Reporting_Service SHALL display the interval distribution in the Global Admin dashboard MRR section.

### Requirement 13: Interval-Aware Pricing Display on Frontend

**User Story:** As a prospective customer viewing the pricing page, I want to toggle between billing intervals and see how much I save with longer commitments, so that I can make an informed decision.

#### Acceptance Criteria

1. THE Interval_Selector component SHALL render as a segmented toggle with labels for each available Billing_Interval (e.g., "Weekly", "Fortnightly", "Monthly", "Annual").
2. WHEN a user toggles to a different Billing_Interval, THE pricing cards SHALL animate the price transition smoothly within 300 milliseconds.
3. THE pricing cards SHALL display a savings badge (e.g., "Save 15%") on intervals that have a non-zero Interval_Discount.
4. THE pricing cards SHALL display the Savings_Amount in currency (e.g., "You save $58.80/yr") below the Effective_Price for discounted intervals.
5. THE pricing cards SHALL display the equivalent monthly cost in smaller text below the main price for weekly, fortnightly, and annual intervals (e.g., "$470/yr ($39.17/mo)").
6. THE Interval_Selector component SHALL highlight the most popular or recommended interval (configurable by admin, defaulting to monthly).

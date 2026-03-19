# Requirements Document

## Introduction

This feature adds a coupon system to the Subscription Management admin page (`/admin/plans`). Global admins can create, manage, and configure discount coupons that apply to any subscription plan. Coupons support three discount modes: percentage off, fixed amount off, and custom trial period extensions. Time-limited discounts allow a discount for a set number of billing months before reverting to full price. Coupons are plan-agnostic (not tied to specific plans) and are tracked per-organisation. The coupon tables are global admin-managed and do NOT use row-level security, following the same pattern as `subscription_plans`. A new "Coupons" tab is added to the existing Subscription Management page alongside the plans table and global storage pricing section.

## Glossary

- **Coupon**: A global admin-created record that defines a discount or trial extension, identified by a unique coupon code. Stored in the `coupons` table without RLS.
- **Coupon_Code**: A case-insensitive alphanumeric string (e.g. "SAVE20", "TRIAL60") that users enter during signup to apply a coupon.
- **Organisation_Coupon**: A join record in the `organisation_coupons` table that tracks which coupon was applied to which organisation, including the applied date and discount state. This table uses RLS scoped to `org_id`.
- **Discount_Type**: One of three coupon modes: "percentage" (percentage off monthly price), "fixed_amount" (fixed NZD amount off monthly price), or "trial_extension" (extends trial period beyond plan default).
- **Time_Limited_Discount**: A discount coupon where `duration_months` is set, meaning the discount applies for that many billing months and then reverts to the plan's full price.
- **Perpetual_Discount**: A discount coupon where `duration_months` is null, meaning the discount applies indefinitely for the lifetime of the subscription.
- **Usage_Limit**: The maximum number of times a coupon can be redeemed across all organisations. Null means unlimited redemptions.
- **Global_Admin**: A platform administrator with access to coupon CRUD, usage limit adjustments, and cross-organisation coupon reporting.
- **Signup_Flow**: The existing organisation registration process where a new user selects a plan and optionally enters a Coupon_Code.
- **Admin_Coupon_UI**: The new "Coupons" tab on the Subscription Management page (`SubscriptionPlans.tsx`) for managing coupons.
- **Effective_Price**: The monthly price an organisation pays after coupon discount is applied, calculated as `plan.monthly_price_nzd - discount_amount` (floored at $0.00).

## Requirements

### Requirement 1: Coupon Data Model

**User Story:** As a developer, I want a coupon data model that supports percentage discounts, fixed amount discounts, and trial extensions with optional time limits and usage caps, so that the platform can store and enforce coupon rules.

#### Acceptance Criteria

1. THE Platform SHALL create a `coupons` table with columns: `id` (UUID, primary key), `code` (String(50), unique, not null), `description` (String(255), nullable), `discount_type` (String(20), not null), `discount_value` (Numeric(10,2), not null), `duration_months` (Integer, nullable), `usage_limit` (Integer, nullable), `times_redeemed` (Integer, default 0), `is_active` (Boolean, default true), `starts_at` (DateTime with timezone, nullable), `expires_at` (DateTime with timezone, nullable), `created_at` (DateTime with timezone), `updated_at` (DateTime with timezone).
2. THE `coupons` table SHALL enforce a check constraint on `discount_type` allowing only the values "percentage", "fixed_amount", or "trial_extension".
3. WHEN `discount_type` is "percentage", THE `discount_value` SHALL represent a percentage between 1 and 100.
4. WHEN `discount_type` is "fixed_amount", THE `discount_value` SHALL represent an NZD amount greater than zero.
5. WHEN `discount_type` is "trial_extension", THE `discount_value` SHALL represent the number of additional trial days to add beyond the plan default.
6. THE `coupons` table SHALL NOT have row-level security enabled, following the same global admin pattern as the `subscription_plans` table.
7. THE Platform SHALL create an `organisation_coupons` table with columns: `id` (UUID, primary key), `org_id` (UUID, foreign key to organisations, not null), `coupon_id` (UUID, foreign key to coupons, not null), `applied_at` (DateTime with timezone, not null), `billing_months_used` (Integer, default 0), `is_expired` (Boolean, default false), `created_at` (DateTime with timezone).
8. THE `organisation_coupons` table SHALL enforce a unique constraint on `(org_id, coupon_id)` to prevent an organisation from applying the same coupon twice.
9. THE `organisation_coupons` table SHALL enforce row-level security scoped to `org_id`, following the existing multi-tenant pattern for organisation-scoped data.
10. THE Platform SHALL create database indexes on `coupons(code)` for fast lookup and `organisation_coupons(org_id)` for efficient per-organisation queries.

### Requirement 2: Coupon CRUD API Endpoints

**User Story:** As a Global Admin, I want API endpoints to create, read, update, and delete coupons, so that I can manage the coupon catalogue from the admin interface.

#### Acceptance Criteria

1. THE Platform SHALL provide a `GET /admin/coupons` endpoint that returns a paginated list of all coupons, ordered by `created_at` descending, including `times_redeemed` for each coupon.
2. THE Platform SHALL provide a `POST /admin/coupons` endpoint that accepts `code`, `description`, `discount_type`, `discount_value`, `duration_months`, `usage_limit`, `starts_at`, and `expires_at` fields and creates a new Coupon record.
3. THE Platform SHALL provide a `GET /admin/coupons/{coupon_id}` endpoint that returns a single coupon with its full details and a list of organisations that have redeemed the coupon.
4. THE Platform SHALL provide a `PUT /admin/coupons/{coupon_id}` endpoint that allows updating `description`, `discount_value`, `duration_months`, `usage_limit`, `is_active`, `starts_at`, and `expires_at` fields on an existing coupon.
5. THE Platform SHALL provide a `DELETE /admin/coupons/{coupon_id}` endpoint that soft-deletes a coupon by setting `is_active` to false.
6. WHEN creating a coupon, THE Platform SHALL normalise the `code` field to uppercase and trim whitespace.
7. IF a coupon with the same `code` already exists, THEN THE Platform SHALL return a 409 Conflict error with a descriptive message.
8. WHEN updating `usage_limit`, THE Platform SHALL allow the Global_Admin to increase or decrease the limit, provided the new limit is not less than `times_redeemed`.

### Requirement 3: Coupon Validation and Redemption

**User Story:** As a new user signing up, I want to enter a coupon code during signup, so that I can receive a discount or extended trial on my subscription.

#### Acceptance Criteria

1. THE Platform SHALL provide a `POST /coupons/validate` public endpoint that accepts a `code` field and returns the coupon details (discount_type, discount_value, duration_months, description) if the coupon is valid, or an error message if invalid.
2. WHEN validating a coupon, THE Platform SHALL check that the coupon `is_active` is true, `times_redeemed` is less than `usage_limit` (if set), the current date is after `starts_at` (if set), and the current date is before `expires_at` (if set).
3. IF any validation check fails, THEN THE Platform SHALL return a specific error message indicating the reason: "Coupon not found", "Coupon has expired", "Coupon is not yet active", or "Coupon usage limit reached".
4. THE Platform SHALL provide a `POST /coupons/redeem` endpoint (called during signup finalisation) that accepts `code` and `org_id`, creates an Organisation_Coupon record, increments the coupon's `times_redeemed` counter, and applies the coupon effect to the organisation.
5. WHEN redeeming a "percentage" or "fixed_amount" coupon, THE Platform SHALL store the Organisation_Coupon record with `billing_months_used` set to 0 and `is_expired` set to false.
6. WHEN redeeming a "trial_extension" coupon, THE Platform SHALL extend the organisation's `trial_ends_at` by the number of days specified in `discount_value`, added to the plan's default trial end date.
7. IF the organisation already has the same coupon applied, THEN THE Platform SHALL return a 409 Conflict error indicating the coupon has already been redeemed.
8. THE coupon redemption operation SHALL be atomic: if any step fails, no partial changes SHALL persist.

### Requirement 4: Coupon Code Entry During Signup

**User Story:** As a new user, I want a coupon code input field on the signup page, so that I can apply a discount before completing registration.

#### Acceptance Criteria

1. THE Signup_Flow SHALL display an optional "Have a coupon code?" expandable section with a text input field and an "Apply" button.
2. WHEN the user enters a code and clicks "Apply", THE Signup_Flow SHALL call the `POST /coupons/validate` endpoint and display the coupon details (discount type, value, duration) on success.
3. WHEN a valid coupon is applied, THE Signup_Flow SHALL display the Effective_Price alongside the original plan price, showing the discount breakdown.
4. WHEN a "trial_extension" coupon is applied, THE Signup_Flow SHALL display the extended trial duration instead of a price discount.
5. IF the validation endpoint returns an error, THEN THE Signup_Flow SHALL display the error message inline below the coupon input field.
6. THE Signup_Flow SHALL allow the user to remove an applied coupon before completing signup.
7. WHEN the user completes signup with a valid coupon applied, THE Signup_Flow SHALL call the `POST /coupons/redeem` endpoint with the coupon code and the newly created organisation ID.

### Requirement 5: Time-Limited Discount Tracking

**User Story:** As a platform operator, I want time-limited discounts to automatically expire after the specified number of billing months, so that organisations revert to full price without manual intervention.

#### Acceptance Criteria

1. WHEN a Time_Limited_Discount coupon is active on an organisation, THE Platform SHALL increment the `billing_months_used` counter on the Organisation_Coupon record at each billing cycle.
2. WHEN `billing_months_used` reaches the coupon's `duration_months` value, THE Platform SHALL set `is_expired` to true on the Organisation_Coupon record.
3. WHILE an Organisation_Coupon `is_expired` is false and the coupon `discount_type` is "percentage", THE Platform SHALL calculate the Effective_Price as `plan.monthly_price_nzd × (1 - discount_value / 100)`.
4. WHILE an Organisation_Coupon `is_expired` is false and the coupon `discount_type` is "fixed_amount", THE Platform SHALL calculate the Effective_Price as `max(0, plan.monthly_price_nzd - discount_value)`.
5. WHEN a Perpetual_Discount coupon is applied, THE Platform SHALL leave `duration_months` as null and the discount SHALL remain active indefinitely without expiring.
6. THE Platform SHALL provide a `GET /admin/coupons/{coupon_id}/redemptions` endpoint that returns all Organisation_Coupon records for a given coupon, including `billing_months_used` and `is_expired` status.

### Requirement 6: Usage Limit Management

**User Story:** As a Global Admin, I want to set and adjust usage limits on coupons, so that I can control how many organisations can redeem each coupon.

#### Acceptance Criteria

1. WHEN creating a coupon with a `usage_limit` value, THE Platform SHALL enforce that no more than `usage_limit` organisations can redeem the coupon.
2. WHEN `usage_limit` is null, THE Platform SHALL allow unlimited redemptions of the coupon.
3. WHEN a Global_Admin updates the `usage_limit` on a coupon, THE Platform SHALL accept the new value only if the new limit is greater than or equal to `times_redeemed`.
4. IF a Global_Admin attempts to set `usage_limit` below `times_redeemed`, THEN THE Platform SHALL return a 422 Unprocessable Entity error with a message indicating the minimum allowed limit.
5. THE Admin_Coupon_UI SHALL display the current `times_redeemed` count alongside the `usage_limit` for each coupon (e.g. "15 / 50 used").

### Requirement 7: Admin Coupon Management UI

**User Story:** As a Global Admin, I want a "Coupons" tab on the Subscription Management page, so that I can create, view, edit, and deactivate coupons from the admin interface.

#### Acceptance Criteria

1. THE Admin_Coupon_UI SHALL add a tab navigation to the Subscription Management page with "Plans" and "Coupons" tabs, where "Plans" shows the existing plans table and global storage pricing, and "Coupons" shows the coupon management interface.
2. THE Admin_Coupon_UI SHALL display a data table listing all coupons with columns: Code, Description, Type, Value, Duration, Usage (times_redeemed / usage_limit), Status (Active/Inactive), Created date, and Actions.
3. THE Admin_Coupon_UI SHALL provide a "Create Coupon" button that opens a modal form with fields for code, description, discount_type (dropdown), discount_value, duration_months, usage_limit, starts_at, and expires_at.
4. WHEN the discount_type dropdown changes, THE Admin_Coupon_UI SHALL update the discount_value field label and validation: "Percentage (1-100)" for percentage, "Amount (NZD)" for fixed_amount, "Additional trial days" for trial_extension.
5. THE Admin_Coupon_UI SHALL provide an "Edit" action on each coupon row that opens the modal pre-filled with the coupon's current values.
6. THE Admin_Coupon_UI SHALL provide a "Deactivate" action on active coupons and a "Reactivate" action on inactive coupons.
7. THE Admin_Coupon_UI SHALL display a confirmation dialog before deactivating a coupon.
8. THE Admin_Coupon_UI SHALL use the existing UI components (DataTable, Modal, Input, Button, Badge, Spinner, AlertBanner, ToastContainer) consistent with the plans management interface.
9. WHILE the coupon list is loading, THE Admin_Coupon_UI SHALL display a Spinner with the label "Loading coupons".
10. IF the coupon list fails to load, THEN THE Admin_Coupon_UI SHALL display an AlertBanner with the message "Could not load coupons."

### Requirement 8: Coupon Form Validation

**User Story:** As a Global Admin, I want the coupon form to validate inputs before submission, so that I cannot create coupons with invalid configurations.

#### Acceptance Criteria

1. THE Admin_Coupon_UI SHALL require the `code` field to be non-empty, alphanumeric (with hyphens and underscores allowed), and between 3 and 50 characters.
2. THE Admin_Coupon_UI SHALL require `discount_type` to be selected.
3. WHEN `discount_type` is "percentage", THE Admin_Coupon_UI SHALL validate that `discount_value` is between 1 and 100.
4. WHEN `discount_type` is "fixed_amount", THE Admin_Coupon_UI SHALL validate that `discount_value` is greater than zero.
5. WHEN `discount_type` is "trial_extension", THE Admin_Coupon_UI SHALL validate that `discount_value` is a whole number greater than zero.
6. IF `duration_months` is provided, THEN THE Admin_Coupon_UI SHALL validate that the value is a whole number greater than zero.
7. IF `usage_limit` is provided, THEN THE Admin_Coupon_UI SHALL validate that the value is a whole number greater than zero.
8. IF `starts_at` and `expires_at` are both provided, THEN THE Admin_Coupon_UI SHALL validate that `expires_at` is after `starts_at`.
9. THE Admin_Coupon_UI SHALL display field-level validation errors inline and prevent form submission until all errors are resolved.
10. WHILE the API request is in progress, THE Admin_Coupon_UI SHALL disable the submit button and display a loading indicator.

### Requirement 9: Database Migration for Coupon System

**User Story:** As a developer, I want the coupon tables added via an Alembic migration, so that the schema changes are versioned and reversible.

#### Acceptance Criteria

1. THE Migration SHALL create the `coupons` table with all columns defined in Requirement 1.
2. THE Migration SHALL create the `organisation_coupons` table with all columns defined in Requirement 1.
3. THE Migration SHALL create the unique constraint on `coupons(code)`.
4. THE Migration SHALL create the unique constraint on `organisation_coupons(org_id, coupon_id)`.
5. THE Migration SHALL create indexes on `coupons(code)` and `organisation_coupons(org_id)`.
6. THE Migration SHALL create the check constraint on `coupons.discount_type` allowing only "percentage", "fixed_amount", or "trial_extension".
7. THE Migration SHALL enable row-level security on the `organisation_coupons` table following the existing RLS pattern, and SHALL NOT enable RLS on the `coupons` table.
8. THE Migration SHALL include a `downgrade()` function that drops the created tables, indexes, and constraints.

### Requirement 10: Coupon Pydantic Schemas

**User Story:** As a developer, I want Pydantic v2 schemas for coupon API request and response payloads, so that input validation and serialisation are consistent with the existing codebase.

#### Acceptance Criteria

1. THE Platform SHALL define a `CouponCreateRequest` schema with fields: `code` (str, min 3, max 50), `description` (str, optional), `discount_type` (str), `discount_value` (float, gt 0), `duration_months` (int, optional, gt 0), `usage_limit` (int, optional, gt 0), `starts_at` (datetime, optional), `expires_at` (datetime, optional).
2. THE Platform SHALL define a `CouponUpdateRequest` schema with all fields optional except `id`.
3. THE Platform SHALL define a `CouponResponse` schema with all coupon fields plus `times_redeemed`, `created_at`, and `updated_at`.
4. THE Platform SHALL define a `CouponListResponse` schema with a `coupons` list and `total` count, following the `PlanListResponse` pattern.
5. THE Platform SHALL define a `CouponValidateRequest` schema with a `code` field.
6. THE Platform SHALL define a `CouponValidateResponse` schema with `valid` (bool), `coupon` (CouponResponse, optional), and `error` (str, optional).
7. THE Platform SHALL define a `CouponRedeemRequest` schema with `code` (str) and `org_id` (str) fields.
8. THE Platform SHALL define a `CouponRedeemResponse` schema with `message` (str) and `organisation_coupon_id` (str) fields.

### Requirement 11: Effective Price Calculation

**User Story:** As a platform operator, I want the effective subscription price to be correctly calculated when a coupon is active, so that organisations are billed the discounted amount.

#### Acceptance Criteria

1. THE Platform SHALL provide a utility function `calculate_effective_price(plan_price: float, coupon: Coupon, org_coupon: OrganisationCoupon) -> float` that returns the discounted price.
2. WHEN the Organisation_Coupon `is_expired` is true, THE utility function SHALL return the full `plan_price` with no discount applied.
3. WHEN `discount_type` is "percentage", THE utility function SHALL return `plan_price × (1 - discount_value / 100)`, rounded to 2 decimal places.
4. WHEN `discount_type` is "fixed_amount", THE utility function SHALL return `max(0.00, plan_price - discount_value)`, rounded to 2 decimal places.
5. WHEN `discount_type` is "trial_extension", THE utility function SHALL return the full `plan_price` (trial extensions do not affect price).
6. FOR ALL valid inputs, THE `calculate_effective_price` function SHALL return a value greater than or equal to zero and less than or equal to `plan_price` (round-trip invariant: discount never increases price).

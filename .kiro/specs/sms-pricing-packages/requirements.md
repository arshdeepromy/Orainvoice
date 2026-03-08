# Requirements Document

## Introduction

This feature adds a comprehensive SMS billing system to the OraInvoice/WorkshopPro platform. It introduces per-SMS pricing on subscription plans, monthly SMS usage tracking per organisation, overage calculation and billing at subscription renewal, and bulk SMS package purchases. The system follows the exact same patterns already established for Carjam lookup pricing/overage and storage tier add-on pricing. MFA/verification SMS is explicitly excluded from all usage tracking and billing — only business SMS (reminders, promotions, overdue notices) counts toward usage.

## Glossary

- **SMS_Billing_System**: The subsystem responsible for tracking business SMS usage, calculating overage, and managing bulk SMS packages across the platform.
- **Business_SMS**: SMS messages sent for business purposes including overdue reminders, WoF/rego reminders, and promotional notifications. Excludes MFA/verification SMS.
- **MFA_SMS**: SMS messages sent for multi-factor authentication and phone verification via `mfa_service._send_sms_otp()`. These are never counted or restricted.
- **Per_SMS_Cost**: A numeric cost field (NZD) on each subscription plan that defines the price per business SMS sent beyond the included quota.
- **SMS_Included_Quota**: An integer field on each subscription plan defining how many business SMS messages are included per billing month at no extra charge.
- **SMS_Overage**: The number of business SMS messages sent beyond the SMS_Included_Quota in a billing month, calculated as `max(0, sms_sent_this_month - sms_included_quota)`.
- **SMS_Package**: A pre-purchased bulk SMS credit bundle that an organisation can buy in advance, following the same pattern as storage tier add-ons.
- **SMS_Package_Tier**: A tier definition within the `sms_package_pricing` JSONB column on SubscriptionPlan, containing tier name, SMS quantity, and price in NZD.
- **Organisation**: A tenant record in the multi-tenant platform, identified by `organisations.id`.
- **SubscriptionPlan**: A plan definition in `subscription_plans` configured by Global Admin.
- **Global_Admin**: A platform administrator with access to plan configuration, integration settings, and cross-organisation reporting.
- **Org_Admin**: An organisation administrator who manages their own organisation's settings and can purchase SMS packages.
- **Renewal_Invoice**: The Stripe invoice generated at subscription renewal that includes base plan cost plus any overage charges.

## Requirements

### Requirement 1: Per-SMS Cost on Subscription Plans

**User Story:** As a Global Admin, I want to configure a per-SMS cost on each subscription plan, so that overage charges can be calculated when organisations exceed their included SMS quota.

#### Acceptance Criteria

1. THE SubscriptionPlan SHALL include a `per_sms_cost_nzd` field of type `Numeric(10,4)` with a default value of 0.
2. THE SubscriptionPlan SHALL include an `sms_included_quota` field of type `Integer` with a default value of 0, representing the number of business SMS messages included per billing month.
3. WHEN a Global_Admin creates a subscription plan, THE SMS_Billing_System SHALL accept `per_sms_cost_nzd` and `sms_included_quota` values alongside existing plan fields.
4. WHEN a Global_Admin updates a subscription plan, THE SMS_Billing_System SHALL allow modification of `per_sms_cost_nzd` and `sms_included_quota` values.
5. THE SMS_Billing_System SHALL validate that `per_sms_cost_nzd` is greater than or equal to 0.
6. THE SMS_Billing_System SHALL validate that `sms_included_quota` is greater than or equal to 0.
7. WHEN `sms_included` is false on a plan, THE SMS_Billing_System SHALL treat `sms_included_quota` as 0 regardless of the stored value.

### Requirement 2: SMS Usage Tracking per Organisation

**User Story:** As a platform operator, I want to track how many business SMS messages each organisation sends per month, so that overage can be calculated accurately.

#### Acceptance Criteria

1. THE Organisation SHALL include an `sms_sent_this_month` field of type `Integer` with a default value of 0.
2. THE Organisation SHALL include an `sms_sent_reset_at` field of type `DateTime(timezone=True)` that records when the monthly SMS counter was last reset.
3. WHEN a Business_SMS is dispatched successfully by the notification service, THE SMS_Billing_System SHALL increment `sms_sent_this_month` by 1 for the sending Organisation.
4. WHEN an MFA_SMS is sent via `mfa_service._send_sms_otp()`, THE SMS_Billing_System SHALL NOT increment `sms_sent_this_month`.
5. WHEN the monthly billing cycle resets for an Organisation, THE SMS_Billing_System SHALL set `sms_sent_this_month` to 0 and update `sms_sent_reset_at` to the current timestamp.
6. THE SMS_Billing_System SHALL provide a `get_org_sms_usage(db, org_id)` service function that returns the organisation name, total SMS sent this month, included quota from the plan, overage count, overage charge in NZD, and per-SMS cost.
7. THE SMS_Billing_System SHALL provide a `get_all_orgs_sms_usage(db)` service function that returns SMS usage data for all non-deleted organisations, following the same structure as `get_all_orgs_carjam_usage()`.

### Requirement 3: SMS Overage Calculation

**User Story:** As a platform operator, I want SMS overage to be calculated using the same pattern as Carjam lookup overage, so that billing is consistent and predictable.

#### Acceptance Criteria

1. THE SMS_Billing_System SHALL provide a `compute_sms_overage(total_sent, included_quota)` function that returns `max(0, total_sent - included_quota)`.
2. THE SMS_Billing_System SHALL calculate the overage charge as `overage_count × per_sms_cost_nzd` from the organisation's subscription plan.
3. WHEN an Organisation has purchased SMS_Packages, THE SMS_Billing_System SHALL add the package credits to the included quota before computing overage: `effective_quota = sms_included_quota + total_package_credits_remaining`.
4. WHEN `sms_included` is false on the Organisation's plan, THE SMS_Billing_System SHALL treat the effective quota as 0 for overage calculation.
5. FOR ALL non-negative integer values of `total_sent` and `included_quota`, THE `compute_sms_overage` function SHALL return a value greater than or equal to 0 (non-negative invariant).
6. FOR ALL values where `total_sent` is less than or equal to `included_quota`, THE `compute_sms_overage` function SHALL return 0 (no overage when within quota).

### Requirement 4: SMS Overage Billing on Subscription Renewal

**User Story:** As a platform operator, I want SMS overage charges to be added to the subscription renewal invoice, so that organisations are billed for excess usage automatically.

#### Acceptance Criteria

1. WHEN a subscription renewal invoice is generated, THE SMS_Billing_System SHALL calculate the SMS overage for the billing period that just ended.
2. WHEN the SMS overage count is greater than 0, THE SMS_Billing_System SHALL add a line item to the Renewal_Invoice with the description "SMS overage: {overage_count} messages × ${per_sms_cost_nzd}", the quantity set to the overage count, and the unit price set to `per_sms_cost_nzd`.
3. WHEN the SMS overage count is 0, THE SMS_Billing_System SHALL NOT add an SMS overage line item to the Renewal_Invoice.
4. THE SMS_Billing_System SHALL reset `sms_sent_this_month` to 0 after the overage has been captured for billing.
5. THE SMS_Billing_System SHALL log the overage calculation details to the audit log with action `sms_overage.billed`, including the organisation ID, overage count, per-SMS cost, and total charge.

### Requirement 5: SMS Package Tier Configuration by Global Admin

**User Story:** As a Global Admin, I want to define SMS package tiers on subscription plans, so that organisations can purchase bulk SMS credits at predefined price points.

#### Acceptance Criteria

1. THE SubscriptionPlan SHALL include an `sms_package_pricing` field of type `JSONB` that stores an array of SMS_Package_Tier objects, following the same pattern as `storage_tier_pricing`.
2. THE SMS_Billing_System SHALL validate each SMS_Package_Tier object contains `tier_name` (string, non-empty), `sms_quantity` (integer, greater than 0), and `price_nzd` (numeric, greater than or equal to 0).
3. WHEN a Global_Admin creates or updates a plan, THE SMS_Billing_System SHALL accept an `sms_package_pricing` array and persist it to the JSONB column.
4. THE SMS_Billing_System SHALL provide a `SmsPackageTierPricing` Pydantic schema that validates each tier entry, following the same pattern as `StorageTierPricing`.
5. WHEN the `sms_package_pricing` array is empty or null, THE SMS_Billing_System SHALL treat the plan as having no SMS package tiers available for purchase.
6. THE Admin_UI SHALL display SMS package tiers in a table with add/remove rows, following the same pattern as the storage tier pricing table in `SubscriptionPlans.tsx`.

### Requirement 6: Bulk SMS Package Purchases by Organisations

**User Story:** As an Org Admin, I want to purchase bulk SMS packages from the available tiers on my plan, so that my organisation gets additional SMS credits beyond the included quota.

#### Acceptance Criteria

1. WHEN an Org_Admin requests to purchase an SMS_Package, THE SMS_Billing_System SHALL verify the requested tier exists in the organisation's plan `sms_package_pricing`.
2. WHEN the tier is valid, THE SMS_Billing_System SHALL create a Stripe one-time charge for the `price_nzd` amount using the organisation's `stripe_customer_id`.
3. WHEN the Stripe charge succeeds, THE SMS_Billing_System SHALL create an `sms_package_purchase` record with the organisation ID, tier name, SMS quantity purchased, price paid, purchase timestamp, and remaining credits.
4. WHEN the Stripe charge fails, THE SMS_Billing_System SHALL return a descriptive error to the Org_Admin and NOT create a package purchase record.
5. THE SMS_Billing_System SHALL provide an API endpoint `GET /org/sms-packages` that returns all active SMS package purchases for the organisation, including remaining credits and purchase date.
6. THE SMS_Billing_System SHALL provide an API endpoint `POST /org/sms-packages/purchase` that accepts a `tier_name` and initiates the purchase flow.
7. WHEN computing SMS overage, THE SMS_Billing_System SHALL deduct from the oldest purchased package credits first (FIFO order).

### Requirement 7: SMS Usage Dashboard and Reporting

**User Story:** As an Org Admin, I want to see my organisation's SMS usage, included quota, overage, and purchased packages, so that I can monitor costs and buy more credits when needed.

#### Acceptance Criteria

1. THE SMS_Billing_System SHALL provide an API endpoint `GET /reports/sms-usage` that returns total SMS sent this month, included quota, overage count, overage charge, and daily breakdown, following the same structure as the Carjam usage report endpoint.
2. THE SMS_Billing_System SHALL provide a frontend `SmsUsage` report page that displays total SMS sent, included in plan, overage count, overage charge, and a daily breakdown chart, following the same layout as `CarjamUsage.tsx`.
3. THE SMS_Billing_System SHALL display active SMS package purchases with remaining credits on the SMS usage report page.
4. THE Global_Admin dashboard SHALL include an SMS usage overview across all organisations, following the same pattern as `get_all_orgs_carjam_usage()`.

### Requirement 8: SMS Usage Exclusion for MFA and Verification Messages

**User Story:** As a platform operator, I want MFA and verification SMS to be completely excluded from usage tracking and billing, so that security-critical messages are never restricted by billing limits.

#### Acceptance Criteria

1. WHEN `mfa_service._send_sms_otp()` sends an SMS, THE SMS_Billing_System SHALL NOT increment `sms_sent_this_month` on the Organisation.
2. WHEN `mfa_service._send_sms_otp()` sends an SMS, THE SMS_Billing_System SHALL NOT deduct from SMS package credits.
3. WHEN an Organisation has exhausted all SMS quota and package credits, THE SMS_Billing_System SHALL continue to allow MFA_SMS delivery without restriction.
4. THE notification service SHALL distinguish between Business_SMS and MFA_SMS by the calling context: messages dispatched via `process_overdue_reminders()`, `process_wof_rego_reminders()`, and similar business notification functions count as Business_SMS; messages dispatched via `mfa_service` count as MFA_SMS.
5. THE SMS_Billing_System SHALL log MFA_SMS in the `notification_log` table with channel "sms" for audit purposes, but SHALL NOT include MFA_SMS in usage count or billing calculations.

### Requirement 9: Database Migration for SMS Billing Fields

**User Story:** As a developer, I want the new SMS billing fields added via an Alembic migration, so that the schema changes are versioned and reversible.

#### Acceptance Criteria

1. THE Migration SHALL add `per_sms_cost_nzd` (Numeric(10,4), default 0) to the `subscription_plans` table.
2. THE Migration SHALL add `sms_included_quota` (Integer, default 0) to the `subscription_plans` table.
3. THE Migration SHALL add `sms_package_pricing` (JSONB, nullable, default '[]') to the `subscription_plans` table.
4. THE Migration SHALL add `sms_sent_this_month` (Integer, default 0) to the `organisations` table.
5. THE Migration SHALL add `sms_sent_reset_at` (DateTime with timezone, nullable) to the `organisations` table.
6. THE Migration SHALL create an `sms_package_purchases` table with columns: `id` (UUID, primary key), `org_id` (UUID, foreign key to organisations), `tier_name` (String), `sms_quantity` (Integer), `price_nzd` (Numeric(10,2)), `credits_remaining` (Integer), `purchased_at` (DateTime with timezone), `created_at` (DateTime with timezone).
7. THE Migration SHALL include a `downgrade()` function that reverses all schema changes.

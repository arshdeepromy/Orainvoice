# Requirements Document: Storage Packages

## Introduction

This feature replaces the current flat "Global Storage Pricing" (single increment + price-per-GB) with a proper storage package system. Global Admins can create named storage packages (e.g. "5 GB — $2.50/mo", "25 GB — $8.00/mo") that org users can purchase from their Billing page. Each organisation has at most one active storage add-on at a time, which can be resized (upgraded or downgraded) rather than stacking multiple purchases. A custom GB option is also available using the fallback price-per-GB rate.

The system replaces the existing `storage_addon_config` in `platform_settings` and the stacking `purchase_storage_addon` flow with a cleaner single-add-on-per-org model.

## Glossary

- **Storage_Package**: A Global Admin-defined storage tier with a name, GB amount, and monthly price. Stored in the `storage_packages` table.
- **Active_Storage_Addon**: The single storage add-on currently applied to an organisation, tracked in the `org_storage_addons` table. An org can have at most one active add-on.
- **Custom_Storage**: When an org user enters a custom GB amount instead of picking a pre-configured package. Priced at the fallback `price_per_gb_nzd` rate.
- **Resize**: Upgrading (more GB) or downgrading (less GB) an existing storage add-on. Upgrades take effect immediately with prorated charges. Downgrades take effect at the next billing cycle.
- **Base_Quota**: The storage quota included in the org's subscription plan (`subscription_plans.storage_quota_gb`). This is separate from any add-on.
- **Total_Quota**: `Base_Quota + Active_Storage_Addon.quantity_gb`. This is what the org sees as their total storage.
- **Fallback_Price_Per_GB**: The default per-GB monthly rate used for custom storage amounts and when no package tier matches. Configured in `platform_settings` as `storage_pricing.price_per_gb_nzd`.

## Requirements

### Requirement 1: Storage Package Data Model

**User Story:** As a developer, I want a storage package data model that supports named tiers with GB amounts and monthly prices, plus a per-org active add-on tracker, so that the platform can manage storage purchases cleanly.

#### Acceptance Criteria

1. THE Platform SHALL create a `storage_packages` table with columns: `id` (UUID PK), `name` (String(100), not null), `storage_gb` (Integer, not null, > 0), `price_nzd_per_month` (Numeric(10,2), not null, >= 0), `description` (String(255), nullable), `is_active` (Boolean, default true), `sort_order` (Integer, default 0), `created_at` (DateTime with timezone), `updated_at` (DateTime with timezone).
2. THE `storage_packages` table SHALL NOT have row-level security enabled, following the same global admin pattern as `subscription_plans` and `coupons`.
3. THE Platform SHALL create an `org_storage_addons` table with columns: `id` (UUID PK), `org_id` (UUID FK → organisations.id, not null, unique), `storage_package_id` (UUID FK → storage_packages.id, nullable — null for custom amounts), `quantity_gb` (Integer, not null, > 0), `price_nzd_per_month` (Numeric(10,2), not null), `is_custom` (Boolean, default false), `purchased_at` (DateTime with timezone, not null), `updated_at` (DateTime with timezone).
4. THE `org_storage_addons` table SHALL enforce a unique constraint on `org_id` to ensure at most one active storage add-on per organisation.
5. THE `org_storage_addons` table SHALL enable row-level security scoped to `org_id`, following the existing multi-tenant pattern.
6. THE Organisation model SHALL track total effective storage as `plan.storage_quota_gb + COALESCE(org_storage_addon.quantity_gb, 0)`.

### Requirement 2: Storage Package CRUD API (Global Admin)

**User Story:** As a Global Admin, I want API endpoints to create, read, update, and deactivate storage packages, so that I can manage the storage tier catalogue.

#### Acceptance Criteria

1. THE Platform SHALL provide a `GET /admin/storage-packages` endpoint that returns all storage packages ordered by `sort_order` ascending, optionally filtered by `is_active`.
2. THE Platform SHALL provide a `POST /admin/storage-packages` endpoint that creates a new storage package with `name`, `storage_gb`, `price_nzd_per_month`, `description`, and `sort_order`.
3. THE Platform SHALL provide a `PUT /admin/storage-packages/{id}` endpoint that updates `name`, `storage_gb`, `price_nzd_per_month`, `description`, `is_active`, and `sort_order`.
4. THE Platform SHALL provide a `DELETE /admin/storage-packages/{id}` endpoint that soft-deletes by setting `is_active = false`.
5. THE Platform SHALL validate that `storage_gb` is greater than 0 and `price_nzd_per_month` is >= 0 on create and update.
6. THE Platform SHALL prevent deletion of a storage package that is currently referenced by any `org_storage_addons` record — instead it should only deactivate.

### Requirement 3: Storage Package Admin UI (Global Admin)

**User Story:** As a Global Admin, I want a "Storage" tab on the Subscription Management page where I can manage storage packages, so that I can configure what storage tiers are available to organisations.

#### Acceptance Criteria

1. THE Subscription Management page SHALL display a third tab "Storage" alongside "Plans" and "Coupons".
2. THE Storage tab SHALL display a DataTable listing all active storage packages with columns: Name, Storage (GB), Price/month (NZD), Description, Sort Order, Status, Actions.
3. THE Storage tab SHALL include a "Create package" button that opens a modal form for creating a new storage package.
4. THE Storage tab SHALL include Edit and Deactivate action buttons per row.
5. THE Storage tab SHALL retain the existing "Global Storage Pricing" card (fallback price_per_gb_nzd) above the packages table, since it's used for custom storage pricing.
6. THE Storage tab SHALL include a "Show deactivated" checkbox to toggle visibility of deactivated packages.

### Requirement 4: Org User Storage Purchase Flow

**User Story:** As an Org Admin, I want to purchase a storage add-on from pre-configured packages or enter a custom amount on my Billing page, so that I can increase my organisation's storage quota.

#### Acceptance Criteria

1. THE Billing page Storage section SHALL replace the current disabled "Buy more storage" button with a functional "Manage storage" button.
2. WHEN the org has no active storage add-on, clicking "Manage storage" SHALL open a modal showing available storage packages as selectable cards, plus a "Custom" option where the user enters a GB amount.
3. EACH package card SHALL display the package name, GB amount, and monthly price.
4. THE Custom option SHALL display the fallback price-per-GB rate and let the user enter any GB amount (minimum 1 GB).
5. THE modal SHALL show a confirmation step with the selected package/amount, monthly charge, and new total quota before purchase.
6. ON confirmation, THE Platform SHALL create an `org_storage_addons` record and increase the org's `storage_quota_gb` by the add-on amount.
7. THE Platform SHALL NOT require Stripe for the initial implementation — the purchase is recorded internally and the quota is increased immediately. Stripe charging will be added when billing integration is complete.

### Requirement 5: Org User Storage Resize Flow

**User Story:** As an Org Admin, I want to upgrade or downgrade my existing storage add-on, so that I can adjust my storage as needs change without stacking multiple purchases.

#### Acceptance Criteria

1. WHEN the org has an active storage add-on, the Billing page Storage section SHALL show the current add-on details (package name or "Custom", GB amount, monthly price).
2. THE "Manage storage" button SHALL open a modal showing the current add-on and available resize options.
3. THE user SHALL be able to select a different package or enter a new custom GB amount.
4. WHEN upgrading (more GB), THE change SHALL take effect immediately — the `org_storage_addons` record is updated and `storage_quota_gb` is increased.
5. WHEN downgrading (less GB), THE Platform SHALL validate that current storage usage does not exceed the new total quota (base + new add-on). If it does, show a warning and block the downgrade.
6. THE modal SHALL clearly show the price difference between current and new add-on.
7. THE user SHALL be able to remove their storage add-on entirely, reverting to the plan's base quota only (with the same usage validation as downgrade).

### Requirement 6: Billing Dashboard Integration

**User Story:** As an Org Admin, I want my billing dashboard to reflect my storage add-on in the next bill estimate, so that I can see the full cost breakdown.

#### Acceptance Criteria

1. THE `BillingDashboardResponse` SHALL include `storage_addon_gb` (int|null), `storage_addon_price_nzd` (float|null), and `storage_addon_package_name` (str|null) fields.
2. THE "Your next bill" estimate SHALL include the storage add-on charge as a separate line item (e.g. "Storage add-on (10 GB): $4.00").
3. THE estimated total SHALL include `plan_fee + storage_addon + carjam_overage` (with coupon discount applied to plan fee).
4. THE Storage usage card SHALL show the total quota (base + add-on) and indicate how much is from the plan vs the add-on.

### Requirement 7: Audit Logging

**User Story:** As a Global Admin, I want all storage package and add-on operations to be audit logged, so that I can track changes.

#### Acceptance Criteria

1. THE Platform SHALL write audit log entries for: storage package created, updated, deactivated.
2. THE Platform SHALL write audit log entries for: org storage add-on purchased, resized (upgraded/downgraded), removed.
3. EACH audit entry SHALL include before/after values showing the change.

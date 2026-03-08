# Requirements Document

## Introduction

The platform already has a feature flag system with a database-backed `feature_flags` table, a pure evaluation engine (`app/core/feature_flags.py`), a CRUD service, admin API endpoints, a React context/hook for frontend consumption, and an admin UI page. However, the current system only covers a handful of flags and does not comprehensively gate every platform feature end-to-end.

This spec extends the feature flag system so that every platform feature is registered as a flag, the backend API middleware blocks requests when a flag is disabled, the frontend hides UI for disabled features, and the admin UI provides full category-based management with metadata (access level, dependencies, code key). The goal is a single source of truth where an admin can toggle any feature on or off and have it take effect immediately across the entire stack.

## Glossary

- **Flag_Registry**: The database table storing all feature flag definitions including key, display name, category, access level, dependencies, and default value.
- **Flag_Evaluation_Engine**: The pure-function evaluation logic in `app/core/feature_flags.py` that resolves a flag's boolean value given an organisation context and targeting rules.
- **Flag_Middleware**: A backend middleware layer that intercepts API requests and returns HTTP 403 when the corresponding feature flag is disabled for the requesting organisation.
- **Flag_Context**: The React context (`FeatureFlagContext`) that fetches evaluated flags from the backend and exposes them to frontend components via hooks.
- **Flag_Gate**: A frontend component or hook that conditionally renders UI elements based on the evaluated state of a feature flag.
- **Admin_Flag_UI**: The admin page (`FeatureFlags.tsx`) where Global Admins manage all feature flags grouped by category.
- **Seed_Migration**: An Alembic migration that inserts all platform feature flags into the Flag_Registry with correct metadata.
- **Feature_Category**: A grouping label (e.g., "Operations", "Hospitality", "Construction") used to organise flags in the Admin_Flag_UI.
- **Access_Level**: A metadata field on a flag indicating whether the feature is available to "All Users" or restricted to "Admin Only".
- **Org_Context**: The immutable snapshot of an organisation's attributes (org_id, trade_category, country, plan_tier) used for flag targeting.

## Requirements

### Requirement 1: Comprehensive Flag Registry Seed Data

**User Story:** As a platform administrator, I want every platform feature to be registered as a feature flag in the database, so that I have a single place to enable or disable any feature.

#### Acceptance Criteria

1. THE Seed_Migration SHALL insert a feature flag row into the Flag_Registry for each of the following platform modules: invoicing, customers, notifications, quotes, jobs, projects, time_tracking, expenses, inventory, purchase_orders, pos, tipping, tables, kitchen_display, scheduling, staff, bookings, progress_claims, retentions, variations, compliance_docs, multi_currency, recurring, loyalty, franchise, ecommerce, branding, assets, webhooks, reports, portal, analytics, i18n, migration_tool, data_import_export, receipt_printer, floor_plans, digital_wallet, kyc_verification, ai_categorization, ai_vendor_matching, ai_insights, auto_sync, manual_sync, internal_transfers, external_payments.
2. WHEN the Seed_Migration runs, THE Seed_Migration SHALL assign each flag a unique snake_case key, a human-readable display_name, a description, a Feature_Category, an Access_Level, a dependencies list, and a default_value of true for core modules and false for non-core modules.
3. THE Seed_Migration SHALL assign each flag to exactly one Feature_Category from the set: Core, Sales, Operations, Inventory, POS, Hospitality, Staff, Construction, Finance, Compliance, Engagement, Enterprise, Ecommerce, Admin, Banking & Payments, AI & Automation, Reports, Data.
4. THE Seed_Migration SHALL be idempotent so that running the migration multiple times does not create duplicate flag rows.
5. IF a flag key already exists in the Flag_Registry, THEN THE Seed_Migration SHALL skip that row without error.

### Requirement 2: Backend Feature Flag Middleware for API Gating

**User Story:** As a platform administrator, I want the backend to block API requests for disabled features, so that disabling a flag actually prevents access to that feature's endpoints.

#### Acceptance Criteria

1. THE Flag_Middleware SHALL maintain a mapping from API endpoint path prefixes to feature flag keys covering all gated platform modules.
2. WHEN an authenticated request arrives for a path prefix mapped to a feature flag, THE Flag_Middleware SHALL evaluate the flag for the requesting organisation's Org_Context.
3. IF the evaluated flag value is false, THEN THE Flag_Middleware SHALL return HTTP 403 with a JSON body containing the flag key and a descriptive message.
4. IF the evaluated flag value is true, THEN THE Flag_Middleware SHALL allow the request to proceed to the route handler.
5. WHILE a flag is marked as a core feature (e.g., invoicing, customers, notifications), THE Flag_Middleware SHALL allow requests regardless of the flag's evaluated value.
6. IF the flag evaluation fails due to a database or cache error, THEN THE Flag_Middleware SHALL allow the request to proceed (fail-open behaviour).
7. THE Flag_Middleware SHALL cache evaluated flag results per organisation in Redis with a configurable TTL to avoid per-request database queries.
8. WHEN a flag is updated via the admin API, THE Flag_Middleware SHALL invalidate the cached evaluation for all affected organisations within 5 seconds.

### Requirement 3: Frontend Feature Flag Gating

**User Story:** As a platform administrator, I want the frontend to hide UI elements for disabled features, so that users do not see or interact with features that are turned off.

#### Acceptance Criteria

1. THE Flag_Context SHALL fetch all evaluated flag values from the `/v2/flags` endpoint on authentication and expose them via the `useFlag(key)` hook.
2. WHEN the `useFlag` hook is called with a flag key that evaluates to false, THE Flag_Gate SHALL prevent the associated UI component from rendering.
3. WHEN the `useFlag` hook is called with a flag key that evaluates to true, THE Flag_Gate SHALL render the associated UI component normally.
4. THE Flag_Context SHALL provide a `FeatureGate` wrapper component that accepts a `flagKey` prop and conditionally renders its children based on the flag evaluation.
5. THE Flag_Context SHALL provide an optional `fallback` prop on the `FeatureGate` component that renders alternative content when the flag is disabled.
6. WHEN the flag data is still loading, THE Flag_Gate SHALL not render the gated component (default to hidden until flags are resolved).
7. THE Flag_Context SHALL re-fetch flag values when the `refetch` function is called, allowing the admin UI to trigger a refresh after flag changes.
8. THE Flag_Context SHALL expose an `isLoading` boolean so that consuming components can show loading states during flag resolution.

### Requirement 4: Admin UI for Comprehensive Flag Management

**User Story:** As a Global Admin, I want a comprehensive admin page to view, search, filter, and toggle all feature flags grouped by category, so that I can manage the entire platform's feature availability from one place.

#### Acceptance Criteria

1. THE Admin_Flag_UI SHALL display all flags from the Flag_Registry grouped by Feature_Category with collapsible category sections.
2. THE Admin_Flag_UI SHALL display for each flag: the display_name, description, code key, Access_Level badge, dependency list, and a toggle switch for the `is_active` state.
3. WHEN a Global Admin toggles a flag's `is_active` switch, THE Admin_Flag_UI SHALL send a PUT request to `/api/v2/admin/flags/{key}` and update the UI optimistically.
4. IF the PUT request fails, THEN THE Admin_Flag_UI SHALL revert the toggle to its previous state and display an error toast notification.
5. THE Admin_Flag_UI SHALL provide a search input that filters flags by display_name, key, or description across all categories.
6. THE Admin_Flag_UI SHALL provide a filter dropdown to show flags by Feature_Category, Access_Level, or enabled/disabled status.
7. WHEN a flag has dependencies, THE Admin_Flag_UI SHALL display a warning when the admin attempts to disable a flag that other enabled flags depend on.
8. THE Admin_Flag_UI SHALL display a count of enabled vs total flags per category in the category header.
9. THE Admin_Flag_UI SHALL be accessible only to users with the Global Admin role.

### Requirement 5: Flag Evaluation Engine Enhancement

**User Story:** As a developer, I want the flag evaluation engine to support the comprehensive flag registry with proper caching and bulk evaluation, so that flag checks are fast and consistent.

#### Acceptance Criteria

1. THE Flag_Evaluation_Engine SHALL evaluate a flag by checking targeting rules in priority order: org_override, trade_category, trade_family, country, plan_tier, percentage.
2. WHEN no targeting rule matches, THE Flag_Evaluation_Engine SHALL return the flag's default_value.
3. WHEN a flag's `is_active` field is false, THE Flag_Evaluation_Engine SHALL return the default_value regardless of targeting rules.
4. THE Flag_Evaluation_Engine SHALL remain a pure function with no I/O, receiving all inputs as parameters.
5. THE Flag_Evaluation_Engine SHALL support bulk evaluation of all flags for a given Org_Context in a single call, returning a dictionary of flag_key to boolean.
6. FOR ALL valid Org_Context values, evaluating a flag twice with the same inputs SHALL produce the same boolean result (deterministic evaluation).

### Requirement 6: Feature Flag Database Schema

**User Story:** As a developer, I want the feature flag database schema to support all metadata needed for comprehensive flag management, so that the system can store categories, access levels, dependencies, and audit information.

#### Acceptance Criteria

1. THE Flag_Registry table SHALL include columns: id (UUID primary key), key (unique string), display_name (string), description (text, nullable), category (string), access_level (string, default "all_users"), dependencies (JSONB array, default empty), default_value (boolean), is_active (boolean), targeting_rules (JSONB array, default empty), created_at (timestamp), updated_at (timestamp), created_by (UUID, nullable), updated_by (UUID, nullable).
2. THE Flag_Registry table SHALL enforce a unique constraint on the key column.
3. THE Flag_Registry table SHALL have an index on the category column for efficient category-based queries.
4. THE Flag_Registry table SHALL have an index on the is_active column for efficient filtering of active flags.
5. WHEN a flag row is updated, THE Flag_Registry SHALL automatically update the updated_at timestamp.

### Requirement 7: End-to-End Flag Integration

**User Story:** As a platform administrator, I want disabling a feature flag to immediately block the backend API and hide the frontend UI for that feature, so that the flag system works as a true kill switch.

#### Acceptance Criteria

1. WHEN a Global Admin sets a flag's `is_active` to false via the Admin_Flag_UI, THE Flag_Middleware SHALL begin returning HTTP 403 for that feature's API endpoints within 5 seconds.
2. WHEN a Global Admin sets a flag's `is_active` to false via the Admin_Flag_UI, THE Flag_Context SHALL reflect the updated value on the next flag fetch, causing the Flag_Gate to hide the corresponding UI.
3. WHEN a Global Admin sets a flag's `is_active` to true via the Admin_Flag_UI, THE Flag_Middleware SHALL begin allowing requests to that feature's API endpoints within 5 seconds.
4. WHEN a Global Admin sets a flag's `is_active` to true via the Admin_Flag_UI, THE Flag_Context SHALL reflect the updated value on the next flag fetch, causing the Flag_Gate to show the corresponding UI.
5. THE Flag_Middleware and the Flag_Context SHALL use the same Flag_Evaluation_Engine to ensure consistent evaluation between backend and frontend.
6. FOR ALL feature flags, the backend gating result and the frontend gating result SHALL agree for the same Org_Context and flag state (consistency property).

### Requirement 8: Frontend Route and Navigation Gating

**User Story:** As a user, I want navigation links and routes for disabled features to be hidden, so that I do not encounter dead ends or error pages for features that are turned off.

#### Acceptance Criteria

1. THE Flag_Gate SHALL hide sidebar navigation items for features whose corresponding flag evaluates to false.
2. THE Flag_Gate SHALL hide route entries in the application router for features whose corresponding flag evaluates to false.
3. WHEN a user navigates directly to a URL for a disabled feature, THE Flag_Gate SHALL redirect the user to a "Feature not available" page or the dashboard.
4. THE Flag_Gate SHALL re-evaluate navigation visibility when flag values change (e.g., after a refetch).
